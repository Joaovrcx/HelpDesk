"""Área restrita (exige login) com acesso diferenciado por tipo de usuário.

- /painel              : perfil do usuário (qualquer usuário autenticado)
- /painel/funcionario  : dashboard do funcionário
- /painel/tecnico      : dashboard do técnico
"""

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app import services
from app.decorators import tipo_required
from app.models import TIPO_FUNCIONARIO, TIPO_TECNICO

painel_bp = Blueprint("painel", __name__, url_prefix="/painel")


@painel_bp.route("")
@login_required
def index():
    """Painel inicial: qualquer usuário autenticado."""
    return render_template("painel/index.html")


@painel_bp.route("/funcionario")
@tipo_required(TIPO_FUNCIONARIO)
def area_funcionario():
    """Dashboard exclusivo de funcionários."""
    resumo = services.resumo_funcionario(current_user._get_current_object())
    return render_template("painel/funcionario.html", **resumo)


@painel_bp.route("/tecnico")
@tipo_required(TIPO_TECNICO)
def area_tecnico():
    """Dashboard exclusivo de técnicos."""
    resumo = services.resumo_tecnico(current_user._get_current_object())
    return render_template("painel/tecnico.html", **resumo)
