"""Testes da Etapa 4 (Fase A): indicadores dos dashboards.

Execute na raiz do projeto, com o .venv ativado:
    python -X dev -m unittest discover -s tests -v

Datas são ajustadas direto no arquivo SQLite (sqlite3) para simular chamados
antigos, e os serviços recebem um "agora" fixo para o resultado ser estável.
"""

import contextlib
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app import services
from app.extensions import db
from app.models import User
from test_chamados import CenarioChamados

# 24/11/2026 15:00 UTC = 24/11/2026 12:00 em Brasília
AGORA = datetime(2026, 11, 24, 15, 0)
FORMATO = "%Y-%m-%d %H:%M:%S.%f"


def agora_real():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BaseDashboards(CenarioChamados):
    def datas(self, chamado_id, criado=None, atualizado=None, concluido=None):
        """Reescreve datas do chamado (naive UTC) direto no SQLite."""
        campos = {"criado_em": criado, "atualizado_em": atualizado, "concluido_em": concluido}
        with contextlib.closing(sqlite3.connect(self.db_path)) as con:
            for coluna, valor in campos.items():
                if valor is not None:
                    con.execute(
                        f"UPDATE chamados SET {coluna} = ? WHERE id = ?",
                        (valor.strftime(FORMATO), chamado_id),
                    )
            con.commit()

    def data_evento(self, chamado_id, tipo, quando):
        with contextlib.closing(sqlite3.connect(self.db_path)) as con:
            con.execute(
                "UPDATE historico_chamados SET criado_em = ? WHERE chamado_id = ? AND tipo = ?",
                (quando.strftime(FORMATO), chamado_id, tipo),
            )
            con.commit()

    def resumo_func(self, usuario_id, **kw):
        with self.app.app_context():
            return services.resumo_funcionario(db.session.get(User, usuario_id), agora=AGORA, **kw)

    def resumo_tec(self, usuario_id, **kw):
        with self.app.app_context():
            return services.resumo_tecnico(db.session.get(User, usuario_id), agora=AGORA, **kw)


