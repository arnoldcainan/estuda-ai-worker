import pika
import json
import time
import os
import logging
import boto3

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

from db_config import worker_app, database, Estudo, Questao
from ai_processor import process_study_material

RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
QUEUE_NAME = 'ai_task_queue'

def get_r2_client():
    return boto3.client(
        's3',
        endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY')
    )

def update_db_on_failure(estudo_id, error_msg):
    """Atualiza o status do DB quando a IA falha."""
    with worker_app.app_context():
        try:
            estudo = database.session.get(Estudo, estudo_id)
            if estudo:
                estudo.status = 'falha'
                estudo.resumo = f"Falha no processamento: {error_msg[:1000]}"
                database.session.commit()
                log.error(f"Tarefa {estudo_id} falhou. Status atualizado no DB.")
        except Exception as e:
            log.critical(f"ERRO CRÍTICO ao atualizar falha no DB para {estudo_id}: {e}", exc_info=True)
            database.session.rollback()


def callback(ch, method, properties, body):
    try:
        payload = json.loads(body)
        estudo_id = payload.get('estudo_id')
        filename = payload.get('filename')

        if not estudo_id or not filename:
            log.error(f"Mensagem inválida: {payload}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        log.info(f"Recebida Tarefa ID: {estudo_id}. Arquivo na Nuvem: {filename}")

        local_temp_path = os.path.join('/tmp', filename)
        try:
            log.info("Baixando arquivo do Cloudflare R2...")
            r2 = get_r2_client()
            r2.download_file(os.getenv('R2_BUCKET_NAME'), filename, local_temp_path)
            log.info("Download concluído com sucesso.")
        except Exception as e:
            log.error(f"Erro ao baixar do R2: {e}")
            raise FileNotFoundError(f"Não foi possível baixar {filename} da nuvem.")

        ia_result = process_study_material(local_temp_path)

        if ia_result['status'] == 'completed':
            with worker_app.app_context():
                estudo = database.session.get(Estudo, estudo_id)
                if estudo:
                    estudo.resumo = ia_result['resumo']
                    estudo.status = 'pronto'

                    qcm_data = ia_result['qcm_json']
                    Questao.query.filter_by(estudo_id=estudo.id).delete()
                    database.session.flush()

                    for q_data in qcm_data['questoes']:
                        nova_questao = Questao(
                            estudo_id=estudo.id,
                            pergunta=q_data['pergunta'],
                            opcoes_json=json.dumps(q_data['opcoes']),
                            resposta_correta=q_data['resposta_correta']
                        )
                        database.session.add(nova_questao)

                    database.session.commit()
                    log.info(f"Sucesso! Estudo ID {estudo_id} salvo.")

                    # 4. Limpeza: Apagar o arquivo temporário
                    if os.path.exists(local_temp_path):
                        os.remove(local_temp_path)

                ch.basic_ack(delivery_tag=method.delivery_tag)

        else:
            error_msg = ia_result.get('error', 'Erro desconhecido da IA.')
            raise Exception(f"Retorno de falha da IA: {error_msg}")

    except Exception as e:
        log.exception(f"ERRO DE EXECUÇÃO ID {estudo_id}: {e}")
        update_db_on_failure(estudo_id, f"Erro interno: {str(e)[:500]}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        try:
            local_temp_path = os.path.join('/tmp', filename) # Recria variável por segurança
            if os.path.exists(local_temp_path):
                os.remove(local_temp_path)
        except: pass

def start_worker():
    log.info("------------------------------------------------")
    log.info("AI-WORKER INICIANDO (PRODUÇÃO RAILWAY + R2)...")
    log.info("------------------------------------------------")

    retries = 0
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=credentials,
                    virtual_host=RABBITMQ_VHOST,
                    heartbeat=600
                )
            )
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)

            log.info(f"Conectado! Aguardando tarefas na fila '{QUEUE_NAME}'...")
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
            channel.start_consuming()

        except pika.exceptions.AMQPConnectionError as e:
            retries += 1
            wait_time = min(retries * 2, 30)
            log.warning(f"Reconectando em {wait_time}s... Erro: {e}")
            time.sleep(wait_time)
        except Exception as e:
            log.critical(f"Erro inesperado: {e}", exc_info=True)
            time.sleep(5)

if __name__ == '__main__':
    with worker_app.app_context():
        try:
            database.create_all()
        except Exception as e:
            log.critical(f"DB Error: {e}")
    start_worker()