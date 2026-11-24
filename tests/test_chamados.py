"""Testes da Etapa 3: chamados, permissões, atribuição e concorrência.

Execute na raiz do projeto, com o .venv ativado:
    python -m unittest discover -s tests -v

A classe-base (banco temporário e auxiliares) fica em tests/base_testes.py.
"""

import sqlite3
import threading
import unittest
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app import services
from app.extensions import db
from app.models import (
    TIPO_FUNCIONARIO,
    TIPO_TECNICO,
    Chamado,
    HistoricoChamado,
    User,
)
from app.utils import formatar_datahora
from base_testes import BaseTestCase


def dados_chamado(**extra):
    dados = {
        "titulo": "Impressora não imprime",
        "descricao": "A impressora do segundo andar não responde.",
        "categoria": "impressora",
        "prioridade": "alta",
    }
    dados.update(extra)
    return dados


class CenarioChamados(BaseTestCase):
    """Cria dois funcionários (Ana e Bruno) e dois técnicos (tec1 e tec2)."""

    def setUp(self):
        super().setUp()
        self.ana = self.criar_usuario("Ana Silva", "ana@empresa.com")
        self.bruno = self.criar_usuario("Bruno Souza", "bruno@empresa.com")
        self.tec1 = self.criar_usuario("Tião Técnico", "tec1@empresa.com", tipo=TIPO_TECNICO)
        self.tec2 = self.criar_usuario("Carla Técnica", "tec2@empresa.com", tipo=TIPO_TECNICO)

    def estado(self, chamado_id):
        """(status, tecnico_id) do chamado, lido direto do arquivo SQLite."""
        return self.sql("SELECT status, tecnico_id FROM chamados WHERE id = ?", (chamado_id,))[0]

    def eventos(self, chamado_id):
        """Histórico do chamado: [(tipo, autor_id, status_anterior, status_novo, descricao)]."""
        return self.sql(
            "SELECT tipo, autor_id, status_anterior, status_novo, descricao "
            "FROM historico_chamados WHERE chamado_id = ? ORDER BY criado_em, id",
            (chamado_id,),
        )

    def tipos_de_evento(self, chamado_id):
        return [e[0] for e in self.eventos(chamado_id)]


# =====================================================================
# Banco de dados
# =====================================================================
class TestEstruturaDoBanco(BaseTestCase):
    def test_tabelas_e_colunas(self):
        chamados = [c[1] for c in self.sql("PRAGMA table_info(chamados)")]
        for esperado in ("id", "titulo", "descricao", "categoria", "prioridade", "status",
                         "solucao", "solicitante_id", "tecnico_id",
                         "criado_em", "atualizado_em", "concluido_em"):
            self.assertIn(esperado, chamados)
        historico = [c[1] for c in self.sql("PRAGMA table_info(historico_chamados)")]
        for esperado in ("id", "chamado_id", "autor_id", "tipo", "status_anterior",
                         "status_novo", "descricao", "criado_em"):
            self.assertIn(esperado, historico)

    def test_tabela_de_usuarios_nao_foi_alterada(self):
        colunas = [c[1] for c in self.sql("PRAGMA table_info(usuarios)")]
        self.assertEqual(
            colunas, ["id", "nome", "email", "senha_hash", "tipo", "data_cadastro"]
        )

    def test_banco_rejeita_status_invalido(self):
        with self.assertRaises(sqlite3.IntegrityError):
            conexao = sqlite3.connect(self.db_path)
            try:
                conexao.execute(
                    "INSERT INTO chamados (titulo, descricao, categoria, prioridade, status, "
                    "solicitante_id, criado_em, atualizado_em) "
                    "VALUES ('t', 'd', 'outros', 'media', 'invalido', 1, '2026-01-01', '2026-01-01')"
                )
            finally:
                conexao.close()

    def test_banco_rejeita_prioridade_invalida(self):
        with self.assertRaises(sqlite3.IntegrityError):
            conexao = sqlite3.connect(self.db_path)
            try:
                conexao.execute(
                    "INSERT INTO chamados (titulo, descricao, categoria, prioridade, status, "
                    "solicitante_id, criado_em, atualizado_em) "
                    "VALUES ('t', 'd', 'outros', 'urgentissima', 'aberto', 1, '2026-01-01', '2026-01-01')"
                )
            finally:
                conexao.close()

    def test_chave_estrangeira_e_aplicada(self):
        with self.app.app_context():
            db.session.add(
                HistoricoChamado(chamado_id=999, autor_id=1, tipo="abertura", descricao="x")
            )
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_create_all_preserva_usuarios_existentes(self):
        """Simula um banco da Etapa 2 (só 'usuarios') e confere que nada é perdido."""
        self.criar_usuario()
        with self.app.app_context():
            db.metadata.tables["historico_chamados"].drop(db.engine)
            db.metadata.tables["chamados"].drop(db.engine)

        consulta = "SELECT name FROM sqlite_master WHERE type = 'table'"
        tabelas = {t[0] for t in self.sql(consulta)}
        self.assertIn("usuarios", tabelas)
        self.assertNotIn("chamados", tabelas)

        self.novo_app()  # create_app() executa db.create_all()

        tabelas = {t[0] for t in self.sql(consulta)}
        self.assertIn("chamados", tabelas)
        self.assertIn("historico_chamados", tabelas)
        self.assertEqual(self.sql("SELECT email, tipo FROM usuarios"),
                         [("ana@empresa.com", TIPO_FUNCIONARIO)])


