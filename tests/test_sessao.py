"""Testes da sessão de login diante da troca de User-Agent (simulação mobile).

Contexto: com session_protection = "strong", o Flask-Login apagava a sessão
quando o User-Agent mudava entre o login e as requisições seguintes (o que
acontece ao alternar entre desktop e simulação mobile no DevTools). Com "basic"
o usuário continua logado.

Execute na raiz do projeto, com o .venv ativado:
    python -X dev -m unittest discover -s tests -v
"""

import unittest

from app.extensions import login_manager
from app.models import TIPO_TECNICO
from base_testes import SENHA, BaseTestCase

DESKTOP = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 OPR/115"}
MOBILE = {"User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) Chrome/130 Mobile Safari/537.36"}

ROTAS_PROTEGIDAS = (
    "/painel",
    "/painel/funcionario",
    "/painel/tecnico",
    "/chamados/",
    "/chamados/novo",
)


class BaseSessao(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.criar_usuario("Ana Silva", "ana@empresa.com")
        self.criar_usuario("Tião Técnico", "tec@empresa.com", tipo=TIPO_TECNICO)

    def entrar_como(self, email, headers, **extra):
        """Novo cliente que faz login com os cabeçalhos informados."""
        cliente = self.app.test_client()
        resposta = cliente.post(
            "/login", data={"email": email, "senha": SENHA, **extra}, headers=headers
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("/login", resposta.headers["Location"])
        return cliente


class TestTrocaDeUserAgent(BaseSessao):
    def test_configuracao_nao_apaga_a_sessao(self):
        self.assertEqual(login_manager.session_protection, "basic")

    def test_login_no_desktop_e_navegacao_no_mobile_mantem_a_sessao(self):
        cliente = self.entrar_como("ana@empresa.com", DESKTOP)
        self.assertEqual(cliente.get("/painel/funcionario", headers=DESKTOP).status_code, 200)
        for url in ("/painel/funcionario", "/chamados/", "/chamados/novo", "/painel"):
            with self.subTest(url=url):
                resposta = cliente.get(url, headers=MOBILE)
                self.assertEqual(resposta.status_code, 200, "a troca de User-Agent derrubou a sessão")
        # e a sessão continua valida ao voltar para o desktop
        self.assertEqual(cliente.get("/painel/funcionario", headers=DESKTOP).status_code, 200)

    def test_login_no_mobile_e_navegacao_no_desktop_mantem_a_sessao(self):
        cliente = self.entrar_como("ana@empresa.com", MOBILE)
        self.assertEqual(cliente.get("/painel/funcionario", headers=MOBILE).status_code, 200)
        for url in ("/painel/funcionario", "/chamados/", "/chamados/novo", "/painel"):
            with self.subTest(url=url):
                resposta = cliente.get(url, headers=DESKTOP)
                self.assertEqual(resposta.status_code, 200, "a troca de User-Agent derrubou a sessão")
        self.assertEqual(cliente.get("/painel/funcionario", headers=MOBILE).status_code, 200)

    def test_tecnico_tambem_mantem_a_sessao_ao_trocar_de_user_agent(self):
        cliente = self.entrar_como("tec@empresa.com", DESKTOP)
        self.assertEqual(cliente.get("/painel/tecnico", headers=MOBILE).status_code, 200)
        self.assertEqual(cliente.get("/chamados/", headers=MOBILE).status_code, 200)

    def test_logout_continua_funcionando_com_outro_user_agent(self):
        cliente = self.entrar_como("ana@empresa.com", DESKTOP)
        resposta = cliente.post("/logout", headers=MOBILE)
        self.assertEqual(resposta.status_code, 302)
        resposta = cliente.get("/painel", headers=MOBILE)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.headers["Location"])


class TestPermissoesNaoMudam(BaseSessao):
    def test_funcionario_nao_acessa_rotas_de_tecnico_com_nenhum_user_agent(self):
        cliente = self.entrar_como("ana@empresa.com", DESKTOP)
        for headers in (DESKTOP, MOBILE):
            with self.subTest(agente=headers["User-Agent"][:30]):
                self.assertEqual(cliente.get("/painel/tecnico", headers=headers).status_code, 403)
                for acao in ("assumir", "comentarios", "concluir"):
                    resposta = cliente.post(f"/chamados/1/{acao}", headers=headers)
                    self.assertEqual(resposta.status_code, 403, acao)

    def test_tecnico_nao_acessa_dashboard_de_funcionario(self):
        cliente = self.entrar_como("tec@empresa.com", DESKTOP)
        self.assertEqual(cliente.get("/painel/funcionario", headers=MOBILE).status_code, 403)
        self.assertEqual(cliente.get("/chamados/novo", headers=MOBILE).status_code, 403)

    def test_nao_autenticado_continua_sem_acesso(self):
        anonimo = self.app.test_client()
        for headers in (DESKTOP, MOBILE):
            for url in ROTAS_PROTEGIDAS:
                with self.subTest(url=url, agente=headers["User-Agent"][:30]):
                    resposta = anonimo.get(url, headers=headers)
                    self.assertEqual(resposta.status_code, 302)
                    self.assertIn("/login", resposta.headers["Location"])

    def test_cookie_invalido_nao_autentica(self):
        cliente = self.app.test_client()
        cliente.set_cookie("session", "valor-forjado")
        resposta = cliente.get("/painel", headers=MOBILE)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.headers["Location"])