class TestResumoFuncionario(BaseDashboards):
    def setUp(self):
        super().setUp()
        # Ana: c1 aberto há 30 h (alta), c2 aberto há 2 h (baixa),
        #      c3 em andamento (media), c4 concluído em 3 h (media)
        self.c1 = self.novo_chamado(titulo="Velho", prioridade="alta")
        self.c2 = self.novo_chamado(titulo="Novo", prioridade="baixa")
        self.c3 = self.novo_chamado(titulo="Andamento", prioridade="media")
        self.c4 = self.novo_chamado(titulo="Concluido", prioridade="media")
        self.bruno_c = self.novo_chamado(email="bruno@empresa.com", titulo="Do Bruno", prioridade="alta")
        self.assumir_direto(self.c3)
        self.assumir_direto(self.c4)
        self.concluir_direto(self.c4)
        self.datas(self.c1, criado=AGORA - timedelta(hours=30))
        self.datas(self.c2, criado=AGORA - timedelta(hours=2))
        self.datas(self.c3, criado=AGORA - timedelta(hours=3))
        self.datas(self.c4, criado=AGORA - timedelta(hours=5), concluido=AGORA - timedelta(hours=2))
        self.datas(self.bruno_c, criado=AGORA - timedelta(hours=4))

    def test_chaves_originais_preservadas(self):
        r = self.resumo_func(self.ana)
        self.assertEqual(r["contagem"], {"aberto": 2, "em_andamento": 1, "concluido": 1})
        self.assertEqual(len(r["recentes"]), 4)

    def test_totais_e_status(self):
        r = self.resumo_func(self.ana)
        self.assertEqual(r["total_chamados"], 4)
        self.assertEqual(r["barra_status"]["total"], 4)
        self.assertEqual([i["quantidade"] for i in r["barra_status"]["itens"]], [2, 1, 1])

    def test_pendentes_por_prioridade_ignora_concluidos(self):
        r = self.resumo_func(self.ana)["por_prioridade"]
        quantidades = {i["chave"]: i["quantidade"] for i in r["itens"]}
        self.assertEqual(quantidades, {"alta": 1, "media": 1, "baixa": 1})

    def test_espera_considera_somente_abertos_e_limite(self):
        espera = self.resumo_func(self.ana)["espera"]
        self.assertEqual(espera["quantidade"], 2)
        self.assertEqual(espera["ids_longa"], [self.c1])
        self.assertEqual(espera["mais_longa"], timedelta(hours=30))

    def test_limite_configuravel(self):
        espera = self.resumo_func(self.ana, limite_alerta_horas=1)["espera"]
        self.assertEqual(sorted(espera["ids_longa"]), sorted([self.c1, self.c2]))

    def test_tempo_medio_de_resolucao(self):
        self.assertEqual(self.resumo_func(self.ana)["tempo_medio_resolucao"], timedelta(hours=3))

    def test_nao_mistura_chamados_de_outro_funcionario(self):
        r = self.resumo_func(self.bruno)
        self.assertEqual(r["total_chamados"], 1)
        self.assertEqual(r["espera"]["quantidade"], 1)
        self.assertIsNone(r["tempo_medio_resolucao"])
        self.assertEqual([c.id for c in r["recentes"]], [self.bruno_c])

    def test_ultimas_atualizacoes_so_do_proprio_usuario_e_sem_abertura(self):
        with self.app.app_context():
            services.adicionar_comentario(self.c3, db.session.get(User, self.tec1), "Testando")
        ana = self.resumo_func(self.ana)["ultimas_atualizacoes"]
        self.assertTrue(ana)
        self.assertTrue(all(e.tipo != "abertura" for e in ana))
        self.assertTrue(all(e.chamado.id != self.bruno_c for e in ana))
        self.assertLessEqual(len(ana), 5)
        # Bruno não tem nenhuma atualização (só a abertura)
        self.assertEqual(self.resumo_func(self.bruno)["ultimas_atualizacoes"], [])

    def test_serie_de_7_dias(self):
        serie = self.resumo_func(self.ana)["serie_7_dias"]
        self.assertEqual(len(serie), 7)
        self.assertEqual(serie[-1]["data"], AGORA.date())
        self.assertEqual(sum(p["abertos"] for p in serie), 4)
        self.assertEqual(sum(p["concluidos"] for p in serie), 1)

    def test_virada_de_dia_usa_fuso_local(self):
        def por_dia():
            serie = self.resumo_func(self.ana)["serie_7_dias"]
            return {p["data"]: p["abertos"] for p in serie}

        ontem, hoje = AGORA.date() - timedelta(days=1), AGORA.date()
        # Antes: c1 (30 h atrás = 23/11 06:00 local) está em ontem;
        # c2, c3 e c4 estão em hoje.
        antes = por_dia()
        self.assertEqual((antes[ontem], antes[hoje]), (1, 3))

        # 02:30 UTC de 24/11 = 23:30 de 23/11 em Brasília: c2 passa para "ontem",
        # embora a data em UTC ainda seja 24/11. O total não muda.
        self.datas(self.c2, criado=datetime(2026, 11, 24, 2, 30))
        depois = por_dia()
        self.assertEqual((depois[ontem], depois[hoje]), (2, 2))
        self.assertEqual(sum(depois.values()), sum(antes.values()))

    def test_chamado_fora_da_janela_nao_entra_na_serie(self):
        self.datas(self.c1, criado=AGORA - timedelta(days=20))
        serie = self.resumo_func(self.ana)["serie_7_dias"]
        self.assertEqual(sum(p["abertos"] for p in serie), 3)

    def test_sem_chamados(self):
        with self.app.app_context():
            novo = User(nome="Novo", email="novo@empresa.com", tipo="funcionario")
            novo.set_password("SenhaForte123")
            db.session.add(novo)
            db.session.commit()
            r = services.resumo_funcionario(novo, agora=AGORA)
        self.assertEqual(r["total_chamados"], 0)
        self.assertEqual(r["espera"]["quantidade"], 0)
        self.assertIsNone(r["tempo_medio_resolucao"])
        self.assertEqual(r["ultimas_atualizacoes"], [])
        self.assertEqual(sum(p["abertos"] for p in r["serie_7_dias"]), 0)