class TestRelacionamentos(CenarioChamados):
    def test_relacionamentos_entre_usuarios_chamados_e_historico(self):
        chamado_id = self.novo_chamado()
        self.assumir_direto(chamado_id)
        with self.app.app_context():
            chamado = db.session.get(Chamado, chamado_id)
            self.assertEqual(chamado.solicitante.email, "ana@empresa.com")
            self.assertEqual(chamado.tecnico.email, "tec1@empresa.com")
            self.assertEqual([h.tipo for h in chamado.historico], ["abertura", "assumido"])
            self.assertEqual(chamado.historico[1].autor.email, "tec1@empresa.com")

            ana = db.session.get(User, self.ana)
            tec1 = db.session.get(User, self.tec1)
            self.assertEqual([c.id for c in ana.chamados_abertos], [chamado_id])
            self.assertEqual([c.id for c in tec1.chamados_atendidos], [chamado_id])


# =====================================================================
# Funcionário: abrir chamados
# =====================================================================
class TestAbrirChamado(CenarioChamados):
    def abrir(self, cliente=None, **extra):
        return (cliente or self.client).post("/chamados/novo", data=dados_chamado(**extra))

    def test_formulario_de_abertura(self):
        self.entrar()
        r = self.client.get("/chamados/novo")
        self.assertEqual(r.status_code, 200)
        html = self.texto(r)
        for campo in ('name="titulo"', 'name="descricao"', 'name="categoria"', 'name="prioridade"'):
            self.assertIn(campo, html)
        for proibido in ('name="status"', 'name="tecnico_id"', 'name="solicitante_id"'):
            self.assertNotIn(proibido, html)

    def test_abertura_valida_salva_no_sqlite(self):
        self.entrar()
        r = self.abrir()
        self.assertEqual(r.status_code, 302)

        linhas = self.sql(
            "SELECT id, titulo, descricao, categoria, prioridade, status, solicitante_id, "
            "tecnico_id, criado_em, atualizado_em, concluido_em FROM chamados"
        )
        self.assertEqual(len(linhas), 1)
        (cid, titulo, descricao, categoria, prioridade, status,
         solicitante_id, tecnico_id, criado, atualizado, concluido) = linhas[0]
        self.assertEqual(titulo, "Impressora não imprime")
        self.assertEqual(descricao, "A impressora do segundo andar não responde.")
        self.assertEqual(categoria, "impressora")
        self.assertEqual(prioridade, "alta")
        self.assertEqual(status, "aberto")
        self.assertEqual(solicitante_id, self.ana)
        self.assertIsNone(tecnico_id)
        self.assertTrue(criado)
        self.assertTrue(atualizado)
        self.assertIsNone(concluido)
        self.assertTrue(r.headers["Location"].endswith(f"/chamados/{cid}"))

    def test_abertura_registra_historico(self):
        self.entrar()
        self.abrir()
        cid = self.sql("SELECT id FROM chamados")[0][0]
        self.assertEqual(
            self.eventos(cid),
            [("abertura", self.ana, None, "aberto", "Chamado aberto.")],
        )

    def test_mensagem_de_sucesso(self):
        self.entrar()
        r = self.client.post("/chamados/novo", data=dados_chamado(), follow_redirects=True)
        self.assertIn("Chamado aberto com sucesso", self.texto(r))

    def test_prioridade_padrao_e_media_no_formulario(self):
        self.entrar()
        html = self.texto(self.client.get("/chamados/novo"))
        # Independe da ordem dos atributos gerada pelo WTForms
        self.assertRegex(
            html,
            r'<option[^>]*selected[^>]*value="media"|<option[^>]*value="media"[^>]*selected',
        )
        self.assertNotRegex(html, r'<option[^>]*selected[^>]*value="(alta|baixa)"')

    def test_validacoes(self):
        self.entrar()
        casos = {
            "título curto": ({"titulo": "abc"}, "entre 5 e 150"),
            "título vazio": ({"titulo": ""}, "Informe o título"),
            "descrição curta": ({"descricao": "curta"}, "entre 10 e 5000"),
            "descrição vazia": ({"descricao": ""}, "Descreva o problema"),
            "categoria vazia": ({"categoria": ""}, "Selecione uma categoria"),
            "categoria inexistente": ({"categoria": "magia"}, "Selecione uma categoria"),
            "prioridade inválida": ({"prioridade": "urgentissima"}, "Selecione uma prioridade"),
        }
        for descricao, (extra, mensagem) in casos.items():
            with self.subTest(descricao):
                r = self.abrir(**extra)
                self.assertEqual(r.status_code, 200)
                self.assertIn(mensagem, self.texto(r))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM chamados")[0][0], 0)

    def test_funcionario_nao_define_status_tecnico_nem_solicitante(self):
        self.entrar()
        self.abrir(status="concluido", tecnico_id=str(self.tec1),
                   solicitante_id=str(self.bruno), solucao="resolvido", concluido_em="2026-01-01")
        status, tecnico_id = self.estado(1)
        self.assertEqual(status, "aberto")
        self.assertIsNone(tecnico_id)
        self.assertEqual(self.sql("SELECT solicitante_id, solucao, concluido_em FROM chamados"),
                         [(self.ana, None, None)])

    def test_texto_com_html_e_escapado(self):
        self.entrar()
        self.abrir(titulo="<script>alert(1)</script>", descricao="<b>negrito</b> no texto do chamado")
        cid = self.sql("SELECT id FROM chamados")[0][0]
        for url in ("/chamados/", f"/chamados/{cid}", "/painel/funcionario"):
            with self.subTest(url):
                html = self.texto(self.client.get(url))
                self.assertNotIn("<script>alert(1)</script>", html)
                self.assertNotIn("<b>negrito</b>", html)
                self.assertIn("&lt;script&gt;", html)

    def test_tecnico_nao_abre_chamado(self):
        self.entrar("tec1@empresa.com")
        self.assertEqual(self.client.get("/chamados/novo").status_code, 403)
        self.assertEqual(self.abrir().status_code, 403)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM chamados")[0][0], 0)

    def test_visitante_vai_para_o_login(self):
        for metodo, url in (("get", "/chamados/novo"), ("post", "/chamados/novo"),
                            ("get", "/chamados/"), ("get", "/chamados/1")):
            with self.subTest(url=url, metodo=metodo):
                r = getattr(self.client, metodo)(url)
                self.assertEqual(r.status_code, 302)
                self.assertIn("/login", r.headers["Location"])


