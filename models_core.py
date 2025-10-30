from datetime import datetime
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import ForeignKey, Boolean, Text, Integer, String, DateTime
from pytz import timezone
import json
from flask_login import UserMixin


# --- Funções de Ajuda ---
def now_brazil():
    """Retorna a data e hora atual no fuso horário de Brasília."""
    fuso_brasilia = timezone('America/Sao_Paulo')
    return datetime.now(fuso_brasilia)


# --- Função Principal para Ligar os Modelos ao DB ---
def define_models(db_instance):
    """
    Define e retorna as classes Usuario, Estudo e Questao, ligando-as à instância do DB
    passada como argumento (db_instance).
    """

    # --- MODELO USUARIO (COPIADO DO FLASK) ---
    class Usuario(db_instance.Model, UserMixin):
        __tablename__ = 'usuario'  # Garante o mesmo nome de tabela do Flask
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        foto_perfil: Mapped[str | None] = mapped_column(Text, nullable=True)
        nome: Mapped[str] = mapped_column(String(100), nullable=False)
        cpf: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
        whatsapp: Mapped[str] = mapped_column(String(15), nullable=False)
        email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
        senha: Mapped[str] = mapped_column(String(200), nullable=False)
        data_cadastro: Mapped[datetime] = mapped_column(DateTime, default=now_brazil, nullable=False)
        is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
        is_validated: Mapped[bool] = mapped_column(Boolean, default=False)

        estudos: Mapped[list["Estudo"]] = relationship("Estudo", back_populates="usuario")

    # --- MODELO ESTUDO ---
    class Estudo(db_instance.Model):
        __tablename__ = 'estudos'

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        user_id: Mapped[int] = mapped_column(Integer, ForeignKey('usuario.id'), nullable=False)
        titulo: Mapped[str] = mapped_column(String(255), nullable=False)
        data_criacao: Mapped[datetime] = mapped_column(DateTime, default=now_brazil)
        resumo: Mapped[str] = mapped_column(Text, nullable=False)
        status: Mapped[str] = mapped_column(String(50), default='processando', nullable=False)
        caminho_arquivo: Mapped[str | None] = mapped_column(String(512), nullable=True)

        questoes: Mapped[list["Questao"]] = relationship("Questao", back_populates="estudo", lazy='dynamic',
                                                         cascade="all, delete-orphan")
        usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="estudos")

    # --- MODELO QUESTAO ---
    class Questao(db_instance.Model):
        __tablename__ = 'questoes'

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        estudo_id: Mapped[int] = mapped_column(Integer, ForeignKey('estudos.id'), nullable=False)

        pergunta: Mapped[str] = mapped_column(Text, nullable=False)
        opcoes_json: Mapped[str] = mapped_column(Text, nullable=False)
        resposta_correta: Mapped[str] = mapped_column(String(255), nullable=False)

        resposta_usuario: Mapped[str | None] = mapped_column(String(255), nullable=True)
        correta: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

        estudo: Mapped["Estudo"] = relationship("Estudo", back_populates="questoes")

        @property
        def opcoes(self):
            try:
                return json.loads(self.opcoes_json)
            except json.JSONDecodeError:
                return []

    return Usuario, Estudo, Questao

