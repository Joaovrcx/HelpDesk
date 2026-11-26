"""Testes do filtro de categoria na lista de chamados (Etapa 4).

Execute na raiz do projeto, com o .venv ativado:
    python -X dev -m unittest discover -s tests -v
"""

import re
import unittest

from app import services
from app.extensions import db
from app.models import CATEGORIA_LABELS, User
from test_chamados import CenarioChamados


class BaseFiltroCategoria(CenarioChamados):
    """Chamados da Ana (hardware x3, rede x1) e do Bruno (hardware x1).

    O técnico 1 assume o "Teclado Beta" (em andamento) e conclui o "Mouse Gama".
    """

    def setUp(self):
        super().setUp()
        nc = self.novo_chamado
        self.a1 = nc("ana@empresa.com", "Tela Alfa", categoria="hardware", prioridade="alta")
        self.a2 = nc("ana@empresa.com", "Teclado Beta", categoria="hardware", prioridade="baixa")
        self.a3 = nc("ana@empresa.com", "Mouse Gama", categoria="hardware", prioridade="alta")
        self.a4 = nc("ana@empresa.com", "VPN Delta", categoria="rede", prioridade="alta")
        self.b1 = nc("bruno@empresa.com", "Planilha Bruno", categoria="hardware", prioridade="alta")
        self.assumir_direto(self.a2)
        self.assumir_direto(self.a3)
        self.concluir_direto(self.a3)

    def get(self, cliente, url):
        resposta = cliente.get(url)
        self.assertEqual(resposta.status_code, 200)
        return self.texto(resposta)

    def conferir(self, html, presentes=(), ausentes=()):
        for titulo in presentes:
            self.assertIn(titulo, html)
        for titulo in ausentes:
            self.assertNotIn(titulo, html)


