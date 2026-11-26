"""Testes das funções puras dos indicadores (sem banco de dados).

Cobrem app/utils.py (duração, percentual, fuso e janelas de tempo) e
app/indicadores.py (montagem dos dados dos dashboards).

Execute na raiz do projeto, com o .venv ativado:
    python -m unittest discover -s tests -v
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from app.indicadores import (
    barra_status,
    barras_prioridade,
    contar_chaves,
    contar_desde,
    resumir_espera,
    serie_dupla,
    tempo_medio,
)
from app.utils import (
    data_local,
    formatar_duracao,
    inicio_do_dia_local_em_utc,
    naive_utc,
    percentual,
    serie_por_dia,
)

# 24/11/2026 15:00 UTC = 24/11/2026 12:00 em Brasília (UTC-3)
AGORA = datetime(2026, 11, 24, 15, 0)

ROTULOS_STATUS = {"aberto": "Aberto", "em_andamento": "Em andamento", "concluido": "Concluído"}
ROTULOS_PRIORIDADE = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}  # ordem crescente


class TestFormatarDuracao(unittest.TestCase):
    def test_formatos(self):
        casos = {
            timedelta(seconds=30): "menos de 1 min",
            timedelta(minutes=1): "1 min",
            timedelta(minutes=35): "35 min",
            timedelta(hours=2): "2 h",
            timedelta(hours=2, minutes=15): "2 h 15 min",
            timedelta(hours=24): "1 d",
            timedelta(days=1, hours=3): "1 d 3 h",
            timedelta(days=3): "3 d",
            timedelta(days=2, hours=5, minutes=40): "2 d 5 h",
        }
        for duracao, esperado in casos.items():
            with self.subTest(duracao=duracao):
                self.assertEqual(formatar_duracao(duracao), esperado)

    def test_sem_valor(self):
        self.assertEqual(formatar_duracao(None), "—")

    def test_duracao_negativa_vira_zero(self):
        self.assertEqual(formatar_duracao(timedelta(hours=-5)), "menos de 1 min")


class TestPercentual(unittest.TestCase):
    def test_valores(self):
        self.assertEqual(percentual(1, 3), 33)
        self.assertEqual(percentual(2, 3), 67)
        self.assertEqual(percentual(1, 2), 50)
        self.assertEqual(percentual(3, 3), 100)
        self.assertEqual(percentual(0, 5), 0)
        self.assertEqual(percentual(1, 3, 1), 33.3)

    def test_total_zero_nao_divide_por_zero(self):
        self.assertEqual(percentual(0, 0), 0)
        self.assertEqual(percentual(5, 0, 1), 0)


class TestFusoEJanelas(unittest.TestCase):
    def test_naive_utc(self):
        self.assertEqual(naive_utc(datetime(2026, 11, 24, 15, 0)), AGORA)
        self.assertEqual(naive_utc(datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)), AGORA)
        brasilia = timezone(timedelta(hours=-3))
        self.assertEqual(naive_utc(datetime(2026, 11, 24, 12, 0, tzinfo=brasilia)), AGORA)
        self.assertIsNone(naive_utc(datetime(2026, 11, 24, 12, 0, tzinfo=brasilia)).tzinfo)

    def test_data_local_na_virada_do_dia(self):
        self.assertEqual(data_local(datetime(2026, 11, 24, 2, 59), -3), date(2026, 11, 23))
        self.assertEqual(data_local(datetime(2026, 11, 24, 3, 0), -3), date(2026, 11, 24))
        self.assertEqual(data_local(datetime(2026, 11, 24, 2, 59), 0), date(2026, 11, 24))

    def test_inicio_do_dia_local_em_utc(self):
        self.assertEqual(inicio_do_dia_local_em_utc(AGORA, -3), datetime(2026, 11, 24, 3, 0))
        self.assertEqual(inicio_do_dia_local_em_utc(AGORA, -3, dias_atras=6), datetime(2026, 11, 18, 3, 0))
        self.assertEqual(inicio_do_dia_local_em_utc(AGORA, 0), datetime(2026, 11, 24, 0, 0))

    def test_inicio_do_dia_local_quando_ainda_e_ontem_em_brasilia(self):
        # 02:00 UTC de 24/11 = 23:00 de 23/11 em Brasília
        agora = datetime(2026, 11, 24, 2, 0)
        self.assertEqual(inicio_do_dia_local_em_utc(agora, -3), datetime(2026, 11, 23, 3, 0))

    def test_inicio_do_dia_aceita_data_com_fuso(self):
        agora = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(inicio_do_dia_local_em_utc(agora, -3), datetime(2026, 11, 24, 3, 0))

    def test_serie_por_dia(self):
        datas = [
            datetime(2026, 11, 24, 14, 0),   # 24/11 local
            datetime(2026, 11, 24, 2, 0),    # 23/11 23:00 local (virada de dia)
            datetime(2026, 11, 23, 10, 0),   # 23/11 local
            datetime(2026, 11, 17, 12, 0),   # fora da janela (antes)
            datetime(2026, 11, 25, 12, 0),   # fora da janela (futuro)
            None,
        ]
        serie = serie_por_dia(datas, AGORA, dias=7, horas=-3)
        self.assertEqual(len(serie), 7)
        self.assertEqual(serie[0][0], date(2026, 11, 18))
        self.assertEqual(serie[-1][0], date(2026, 11, 24))
        contagem = dict(serie)
        self.assertEqual(contagem[date(2026, 11, 24)], 1)
        self.assertEqual(contagem[date(2026, 11, 23)], 2)
        self.assertEqual(sum(contagem.values()), 3)

    def test_serie_por_dia_vazia(self):
        serie = serie_por_dia([], AGORA)
        self.assertEqual([q for _, q in serie], [0] * 7)

    def test_serie_em_ordem_cronologica(self):
        dias = [d for d, _ in serie_por_dia([], AGORA)]
        self.assertEqual(dias, sorted(dias))


class TestContarChaves(unittest.TestCase):
    def test_conta_e_mantem_todas_as_chaves(self):
        self.assertEqual(
            contar_chaves(["a", "b", "a", "x"], ("a", "b", "c")),
            {"a": 2, "b": 1, "c": 0},
        )

    def test_vazio(self):
        self.assertEqual(contar_chaves([], ("a", "b")), {"a": 0, "b": 0})


class TestBarraStatus(unittest.TestCase):
    def test_percentuais(self):
        barra = barra_status({"aberto": 1, "em_andamento": 1, "concluido": 1}, ROTULOS_STATUS)
        self.assertEqual(barra["total"], 3)
        self.assertEqual([i["chave"] for i in barra["itens"]], ["aberto", "em_andamento", "concluido"])
        self.assertEqual([i["percentual"] for i in barra["itens"]], [33, 33, 33])
        self.assertEqual([i["largura"] for i in barra["itens"]], [33.3, 33.3, 33.3])
        self.assertEqual(barra["itens"][1]["rotulo"], "Em andamento")

    def test_proporcoes(self):
        barra = barra_status({"aberto": 1, "em_andamento": 0, "concluido": 3}, ROTULOS_STATUS)
        self.assertEqual([i["percentual"] for i in barra["itens"]], [25, 0, 75])

    def test_sem_chamados(self):
        barra = barra_status({"aberto": 0, "em_andamento": 0, "concluido": 0}, ROTULOS_STATUS)
        self.assertEqual(barra["total"], 0)
        self.assertEqual([i["largura"] for i in barra["itens"]], [0, 0, 0])


class TestBarrasPrioridade(unittest.TestCase):
    def test_ordem_da_mais_importante_para_a_menos(self):
        barras = barras_prioridade({"baixa": 1, "media": 2, "alta": 4}, ROTULOS_PRIORIDADE)
        self.assertEqual([i["chave"] for i in barras["itens"]], ["alta", "media", "baixa"])
        self.assertEqual([i["quantidade"] for i in barras["itens"]], [4, 2, 1])

    def test_largura_proporcional_a_maior_contagem(self):
        barras = barras_prioridade({"baixa": 1, "media": 2, "alta": 4}, ROTULOS_PRIORIDADE)
        self.assertEqual([i["largura"] for i in barras["itens"]], [100, 50, 25])
        self.assertEqual(barras["maximo"], 4)
        self.assertEqual(barras["total"], 7)

    def test_sem_chamados(self):
        barras = barras_prioridade({"baixa": 0, "media": 0, "alta": 0}, ROTULOS_PRIORIDADE)
        self.assertEqual(barras["total"], 0)
        self.assertEqual([i["largura"] for i in barras["itens"]], [0, 0, 0])


class TestResumirEspera(unittest.TestCase):
    def test_limite_e_maior_espera(self):
        itens = [
            (1, AGORA - timedelta(hours=30)),
            (2, AGORA - timedelta(hours=2)),
            (3, AGORA - timedelta(hours=24)),   # exatamente 24 h: não passa do limite
        ]
        resumo = resumir_espera(itens, AGORA, 24)
        self.assertEqual(resumo["quantidade"], 3)
        self.assertEqual(resumo["mais_longa"], timedelta(hours=30))
        self.assertEqual(resumo["quantidade_longa"], 1)
        self.assertEqual(resumo["ids_longa"], [1])

    def test_limite_configuravel(self):
        itens = [(1, AGORA - timedelta(hours=5)), (2, AGORA - timedelta(hours=1))]
        self.assertEqual(resumir_espera(itens, AGORA, 4)["ids_longa"], [1])
        self.assertEqual(resumir_espera(itens, AGORA, 48)["ids_longa"], [])

    def test_lista_vazia(self):
        resumo = resumir_espera([], AGORA, 24)
        self.assertEqual(resumo, {"quantidade": 0, "mais_longa": None,
                                  "quantidade_longa": 0, "ids_longa": []})

    def test_aceita_agora_com_fuso(self):
        agora = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
        resumo = resumir_espera([(1, AGORA - timedelta(hours=30))], agora, 24)
        self.assertEqual(resumo["ids_longa"], [1])


class TestTempoMedio(unittest.TestCase):
    def test_media(self):
        inicio = datetime(2026, 11, 20, 10, 0)
        pares = [(inicio, inicio + timedelta(hours=2)), (inicio, inicio + timedelta(hours=4))]
        self.assertEqual(tempo_medio(pares), timedelta(hours=3))

    def test_sem_dados(self):
        self.assertIsNone(tempo_medio([]))
        self.assertIsNone(tempo_medio([(datetime(2026, 11, 20), None)]))


class TestContarDesde(unittest.TestCase):
    def test_limite_inclusivo_e_ignora_none(self):
        inicio = datetime(2026, 11, 24, 3, 0)
        datas = [datetime(2026, 11, 24, 3, 0), datetime(2026, 11, 24, 2, 59), None,
                 datetime(2026, 11, 25, 1, 0)]
        self.assertEqual(contar_desde(datas, inicio), 2)


class TestSerieDupla(unittest.TestCase):
    def test_duas_series_alinhadas(self):
        abertos = [datetime(2026, 11, 24, 14, 0), datetime(2026, 11, 23, 10, 0)]
        concluidos = [datetime(2026, 11, 24, 13, 0), datetime(2026, 11, 24, 12, 0)]
        serie = serie_dupla(abertos, concluidos, AGORA, "abertos", "concluidos")
        self.assertEqual(len(serie), 7)
        self.assertEqual(set(serie[0]), {"data", "abertos", "concluidos"})
        self.assertEqual(serie[-1], {"data": date(2026, 11, 24), "abertos": 1, "concluidos": 2})
        self.assertEqual(serie[-2], {"data": date(2026, 11, 23), "abertos": 1, "concluidos": 0})

    def test_sem_dados(self):
        serie = serie_dupla([], [], AGORA, "a", "b")
        self.assertTrue(all(p["a"] == 0 and p["b"] == 0 for p in serie))


if __name__ == "__main__":
    unittest.main()
