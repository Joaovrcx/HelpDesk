"""Funções utilitárias sem dependência de extensões Flask."""

import re
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlparse

# Validação simples de e-mail: algo@dominio.ext (sem espaços).
# Evita depender do pacote extra "email-validator".
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def destino_seguro(destino):
    """Indica se 'destino' é um caminho interno seguro para redirecionamento.

    Usado no parâmetro ?next= do login para impedir "open redirect"
    (levar o usuário a um site externo após autenticar).
    """
    if not destino or not isinstance(destino, str):
        return False
    if "\\" in destino or not destino.startswith("/") or destino.startswith("//"):
        return False
    partes = urlparse(destino)
    return not partes.scheme and not partes.netloc


def formatar_datahora(valor, horas=-3, formato="%d/%m/%Y %H:%M"):
    """Formata uma data guardada em UTC para exibição no fuso informado.

    O banco guarda datas "ingênuas" (sem fuso) em UTC. 'horas' é a diferença
    para UTC (Brasília = -3). Usa deslocamento fixo para não depender do
    pacote tzdata no Windows.
    """
    if valor is None:
        return "—"
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone(timedelta(hours=horas))).strftime(formato)


# ---------------------------------------------------------------------
# Tempo, durações e percentuais (usados pelos indicadores dos dashboards)
# ---------------------------------------------------------------------
def naive_utc(valor):
    """Converte para datetime UTC sem fuso (o formato lido do SQLite).

    O banco devolve datas "ingênuas" em UTC, enquanto agora_utc() devolve uma
    data com fuso. Comparar as duas gera TypeError, então tudo é normalizado.
    """
    if valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def formatar_duracao(duracao):
    """Texto curto para um timedelta: '35 min', '2 h 15 min', '1 d 3 h'."""
    if duracao is None:
        return "—"
    minutos_totais = max(int(duracao.total_seconds()), 0) // 60
    if minutos_totais < 1:
        return "menos de 1 min"
    dias, resto = divmod(minutos_totais, 1440)
    horas, minutos = divmod(resto, 60)
    if dias:
        return f"{dias} d {horas} h" if horas else f"{dias} d"
    if horas:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    return f"{minutos} min"


def percentual(parte, total, casas=0):
    """Percentual de 'parte' em 'total'. Total zero (ou vazio) resulta em 0."""
    if not total:
        return 0
    valor = parte * 100 / total
    return round(valor) if casas == 0 else round(valor, casas)


def data_local(valor_utc, horas=-3):
    """Dia (date) no fuso local de uma data guardada em UTC."""
    return (naive_utc(valor_utc) + timedelta(hours=horas)).date()


def inicio_do_dia_local_em_utc(agora, horas=-3, dias_atras=0):
    """Meia-noite local (de hoje menos 'dias_atras') expressa em UTC sem fuso.

    Serve de limite inferior nas consultas SQL. Com horas=-3, a meia-noite de
    Brasília corresponde a 03:00 UTC.
    """
    local = naive_utc(agora) + timedelta(hours=horas)
    dia = local.date() - timedelta(days=dias_atras)
    return datetime.combine(dia, time.min) - timedelta(hours=horas)


def serie_por_dia(datas_utc, agora, dias=7, horas=-3):
    """Conta ocorrências por dia local nos últimos 'dias' dias (hoje incluso).

    Devolve [(date, quantidade), ...] do dia mais antigo ao de hoje. Datas
    fora da janela e valores None são ignorados.
    """
    hoje = data_local(agora, horas)
    dias_da_janela = [hoje - timedelta(days=i) for i in range(dias - 1, -1, -1)]
    contagem = dict.fromkeys(dias_da_janela, 0)
    for valor in datas_utc:
        if valor is None:
            continue
        dia = data_local(valor, horas)
        if dia in contagem:
            contagem[dia] += 1
    return [(dia, contagem[dia]) for dia in dias_da_janela]