class TestFiltroCategoriaFuncionario(BaseFiltroCategoria):
    def setUp(self):
        super().setUp()
        self.ana_c = self.cliente_logado("ana@empresa.com")

    def test_filtra_por_categoria(self):
        html = self.get(self.ana_c, "/chamados/?categoria=hardware")
        self.conferir(html, ("Tela Alfa", "Teclado Beta", "Mouse Gama"), ("VPN Delta",))
        html = self.get(self.ana_c, "/chamados/?categoria=rede")
        self.conferir(html, ("VPN Delta",), ("Tela Alfa", "Teclado Beta", "Mouse Gama"))

    def test_categoria_sem_chamados(self):
        html = self.get(self.ana_c, "/chamados/?categoria=impressora")
        self.assertIn("Nenhum chamado encontrado", html)
        self.assertIn("0 chamado(s)", html)

    def test_sem_filtro_continua_mostrando_todos_os_proprios(self):
        html = self.get(self.ana_c, "/chamados/")
        self.conferir(html, ("Tela Alfa", "Teclado Beta", "Mouse Gama", "VPN Delta"), ("Planilha Bruno",))

    def test_nunca_mostra_chamado_de_outro_funcionario(self):
        # O Bruno também tem um chamado de hardware, mas a Ana não pode vê-lo.
        html = self.get(self.ana_c, "/chamados/?categoria=hardware")
        self.assertNotIn("Planilha Bruno", html)
        bruno_c = self.cliente_logado("bruno@empresa.com")
        html = self.get(bruno_c, "/chamados/?categoria=hardware")
        self.conferir(html, ("Planilha Bruno",), ("Tela Alfa", "Teclado Beta", "Mouse Gama"))

    def test_categoria_com_status(self):
        html = self.get(self.ana_c, "/chamados/?categoria=hardware&status=em_andamento")
        self.conferir(html, ("Teclado Beta",), ("Tela Alfa", "Mouse Gama", "VPN Delta"))

    def test_categoria_com_prioridade(self):
        html = self.get(self.ana_c, "/chamados/?categoria=hardware&prioridade=alta")
        self.conferir(html, ("Tela Alfa", "Mouse Gama"), ("Teclado Beta", "VPN Delta"))

    def test_tres_filtros_combinados(self):
        html = self.get(self.ana_c, "/chamados/?categoria=hardware&prioridade=alta&status=concluido")
        self.conferir(html, ("Mouse Gama",), ("Tela Alfa", "Teclado Beta", "VPN Delta"))
        html = self.get(self.ana_c, "/chamados/?categoria=rede&prioridade=alta&status=aberto")
        self.conferir(html, ("VPN Delta",), ("Tela Alfa", "Mouse Gama"))

    def test_combinacao_sem_resultado(self):
        html = self.get(self.ana_c, "/chamados/?categoria=hardware&prioridade=baixa&status=concluido")
        self.assertIn("Nenhum chamado encontrado", html)

    def test_filtros_de_status_e_prioridade_continuam_funcionando(self):
        html = self.get(self.ana_c, "/chamados/?status=em_andamento")
        self.conferir(html, ("Teclado Beta",), ("Tela Alfa", "VPN Delta"))
        html = self.get(self.ana_c, "/chamados/?prioridade=baixa")
        self.conferir(html, ("Teclado Beta",), ("Tela Alfa", "VPN Delta"))

    def test_formulario_lista_todas_as_categorias(self):
        html = self.get(self.ana_c, "/chamados/")
        self.assertIn('name="categoria"', html)
        self.assertIn('<option value="">Todas</option>', html)
        for valor, rotulo in CATEGORIA_LABELS.items():
            self.assertIn(f'<option value="{valor}"', html)
            self.assertIn(rotulo, html)
        self.assertEqual(len(CATEGORIA_LABELS), 7)

    def test_categoria_escolhida_fica_selecionada(self):
        for valor in CATEGORIA_LABELS:
            with self.subTest(categoria=valor):
                html = self.get(self.ana_c, f"/chamados/?categoria={valor}")
                self.assertRegex(html, rf'<option value="{valor}"\s+selected')
                self.assertEqual(len(re.findall(r'<option value="\w+"\s+selected', html)), 1)

    def test_categoria_invalida_e_ignorada(self):
        for valor in ("xxx", "HARDWARE", "<script>alert(1)</script>", "hardware%20"):
            with self.subTest(valor=valor):
                resposta = self.ana_c.get("/chamados/", query_string={"categoria": valor})
                self.assertEqual(resposta.status_code, 200)
                html = self.texto(resposta)
                self.conferir(html, ("Tela Alfa", "VPN Delta"))
                self.assertNotIn("<script>alert(1)</script>", html)

    def test_categoria_invalida_com_outros_filtros_validos(self):
        html = self.get(self.ana_c, "/chamados/?categoria=xxx&status=em_andamento")
        self.conferir(html, ("Teclado Beta",), ("Tela Alfa", "VPN Delta"))


