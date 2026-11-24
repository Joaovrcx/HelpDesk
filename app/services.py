"""Regras de negócio dos chamados.

Todas as mudanças de estado usam um UPDATE condicional ("só atualiza se o
chamado ainda estiver no estado esperado") e conferem quantas linhas foram
alteradas. Como o banco executa cada UPDATE de forma atômica, dois técnicos
que tentam assumir o mesmo chamado ao mesmo tempo nunca conseguem os dois:
um UPDATE altera 1 linha e o outro altera 0.
"""

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import (
    EVENTO_ABERTURA,
    EVENTO_ASSUMIDO,
    EVENTO_COMENTARIO,
    EVENTO_CONCLUSAO,
    PRIORIDADE_ALTA,
    PRIORIDADE_MEDIA,
    STATUS_ABERTO,
    STATUS_CONCLUIDO,
    STATUS_EM_ANDAMENTO,
    STATUS_LABELS,
    Chamado,
    HistoricoChamado,
    agora_utc,
)

# Opções de "exibir" na lista do técnico
ESCOPOS_TECNICO = ("disponiveis", "meus", "todos")

# Alta primeiro, depois média, depois baixa
_RANK_PRIORIDADE = case(
    (Chamado.prioridade == PRIORIDADE_ALTA, 3),
    (Chamado.prioridade == PRIORIDADE_MEDIA, 2),
    else_=1,
)


# ---------------------------------------------------------------------
# Consultas e visibilidade
# ---------------------------------------------------------------------
def _disponivel():
    """Condição SQL: chamado aberto e sem técnico responsável."""
    return and_(Chamado.status == STATUS_ABERTO, Chamado.tecnico_id.is_(None))


def _visibilidade(usuario):
    """Condição SQL com o que o usuário tem permissão de enxergar.

    - Funcionário: apenas os chamados que ele mesmo abriu.
    - Técnico: os chamados disponíveis e os que ele assumiu.
    """
    if usuario.is_tecnico:
        return or_(_disponivel(), Chamado.tecnico_id == usuario.id)
    return Chamado.solicitante_id == usuario.id


def obter_chamado_visivel(chamado_id, usuario):
    """Devolve o chamado (com histórico) se o usuário puder vê-lo; senão None."""
    consulta = (
        select(Chamado)
        .options(
            joinedload(Chamado.solicitante),
            joinedload(Chamado.tecnico),
            selectinload(Chamado.historico).joinedload(HistoricoChamado.autor),
        )
        .where(Chamado.id == chamado_id, _visibilidade(usuario))
    )
    return db.session.execute(consulta).unique().scalar_one_or_none()


def listar_chamados(usuario, status="", prioridade="", escopo=None, limite=None):
    """Lista os chamados que o usuário pode ver, com filtros opcionais."""
    consulta = select(Chamado).options(
        joinedload(Chamado.solicitante), joinedload(Chamado.tecnico)
    )

    if usuario.is_tecnico:
        if escopo == "meus":
            consulta = consulta.where(Chamado.tecnico_id == usuario.id)
        elif escopo == "todos":
            consulta = consulta.where(_visibilidade(usuario))
        else:
            consulta = consulta.where(_disponivel())
    else:
        consulta = consulta.where(Chamado.solicitante_id == usuario.id)

    if status:
        consulta = consulta.where(Chamado.status == status)
    if prioridade:
        consulta = consulta.where(Chamado.prioridade == prioridade)

    if not usuario.is_tecnico:
        consulta = consulta.order_by(Chamado.criado_em.desc(), Chamado.id.desc())
    elif escopo == "meus":
        consulta = consulta.order_by(Chamado.atualizado_em.desc(), Chamado.id.desc())
    else:
        consulta = consulta.order_by(
            _RANK_PRIORIDADE.desc(), Chamado.criado_em.asc(), Chamado.id.asc()
        )

    if limite:
        consulta = consulta.limit(limite)
    return db.session.execute(consulta).unique().scalars().all()


def contar_por_status(condicao):
    """Conta chamados por status, sempre com as três chaves presentes."""
    linhas = db.session.execute(
        select(Chamado.status, func.count(Chamado.id)).where(condicao).group_by(Chamado.status)
    ).all()
    contagem = dict.fromkeys(STATUS_LABELS, 0)
    for status, total in linhas:
        contagem[status] = total
    return contagem


def resumo_funcionario(usuario):
    """Dados do dashboard do funcionário."""
    return {
        "contagem": contar_por_status(Chamado.solicitante_id == usuario.id),
        "recentes": listar_chamados(usuario, limite=5),
    }