class TestResumoTecnico(BaseDashboards):
    def setUp(self):
        super().setUp()
        # Fila: f1 (alta, 30 h), f2 (baixa, 1 h)
        self.f1 = self.novo_chamado(titulo="Fila velha", prioridade="alta")
        self.f2 = self.novo_chamado(titulo="Fila nova", prioridade="baixa")
        # tec1: a1 em andamento (media), a2 em andamento parado, k1 concluído (4 h)
        self.a1 = self.novo_chamado(titulo="Ativo 1", prioridade="media")
        self.a2 = self.novo_chamado(titulo="Ativo parado", prioridade="alta")
        self.k1 = self.novo_chamado(titulo="Concluido tec1", prioridade="baixa")
        # tec2: t2 em andamento e k2 concluído
        self.t2 = self.novo_chamado(titulo="Ativo tec2", prioridade="alta")
        self.k2 = self.novo_chamado(titulo="Concluido tec2", prioridade="alta")
        for cid in (self.a1, self.a2, self.k1):
            self.assumir_direto(cid)
        self.concluir_direto(self.k1)
        for cid in (self.t2, self.k2):
            self.assumir_direto(cid, "tec2@empresa.com")
        self.concluir_direto(self.k2, "tec2@empresa.com")

        self.datas(self.f1, criado=AGORA - timedelta(hours=30))
        self.datas(self.f2, criado=AGORA - timedelta(hours=1))
        self.datas(self.a1, atualizado=AGORA - timedelta(hours=1))
        self.datas(self.a2, atualizado=AGORA - timedelta(hours=30))
        self.datas(self.k1, criado=AGORA - timedelta(hours=6), concluido=AGORA - timedelta(hours=2))
        self.datas(self.k2, criado=AGORA - timedelta(hours=10), concluido=AGORA - timedelta(hours=1))
        # Datas fixas também para os eventos "assumido" (a janela usa o AGORA fixo)
        self.data_evento(self.a1, "assumido", AGORA - timedelta(hours=8))
        self.data_evento(self.a2, "assumido", AGORA - timedelta(hours=40))
        self.data_evento(self.k1, "assumido", AGORA - timedelta(hours=5))
        self.data_evento(self.t2, "assumido", AGORA - timedelta(hours=9))
        self.data_evento(self.k2, "assumido", AGORA - timedelta(hours=9))
        self.datas(self.t2, atualizado=AGORA - timedelta(hours=2))

    def test_chaves_originais_preservadas(self):
        r = self.resumo_tec(self.tec1)
        self.assertEqual(r["total_disponiveis"], 2)
        self.assertEqual(r["em_andamento"], 2)
        self.assertEqual(r["concluidos"], 1)
        self.assertEqual({c.id for c in r["disponiveis"]}, {self.f1, self.f2})
        self.assertEqual({c.id for c in r["meus_ativos"]}, {self.a1, self.a2})

    def test_fila_por_prioridade_e_espera(self):
        r = self.resumo_tec(self.tec1)
        fila = {i["chave"]: i["quantidade"] for i in r["fila_por_prioridade"]["itens"]}
        self.assertEqual(fila, {"alta": 1, "media": 0, "baixa": 1})
        self.assertEqual(r["espera_fila"]["ids_longa"], [self.f1])
        self.assertEqual(r["espera_fila"]["mais_longa"], timedelta(hours=30))

    def test_carga_so_com_meus_atendimentos(self):
        carga = {i["chave"]: i["quantidade"] for i in self.resumo_tec(self.tec1)["carga_por_prioridade"]["itens"]}
        self.assertEqual(carga, {"alta": 1, "media": 1, "baixa": 0})

    def test_privacidade_outro_tecnico_nao_aparece(self):
        r1, r2 = self.resumo_tec(self.tec1), self.resumo_tec(self.tec2)
        self.assertEqual(r1["concluidos_30_dias"], 1)
        self.assertEqual(r2["concluidos_30_dias"], 1)
        self.assertEqual(r1["tempo_medio_resolucao"], timedelta(hours=4))
        self.assertEqual(r2["tempo_medio_resolucao"], timedelta(hours=9))
        self.assertEqual({c.id for c in r2["meus_ativos"]}, {self.t2})
        self.assertEqual(r2["ids_parados"], [])
        # nenhuma chave com ranking ou dados de outros técnicos
        for chave in r1:
            self.assertNotIn("ranking", chave)
            self.assertNotIn("tecnicos", chave)

    def test_ids_parados(self):
        self.assertEqual(self.resumo_tec(self.tec1)["ids_parados"], [self.a2])
        self.assertEqual(self.resumo_tec(self.tec1, limite_alerta_horas=48)["ids_parados"], [])

    def test_concluidos_por_periodo(self):
        # k1 concluído às 13:00 UTC de hoje (10:00 local): entra em hoje, 7 e 30 dias
        r = self.resumo_tec(self.tec1)
        self.assertEqual((r["concluidos_hoje"], r["concluidos_7_dias"], r["concluidos_30_dias"]), (1, 1, 1))
        self.datas(self.k1, concluido=AGORA - timedelta(days=3))
        r = self.resumo_tec(self.tec1)
        self.assertEqual((r["concluidos_hoje"], r["concluidos_7_dias"], r["concluidos_30_dias"]), (0, 1, 1))
        self.datas(self.k1, concluido=AGORA - timedelta(days=45))
        r = self.resumo_tec(self.tec1)
        self.assertEqual((r["concluidos_hoje"], r["concluidos_7_dias"], r["concluidos_30_dias"]), (0, 0, 0))

    def test_concluido_antes_da_meia_noite_local_nao_conta_hoje(self):
        # 02:30 UTC de 24/11 = 23:30 de 23/11 em Brasília -> ainda é "ontem"
        self.datas(self.k1, concluido=datetime(2026, 11, 24, 2, 30))
        r = self.resumo_tec(self.tec1)
        self.assertEqual(r["concluidos_hoje"], 0)
        self.assertEqual(r["concluidos_7_dias"], 1)

    def test_serie_assumidos_so_do_proprio_tecnico(self):
        serie1 = self.resumo_tec(self.tec1)["serie_7_dias"]
        serie2 = self.resumo_tec(self.tec2)["serie_7_dias"]
        self.assertEqual(sum(p["assumidos"] for p in serie1), 3)
        self.assertEqual(sum(p["assumidos"] for p in serie2), 2)
        self.assertEqual(sum(p["concluidos"] for p in serie1), 1)

    def test_sem_dados(self):
        with self.app.app_context():
            novo = User(nome="Novo Tec", email="novotec@empresa.com", tipo="tecnico")
            novo.set_password("SenhaForte123")
            db.session.add(novo)
            db.session.commit()
            r = services.resumo_tecnico(novo, agora=AGORA)
        self.assertEqual((r["concluidos_hoje"], r["concluidos_7_dias"], r["concluidos_30_dias"]), (0, 0, 0))
        self.assertIsNone(r["tempo_medio_resolucao"])
        self.assertEqual(r["ids_parados"], [])
        self.assertEqual(r["carga_por_prioridade"]["total"], 0)


