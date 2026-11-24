"""Páginas de erro amigáveis."""

from flask import render_template
from flask_wtf.csrf import CSRFError


def _pagina_erro(codigo, titulo, mensagem):
    return render_template("errors/error.html", codigo=codigo, titulo=titulo, mensagem=mensagem), codigo


def register_error_handlers(app):
    @app.errorhandler(403)
    def acesso_negado(erro):
        return _pagina_erro(
            403,
            "Acesso negado",
            "Você não tem permissão para acessar esta página.",
        )

    @app.errorhandler(404)
    def nao_encontrado(erro):
        return _pagina_erro(
            404,
            "Página não encontrada",
            "O endereço acessado não existe.",
        )

    @app.errorhandler(CSRFError)
    def csrf_invalido(erro):
        return _pagina_erro(
            400,
            "Formulário inválido ou expirado",
            "Não foi possível validar o formulário. Volte, recarregue a página e tente novamente.",
        )
