"""Montagem dos indicadores dos dashboards (lógica pura, sem banco).

Este módulo não consulta o banco nem importa Flask/SQLAlchemy: recebe valores
já lidos (contagens, datas) e devolve estruturas prontas para os templates.
As consultas ficam em services.py, o que mantém esta parte simples de testar.

Atenção: os alertas de "espera longa" e "parado" são apenas avisos visuais
configuráveis (ALERTA_ESPERA_HORAS). Não representam um prazo (SLA).
"""

from datetime import timedelta

from app.utils import naive_utc, percentual, serie_por_dia


def contar_chaves(valores, chaves):
    """Conta quantas vezes cada chave aparece; sempre devolve todas as chaves."""
    contagem = dict.fromkeys(chaves, 0)
    for valor in valores:
        if valor in contagem:
            contagem[valor] += 1
    return contagem


def barra_status(contagem, rotulos):
    """Dados da barra empilhada por status (mantém a ordem de 'rotulos')."""
    total = sum(contagem.values())
    itens = [
        {
            "chave": chave,
            "rotulo": rotulo,
            "quantidade": contagem.get(chave, 0),
            "percentual": percentual(contagem.get(chave, 0), total),
            "largura": percentual(contagem.get(chave, 0), total, 1),
        }
        for chave, rotulo in rotulos.items()
    ]
    return {"total": total, "itens": itens}


def barras_prioridade(contagem, rotulos):
    """Dados das barras por prioridade, da mais importante para a menos.

    'rotulos' vem em ordem crescente (baixa, média, alta); aqui é invertido.
    A largura de cada barra é proporcional à maior contagem.
    """
    maior = max(contagem.values(), default=0)
    itens = [
        {
            "chave": chave,
            "rotulo": rotulos[chave],
            "quantidade": contagem.get(chave, 0),
            "largura": percentual(contagem.get(chave, 0), maior, 1),
        }
        for chave in reversed(list(rotulos))
    ]
    return {"total": sum(contagem.values()), "maximo": maior, "itens": itens}


def resumir_espera(itens, agora, limite_horas):
    """Resume o tempo de espera de uma lista de chamados.

    'itens' é uma lista de (id, data_de_referencia_em_utc). Devolve a
    quantidade, a maior espera, quantos passaram do limite e quais ids.
    """
    agora = naive_utc(agora)
    limite = timedelta(hours=limite_horas)
    esperas = [(chamado_id, agora - naive_utc(data)) for chamado_id, data in itens]
    ids_longa = [chamado_id for chamado_id, espera in esperas if espera > limite]
    return {
        "quantidade": len(esperas),
        "mais_longa": max((espera for _, espera in esperas), default=None),
        "quantidade_longa": len(ids_longa),
        "ids_longa": ids_longa,
    }


def tempo_medio(pares):
    """Duração média de uma lista de (inicio, fim); None se não houver pares."""
    duracoes = [fim - inicio for inicio, fim in pares if inicio is not None and fim is not None]
    if not duracoes:
        return None
    return sum(duracoes, timedelta()) / len(duracoes)


def contar_desde(datas, inicio):
    """Quantas datas são maiores ou iguais a 'inicio' (ignora None)."""
    return sum(1 for data in datas if data is not None and data >= inicio)


def serie_dupla(datas_a, datas_b, agora, chave_a, chave_b, dias=7, horas=-3):
    """Duas séries diárias alinhadas: [{"data": date, chave_a: n, chave_b: m}]."""
    serie_a = serie_por_dia(datas_a, agora, dias, horas)
    serie_b = serie_por_dia(datas_b, agora, dias, horas)
    return [
        {"data": dia, chave_a: qtd_a, chave_b: qtd_b}
        for (dia, qtd_a), (_, qtd_b) in zip(serie_a, serie_b)
    ]