class TestPaginasDosDashboards(BaseDashboards):
    def setUp(self):
        super().setUp()
        self.velho = self.novo_chamado(titulo="Chamado antigo", prioridade="alta")
        self.recente = self.novo_chamado(titulo="Chamado recente", prioridade="baixa")
        self.datas(self.velho, criado=agora_real() - timedelta(hours=30))
        self.ana_c = self.cliente_logado("ana@empresa.com")
        self.tec_c = self.cliente_logado("tec1@empresa.com")

    def test_dashboard_funcionario_tem_indicadores(self):
        resp = self.ana_c.get("/painel/funcionario")
        self.assertEqual(resp.status_code, 200)
        html = self.texto(resp)
        for marcador in ("Chamados por status", "Pendentes por prioridade", "Últimos 7 dias",
                         "Últimas atualizações", "Tempo médio de resolução", "<svg",
                         "hd-barra-empilhada", "Abrir novo chamado", "status=aberto"):
            self.assertIn(marcador, html)

    def test_alerta_so_para_chamado_com_mais_de_24h(self):
        html = self.texto(self.ana_c.get("/painel/funcionario"))
        self.assertEqual(html.count('class="table-warning"'), 1)
        self.assertIn("Chamado antigo", html)
        linha = html.split('class="table-warning"')[1].split("</tr>")[0]
        self.assertIn("Chamado antigo", linha)
        self.assertNotIn("Chamado recente", linha)

    def test_sem_alerta_quando_tudo_recente(self):
        self.datas(self.velho, criado=agora_real() - timedelta(hours=2))
        html = self.texto(self.ana_c.get("/painel/funcionario"))
        self.assertNotIn("table-warning", html)
        self.assertNotIn("alert-warning", html)

    def test_dashboard_tecnico_tem_indicadores_e_alerta_na_fila(self):
        resp = self.tec_c.get("/painel/tecnico")
        self.assertEqual(resp.status_code, 200)
        html = self.texto(resp)
        for marcador in ("Meu desempenho", "Fila disponível por prioridade",
                         "Minha carga por prioridade", "Meus últimos 7 dias", "<svg",
                         "Meus atendimentos em andamento", "Próximos chamados disponíveis"):
            self.assertIn(marcador, html)
        self.assertEqual(html.count('class="table-warning"'), 1)
        self.assertIn("não é um prazo", html)

    def test_dashboard_do_tecnico_nao_mostra_dados_de_outro_tecnico(self):
        cid = self.novo_chamado(titulo="Atendimento secreto da Carla")
        self.assumir_direto(cid, "tec2@empresa.com")
        html = self.texto(self.tec_c.get("/painel/tecnico"))
        self.assertNotIn("Atendimento secreto da Carla", html)
        self.assertNotIn("Carla Técnica", html)
        self.assertNotIn("ranking", html.lower())

    def test_dashboard_do_funcionario_nao_mostra_chamado_de_outro(self):
        self.novo_chamado(email="bruno@empresa.com", titulo="Segredo do Bruno")
        html = self.texto(self.ana_c.get("/painel/funcionario"))
        self.assertNotIn("Segredo do Bruno", html)

    def test_titulo_com_html_e_escapado_no_feed(self):
        cid = self.novo_chamado(titulo="<script>alert(1)</script>")
        self.assumir_direto(cid)
        html = self.texto(self.ana_c.get("/painel/funcionario"))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_permissoes_continuam_as_mesmas(self):
        self.assertEqual(self.ana_c.get("/painel/tecnico").status_code, 403)
        self.assertEqual(self.tec_c.get("/painel/funcionario").status_code, 403)
        anonimo = self.app.test_client()
        for url in ("/painel/funcionario", "/painel/tecnico"):
            resp = anonimo.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/login", resp.headers["Location"])

    def test_paginas_de_lista_nao_ganham_destaque(self):
        html = self.texto(self.ana_c.get("/chamados/"))
        self.assertNotIn("table-warning", html)


class TestNumeroDeConsultas(BaseDashboards):
    """Evita regressão de desempenho (consultas em laço, N+1)."""

    def contar(self, funcao, usuario_id):
        consultas = []
        with self.app.app_context():
            usuario = db.session.get(User, usuario_id)
            motor = db.engine

            def registrar(conn, cursor, statement, *args):
                consultas.append(statement)

            event.listen(motor, "before_cursor_execute", registrar)
            try:
                funcao(usuario, agora=AGORA)
            finally:
                event.remove(motor, "before_cursor_execute", registrar)
        return len(consultas)

    def test_funcionario_com_muitos_chamados(self):
        for i in range(15):
            cid = self.novo_chamado(titulo=f"Chamado {i}")
            if i % 3 == 0:
                self.assumir_direto(cid)
        self.assertLessEqual(self.contar(services.resumo_funcionario, self.ana), 12)

    def test_tecnico_com_muitos_chamados(self):
        for i in range(15):
            cid = self.novo_chamado(titulo=f"Chamado {i}")
            if i % 2 == 0:
                self.assumir_direto(cid)
        self.assertLessEqual(self.contar(services.resumo_tecnico, self.tec1), 12)


if __name__ == "__main__":
    unittest.main()
