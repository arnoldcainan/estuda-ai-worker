import pika
import json
import time
import os
import logging
import requests
from sqlalchemy import text

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- IMPORTS DO CORE DO WORKER ---
# Importa o setup de DB e os modelos JÁ LIGADOS
# O erro anterior ocorria aqui se db_config falhasse ao importar models_core
from db_config import worker_app, database, Estudo, Questao
# Importa a lógica de IA do arquivo local
from ai_processor import process_study_material

# ----------------------------------

# --- Configurações do RabbitMQ: Lendo do .env ---
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
QUEUE_NAME = 'ai_task_queue'


# -----------------------------------------------

def update_db_on_failure(estudo_id, error_msg):
    """Atualiza o status do DB quando a IA falha."""
    with worker_app.app_context():
        try:
            # Usa a classe Estudo importada
            estudo = database.session.get(Estudo, estudo_id)  # Usar session.get para SQLAlchemy 2.0+
            if estudo:
                estudo.status = 'falha'
                # Limita a mensagem de erro
                estudo.resumo = f"Falha no processamento: {error_msg[:1000]}"
                database.session.commit()
                log.error(f"Tarefa {estudo_id} falhou. Status atualizado no DB.")
        except Exception as e:
            log.critical(f"ERRO CRÍTICO ao atualizar falha no DB para {estudo_id}: {e}", exc_info=True)
            database.session.rollback()


def callback(ch, method, properties, body):
    """Função chamada quando uma nova mensagem é recebida da fila."""

    payload = json.loads(body)
    estudo_id = payload.get('estudo_id')
    file_path = payload.get('file_path')

    # Validação básica do payload
    if not estudo_id or not file_path:
        log.error(f"Mensagem inválida recebida (sem estudo_id ou file_path): {payload}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # Rejeita a mensagem
        return

    log.info(f"Recebida Tarefa para Estudo ID: {estudo_id}. Arquivo: {file_path}")

    # --- 1. CHAMA O PROCESSO DE IA BLOQUEANTE ---
    try:
        log.info(f"[AI WORKER] Verificando existência do arquivo em: {file_path}")
        if not os.path.exists(file_path):
            log.error(f"Arquivo {file_path} não encontrado no Worker para Estudo ID {estudo_id}.")
            raise FileNotFoundError(f"Arquivo {file_path} não encontrado.")

        log.info(f"Arquivo {file_path} encontrado. Iniciando IA...")
        ia_result = process_study_material(file_path)  # Assumindo que está no mesmo diretório

        if ia_result['status'] == 'completed':

            # 2. PERSISTÊNCIA DOS RESULTADOS NO DB
            with worker_app.app_context():
                # Agora 'Estudo' e 'Questao' são os modelos reais do DB
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
                    log.info(f"Sucesso! Estudo ID {estudo_id} atualizado para 'pronto' e QCM salvo.")

                    # 3. Limpa o arquivo local
                    try:
                        os.remove(file_path)
                        log.info(f"Arquivo temporário {file_path} removido.")
                    except OSError as e:
                        log.error(f"Erro ao remover arquivo {file_path}: {e}")

                # --- SUCESSO: ENVIA O ACK ---
                ch.basic_ack(delivery_tag=method.delivery_tag)
                log.info(f"Tarefa {estudo_id} concluída com sucesso e ACK enviado.")

        else:
            # Se o status da IA for 'failed'
            error_msg = ia_result.get('error', 'Erro desconhecido da IA.')
            # Lança uma exceção para ser pega pelo bloco 'except' abaixo
            raise Exception(f"Falha no processamento de IA: {error_msg}")

    except FileNotFoundError as e:
        log.error(f"Erro de Arquivo para ID {estudo_id}: {e}")
        update_db_on_failure(estudo_id, f"Erro: Arquivo original não encontrado ou inacessível.")
        # Rejeita a mensagem (NACK) - não adianta tentar de novo (requeue=False)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except Exception as e:
        # Pega a falha da IA ou qualquer outro erro de execução
        log.exception(f"ERRO DE EXECUÇÃO no Worker para ID {estudo_id}: {e}")
        update_db_on_failure(estudo_id, f"Erro interno do Worker: {str(e)[:500]}")
        # Rejeita a mensagem (NACK) - não tente de novo por enquanto (requeue=False)
        # Mude para requeue=True se quiser que ele tente novamente após uma falha
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    # REMOVA o 'basic_ack' que estava aqui fora

def start_worker():
    """Inicia a conexão e o consumo de mensagens."""
    log.info("------------------------------------------------")
    log.info("AI-WORKER: Tentando conectar ao RabbitMQ...")
    log.info(f"Host: {RABBITMQ_HOST}, User: {RABBITMQ_USER}, VHost: {RABBITMQ_VHOST}")
    log.info("------------------------------------------------")

    retries = 5
    for attempt in range(retries):
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
            # Garante que a fila existe e é durável
            channel.queue_declare(queue=QUEUE_NAME, durable=True)

            log.info(f"Conexão bem-sucedida! Escutando fila: {QUEUE_NAME}")

            # Processa apenas uma mensagem por vez
            channel.basic_qos(prefetch_count=1)
            # Inicia o consumo
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

            log.info("Aguardando mensagens... (Pressione CTRL+C para sair)")
            channel.start_consuming()  # Bloqueia aqui

        except pika.exceptions.AMQPConnectionError as e:
            log.warning(f"Tentativa {attempt + 1}/{retries} falhou: Falha na conexão AMQP. Esperando 5s... Erro: {e}")
            time.sleep(5)

        except KeyboardInterrupt:
            log.info("Encerrando worker por comando do usuário...")
            if connection and connection.is_open:
                connection.close()
            break

        except Exception as e:
            log.critical(f"Erro fatal ao iniciar worker: {e}", exc_info=True)
            if connection and connection.is_open:
                connection.close()
            break

    log.info("AI-WORKER finalizado.")


if __name__ == '__main__':
    # Cria o contexto inicial APENAS para garantir que a conexão funciona
    with worker_app.app_context():
        log.info("Verificando conexão com o banco de dados...")
        try:
            # # Tenta uma operação simples para verificar a conexão
            # # (Você precisará de 'from sqlalchemy import text' no topo)
            # database.session.execute(text('SELECT 1'))
            # log.info("Conexão com o DB verificada com sucesso.")

            # CORRIGIDO: Recria o create_all()
            database.create_all()  # Garante que todas as tabelas existam
            log.info("Verificação/Criação de tabelas do DB concluída.")


        except Exception as e:
            log.critical(f"Erro CRÍTICO ao conectar ao DB no início: {e}", exc_info=True)
            exit(1)  # Não continua se o DB não estiver acessível

    # REMOVIDO: database.create_all()

    start_worker()  # Inicia o loop principal do worker