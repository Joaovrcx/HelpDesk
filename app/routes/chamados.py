"""Rotas de chamados (funcionários e técnicos).

As permissões são verificadas AQUI, no servidor, e não apenas escondendo
botões na interface:
- Funcionário: só abre chamados e só enxerga os próprios.
- Técnico: enxerga chamados disponíveis e os que assumiu; só altera os que
  assumiu.
- Chamado fora do alcance do usuário responde 404 (não revela que existe).
- Técnico que enxerga o chamado, mas não é o responsável, recebe 403.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import services
from app.decorators import tipo_required
from app.extensions import db
from app.forms import ChamadoForm, ComentarioForm, ConclusaoForm
from app.models import (
    PRIORIDADE_LABELS,
    STATUS_LABELS,
    TIPO_FUNCIONARIO,
    TIPO_TECNICO,
    Chamado,
)

chamados_bp = Blueprint("chamados", __name__, url_prefix="/chamados")

_TITULOS_ESCOPO = {
    "disponiveis": "Chamados disponíveis",
    "meus": "Meus atendimentos",
    "todos": "Todos os chamados visíveis",
}


def _usuario():
    return current_user._get_current_object()


def _filtro(valor, validos):
    """Aceita só valores conhecidos; qualquer outra coisa vira 'sem filtro'."""
    return valor if valor in validos else ""


def _erros(form):
    return " ".join(msg for erros in form.errors.values() for msg in erros)


def _chamado_do_tecnico(chamado_id, usuario):
    """Chamado que o técnico enxerga E é responsável; caso contrário, erro."""
    chamado = services.obter_chamado_visivel(chamado_id, usuario)
    if chamado is None:
        abort(404)
    if chamado.tecnico_id != usuario.id:
        abort(403)  # visível (disponível), mas ainda não assumido por ele
    return chamado


@chamados_bp.route("/")
@login_required
def lista():
    usuario = _usuario()
    status = _filtro(request.args.get("status"), STATUS_LABELS)
    prioridade = _filtro(request.args.get("prioridade"), PRIORIDADE_LABELS)

    if usuario.is_tecnico:
        escopo = _filtro(request.args.get("escopo"), services.ESCOPOS_TECNICO) or "disponiveis"
        titulo = _TITULOS_ESCOPO[escopo]
    else:
        escopo = None
        titulo = "Meus chamados"

    chamados = services.listar_chamados(
        usuario, status=status, prioridade=prioridade, escopo=escopo
    )
    return render_template(
        "chamados/lista.html",
        chamados=chamados,
        titulo_pagina=titulo,
        filtros={"status": status, "prioridade": prioridade, "escopo": escopo},
    )


@chamados_bp.route("/novo", methods=["GET", "POST"])
@tipo_required(TIPO_FUNCIONARIO)
def novo():
    form = ChamadoForm()
    if form.validate_on_submit():
        chamado = services.criar_chamado(
            _usuario(),
            titulo=form.titulo.data,
            descricao=form.descricao.data,
            categoria=form.categoria.data,
            prioridade=form.prioridade.data,
        )
        flash("Chamado aberto com sucesso!", "success")
        return redirect(url_for("chamados.detalhe", chamado_id=chamado.id))
    elif request.method == "POST":
        flash("Não foi possível abrir o chamado. Corrija os campos indicados.", "danger")
    return render_template("chamados/novo.html", form=form)


@chamados_bp.route("/<int:chamado_id>")
@login_required
def detalhe(chamado_id):
    usuario = _usuario()
    chamado = services.obter_chamado_visivel(chamado_id, usuario)
    if chamado is None:
        abort(404)

    eh_responsavel = usuario.is_tecnico and chamado.tecnico_id == usuario.id
    pode_assumir = (
        usuario.is_tecnico
        and chamado.esta_disponivel
        and chamado.solicitante_id != usuario.id
    )
    return render_template(
        "chamados/detalhe.html",
        chamado=chamado,
        eh_responsavel=eh_responsavel,
        pode_assumir=pode_assumir,
    )


@chamados_bp.route("/<int:chamado_id>/assumir", methods=["POST"])
@tipo_required(TIPO_TECNICO)
def assumir(chamado_id):
    if db.session.get(Chamado, chamado_id) is None:
        abort(404)

    if services.assumir_chamado(chamado_id, _usuario()):
        flash("Você assumiu o atendimento deste chamado.", "success")
        return redirect(url_for("chamados.detalhe", chamado_id=chamado_id))

    flash("Este chamado não está mais disponível para ser assumido.", "warning")
    return redirect(url_for("chamados.lista"))


@chamados_bp.route("/<int:chamado_id>/comentarios", methods=["POST"])
@tipo_required(TIPO_TECNICO)
def comentar(chamado_id):
    usuario = _usuario()
    _chamado_do_tecnico(chamado_id, usuario)

    form = ComentarioForm()
    if form.validate_on_submit():
        if services.adicionar_comentario(chamado_id, usuario, form.texto.data):
            flash("Comentário registrado.", "success")
        else:
            flash(
                "Não foi possível registrar o comentário: o chamado não está em andamento.",
                "warning",
            )
    else:
        flash(_erros(form), "danger")
    return redirect(url_for("chamados.detalhe", chamado_id=chamado_id))


@chamados_bp.route("/<int:chamado_id>/concluir", methods=["POST"])
@tipo_required(TIPO_TECNICO)
def concluir(chamado_id):
    usuario = _usuario()
    _chamado_do_tecnico(chamado_id, usuario)

    form = ConclusaoForm()
    if form.validate_on_submit():
        if services.concluir_chamado(chamado_id, usuario, form.solucao.data):
            flash("Chamado concluído com sucesso.", "success")
        else:
            flash(
                "Não foi possível concluir: o chamado não está em andamento sob sua responsabilidade.",
                "warning",
            )
    else:
        flash(_erros(form), "danger")
    return redirect(url_for("chamados.detalhe", chamado_id=chamado_id))
