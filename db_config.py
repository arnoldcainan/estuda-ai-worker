import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from models_core import define_models
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
db_relative_path = os.path.join('..', 'EstudaAi', 'instance', 'projeto.db')
db_uri_from_env = os.getenv('DATABASE_URL')
db_fallback_uri = 'sqlite:////app/instance/projeto.db'
worker_app.config['SQLALCHEMY_DATABASE_URI'] = db_uri_from_env or db_fallback_uri
worker_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

worker_app.config['DEEPSEEK_API_KEY'] = os.getenv('DEEPSEEK_API_KEY')
worker_app.config['AI_TIMEOUT_SECONDS'] = int(os.getenv('AI_TIMEOUT_SECONDS', 120))
worker_app.config['AI_MAX_TOKENS'] = int(os.getenv('AI_MAX_TOKENS', 1500))

database = SQLAlchemy(worker_app)

Usuario, Estudo, Questao = define_models(database)
log.info("Modelos (Usuario, Estudo, Questao) ligados com sucesso ao DB.")