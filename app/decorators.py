"""Decorators de controle de acesso."""

from functools import wraps

from flask import abort
from flask_login import current_user

from app.extensions import login_manager


def tipo_required(*tipos):
    """Permite acesso apenas a usuários autenticados de certos tipos.

    Uso:
        @painel_bp.route("/tecnico")
        @tipo_required(TIPO_TECNICO)
        def area_tecnico(): ...

    - Não autenticado -> redirecionado para o login (com mensagem).
    - Autenticado com tipo não permitido -> erro 403 (acesso negado).
    """

    def decorador(view):
        @wraps(view)
        def protegida(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.tipo not in tipos:
                abort(403)
            return view(*args, **kwargs)

        return protegida

    return decorador
