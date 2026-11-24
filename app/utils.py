"""Funções utilitárias sem dependência de extensões Flask."""

import re
from datetime import timedelta, timezone
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
