"""Regras de negócio dos chamados.

Todas as mudanças de estado usam um UPDATE condicional ("só atualiza se o
chamado ainda estiver no estado esperado") e conferem quantas linhas foram
alteradas. Como o banco executa cada UPDATE de forma atômica, dois técnicos
que tentam assumir o mesmo chamado ao mesmo tempo nunca conseguem os dois:
um UPDATE altera 1 linha e o outro altera 0.
"""

from datetime import timedelta

from flask import current_app
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import (
    EVENTO_ABERTURA,
    EVENTO_ASSUMIDO,
    EVENTO_COMENTARIO,
    EVENTO_CONCLUSAO,
    PRIORIDADE_ALTA,
    PRIORIDADE_LABELS,
    PRIORIDADE_MEDIA,
    STATUS_ABERTO,
    STATUS_CONCLUIDO,
    STATUS_EM_ANDAMENTO,
    STATUS_LABELS,
    Chamado,
    HistoricoChamado,
    agora_utc,
)
from app.indicadores import (
    barra_status,
    barras_prioridade,
    contar_chaves,
    contar_desde,
    resumir_espera,
    serie_dupla,
    tempo_medio,
)
from app.utils import inicio_do_dia_local_em_utc, naive_utc

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


def listar_chamados(usuario, status="", prioridade="", escopo=None, limite=None, categoria=""):
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
    if categoria:
        consulta = consulta.where(Chamado.categoria == categoria)

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


def _parametros_tempo(agora, horas_fuso, limite_alerta_horas):
    """Resolve 'agora', o fuso e o limite do alerta (da configuração, se omitidos).

    Os parâmetros existem para que os testes possam fixar a data e o limite.
    """
    configuracao = current_app.config
    agora = naive_utc(agora if agora is not None else agora_utc())
    if horas_fuso is None:
        horas_fuso = configuracao.get("FUSO_HORARIO_HORAS", -3)
    if limite_alerta_horas is None:
        limite_alerta_horas = configuracao.get("ALERTA_ESPERA_HORAS", 24)
    return agora, horas_fuso, limite_alerta_horas


def _ultimas_atualizacoes(usuario, limite=5):
    """Últimos eventos (assumido, comentário, conclusão) dos chamados DO usuário."""
    consulta = (
        select(HistoricoChamado)
        .join(Chamado, HistoricoChamado.chamado_id == Chamado.id)
        .where(
            Chamado.solicitante_id == usuario.id,
            HistoricoChamado.tipo != EVENTO_ABERTURA,
        )
        .options(joinedload(HistoricoChamado.autor), joinedload(HistoricoChamado.chamado))
        .order_by(HistoricoChamado.criado_em.desc(), HistoricoChamado.id.desc())
        .limit(limite)
    )
    return db.session.execute(consulta).unique().scalars().all()


def resumo_funcionario(usuario, agora=None, horas_fuso=None, limite_alerta_horas=None):
    """Dados do dashboard do funcionário.

    "contagem" e "recentes" são as chaves originais (cobertas por testes). As
    demais são os indicadores da Etapa 4. Toda consulta é restrita aos chamados
    abertos pelo próprio usuário.
    """
    agora, horas, limite = _parametros_tempo(agora, horas_fuso, limite_alerta_horas)
    meus = Chamado.solicitante_id == usuario.id
    contagem = contar_por_status(meus)

    # Chamados ainda não concluídos: prioridade e tempo de espera
    pendentes = db.session.execute(
        select(Chamado.id, Chamado.prioridade, Chamado.status, Chamado.criado_em).where(
            meus, Chamado.status != STATUS_CONCLUIDO
        )
    ).all()
    aguardando = [(p.id, p.criado_em) for p in pendentes if p.status == STATUS_ABERTO]

    # Tempo médio de resolução (abertura até conclusão)
    concluidos = db.session.execute(
        select(Chamado.criado_em, Chamado.concluido_em).where(
            meus, Chamado.status == STATUS_CONCLUIDO, Chamado.concluido_em.is_not(None)
        )
    ).all()

    # Janela de 7 dias: abertos (criado_em) e concluídos (concluido_em)
    inicio_7d = inicio_do_dia_local_em_utc(agora, horas, dias_atras=6)
    janela = db.session.execute(
        select(Chamado.criado_em, Chamado.concluido_em).where(
            meus, or_(Chamado.criado_em >= inicio_7d, Chamado.concluido_em >= inicio_7d)
        )
    ).all()

    return {
        "contagem": contagem,
        "recentes": listar_chamados(usuario, limite=5),
        # --- Etapa 4 ---
        "total_chamados": sum(contagem.values()),
        "barra_status": barra_status(contagem, STATUS_LABELS),
        "por_prioridade": barras_prioridade(
            contar_chaves((p.prioridade for p in pendentes), PRIORIDADE_LABELS),
            PRIORIDADE_LABELS,
        ),
        "espera": resumir_espera(aguardando, agora, limite),
        "tempo_medio_resolucao": tempo_medio([(c.criado_em, c.concluido_em) for c in concluidos]),
        "ultimas_atualizacoes": _ultimas_atualizacoes(usuario),
        "serie_7_dias": serie_dupla(
            [j.criado_em for j in janela],
            [j.concluido_em for j in janela],
            agora, "abertos", "concluidos", dias=7, horas=horas,
        ),
        "limite_alerta_horas": limite,
    }