# =====================================================================
# Funcionário: consultar chamados
# =====================================================================
class TestFuncionarioConsulta(CenarioChamados):
    def setUp(self):
        super().setUp()
        self.c_aberto = self.novo_chamado("ana@empresa.com", "Monitor piscando", prioridade="alta")
        self.c_andamento = self.novo_chamado("ana@empresa.com", "Teclado quebrado", prioridade="baixa")
        self.c_concluido = self.novo_chamado("ana@empresa.com", "Mouse travando", prioridade="media")
        self.c_bruno = self.novo_chamado("bruno@empresa.com", "Planilha corrompida")
        self.assumir_direto(self.c_andamento)
        self.assumir_direto(self.c_concluido)
        self.concluir_direto(self.c_concluido, solucao="Troquei o mouse por um novo.")
        self.entrar()

    def test_lista_mostra_apenas_os_proprios_chamados(self):
        html = self.texto(self.client.get("/chamados/"))
        for titulo in ("Monitor piscando", "Teclado quebrado", "Mouse travando"):
            self.assertIn(titulo, html)
        self.assertNotIn("Planilha corrompida", html)

    def test_filtro_por_status(self):
        html = self.texto(self.client.get("/chamados/?status=em_andamento"))
        self.assertIn("Teclado quebrado", html)
        self.assertNotIn("Monitor piscando", html)
        self.assertNotIn("Mouse travando", html)

    def test_filtro_por_prioridade(self):
        html = self.texto(self.client.get("/chamados/?prioridade=alta"))
        self.assertIn("Monitor piscando", html)
        self.assertNotIn("Teclado quebrado", html)

    def test_filtros_combinados(self):
        html = self.texto(self.client.get("/chamados/?status=concluido&prioridade=media"))
        self.assertIn("Mouse travando", html)
        self.assertNotIn("Monitor piscando", html)
        html = self.texto(self.client.get("/chamados/?status=concluido&prioridade=alta"))
        self.assertIn("Nenhum chamado encontrado", html)

    def test_filtros_invalidos_sao_ignorados(self):
        r = self.client.get("/chamados/?status=xxx&prioridade=<script>&escopo=zzz")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Monitor piscando", self.texto(r))

    def test_funcionario_ignora_escopo_de_tecnico(self):
        html = self.texto(self.client.get("/chamados/?escopo=todos"))
        self.assertNotIn("Planilha corrompida", html)

    def test_detalhe_do_proprio_chamado(self):
        r = self.client.get(f"/chamados/{self.c_aberto}")
        self.assertEqual(r.status_code, 200)
        html = self.texto(r)
        self.assertIn("Monitor piscando", html)
        self.assertIn("Aguardando um técnico", html)
        self.assertIn("Histórico de atualizações", html)
        self.assertIn("Chamado aberto", html)

    def test_detalhe_mostra_tecnico_status_e_historico(self):
        html = self.texto(self.client.get(f"/chamados/{self.c_andamento}"))
        self.assertIn("Tião Técnico", html)
        self.assertIn("Em andamento", html)
        self.assertIn("Tião Técnico assumiu o atendimento.", html)
        self.assertIn("Atendimento assumido", html)

    def test_detalhe_mostra_solucao_dos_concluidos(self):
        html = self.texto(self.client.get(f"/chamados/{self.c_concluido}"))
        self.assertIn("Troquei o mouse por um novo.", html)
        self.assertIn("Concluído", html)

    def test_comentarios_do_tecnico_aparecem_no_historico(self):
        tec = self.cliente_logado("tec1@empresa.com")
        tec.post(f"/chamados/{self.c_andamento}/comentarios", data={"texto": "Peça pedida ao fornecedor."})
        html = self.texto(self.client.get(f"/chamados/{self.c_andamento}"))
        self.assertIn("Peça pedida ao fornecedor.", html)

    def test_nao_acessa_chamado_de_outro_funcionario(self):
        self.assertEqual(self.client.get(f"/chamados/{self.c_bruno}").status_code, 404)

    def test_chamado_inexistente(self):
        self.assertEqual(self.client.get("/chamados/9999").status_code, 404)

    def test_funcionario_nao_ve_botoes_de_tecnico(self):
        html = self.texto(self.client.get(f"/chamados/{self.c_aberto}"))
        self.assertNotIn("Assumir atendimento", html)
        self.assertNotIn("Registrar solução e concluir", html)

    def test_funcionario_nao_consegue_alterar_chamados_pelas_rotas_de_tecnico(self):
        antes = self.estado(self.c_aberto)
        for url, dados in ((f"/chamados/{self.c_aberto}/assumir", {}),
                           (f"/chamados/{self.c_aberto}/comentarios", {"texto": "hack"}),
                           (f"/chamados/{self.c_aberto}/concluir", {"solucao": "hack hack"}),
                           (f"/chamados/{self.c_bruno}/assumir", {})):
            with self.subTest(url):
                self.assertEqual(self.client.post(url, data=dados).status_code, 403)
        self.assertEqual(self.estado(self.c_aberto), antes)
        self.assertEqual(self.tipos_de_evento(self.c_aberto), ["abertura"])

    def test_dashboard_do_funcionario(self):
        r = self.client.get("/painel/funcionario")
        self.assertEqual(r.status_code, 200)
        html = self.texto(r)
        self.assertIn("Dashboard do funcionário", html)
        self.assertIn("Abrir novo chamado", html)
        self.assertIn("Monitor piscando", html)
        self.assertNotIn("Planilha corrompida", html)

    def test_resumo_do_funcionario_conta_por_status(self):
        with self.app.app_context():
            resumo = services.resumo_funcionario(db.session.get(User, self.ana))
        self.assertEqual(resumo["contagem"], {"aberto": 1, "em_andamento": 1, "concluido": 1})
        self.assertEqual(len(resumo["recentes"]), 3)

    def test_lista_do_funcionario_ordenada_do_mais_recente_para_o_mais_antigo(self):
        html = self.texto(self.client.get("/chamados/"))
        self.assertLess(html.index("Mouse travando"), html.index("Teclado quebrado"))
        self.assertLess(html.index("Teclado quebrado"), html.index("Monitor piscando"))


