"""Comandos administrativos (linha de comando).

Funcionam somente com acesso ao servidor/terminal onde o sistema roda, por
isso são o mecanismo seguro para criar e promover técnicos: nenhuma página
web permite escolher ou alterar o tipo de usuário.

Uso (na raiz do projeto, com o .venv ativado):
    flask --app run criar-tecnico
    flask --app run promover-tecnico email@empresa.com
    flask --app run rebaixar-tecnico email@empresa.com
    flask --app run listar-usuarios
"""

import click
from flask.cli import with_appcontext
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import TIPO_FUNCIONARIO, TIPO_TECNICO, User
from app.utils import EMAIL_REGEX


def _buscar_usuario(email):
    email = email.strip().lower()
    usuario = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if usuario is None:
        raise click.ClickException(f"Nenhum usuário encontrado com o e-mail '{email}'.")
    return usuario


@click.command("criar-tecnico")
@click.option("--nome", prompt="Nome completo", help="Nome completo do técnico.")
@click.option("--email", prompt="E-mail", help="E-mail de login do técnico.")
@click.option(
    "--senha",
    prompt="Senha",
    hide_input=True,
    confirmation_prompt=True,
    help="Senha (se omitida, será pedida sem aparecer na tela).",
)
@with_appcontext
def criar_tecnico(nome, email, senha):
    """Cria um novo usuário do tipo técnico."""
    nome = nome.strip()
    email = email.strip().lower()

    if not 2 <= len(nome) <= 100:
        raise click.ClickException("O nome deve ter entre 2 e 100 caracteres.")
    if len(email) > 120 or not EMAIL_REGEX.match(email):
        raise click.ClickException("Informe um e-mail válido (máximo 120 caracteres).")
    if not 8 <= len(senha) <= 128:
        raise click.ClickException("A senha deve ter entre 8 e 128 caracteres.")

    existente = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if existente is not None:
        raise click.ClickException(
            "Já existe um usuário com este e-mail. "
            "Para torná-lo técnico use: promover-tecnico"
        )

    usuario = User(nome=nome, email=email, tipo=TIPO_TECNICO)
    usuario.set_password(senha)
    db.session.add(usuario)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise click.ClickException("Não foi possível criar o usuário (e-mail já cadastrado).")

    click.echo(f"Técnico criado: {usuario.nome} <{usuario.email}>")


@click.command("promover-tecnico")
@click.argument("email")
@with_appcontext
def promover_tecnico(email):
    """Transforma um usuário já cadastrado em técnico."""
    usuario = _buscar_usuario(email)
    if usuario.tipo == TIPO_TECNICO:
        click.echo(f"{usuario.email} já é técnico. Nada a fazer.")
        return
    usuario.tipo = TIPO_TECNICO
    db.session.commit()
    click.echo(f"{usuario.email} agora é técnico.")


@click.command("rebaixar-tecnico")
@click.argument("email")
@with_appcontext
def rebaixar_tecnico(email):
    """Devolve um técnico ao tipo funcionário."""
    usuario = _buscar_usuario(email)
    if usuario.tipo == TIPO_FUNCIONARIO:
        click.echo(f"{usuario.email} já é funcionário. Nada a fazer.")
        return
    usuario.tipo = TIPO_FUNCIONARIO
    db.session.commit()
    click.echo(f"{usuario.email} agora é funcionário.")


@click.command("listar-usuarios")
@with_appcontext
def listar_usuarios():
    """Lista os usuários cadastrados (sem exibir senhas)."""
    usuarios = db.session.execute(db.select(User).order_by(User.id)).scalars().all()
    if not usuarios:
        click.echo("Nenhum usuário cadastrado.")
        return
    for u in usuarios:
        click.echo(f"{u.id:>3}  {u.tipo:<12}  {u.nome}  <{u.email}>")


def register_commands(app):
    for comando in (criar_tecnico, promover_tecnico, rebaixar_tecnico, listar_usuarios):
        app.cli.add_command(comando)
