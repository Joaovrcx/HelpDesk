"""Testes da Etapa 2: cadastro, login, logout, controle de acesso e SQLite.

Execute na raiz do projeto, com o .venv ativado:
    python -m unittest discover -s tests -v

A classe-base (banco temporário, limpeza de conexões e auxiliares) fica em
tests/base_testes.py.
"""

import re
import sqlite3
import unittest

from werkzeug.security import check_password_hash

from app.models import TIPO_FUNCIONARIO, TIPO_TECNICO
from app.utils import destino_seguro
from base_testes import SENHA, BaseTestCase


class TestPaginaInicial(BaseTestCase):
    def test_home_continua_funcionando(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("HelpDesk", self.texto(r))
        self.assertIn("Como funciona", self.texto(r))

    def test_arquivos_estaticos(self):
        self.assertEqual(self.client.get("/static/css/style.css").status_code, 200)
        self.assertEqual(self.client.get("/static/js/script.js").status_code, 200)

    def test_pagina_inexistente_retorna_404(self):
        self.assertEqual(self.client.get("/nao-existe").status_code, 404)


class TestBancoDeDados(BaseTestCase):
    def test_arquivo_sqlite_e_tabela_criados(self):
        self.assertTrue(self.db_path.exists())
        colunas = [c[1] for c in self.sql("PRAGMA table_info(usuarios)")]
        for esperado in ("id", "nome", "email", "senha_hash", "tipo", "data_cadastro"):
            self.assertIn(esperado, colunas)

    def test_banco_rejeita_tipo_invalido(self):
        with self.assertRaises(sqlite3.IntegrityError):
            conexao = sqlite3.connect(self.db_path)
            try:
                conexao.execute(
                    "INSERT INTO usuarios (nome, email, senha_hash, tipo, data_cadastro) "
                    "VALUES ('X', 'x@x.com', 'h', 'admin', '2026-01-01')"
                )
            finally:
                conexao.close()


class TestCadastro(BaseTestCase):
    def test_pagina_de_cadastro_nao_tem_campo_tipo(self):
        r = self.client.get("/cadastro")
        self.assertEqual(r.status_code, 200)
        html = self.texto(r)
        self.assertNotIn('name="tipo"', html)
        self.assertIn('name="nome"', html)
        self.assertIn('name="email"', html)

    def test_cadastro_valido_salva_funcionario_no_sqlite(self):
        r = self.cadastrar()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

        linhas = self.sql(
            "SELECT nome, email, tipo, senha_hash, data_cadastro FROM usuarios"
        )
        self.assertEqual(len(linhas), 1)
        nome, email, tipo, senha_hash, data_cadastro = linhas[0]
        self.assertEqual(nome, "Ana Silva")
        self.assertEqual(email, "ana@empresa.com")
        self.assertEqual(tipo, TIPO_FUNCIONARIO)
        self.assertTrue(data_cadastro)

        # A senha nunca fica em texto puro: só o hash
        self.assertNotEqual(senha_hash, SENHA)
        self.assertNotIn(SENHA, senha_hash)
        self.assertTrue(senha_hash.startswith(("scrypt:", "pbkdf2:")))
        self.assertTrue(check_password_hash(senha_hash, SENHA))
        self.assertFalse(check_password_hash(senha_hash, "outra-senha"))

    def test_mensagem_de_sucesso_apos_cadastro(self):
        self.cadastrar()
        r = self.client.get("/login")
        self.assertIn("Cadastro realizado com sucesso", self.texto(r))

    def test_nao_e_possivel_escolher_tipo_tecnico_pelo_formulario(self):
        for valor in ("tecnico", "TECNICO", "admin"):
            self.cadastrar(email=f"{valor}@empresa.com", tipo=valor)
        tipos = {t[0] for t in self.sql("SELECT tipo FROM usuarios")}
        self.assertEqual(tipos, {TIPO_FUNCIONARIO})

    def test_email_duplicado_e_rejeitado_sem_diferenciar_maiusculas(self):
        self.cadastrar()
        r = self.cadastrar(nome="Outra Pessoa", email="ANA@Empresa.com")
        self.assertEqual(r.status_code, 200)
        self.assertIn("já está cadastrado", self.texto(r))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios")[0][0], 1)

    def test_email_e_salvo_normalizado(self):
        self.cadastrar(email="  Ana@Empresa.COM ")
        self.assertEqual(self.sql("SELECT email FROM usuarios")[0][0], "ana@empresa.com")

    def test_validacoes_do_formulario(self):
        casos = {
            "senha curta": ({"senha": "abc123", "confirmar_senha": "abc123"},
                            "entre 8 e 128"),
            "senhas diferentes": ({"confirmar_senha": "OutraSenha123"},
                                  "não coincidem"),
            "e-mail inválido": ({"email": "isso-nao-e-email"}, "e-mail válido"),
            "nome vazio": ({"nome": ""}, "Informe seu nome"),
        }
        for descricao, (extra, mensagem) in casos.items():
            with self.subTest(descricao):
                r = self.cadastrar(**extra)
                self.assertEqual(r.status_code, 200)
                self.assertIn(mensagem, self.texto(r))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios")[0][0], 0)


class TestLogin(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.criar_usuario()

    def test_pagina_de_login(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="senha"', self.texto(r))

    def test_login_valido_redireciona_para_o_painel(self):
        r = self.entrar()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/painel"))
        painel = self.client.get("/painel")
        self.assertEqual(painel.status_code, 200)
        self.assertIn("Ana Silva", self.texto(painel))

    def test_login_aceita_email_com_maiusculas(self):
        self.assertEqual(self.entrar(email="ANA@empresa.com").status_code, 302)

    def test_senha_errada(self):
        r = self.entrar(senha="senha-errada")
        self.assertEqual(r.status_code, 200)
        self.assertIn("E-mail ou senha inválidos", self.texto(r))
        self.assertEqual(self.client.get("/painel").status_code, 302)

    def test_email_inexistente_usa_a_mesma_mensagem(self):
        r = self.entrar(email="ninguem@empresa.com")
        self.assertEqual(r.status_code, 200)
        self.assertIn("E-mail ou senha inválidos", self.texto(r))

    def test_next_interno_e_respeitado(self):
        r = self.entrar(url="/login?next=/painel/funcionario")
        self.assertTrue(r.headers["Location"].endswith("/painel/funcionario"))

    def test_next_externo_e_ignorado(self):
        for destino in ("https://evil.example/", "//evil.example", "/\\evil.example"):
            with self.subTest(destino):
                self.client.post("/logout")
                r = self.entrar(url=f"/login?next={destino}")
                self.assertEqual(r.status_code, 302)
                self.assertNotIn("evil", r.headers["Location"])
                self.assertTrue(r.headers["Location"].endswith("/painel"))

    def test_usuario_logado_e_redirecionado_de_login_e_cadastro(self):
        self.entrar()
        for rota in ("/login", "/cadastro"):
            with self.subTest(rota):
                self.assertEqual(self.client.get(rota).status_code, 302)


class TestLogoutEAcesso(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.criar_usuario()
        self.criar_usuario("Tião Técnico", "tec@empresa.com", tipo=TIPO_TECNICO)

    def test_logout_encerra_a_sessao(self):
        self.entrar()
        self.assertEqual(self.client.get("/painel").status_code, 200)
        r = self.client.post("/logout")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/painel").status_code, 302)

    def test_logout_nao_funciona_com_get(self):
        self.entrar()
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.get("/painel").status_code, 200)

    def test_visitante_e_enviado_para_o_login(self):
        for rota in ("/painel", "/painel/funcionario", "/painel/tecnico"):
            with self.subTest(rota):
                r = self.client.get(rota)
                self.assertEqual(r.status_code, 302)
                self.assertIn("/login", r.headers["Location"])

    def test_mensagem_de_login_necessario(self):
        r = self.client.get("/painel", follow_redirects=True)
        self.assertIn("Faça login para acessar", self.texto(r))

    def test_funcionario_acessa_apenas_a_propria_area(self):
        self.entrar()
        self.assertEqual(self.client.get("/painel/funcionario").status_code, 200)
        r = self.client.get("/painel/tecnico")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Acesso negado", self.texto(r))

    def test_tecnico_acessa_apenas_a_propria_area(self):
        self.entrar(email="tec@empresa.com")
        self.assertEqual(self.client.get("/painel/tecnico").status_code, 200)
        self.assertEqual(self.client.get("/painel/funcionario").status_code, 403)

    def test_painel_mostra_o_tipo_do_usuario(self):
        self.entrar(email="tec@empresa.com")
        self.assertIn("Técnico", self.texto(self.client.get("/painel")))


class TestCSRF(BaseTestCase):
    csrf = True

    def token(self, url):
        html = self.texto(self.client.get(url))
        achado = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertIsNotNone(achado, "token CSRF não encontrado em " + url)
        return achado.group(1)

    def test_formularios_incluem_token(self):
        for url in ("/login", "/cadastro"):
            with self.subTest(url):
                self.token(url)

    def test_cadastro_sem_token_e_rejeitado(self):
        r = self.client.post("/cadastro", data={
            "nome": "Ana Silva", "email": "ana@empresa.com",
            "senha": SENHA, "confirmar_senha": SENHA,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios")[0][0], 0)

    def test_login_sem_token_e_rejeitado(self):
        self.criar_usuario()
        r = self.client.post("/login", data={"email": "ana@empresa.com", "senha": SENHA})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/painel").status_code, 302)

    def test_cadastro_com_token_valido(self):
        r = self.client.post("/cadastro", data={
            "csrf_token": self.token("/cadastro"),
            "nome": "Ana Silva", "email": "ana@empresa.com",
            "senha": SENHA, "confirmar_senha": SENHA,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios")[0][0], 1)

    def test_logout_exige_token(self):
        self.criar_usuario()
        self.client.post("/login", data={
            "csrf_token": self.token("/login"),
            "email": "ana@empresa.com", "senha": SENHA,
        })
        self.assertEqual(self.client.get("/painel").status_code, 200)

        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.client.get("/painel").status_code, 200)

        token = self.token("/painel")
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(self.client.get("/painel").status_code, 302)


class TestComandosAdmin(BaseTestCase):
    def executar(self, *args, **kwargs):
        return self.app.test_cli_runner().invoke(args=list(args), **kwargs)

    def tipo_no_banco(self, email):
        linhas = self.sql("SELECT tipo FROM usuarios WHERE email = ?", (email,))
        return linhas[0][0] if linhas else None

    def test_criar_tecnico(self):
        r = self.executar("criar-tecnico", "--nome", "Tião Técnico",
                          "--email", "TEC@empresa.com", "--senha", SENHA)
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(self.tipo_no_banco("tec@empresa.com"), TIPO_TECNICO)
        senha_hash = self.sql("SELECT senha_hash FROM usuarios")[0][0]
        self.assertTrue(check_password_hash(senha_hash, SENHA))

    def test_criar_tecnico_pedindo_a_senha_no_terminal(self):
        r = self.executar("criar-tecnico", input=f"Tião\ntec@empresa.com\n{SENHA}\n{SENHA}\n")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(self.tipo_no_banco("tec@empresa.com"), TIPO_TECNICO)

    def test_criar_tecnico_com_dados_invalidos(self):
        casos = [
            ("--nome", "Tião", "--email", "invalido", "--senha", SENHA),
            ("--nome", "Tião", "--email", "t@empresa.com", "--senha", "curta"),
            ("--nome", "T", "--email", "t@empresa.com", "--senha", SENHA),
        ]
        for args in casos:
            with self.subTest(args):
                r = self.executar("criar-tecnico", *args)
                self.assertNotEqual(r.exit_code, 0)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios")[0][0], 0)

    def test_criar_tecnico_com_email_existente_falha(self):
        self.criar_usuario()
        r = self.executar("criar-tecnico", "--nome", "Ana", "--email", "ana@empresa.com",
                          "--senha", SENHA)
        self.assertNotEqual(r.exit_code, 0)
        self.assertEqual(self.tipo_no_banco("ana@empresa.com"), TIPO_FUNCIONARIO)

    def test_promover_e_rebaixar(self):
        self.criar_usuario()
        r = self.executar("promover-tecnico", "ana@empresa.com")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(self.tipo_no_banco("ana@empresa.com"), TIPO_TECNICO)

        r = self.executar("rebaixar-tecnico", "ana@empresa.com")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(self.tipo_no_banco("ana@empresa.com"), TIPO_FUNCIONARIO)

    def test_promover_usuario_inexistente_falha(self):
        r = self.executar("promover-tecnico", "ninguem@empresa.com")
        self.assertNotEqual(r.exit_code, 0)

    def test_usuario_promovido_acessa_a_area_do_tecnico(self):
        self.criar_usuario()
        self.entrar()
        self.assertEqual(self.client.get("/painel/tecnico").status_code, 403)
        self.client.post("/logout")

        self.executar("promover-tecnico", "ana@empresa.com")
        self.entrar()
        self.assertEqual(self.client.get("/painel/tecnico").status_code, 200)

    def test_listar_usuarios_nao_mostra_senhas(self):
        self.criar_usuario()
        r = self.executar("listar-usuarios")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("ana@empresa.com", r.output)
        self.assertNotIn("scrypt", r.output)
        self.assertNotIn(SENHA, r.output)


class TestDestinoSeguro(unittest.TestCase):
    def test_destinos_validos(self):
        for destino in ("/painel", "/painel/tecnico", "/painel?x=1"):
            with self.subTest(destino):
                self.assertTrue(destino_seguro(destino))

    def test_destinos_invalidos(self):
        for destino in (None, "", "painel", "//evil.com", "/\\evil.com",
                        "https://evil.com", "http://evil.com/x", "javascript:alert(1)"):
            with self.subTest(destino):
                self.assertFalse(destino_seguro(destino))


if __name__ == "__main__":
    unittest.main()