# =====================================================================
# Técnico: listar e filtrar
# =====================================================================
class TestTecnicoLista(CenarioChamados):
    def setUp(self):
        super().setUp()
        self.t1 = self.novo_chamado("ana@empresa.com", "Monitor piscando", prioridade="alta")
        self.t2 = self.novo_chamado("ana@empresa.com", "Teclado quebrado", prioridade="baixa")
        self.t3 = self.novo_chamado("ana@empresa.com", "Mouse travando", prioridade="media")
        self.t4 = self.novo_chamado("ana@empresa.com", "VPN não conecta", prioridade="alta")
        self.t5 = self.novo_chamado("bruno@empresa.com", "Planilha corrompida", prioridade="media")
        self.assumir_direto(self.t3, "tec1@empresa.com")
        self.assumir_direto(self.t4, "tec1@empresa.com")
        self.concluir_direto(self.t4, "tec1@empresa.com", "Reiniciei o serviço de VPN.")
        self.tec1_cliente = self.cliente_logado("tec1@empresa.com")
        self.tec2_cliente = self.cliente_logado("tec2@empresa.com")

    def get(self, cliente, url):
        return self.texto(cliente.get(url))

    def test_lista_padrao_mostra_apenas_disponiveis(self):
        html = self.get(self.tec2_cliente, "/chamados/")
        for titulo in ("Monitor piscando", "Teclado quebrado", "Planilha corrompida"):
            self.assertIn(titulo, html)
        for titulo in ("Mouse travando", "VPN não conecta"):
            self.assertNotIn(titulo, html)

    def test_tecnico_ve_chamados_de_todos_os_funcionarios_disponiveis(self):
        html = self.get(self.tec1_cliente, "/chamados/")
        self.assertIn("Ana Silva", html)
        self.assertIn("Bruno Souza", html)

    def test_filtro_por_prioridade(self):
        html = self.get(self.tec2_cliente, "/chamados/?prioridade=alta")
        self.assertIn("Monitor piscando", html)
        self.assertNotIn("Teclado quebrado", html)
        self.assertNotIn("Planilha corrompida", html)

    def test_filtro_por_status(self):
        html = self.get(self.tec2_cliente, "/chamados/?status=aberto")
        self.assertIn("Monitor piscando", html)
        html = self.get(self.tec2_cliente, "/chamados/?status=em_andamento")
        self.assertIn("Nenhum chamado encontrado", html)

    def test_meus_atendimentos_inclui_em_andamento_e_concluidos(self):
        html = self.get(self.tec1_cliente, "/chamados/?escopo=meus")
        self.assertIn("Mouse travando", html)
        self.assertIn("VPN não conecta", html)
        self.assertNotIn("Monitor piscando", html)

    def test_meus_atendimentos_filtrados_por_status(self):
        html = self.get(self.tec1_cliente, "/chamados/?escopo=meus&status=concluido")
        self.assertIn("VPN não conecta", html)
        self.assertNotIn("Mouse travando", html)
        html = self.get(self.tec1_cliente, "/chamados/?escopo=meus&prioridade=media")
        self.assertIn("Mouse travando", html)
        self.assertNotIn("VPN não conecta", html)

    def test_outro_tecnico_nao_ve_meus_atendimentos(self):
        html = self.get(self.tec2_cliente, "/chamados/?escopo=meus")
        self.assertIn("Nenhum chamado encontrado", html)
        self.assertNotIn("Mouse travando", html)

    def test_escopo_todos_mostra_disponiveis_e_assumidos_por_mim(self):
        html = self.get(self.tec1_cliente, "/chamados/?escopo=todos")
        for titulo in ("Monitor piscando", "Teclado quebrado", "Planilha corrompida",
                       "Mouse travando", "VPN não conecta"):
            self.assertIn(titulo, html)
        html = self.get(self.tec2_cliente, "/chamados/?escopo=todos")
        self.assertIn("Monitor piscando", html)
        self.assertNotIn("Mouse travando", html)
        self.assertNotIn("VPN não conecta", html)

    def test_ordenacao_por_prioridade(self):
        html = self.get(self.tec2_cliente, "/chamados/")
        self.assertLess(html.index("Monitor piscando"), html.index("Planilha corrompida"))
        self.assertLess(html.index("Planilha corrompida"), html.index("Teclado quebrado"))

    def test_filtros_invalidos_sao_ignorados(self):
        r = self.tec2_cliente.get("/chamados/?status=xxx&prioridade=yyy&escopo=zzz")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Monitor piscando", self.texto(r))

    def test_detalhe_de_chamado_disponivel_mostra_botao_assumir(self):
        r = self.tec2_cliente.get(f"/chamados/{self.t1}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Assumir atendimento", self.texto(r))

    def test_tecnico_nao_ve_chamado_assumido_por_outro(self):
        for chamado in (self.t3, self.t4):
            with self.subTest(chamado=chamado):
                self.assertEqual(self.tec2_cliente.get(f"/chamados/{chamado}").status_code, 404)

    def test_tecnico_ve_os_proprios_chamados_assumidos(self):
        self.assertEqual(self.tec1_cliente.get(f"/chamados/{self.t3}").status_code, 200)
        self.assertEqual(self.tec1_cliente.get(f"/chamados/{self.t4}").status_code, 200)

    def test_dashboard_do_tecnico(self):
        r = self.tec1_cliente.get("/painel/tecnico")
        self.assertEqual(r.status_code, 200)
        html = self.texto(r)
        self.assertIn("Dashboard do técnico", html)
        self.assertIn("Monitor piscando", html)     # disponível
        self.assertIn("Mouse travando", html)       # meu em andamento

    def test_resumo_do_tecnico(self):
        with self.app.app_context():
            resumo = services.resumo_tecnico(db.session.get(User, self.tec1))
        self.assertEqual(resumo["total_disponiveis"], 3)
        self.assertEqual(resumo["em_andamento"], 1)
        self.assertEqual(resumo["concluidos"], 1)
        self.assertEqual([c.titulo for c in resumo["meus_ativos"]], ["Mouse travando"])

    def test_funcionario_nao_acessa_dashboard_do_tecnico(self):
        cliente = self.cliente_logado("ana@empresa.com")
        self.assertEqual(cliente.get("/painel/tecnico").status_code, 403)