def resumo_tecnico(usuario, agora=None, horas_fuso=None, limite_alerta_horas=None):
    """Dados do dashboard do técnico.

    Privacidade: a fila (chamados disponíveis) é visível a qualquer técnico; todos
    os demais indicadores usam somente chamados e eventos DO PRÓPRIO técnico.
    Não há dados sobre outros técnicos.
    """
    agora, horas, limite = _parametros_tempo(agora, horas_fuso, limite_alerta_horas)
    meus = contar_por_status(Chamado.tecnico_id == usuario.id)
    total_disponiveis = db.session.scalar(
        select(func.count(Chamado.id)).where(_disponivel())
    )
    meus_ativos = listar_chamados(usuario, escopo="meus", status=STATUS_EM_ANDAMENTO)

    # Fila de chamados disponíveis: prioridade e tempo de espera
    fila = db.session.execute(
        select(Chamado.id, Chamado.prioridade, Chamado.criado_em).where(_disponivel())
    ).all()

    # Conclusões do técnico nos últimos 30 dias
    inicio_hoje = inicio_do_dia_local_em_utc(agora, horas)
    inicio_7d = inicio_do_dia_local_em_utc(agora, horas, dias_atras=6)
    inicio_30d = inicio_do_dia_local_em_utc(agora, horas, dias_atras=29)
    conclusoes = db.session.scalars(
        select(Chamado.concluido_em).where(
            Chamado.tecnico_id == usuario.id,
            Chamado.status == STATUS_CONCLUIDO,
            Chamado.concluido_em >= inicio_30d,
        )
    ).all()

    # Tempo médio de resolução dos chamados concluídos pelo técnico
    concluidos = db.session.execute(
        select(Chamado.criado_em, Chamado.concluido_em).where(
            Chamado.tecnico_id == usuario.id,
            Chamado.status == STATUS_CONCLUIDO,
            Chamado.concluido_em.is_not(None),
        )
    ).all()

    # Chamados que o técnico assumiu nos últimos 7 dias (evento do próprio técnico)
    assumidos = db.session.scalars(
        select(HistoricoChamado.criado_em).where(
            HistoricoChamado.tipo == EVENTO_ASSUMIDO,
            HistoricoChamado.autor_id == usuario.id,
            HistoricoChamado.criado_em >= inicio_7d,
        )
    ).all()

    # Atendimentos em andamento sem atualização há mais tempo que o limite do alerta
    limite_parado = agora - timedelta(hours=limite)
    ids_parados = [c.id for c in meus_ativos if naive_utc(c.atualizado_em) < limite_parado]

    return {
        "total_disponiveis": total_disponiveis,
        "em_andamento": meus[STATUS_EM_ANDAMENTO],
        "concluidos": meus[STATUS_CONCLUIDO],
        "disponiveis": listar_chamados(usuario, escopo="disponiveis", limite=5),
        "meus_ativos": meus_ativos,
        # --- Etapa 4 ---
        "fila_por_prioridade": barras_prioridade(
            contar_chaves((f.prioridade for f in fila), PRIORIDADE_LABELS),
            PRIORIDADE_LABELS,
        ),
        "espera_fila": resumir_espera([(f.id, f.criado_em) for f in fila], agora, limite),
        "carga_por_prioridade": barras_prioridade(
            contar_chaves((c.prioridade for c in meus_ativos), PRIORIDADE_LABELS),
            PRIORIDADE_LABELS,
        ),
        "concluidos_hoje": contar_desde(conclusoes, inicio_hoje),
        "concluidos_7_dias": contar_desde(conclusoes, inicio_7d),
        "concluidos_30_dias": len(conclusoes),
        "tempo_medio_resolucao": tempo_medio([(c.criado_em, c.concluido_em) for c in concluidos]),
        "ids_parados": ids_parados,
        "serie_7_dias": serie_dupla(
            assumidos, conclusoes, agora, "assumidos", "concluidos", dias=7, horas=horas,
        ),
        "limite_alerta_horas": limite,
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