def resumo_tecnico(usuario):
    """Dados do dashboard do técnico."""
    meus = contar_por_status(Chamado.tecnico_id == usuario.id)
    total_disponiveis = db.session.scalar(
        select(func.count(Chamado.id)).where(_disponivel())
    )
    return {
        "total_disponiveis": total_disponiveis,
        "em_andamento": meus[STATUS_EM_ANDAMENTO],
        "concluidos": meus[STATUS_CONCLUIDO],
        "disponiveis": listar_chamados(usuario, escopo="disponiveis", limite=5),
        "meus_ativos": listar_chamados(usuario, escopo="meus", status=STATUS_EM_ANDAMENTO),
    }


# ---------------------------------------------------------------------
# Alterações (todas registram o histórico na mesma transação)
# ---------------------------------------------------------------------
def _mudar_se(chamado_id, condicoes, valores):
    """UPDATE condicional. Retorna True se exatamente uma linha foi alterada."""
    resultado = db.session.execute(
        update(Chamado)
        .where(Chamado.id == chamado_id, *condicoes)
        .values(**valores)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount == 1


def criar_chamado(solicitante, titulo, descricao, categoria, prioridade):
    """Abre um chamado para o funcionário. Sempre começa Aberto e sem técnico."""
    agora = agora_utc()
    chamado = Chamado(
        titulo=titulo,
        descricao=descricao,
        categoria=categoria,
        prioridade=prioridade,
        status=STATUS_ABERTO,
        solicitante_id=solicitante.id,
        tecnico_id=None,
        criado_em=agora,
        atualizado_em=agora,
    )
    chamado.historico.append(
        HistoricoChamado(
            autor_id=solicitante.id,
            tipo=EVENTO_ABERTURA,
            status_novo=STATUS_ABERTO,
            descricao="Chamado aberto.",
            criado_em=agora,
        )
    )
    db.session.add(chamado)
    db.session.commit()
    return chamado


def assumir_chamado(chamado_id, tecnico):
    """Técnico assume um chamado disponível; o status passa a Em andamento.

    Retorna True se conseguiu. Retorna False se o chamado não está mais
    disponível (outro técnico assumiu primeiro, já foi concluído, não existe)
    ou se o técnico foi quem abriu o chamado.
    """
    if not tecnico.is_tecnico:
        return False

    agora = agora_utc()
    conseguiu = _mudar_se(
        chamado_id,
        (
            Chamado.status == STATUS_ABERTO,
            Chamado.tecnico_id.is_(None),
            Chamado.solicitante_id != tecnico.id,
        ),
        {
            "tecnico_id": tecnico.id,
            "status": STATUS_EM_ANDAMENTO,
            "atualizado_em": agora,
        },
    )
    if not conseguiu:
        db.session.rollback()
        return False

    db.session.add(
        HistoricoChamado(
            chamado_id=chamado_id,
            autor_id=tecnico.id,
            tipo=EVENTO_ASSUMIDO,
            status_anterior=STATUS_ABERTO,
            status_novo=STATUS_EM_ANDAMENTO,
            descricao=f"{tecnico.nome} assumiu o atendimento.",
            criado_em=agora,
        )
    )
    db.session.commit()
    return True


def adicionar_comentario(chamado_id, tecnico, texto):
    """Registra um comentário do técnico responsável (chamado em andamento)."""
    agora = agora_utc()
    conseguiu = _mudar_se(
        chamado_id,
        (
            Chamado.tecnico_id == tecnico.id,
            Chamado.status == STATUS_EM_ANDAMENTO,
        ),
        {"atualizado_em": agora},
    )
    if not conseguiu:
        db.session.rollback()
        return False

    db.session.add(
        HistoricoChamado(
            chamado_id=chamado_id,
            autor_id=tecnico.id,
            tipo=EVENTO_COMENTARIO,
            descricao=texto,
            criado_em=agora,
        )
    )
    db.session.commit()
    return True


def concluir_chamado(chamado_id, tecnico, solucao):
    """Registra a solução e conclui o chamado (somente o técnico responsável)."""
    agora = agora_utc()
    conseguiu = _mudar_se(
        chamado_id,
        (
            Chamado.tecnico_id == tecnico.id,
            Chamado.status == STATUS_EM_ANDAMENTO,
        ),
        {
            "status": STATUS_CONCLUIDO,
            "solucao": solucao,
            "concluido_em": agora,
            "atualizado_em": agora,
        },
    )
    if not conseguiu:
        db.session.rollback()
        return False

    db.session.add(
        HistoricoChamado(
            chamado_id=chamado_id,
            autor_id=tecnico.id,
            tipo=EVENTO_CONCLUSAO,
            status_anterior=STATUS_EM_ANDAMENTO,
            status_novo=STATUS_CONCLUIDO,
            descricao=solucao,
            criado_em=agora,
        )
    )
    db.session.commit()
    return True