# =====================================================================
# Técnico: assumir
# =====================================================================
class TestAssumirChamado(CenarioChamados):
    def setUp(self):
        super().setUp()
        self.cid = self.novo_chamado()
        self.tec1_cliente = self.cliente_logado("tec1@empresa.com")
        self.tec2_cliente = self.cliente_logado("tec2@empresa.com")

    def assumir(self, cliente, chamado_id=None, **kwargs):
        return cliente.post(f"/chamados/{chamado_id or self.cid}/assumir", **kwargs)

    def test_assumir_atribui_tecnico_e_muda_status(self):
        r = self.assumir(self.tec1_cliente)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith(f"/chamados/{self.cid}"))
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))

    def test_assumir_registra_historico(self):
        self.assumir(self.tec1_cliente)
        self.assertEqual(
            self.eventos(self.cid)[1],
            ("assumido", self.tec1, "aberto", "em_andamento", "Tião Técnico assumiu o atendimento."),
        )

    def test_assumir_atualiza_a_data_de_atualizacao(self):
        criado, atualizado_antes = self.sql(
            "SELECT criado_em, atualizado_em FROM chamados WHERE id = ?", (self.cid,))[0]
        self.assumir(self.tec1_cliente)
        atualizado_depois = self.sql(
            "SELECT atualizado_em FROM chamados WHERE id = ?", (self.cid,))[0][0]
        self.assertGreater(atualizado_depois, atualizado_antes)
        self.assertGreaterEqual(atualizado_depois, criado)

    def test_mensagem_de_sucesso(self):
        r = self.assumir(self.tec1_cliente, follow_redirects=True)
        self.assertIn("Você assumiu o atendimento", self.texto(r))

    def test_segundo_tecnico_nao_consegue_assumir(self):
        self.assumir(self.tec1_cliente)
        r = self.assumir(self.tec2_cliente, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("não está mais disponível", self.texto(r))
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido"])

    def test_mesmo_tecnico_nao_assume_duas_vezes(self):
        self.assumir(self.tec1_cliente)
        self.assumir(self.tec1_cliente)
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido"])

    def test_chamado_concluido_nao_pode_ser_assumido_novamente(self):
        self.assumir_direto(self.cid, "tec1@empresa.com")
        self.concluir_direto(self.cid, "tec1@empresa.com")
        for cliente in (self.tec1_cliente, self.tec2_cliente):
            r = self.assumir(cliente, follow_redirects=True)
            self.assertIn("não está mais disponível", self.texto(r))
        self.assertEqual(self.estado(self.cid), ("concluido", self.tec1))
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido", "conclusao"])

    def test_servico_recusa_assumir_chamado_concluido(self):
        self.assumir_direto(self.cid, "tec1@empresa.com")
        self.concluir_direto(self.cid, "tec1@empresa.com")
        self.assertFalse(self.assumir_direto(self.cid, "tec2@empresa.com"))

    def test_chamado_inexistente(self):
        self.assertEqual(self.assumir(self.tec1_cliente, 9999).status_code, 404)

    def test_tecnico_nao_assume_chamado_que_ele_mesmo_abriu(self):
        proprio = self.novo_chamado("tec1@empresa.com", "Chamado do próprio técnico")
        r = self.assumir(self.tec1_cliente, proprio, follow_redirects=True)
        self.assertIn("não está mais disponível", self.texto(r))
        self.assertEqual(self.estado(proprio), ("aberto", None))

    def test_tecnico_comum_nao_assume_via_get(self):
        self.assertEqual(self.tec1_cliente.get(f"/chamados/{self.cid}/assumir").status_code, 405)

    def test_visitante_nao_assume(self):
        r = self.client.post(f"/chamados/{self.cid}/assumir")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])
        self.assertEqual(self.estado(self.cid), ("aberto", None))

    def test_servico_exige_usuario_tecnico(self):
        with self.app.app_context():
            self.assertFalse(services.assumir_chamado(self.cid, db.session.get(User, self.ana)))
        self.assertEqual(self.estado(self.cid), ("aberto", None))


