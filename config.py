"""Configurações da aplicação HelpDesk.

As configurações sensíveis (como SECRET_KEY) são lidas de variáveis de
ambiente, que podem ser definidas em um arquivo .env na raiz do projeto.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Carrega as variáveis do arquivo .env (se ele existir)
load_dotenv(BASE_DIR / ".env")

# Valor usado apenas quando nenhuma SECRET_KEY é definida no .env.
# A aplicação emite um aviso se ele for usado fora do modo debug.
DEFAULT_SECRET_KEY = "chave-de-desenvolvimento-troque-isto"


def _fuso_horas():
    """Diferença para UTC (em horas) usada ao exibir datas. Padrão: -3 (Brasília)."""
    try:
        return int(os.environ.get("FUSO_HORARIO_HORAS", "-3"))
    except ValueError:
        return -3


def _alerta_espera_horas():
    """Limite (em horas) para destacar chamados parados. Padrão: 24."""
    try:
        valor = int(os.environ.get("ALERTA_ESPERA_HORAS", "24"))
    except ValueError:
        return 24
    return valor if valor > 0 else 24


class Config:
    """Configuração base, usada em qualquer ambiente."""

    # As datas são guardadas em UTC e exibidas com esta diferença de horas.
    FUSO_HORARIO_HORAS = _fuso_horas()

    # Alerta VISUAL nos dashboards: chamados abertos (ou atendimentos sem
    # atualização) há mais de N horas ganham destaque. Não é um prazo (SLA).
    ALERTA_ESPERA_HORAS = _alerta_espera_horas()

    # Chave usada para assinar sessões e proteger formulários (CSRF).
    # Em produção, SEMPRE defina uma chave própria no arquivo .env.
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

    # Modo debug: ative com FLASK_DEBUG=1 no .env
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

    # Banco de dados SQLite.
    # Um caminho relativo em "sqlite:///" é resolvido pelo Flask-SQLAlchemy
    # dentro da pasta instance/, então o arquivo fica em instance/helpdesk.db
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///helpdesk.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cookies de sessão: inacessíveis ao JavaScript e não enviados em
    # requisições cross-site. Em produção com HTTPS, ative também
    # SESSION_COOKIE_SECURE e REMEMBER_COOKIE_SECURE.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"


class TestingConfig(Config):
    """Configuração usada pelos testes automatizados (pasta tests/)."""

    TESTING = True
    DEBUG = False
    SECRET_KEY = "chave-somente-para-testes"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