class TestRememberMe(BaseSessao):
    """Investiga o "Manter conectado" (cookie remember_token) com troca de User-Agent."""

    def test_remember_me_apos_perder_o_cookie_de_sessao(self):
        # Simula fechar o navegador: o cookie de sessão some, o de remember-me fica.
        cliente = self.entrar_como("ana@empresa.com", DESKTOP, lembrar="y")
        cliente.delete_cookie("session")
        primeira = cliente.get("/painel/funcionario", headers=DESKTOP)
        self.assertEqual(primeira.status_code, 200, "remember-me não restaurou o login")
        segunda = cliente.get("/painel/funcionario", headers=DESKTOP)
        self.assertEqual(segunda.status_code, 200, "o login caiu na 2ª requisição")

    def test_remember_me_apos_perder_a_sessao_e_trocar_de_user_agent(self):
        cliente = self.entrar_como("ana@empresa.com", DESKTOP, lembrar="y")
        cliente.delete_cookie("session")
        self.assertEqual(cliente.get("/painel/funcionario", headers=MOBILE).status_code, 200)
        self.assertEqual(cliente.get("/painel/funcionario", headers=MOBILE).status_code, 200)
        self.assertEqual(cliente.get("/painel/funcionario", headers=DESKTOP).status_code, 200)

    def test_sem_marcar_manter_conectado_nao_ha_cookie_de_remember(self):
        cliente = self.app.test_client()
        resposta = cliente.post(
            "/login", data={"email": "ana@empresa.com", "senha": SENHA}, headers=DESKTOP
        )
        cabecalhos = " ".join(resposta.headers.getlist("Set-Cookie"))
        self.assertNotIn("remember_token", cabecalhos)
        cliente.delete_cookie("session")
        resposta = cliente.get("/painel", headers=DESKTOP)
        self.assertEqual(resposta.status_code, 302)  # sem remember-me, perder a sessão exige novo login

    def test_marcar_manter_conectado_cria_cookie_de_remember(self):
        cliente = self.app.test_client()
        resposta = cliente.post(
            "/login",
            data={"email": "ana@empresa.com", "senha": SENHA, "lembrar": "y"},
            headers=DESKTOP,
        )
        cabecalhos = " ".join(resposta.headers.getlist("Set-Cookie"))
        self.assertIn("remember_token", cabecalhos)
        self.assertIn("HttpOnly", cabecalhos)


if __name__ == "__main__":
    unittest.main()
