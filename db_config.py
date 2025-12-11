import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from models_core import define_models
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

load_dotenv()

worker_app = Flask(__name__)
database_url = os.getenv('DATABASE_URL')

if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    log.info("Ambiente de PRODUÇÃO detectado. Usando banco de dados externo.")
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, 'local_worker.db')
    database_url = f'sqlite:///{db_path}'
    log.warning(f"DATABASE_URL não encontrada. Usando SQLite Local: {database_url}")

worker_app.config['SQLALCHEMY_DATABASE_URI'] = database_url
worker_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
worker_app.config['DEEPSEEK_API_KEY'] = os.getenv('DEEPSEEK_API_KEY')
worker_app.config['AI_TIMEOUT_SECONDS'] = int(os.getenv('AI_TIMEOUT_SECONDS', 120))
worker_app.config['AI_MAX_TOKENS'] = int(os.getenv('AI_MAX_TOKENS', 1500))

database = SQLAlchemy(worker_app)

Usuario, Estudo, Questao = define_models(database)
log.info("Modelos ligados com sucesso.")