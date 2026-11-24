"""Instâncias das extensões Flask.

Ficam em um módulo separado para evitar importações circulares: elas são
criadas aqui "vazias" e ligadas à aplicação em create_app() com init_app().
"""

import sqlite3

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _ativar_chaves_estrangeiras(dbapi_connection, connection_record):
    """O SQLite não aplica chaves estrangeiras por padrão; aqui ativamos."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


csrf = CSRFProtect()

login_manager = LoginManager()
# Para onde redirecionar quem tenta acessar uma página protegida sem login
login_manager.login_view = "auth.login"
login_manager.login_message = "Faça login para acessar esta página."
login_manager.login_message_category = "warning"
# Se o IP/navegador da sessão mudar, a sessão é invalidada
login_manager.session_protection = "strong"
