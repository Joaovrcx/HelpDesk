"""Pacote principal do HelpDesk.

Aqui fica a Application Factory: a função create_app() monta e devolve
a aplicação Flask já configurada. Esse padrão facilita testes e a
adição de extensões (banco de dados, login, formulários).
"""

import os

from flask import Flask

from app.extensions import csrf, db, login_manager
from config import DEFAULT_SECRET_KEY, Config


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Garante que a pasta instance/ exista (guarda o banco SQLite)
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config["SECRET_KEY"] == DEFAULT_SECRET_KEY and not (app.debug or app.testing):
        app.logger.warning(
            "SECRET_KEY padrão em uso. Defina uma chave própria no arquivo .env."
        )

    # Extensões
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Os modelos precisam ser importados para o SQLAlchemy conhecer as tabelas
    from app import models  # noqa: F401

    # Registro dos blueprints (grupos de rotas)
    from app.routes.auth import auth_bp
    from app.routes.chamados import chamados_bp
    from app.routes.main import main_bp
    from app.routes.painel import painel_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(painel_bp)
    app.register_blueprint(chamados_bp)

    # Páginas de erro e comandos administrativos
    from app.cli import register_commands
    from app.errors import register_error_handlers

    register_error_handlers(app)
    register_commands(app)

    # Recursos disponíveis em todos os templates (inclusive dentro de macros)
    from app.utils import formatar_datahora

    horas = app.config.get("FUSO_HORARIO_HORAS", -3)
    app.jinja_env.filters["datahora"] = lambda valor: formatar_datahora(valor, horas)
    app.jinja_env.globals.update(
        STATUS_LABELS=models.STATUS_LABELS,
        PRIORIDADE_LABELS=models.PRIORIDADE_LABELS,
        CATEGORIA_LABELS=models.CATEGORIA_LABELS,
        EVENTO_LABELS=models.EVENTO_LABELS,
    )

    # Cria as tabelas que ainda não existem. Tabelas existentes (como
    # "usuarios") NÃO são alteradas nem apagadas.
    with app.app_context():
        db.create_all()

    return app
