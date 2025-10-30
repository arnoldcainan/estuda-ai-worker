import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from models_core import define_models # Importa a FUNÇÃO
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

load_dotenv()

# --- 1. DEFINIÇÃO DA INSTÂNCIA FLASK MÍNIMA (worker_app) ---
worker_app = Flask(__name__)
# -----------------------------------------------------------

# 2. Configurações
# --- DEBUG PRINT ---
db_url_to_use = os.getenv('DATABASE_URL')
log.info(f"[AI WORKER] Conectando ao Banco de Dados em: {db_url_to_use}")
# ---------------------
# Caminho CORRETO para o DB SQLite do Flask, relativo à raiz do Worker
# Assume que EstudaAi e estuda-ai-worker estão na mesma pasta
db_relative_path = os.path.join('..', 'EstudaAi', 'instance', 'projeto.db')
db_uri_from_env = os.getenv('DATABASE_URL')
db_fallback_uri = 'sqlite:////app/instance/projeto.db'
worker_app.config['SQLALCHEMY_DATABASE_URI'] = db_uri_from_env or db_fallback_uri
worker_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configurações DeepSeek (lidas do .env)
worker_app.config['DEEPSEEK_API_KEY'] = os.getenv('DEEPSEEK_API_KEY')
worker_app.config['AI_TIMEOUT_SECONDS'] = int(os.getenv('AI_TIMEOUT_SECONDS', 120))
worker_app.config['AI_MAX_TOKENS'] = int(os.getenv('AI_MAX_TOKENS', 1500))

# 3. Inicialização do SQLAlchemy
database = SQLAlchemy(worker_app)

# # 4. Ligar os Modelos APÓS o DB ser inicializado
# try:
#     # Esta linha define as classes no escopo deste módulo
#     Estudo, Questao = define_models(database)
# except Exception as e:
#     log.critical(f"Erro CRÍTICO ao ligar modelos! O worker irá falhar. Verifique a conexão DB e a tabela 'usuario'. Erro: {e}", exc_info=True)
#     # Placeholder de falha - Garante que o worker não quebre na importação
#     class Estudo: pass
#     class Questao: pass

# Esta linha agora VAI quebrar se o DB estiver errado, o que é BOM.
Usuario, Estudo, Questao = define_models(database)
log.info("Modelos (Usuario, Estudo, Questao) ligados com sucesso ao DB.")