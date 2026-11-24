"""Base compartilhada pelos testes (não contém testes próprios).

Cada teste usa um banco SQLite temporário em arquivo (não toca em
instance/helpdesk.db) e confere os dados com o módulo sqlite3 do Python.

Limpeza (evita ResourceWarning): ao final de cada teste, a sessão é
removida, o pool de conexões de TODAS as aplicações criadas é descartado
(engine.dispose) e o coletor de lixo é executado antes de apagar a pasta
temporária.
"""

import gc
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app, services
from app.extensions import db
from app.models import TIPO_FUNCIONARIO, User
from config import TestingConfig

SENHA = "SenhaForte123"


class BaseTestCase(unittest.TestCase):
    csrf = False

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="helpdesk_test_")
        self.db_path = Path(self.tmpdir) / "teste.db"
        self.config_teste = type(
            "ConfigTeste",
            (TestingConfig,),
            {
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path.as_posix()}",
                "WTF_CSRF_ENABLED": self.csrf,
            },
        )
        self._apps = []
        self.app = self.novo_app()
        self.client = self.app.test_client()

    def novo_app(self):
        """Cria uma aplicação nova apontando para o mesmo banco de teste."""
        app = create_app(self.config_teste)
        self._apps.append(app)
        return app

    def tearDown(self):
        for app in self._apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self._apps.clear()
        self.app = None
        self.client = None
        gc.collect()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- usuários -----------------------------------------------------
    def criar_usuario(self, nome="Ana Silva", email="ana@empresa.com",
                      senha=SENHA, tipo=TIPO_FUNCIONARIO):
        """Cria o usuário direto no banco e devolve o id."""
        with self.app.app_context():
            usuario = User(nome=nome, email=email, tipo=tipo)
            usuario.set_password(senha)
            db.session.add(usuario)
            db.session.commit()
            return usuario.id

    def cadastrar(self, **extra):
        dados = {
            "nome": "Ana Silva",
            "email": "ana@empresa.com",
            "senha": SENHA,
            "confirmar_senha": SENHA,
        }
        dados.update(extra)
        return self.client.post("/cadastro", data=dados)

    def entrar(self, email="ana@empresa.com", senha=SENHA, url="/login"):
        return self.client.post(url, data={"email": email, "senha": senha})

    def cliente_logado(self, email, senha=SENHA):
        """Devolve um NOVO cliente de teste já autenticado como 'email'."""
        cliente = self.app.test_client()
        dados = {"email": email, "senha": senha}
        if self.csrf:
            dados["csrf_token"] = self.obter_token("/login", cliente)
        cliente.post("/login", data=dados)
        return cliente

    # --- chamados (via camada de serviço) -----------------------------
    def novo_chamado(self, email="ana@empresa.com", titulo="Impressora não imprime",
                     descricao="A impressora do segundo andar não responde.",
                     categoria="impressora", prioridade="media"):
        with self.app.app_context():
            usuario = db.session.execute(db.select(User).filter_by(email=email)).scalar_one()
            chamado = services.criar_chamado(usuario, titulo, descricao, categoria, prioridade)
            return chamado.id

    def assumir_direto(self, chamado_id, email="tec1@empresa.com"):
        with self.app.app_context():
            tecnico = db.session.execute(db.select(User).filter_by(email=email)).scalar_one()
            return services.assumir_chamado(chamado_id, tecnico)

    def concluir_direto(self, chamado_id, email="tec1@empresa.com",
                        solucao="Problema resolvido."):
        with self.app.app_context():
            tecnico = db.session.execute(db.select(User).filter_by(email=email)).scalar_one()
            return services.concluir_chamado(chamado_id, tecnico, solucao)

    # --- acesso direto ao arquivo SQLite ------------------------------
    def sql(self, consulta, params=()):
        """Consulta o arquivo SQLite diretamente, sem passar pelo Flask."""
        conexao = sqlite3.connect(self.db_path)
        try:
            return conexao.execute(consulta, params).fetchall()
        finally:
            conexao.close()

    # --- utilidades ---------------------------------------------------
    def texto(self, resposta):
        return resposta.get_data(as_text=True)

    def obter_token(self, url, cliente=None):
        """Lê o token CSRF de uma página (para testar com CSRF ativo)."""
        cliente = cliente or self.client
        html = self.texto(cliente.get(url))
        achado = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertIsNotNone(achado, "token CSRF não encontrado em " + url)
        return achado.group(1)


if __name__ == "__main__":
    unittest.main()
