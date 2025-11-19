import pika
import json
import time
import os
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Imports do Projeto
from db_config import worker_app, database, Estudo, Questao
from ai_processor import process_study_material

# --- Configurações do RabbitMQ ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
QUEUE_NAME = 'ai_task_queue'

# --- CONFIGURAÇÃO DE CAMINHOS (CRÍTICO PARA O DOCKER) ---
# Define onde os uploads estão montados dentro do container Linux.
# Assumindo que seu Dockerfile define WORKDIR como /app e copia o projeto para lá.
BASE_DIR = os.getcwd()
UPLOAD_FOLDER_WORKER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')


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
    """Função chamada quando uma nova mensagem é recebida da fila."""

    try:
        payload = json.loads(body)

        # 1. Ler o ID e o NOME DO ARQUIVO (filename)
        # Nota: O Flask agora envia 'filename', não mais o caminho completo 'file_path'
        estudo_id = payload.get('estudo_id')
        filename = payload.get('filename')

        # Validação Básica
        if not estudo_id or not filename:
            log.error(f"Mensagem inválida recebida (sem estudo_id ou filename): {payload}")
            # Rejeita sem recolocar na fila para evitar loop infinito de erro
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        # 2. Reconstruir o caminho completo no ambiente Linux
        file_path = os.path.join(UPLOAD_FOLDER_WORKER, filename)

        log.info(f"Recebida Tarefa para Estudo ID: {estudo_id}. Arquivo: {filename}")
        log.info(f"[AI WORKER] Buscando arquivo em: {file_path}")

        # 3. Verificar se o arquivo existe (Volume do Docker)
        if not os.path.exists(file_path):
            log.error(f"Arquivo não encontrado no caminho: {file_path}")
            log.error(f"Verifique se o volume do Docker está mapeado corretamente em {UPLOAD_FOLDER_WORKER}")
            raise FileNotFoundError(f"Arquivo {filename} não encontrado no disco.")

        log.info("Arquivo encontrado. Iniciando processamento de IA...")

        # 4. Processar com a IA
        ia_result = process_study_material(file_path)

        if ia_result['status'] == 'completed':
            with worker_app.app_context():
                estudo = database.session.get(Estudo, estudo_id)
                if estudo:
                    estudo.resumo = ia_result['resumo']
                    estudo.status = 'pronto'

                    # Limpa questões antigas se houver (reprocessamento)
                    qcm_data = ia_result['qcm_json']
                    Questao.query.filter_by(estudo_id=estudo.id).delete()
                    database.session.flush()

                    # Salva novas questões
                    for q_data in qcm_data['questoes']:
                        nova_questao = Questao(
                            estudo_id=estudo.id,
                            pergunta=q_data['pergunta'],
                            opcoes_json=json.dumps(q_data['opcoes']),
                            resposta_correta=q_data['resposta_correta']
                        )
                        database.session.add(nova_questao)

                    database.session.commit()
                    log.info(f"Sucesso! Estudo ID {estudo_id} salvo e pronto.")

                    # Remove arquivo temporário
                    try:
                        os.remove(file_path)
                        log.info(f"Arquivo temporário {filename} removido.")
                    except OSError as e:
                        log.warning(f"Não foi possível remover arquivo {filename}: {e}")

                # Confirma sucesso para o RabbitMQ
                ch.basic_ack(delivery_tag=method.delivery_tag)
                log.info(f"Tarefa {estudo_id} finalizada.")

        else:
            error_msg = ia_result.get('error', 'Erro desconhecido da IA.')
            raise Exception(f"Retorno de falha da IA: {error_msg}")

    except FileNotFoundError as e:
        log.error(f"Erro de Arquivo ID {estudo_id}: {e}")
        update_db_on_failure(estudo_id, "Arquivo não encontrado no servidor.")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except Exception as e:
        log.exception(f"ERRO DE EXECUÇÃO ID {estudo_id}: {e}")
        update_db_on_failure(estudo_id, f"Erro interno: {str(e)[:500]}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_worker():
    """Inicia a conexão e o consumo de mensagens com retry logic."""
    log.info("------------------------------------------------")
    log.info("AI-WORKER INICIANDO...")
    log.info(f"Host: {RABBITMQ_HOST}:{RABBITMQ_PORT}")
    log.info("------------------------------------------------")

    retries = 0
    while True:  # Loop infinito para manter o worker vivo tentando reconectar
        connection = None
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

            # Define QoS para não sobrecarregar a IA (1 por vez)
            channel.basic_qos(prefetch_count=1)

            log.info(f"Conectado! Aguardando tarefas na fila '{QUEUE_NAME}'...")

            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
            channel.start_consuming()

        except pika.exceptions.AMQPConnectionError as e:
            retries += 1
            wait_time = min(retries * 2, 30)  # Backoff exponencial até 30s
            log.warning(f"Falha na conexão (Tentativa {retries}). Reconectando em {wait_time}s... Erro: {e}")
            time.sleep(wait_time)

        except KeyboardInterrupt:
            log.info("Parando worker...")
            if connection and connection.is_open:
                connection.close()
            break
        except Exception as e:
            log.critical(f"Erro inesperado no loop principal: {e}", exc_info=True)
            time.sleep(5)  # Espera antes de tentar reiniciar para não floodar logs


if __name__ == '__main__':
    # Verificação inicial do Banco de Dados
    with worker_app.app_context():
        try:
            database.create_all()
            log.info("Banco de dados verificado/inicializado.")
        except Exception as e:
            log.critical(f"Não foi possível conectar ao DB: {e}")
            # Opcional: exit(1) se o DB for obrigatório para iniciar

    start_worker()