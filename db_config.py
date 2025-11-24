import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from models_core import define_models
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

load_dotenv()

# --- 1. DEFINIÇÃO DA INSTÂNCIA FLASK MÍNIMA (worker_app) ---
worker_app = Flask(__name__)

# --- 2. LÓGICA DE CONEXÃO COM BANCO (Híbrida: Local vs Prod) ---

# Tenta pegar a URL do Railway/Docker
database_url = os.getenv('DATABASE_URL')

if database_url:
    # CORREÇÃO CRÍTICA PARA RAILWAY:
    # O Railway pode enviar "postgres://", mas o SQLAlchemy exige "postgresql://"
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    log.info("Ambiente de PRODUÇÃO detectado. Usando banco de dados externo.")
else:
    # Fallback para Desenvolvimento Local (SQLite)
    # Cria um banco local dentro da pasta do worker para não depender de caminhos absolutos
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, 'local_worker.db')
    database_url = f'sqlite:///{db_path}'
    log.warning(f"DATABASE_URL não encontrada. Usando SQLite Local: {database_url}")

worker_app.config['SQLALCHEMY_DATABASE_URI'] = database_url
worker_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Configurações da IA ---
worker_app.config['DEEPSEEK_API_KEY'] = os.getenv('DEEPSEEK_API_KEY')
worker_app.config['AI_TIMEOUT_SECONDS'] = int(os.getenv('AI_TIMEOUT_SECONDS', 120))
worker_app.config['AI_MAX_TOKENS'] = int(os.getenv('AI_MAX_TOKENS', 1500))

# Inicializa o SQLAlchemy
database = SQLAlchemy(worker_app)

# Liga os modelos
Usuario, Estudo, Questao = define_models(database)
log.info("Modelos ligados com sucesso.")