# =====================================================================
# Técnico: comentar e concluir
# =====================================================================
class TestAtendimento(CenarioChamados):
    def setUp(self):
        super().setUp()
        self.cid = self.novo_chamado()
        self.assumir_direto(self.cid, "tec1@empresa.com")
        self.tec1_cliente = self.cliente_logado("tec1@empresa.com")
        self.tec2_cliente = self.cliente_logado("tec2@empresa.com")
        self.ana_cliente = self.cliente_logado("ana@empresa.com")

    def comentar(self, cliente, texto="Verificando o cabo de rede.", chamado_id=None, **kw):
        return cliente.post(f"/chamados/{chamado_id or self.cid}/comentarios",
                            data={"texto": texto}, **kw)

    def concluir(self, cliente, solucao="Troquei o cabo de rede.", chamado_id=None, **kw):
        return cliente.post(f"/chamados/{chamado_id or self.cid}/concluir",
                            data={"solucao": solucao}, **kw)

    # --- comentários ---------------------------------------------------
    def test_responsavel_registra_comentario(self):
        antes = self.sql("SELECT atualizado_em FROM chamados WHERE id = ?", (self.cid,))[0][0]
        r = self.comentar(self.tec1_cliente, follow_redirects=True)
        self.assertIn("Comentário registrado", self.texto(r))

        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido", "comentario"])
        evento = self.eventos(self.cid)[2]
        self.assertEqual(evento[1], self.tec1)
        self.assertEqual(evento[4], "Verificando o cabo de rede.")
        depois = self.sql("SELECT atualizado_em FROM chamados WHERE id = ?", (self.cid,))[0][0]
        self.assertGreater(depois, antes)
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))

    def test_comentario_vazio_ou_curto_e_rejeitado(self):
        for texto in ("", "   ", "a"):
            with self.subTest(texto=texto):
                r = self.comentar(self.tec1_cliente, texto, follow_redirects=True)
                self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido"])

    def test_comentario_invalido_mostra_mensagem_de_erro(self):
        r = self.comentar(self.tec1_cliente, "", follow_redirects=True)
        self.assertIn("Escreva o comentário", self.texto(r))

    def test_tecnico_sem_assumir_nao_comenta_chamado_disponivel(self):
        livre = self.novo_chamado(titulo="Chamado ainda livre")
        r = self.comentar(self.tec2_cliente, chamado_id=livre)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.tipos_de_evento(livre), ["abertura"])

    def test_tecnico_nao_comenta_chamado_de_outro_tecnico(self):
        r = self.comentar(self.tec2_cliente)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido"])

    def test_nao_comenta_chamado_concluido(self):
        self.concluir(self.tec1_cliente)
        r = self.comentar(self.tec1_cliente, "Comentário tardio", follow_redirects=True)
        self.assertIn("não está em andamento", self.texto(r))
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido", "conclusao"])

    def test_comentario_inexistente(self):
        self.assertEqual(self.comentar(self.tec1_cliente, chamado_id=9999).status_code, 404)

    # --- conclusão -----------------------------------------------------
    def test_responsavel_conclui_com_solucao(self):
        r = self.concluir(self.tec1_cliente, follow_redirects=True)
        self.assertIn("Chamado concluído com sucesso", self.texto(r))

        status, tecnico_id, solucao, concluido, criado, atualizado = self.sql(
            "SELECT status, tecnico_id, solucao, concluido_em, criado_em, atualizado_em "
            "FROM chamados WHERE id = ?", (self.cid,))[0]
        self.assertEqual(status, "concluido")
        self.assertEqual(tecnico_id, self.tec1)
        self.assertEqual(solucao, "Troquei o cabo de rede.")
        self.assertIsNotNone(concluido)
        self.assertGreaterEqual(atualizado, criado)
        self.assertEqual(atualizado, concluido)

        self.assertEqual(
            self.eventos(self.cid)[-1],
            ("conclusao", self.tec1, "em_andamento", "concluido", "Troquei o cabo de rede."),
        )

    def test_solucao_vazia_ou_curta_nao_conclui(self):
        for solucao in ("", "    ", "ok"):
            with self.subTest(solucao=solucao):
                self.concluir(self.tec1_cliente, solucao)
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))
        self.assertEqual(self.sql("SELECT concluido_em FROM chamados")[0][0], None)

    def test_solucao_invalida_mostra_mensagem_de_erro(self):
        r = self.concluir(self.tec1_cliente, "", follow_redirects=True)
        self.assertIn("Descreva a solução aplicada", self.texto(r))

    def test_tecnico_sem_assumir_nao_conclui_chamado_disponivel(self):
        livre = self.novo_chamado(titulo="Chamado ainda livre")
        self.assertEqual(self.concluir(self.tec2_cliente, chamado_id=livre).status_code, 403)
        self.assertEqual(self.estado(livre), ("aberto", None))

    def test_tecnico_nao_conclui_chamado_de_outro_tecnico(self):
        self.assertEqual(self.concluir(self.tec2_cliente).status_code, 404)
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))
        self.assertIsNone(self.sql("SELECT solucao FROM chamados")[0][0])

    def test_nao_conclui_duas_vezes(self):
        self.concluir(self.tec1_cliente, "Primeira solução registrada.")
        r = self.concluir(self.tec1_cliente, "Segunda solução registrada.", follow_redirects=True)
        self.assertIn("não está em andamento", self.texto(r))
        self.assertEqual(self.sql("SELECT solucao FROM chamados")[0][0], "Primeira solução registrada.")
        self.assertEqual(self.tipos_de_evento(self.cid).count("conclusao"), 1)

    def test_servico_nao_conclui_chamado_de_outro_tecnico(self):
        with self.app.app_context():
            tec2 = db.session.get(User, self.tec2)
            self.assertFalse(services.concluir_chamado(self.cid, tec2, "Solução indevida."))
            self.assertFalse(services.adicionar_comentario(self.cid, tec2, "Comentário indevido."))
        self.assertEqual(self.estado(self.cid), ("em_andamento", self.tec1))
        self.assertEqual(self.tipos_de_evento(self.cid), ["abertura", "assumido"])

    def test_funcionario_ve_solucao_e_historico_completo(self):
        self.comentar(self.tec1_cliente, "Cabo testado, está com defeito.")
        self.concluir(self.tec1_cliente, "Cabo substituído por um novo.")
        html = self.texto(self.ana_cliente.get(f"/chamados/{self.cid}"))
        self.assertIn("Cabo testado, está com defeito.", html)
        self.assertIn("Cabo substituído por um novo.", html)
        self.assertIn("Chamado concluído", html)
        self.assertIn("Tião Técnico", html)

    def test_historico_em_ordem_cronologica(self):
        self.comentar(self.tec1_cliente, "Primeiro comentário aqui.")
        self.comentar(self.tec1_cliente, "Segundo comentário aqui.")
        self.concluir(self.tec1_cliente)
        self.assertEqual(self.tipos_de_evento(self.cid),
                         ["abertura", "assumido", "comentario", "comentario", "conclusao"])
        html = self.texto(self.ana_cliente.get(f"/chamados/{self.cid}"))
        self.assertLess(html.index("Primeiro comentário aqui."), html.index("Segundo comentário aqui."))

    def test_formularios_de_atendimento_so_aparecem_para_o_responsavel(self):
        html = self.texto(self.tec1_cliente.get(f"/chamados/{self.cid}"))
        self.assertIn("Registrar solução e concluir", html)
        self.assertIn("Adicionar comentário", html)
        self.assertNotIn("Assumir atendimento", html)

        livre = self.novo_chamado(titulo="Chamado ainda livre")
        html = self.texto(self.tec1_cliente.get(f"/chamados/{livre}"))
        self.assertNotIn("Registrar solução e concluir", html)
        self.assertIn("Assumir atendimento", html)

    def test_formularios_somem_depois_de_concluir(self):
        self.concluir(self.tec1_cliente)
        html = self.texto(self.tec1_cliente.get(f"/chamados/{self.cid}"))
        self.assertNotIn("Registrar solução e concluir", html)
        self.assertNotIn("Adicionar comentário", html)