class TestFiltroCategoriaTecnico(BaseFiltroCategoria):
    def setUp(self):
        super().setUp()
        self.tec1_c = self.cliente_logado("tec1@empresa.com")
        self.tec2_c = self.cliente_logado("tec2@empresa.com")

    def test_disponiveis_por_categoria(self):
        # Escopo padrão = disponíveis: a1, a4 e b1 (a2 e a3 já foram assumidos)
        html = self.get(self.tec2_c, "/chamados/?categoria=hardware")
        self.conferir(html, ("Tela Alfa", "Planilha Bruno"), ("Teclado Beta", "Mouse Gama", "VPN Delta"))
        html = self.get(self.tec2_c, "/chamados/?categoria=rede")
        self.conferir(html, ("VPN Delta",), ("Tela Alfa", "Planilha Bruno"))

    def test_disponiveis_sem_filtro(self):
        html = self.get(self.tec2_c, "/chamados/")
        self.conferir(html, ("Tela Alfa", "VPN Delta", "Planilha Bruno"), ("Teclado Beta", "Mouse Gama"))

    def test_categoria_com_prioridade_e_status(self):
        html = self.get(self.tec2_c, "/chamados/?categoria=hardware&prioridade=alta&status=aberto")
        self.conferir(html, ("Tela Alfa", "Planilha Bruno"), ("VPN Delta",))
        html = self.get(self.tec2_c, "/chamados/?categoria=hardware&status=em_andamento")
        self.assertIn("Nenhum chamado encontrado", html)  # em andamento não está disponível

    def test_meus_atendimentos_por_categoria(self):
        html = self.get(self.tec1_c, "/chamados/?escopo=meus&categoria=hardware")
        self.conferir(html, ("Teclado Beta", "Mouse Gama"), ("Tela Alfa", "Planilha Bruno", "VPN Delta"))
        html = self.get(self.tec1_c, "/chamados/?escopo=meus&categoria=rede")
        self.assertIn("Nenhum chamado encontrado", html)

    def test_meus_atendimentos_com_tres_filtros(self):
        html = self.get(self.tec1_c, "/chamados/?escopo=meus&categoria=hardware&prioridade=alta&status=concluido")
        self.conferir(html, ("Mouse Gama",), ("Teclado Beta",))
        html = self.get(self.tec1_c, "/chamados/?escopo=meus&categoria=hardware&prioridade=baixa&status=em_andamento")
        self.conferir(html, ("Teclado Beta",), ("Mouse Gama",))

    def test_todos_os_visiveis_respeita_a_regra_de_acesso(self):
        # tec1 vê os disponíveis + os próprios; tec2 vê só os disponíveis.
        html = self.get(self.tec1_c, "/chamados/?escopo=todos&categoria=hardware")
        self.conferir(html, ("Tela Alfa", "Planilha Bruno", "Teclado Beta", "Mouse Gama"), ("VPN Delta",))
        html = self.get(self.tec2_c, "/chamados/?escopo=todos&categoria=hardware")
        self.conferir(html, ("Tela Alfa", "Planilha Bruno"), ("Teclado Beta", "Mouse Gama", "VPN Delta"))

    def test_filtro_nao_expoe_atendimento_de_outro_tecnico(self):
        for escopo in ("disponiveis", "meus", "todos"):
            with self.subTest(escopo=escopo):
                html = self.get(self.tec2_c, f"/chamados/?escopo={escopo}&categoria=hardware")
                self.conferir(html, (), ("Teclado Beta", "Mouse Gama"))

    def test_formulario_do_tecnico_tem_escopo_e_categoria(self):
        html = self.get(self.tec1_c, "/chamados/?escopo=meus&categoria=impressora")
        self.assertIn('name="escopo"', html)
        self.assertIn('name="categoria"', html)
        self.assertRegex(html, r'<option value="impressora"\s+selected')
        self.assertRegex(html, r'<option value="meus"\s+selected')

    def test_categoria_invalida_e_ignorada(self):
        resposta = self.tec2_c.get("/chamados/?categoria=zzz&escopo=todos")
        self.assertEqual(resposta.status_code, 200)
        self.conferir(self.texto(resposta), ("Tela Alfa", "VPN Delta"))


class TestListarChamadosCategoria(BaseFiltroCategoria):
    """Camada de serviço, sem passar pela rota."""

    def titulos(self, email, **filtros):
        with self.app.app_context():
            usuario = db.session.execute(db.select(User).filter_by(email=email)).scalar_one()
            return {c.titulo for c in services.listar_chamados(usuario, **filtros)}

    def test_funcionario(self):
        self.assertEqual(self.titulos("ana@empresa.com", categoria="rede"), {"VPN Delta"})
        self.assertEqual(
            self.titulos("ana@empresa.com", categoria="hardware", prioridade="alta"),
            {"Tela Alfa", "Mouse Gama"},
        )
        self.assertEqual(
            self.titulos("ana@empresa.com", categoria="hardware", prioridade="alta", status="aberto"),
            {"Tela Alfa"},
        )

    def test_sem_categoria_nao_filtra(self):
        self.assertEqual(len(self.titulos("ana@empresa.com")), 4)
        self.assertEqual(len(self.titulos("ana@empresa.com", categoria="")), 4)

    def test_tecnico_respeita_escopo(self):
        self.assertEqual(
            self.titulos("tec2@empresa.com", escopo="todos", categoria="hardware"),
            {"Tela Alfa", "Planilha Bruno"},
        )
        self.assertEqual(
            self.titulos("tec1@empresa.com", escopo="meus", categoria="hardware"),
            {"Teclado Beta", "Mouse Gama"},
        )


if __name__ == "__main__":
    unittest.main()