# =====================================================================
# Concorrência
# =====================================================================
class TestConcorrencia(CenarioChamados):
    TECNICOS = 8

    def criar_tecnicos(self):
        return [
            self.criar_usuario(f"Técnico {i}", f"tecnico{i}@empresa.com", tipo=TIPO_TECNICO)
            for i in range(self.TECNICOS)
        ]

    def test_servico_apenas_um_tecnico_assume(self):
        """N técnicos chamam assumir_chamado() ao mesmo tempo: só um consegue."""
        cid = self.novo_chamado()
        ids = self.criar_tecnicos()
        barreira = threading.Barrier(len(ids))
        resultados, erros = {}, []

        def tentar(tecnico_id):
            try:
                with self.app.app_context():
                    tecnico = db.session.get(User, tecnico_id)
                    barreira.wait(timeout=15)
                    resultados[tecnico_id] = services.assumir_chamado(cid, tecnico)
            except Exception as erro:  # noqa: BLE001 - registrado e verificado abaixo
                erros.append(repr(erro))

        threads = [threading.Thread(target=tentar, args=(i,)) for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(erros, [])
        self.assertEqual(len(resultados), len(ids))
        vencedores = [i for i, ok in resultados.items() if ok]
        self.assertEqual(len(vencedores), 1)

        self.assertEqual(self.estado(cid), ("em_andamento", vencedores[0]))
        self.assertEqual(self.tipos_de_evento(cid), ["abertura", "assumido"])
        self.assertEqual(self.eventos(cid)[1][1], vencedores[0])

    def test_http_apenas_um_tecnico_assume(self):
        """N técnicos enviam POST /assumir ao mesmo tempo: só um consegue."""
        cid = self.novo_chamado()
        ids = self.criar_tecnicos()
        clientes = [self.cliente_logado(f"tecnico{i}@empresa.com") for i in range(len(ids))]
        barreira = threading.Barrier(len(clientes))
        codigos, erros = [], []

        def tentar(cliente):
            try:
                barreira.wait(timeout=15)
                codigos.append(cliente.post(f"/chamados/{cid}/assumir").status_code)
            except Exception as erro:  # noqa: BLE001
                erros.append(repr(erro))

        threads = [threading.Thread(target=tentar, args=(c,)) for c in clientes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(erros, [])
        self.assertEqual(codigos, [302] * len(clientes))  # nenhuma resposta de erro (500)

        status, tecnico_id = self.estado(cid)
        self.assertEqual(status, "em_andamento")
        self.assertIn(tecnico_id, ids)
        self.assertEqual(self.tipos_de_evento(cid), ["abertura", "assumido"])
        self.assertEqual(self.eventos(cid)[1][1], tecnico_id)

    def test_concluir_ao_mesmo_tempo_registra_uma_unica_conclusao(self):
        cid = self.novo_chamado()
        self.assumir_direto(cid, "tec1@empresa.com")
        barreira = threading.Barrier(4)
        resultados, erros = [], []

        def tentar():
            try:
                with self.app.app_context():
                    tecnico = db.session.get(User, self.tec1)
                    barreira.wait(timeout=15)
                    resultados.append(services.concluir_chamado(cid, tecnico, "Solução concorrente."))
            except Exception as erro:  # noqa: BLE001
                erros.append(repr(erro))

        threads = [threading.Thread(target=tentar) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(erros, [])
        self.assertEqual(sorted(resultados), [False, False, False, True])
        self.assertEqual(self.tipos_de_evento(cid).count("conclusao"), 1)


# =====================================================================
# CSRF nos formulários novos
# =====================================================================
class TestCSRFChamados(CenarioChamados):
    csrf = True

    def test_abrir_chamado_exige_token(self):
        cliente = self.cliente_logado("ana@empresa.com")
        self.assertEqual(cliente.post("/chamados/novo", data=dados_chamado()).status_code, 400)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM chamados")[0][0], 0)

        token = self.obter_token("/chamados/novo", cliente)
        r = cliente.post("/chamados/novo", data=dados_chamado(csrf_token=token))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM chamados")[0][0], 1)

    def test_assumir_exige_token(self):
        cid = self.novo_chamado()
        tecnico = self.cliente_logado("tec1@empresa.com")
        self.assertEqual(tecnico.post(f"/chamados/{cid}/assumir").status_code, 400)
        self.assertEqual(self.estado(cid), ("aberto", None))

        token = self.obter_token(f"/chamados/{cid}", tecnico)
        r = tecnico.post(f"/chamados/{cid}/assumir", data={"csrf_token": token})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estado(cid), ("em_andamento", self.tec1))

    def test_comentar_e_concluir_exigem_token(self):
        cid = self.novo_chamado()
        self.assumir_direto(cid)
        tecnico = self.cliente_logado("tec1@empresa.com")

        self.assertEqual(tecnico.post(f"/chamados/{cid}/comentarios",
                                      data={"texto": "Sem token aqui."}).status_code, 400)
        self.assertEqual(tecnico.post(f"/chamados/{cid}/concluir",
                                      data={"solucao": "Sem token aqui."}).status_code, 400)
        self.assertEqual(self.tipos_de_evento(cid), ["abertura", "assumido"])
        self.assertEqual(self.estado(cid), ("em_andamento", self.tec1))

        token = self.obter_token(f"/chamados/{cid}", tecnico)
        self.assertEqual(tecnico.post(f"/chamados/{cid}/comentarios",
                                      data={"csrf_token": token, "texto": "Com token aqui."}).status_code, 302)
        self.assertEqual(tecnico.post(f"/chamados/{cid}/concluir",
                                      data={"csrf_token": token, "solucao": "Com token aqui."}).status_code, 302)
        self.assertEqual(self.tipos_de_evento(cid), ["abertura", "assumido", "comentario", "conclusao"])

    def test_formularios_de_acao_incluem_token(self):
        cid = self.novo_chamado()
        tecnico = self.cliente_logado("tec1@empresa.com")
        # Chamado disponível: botão "Assumir" com token
        self.assertIn('name="csrf_token"', self.texto(tecnico.get(f"/chamados/{cid}")))
        # Chamado assumido: formulários de comentário e conclusão com token
        self.assumir_direto(cid)
        html = self.texto(tecnico.get(f"/chamados/{cid}"))
        self.assertGreaterEqual(html.count('name="csrf_token"'), 3)


# =====================================================================
# Datas
# =====================================================================
class TestFormatarDatahora(unittest.TestCase):
    def test_converte_utc_para_o_fuso_informado(self):
        self.assertEqual(formatar_datahora(datetime(2026, 11, 23, 15, 0), -3), "23/11/2026 12:00")

    def test_virada_de_dia(self):
        self.assertEqual(formatar_datahora(datetime(2026, 11, 23, 1, 30), -3), "22/11/2026 22:30")

    def test_sem_data(self):
        self.assertEqual(formatar_datahora(None), "—")


class TestDatasNasPaginas(CenarioChamados):
    def test_detalhe_mostra_datas_formatadas(self):
        cid = self.novo_chamado()
        self.assumir_direto(cid)
        self.concluir_direto(cid)
        cliente = self.cliente_logado("ana@empresa.com")
        html = self.texto(cliente.get(f"/chamados/{cid}"))
        self.assertRegex(html, r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")
        self.assertNotIn("—", html.split("Concluído em")[1].split("</dd>")[0])

    def test_chamado_nao_concluido_mostra_traco_em_concluido_em(self):
        cid = self.novo_chamado()
        cliente = self.cliente_logado("ana@empresa.com")
        html = self.texto(cliente.get(f"/chamados/{cid}"))
        self.assertIn("—", html.split("Concluído em")[1].split("</dd>")[0])


# =====================================================================
# Preservação das telas anteriores
# =====================================================================
class TestPreservacaoEtapa2(CenarioChamados):
    def test_pagina_inicial_e_cadastro_continuam_funcionando(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/cadastro").status_code, 200)

    def test_painel_de_perfil_continua_acessivel(self):
        self.entrar()
        r = self.client.get("/painel")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Ana Silva", self.texto(r))

    def test_navbar_por_tipo_de_usuario(self):
        func = self.texto(self.cliente_logado("ana@empresa.com").get("/painel"))
        self.assertIn("Meus chamados", func)
        self.assertIn("Novo chamado", func)
        self.assertNotIn("Meus atendimentos", func)

        tec = self.texto(self.cliente_logado("tec1@empresa.com").get("/painel"))
        self.assertIn("Meus atendimentos", tec)
        self.assertNotIn("Novo chamado", tec)


if __name__ == "__main__":
    unittest.main()
