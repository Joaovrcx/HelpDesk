"""Rotas de autenticação: cadastro, login e logout."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.forms import LoginForm, RegistrationForm
from app.models import TIPO_FUNCIONARIO, User
from app.utils import destino_seguro

auth_bp = Blueprint("auth", __name__)

# Hash descartável: quando o e-mail não existe, ainda fazemos uma verificação
# de senha para que o tempo de resposta não revele se o e-mail está cadastrado.
_HASH_FALSO = generate_password_hash("senha-falsa-para-igualar-o-tempo")


@auth_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """Cadastro público: sempre cria um usuário do tipo funcionário."""
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    form = RegistrationForm()
    if form.validate_on_submit():
        usuario = User(
            nome=form.nome.data,
            email=form.email.data,
            tipo=TIPO_FUNCIONARIO,  # fixo: o formulário público nunca define o tipo
        )
        usuario.set_password(form.senha.data)
        db.session.add(usuario)
        try:
            db.session.commit()
        except IntegrityError:
            # Corrida rara: o e-mail foi cadastrado entre a validação e o commit
            db.session.rollback()
            flash("Este e-mail já está cadastrado.", "danger")
        else:
            flash("Cadastro realizado com sucesso! Faça login para continuar.", "success")
            return redirect(url_for("auth.login"))
    elif request.method == "POST":
        flash("Não foi possível concluir o cadastro. Corrija os campos indicados.", "danger")

    return render_template("auth/cadastro.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    form = LoginForm()
    if form.validate_on_submit():
        usuario = db.session.execute(
            db.select(User).filter_by(email=form.email.data)
        ).scalar_one_or_none()

        if usuario is not None:
            senha_ok = usuario.check_password(form.senha.data)
        else:
            check_password_hash(_HASH_FALSO, form.senha.data)
            senha_ok = False

        if senha_ok:
            login_user(usuario, remember=form.lembrar.data)
            flash(f"Bem-vindo(a), {usuario.nome}!", "success")
            destino = request.args.get("next")
            if destino_seguro(destino):
                return redirect(destino)
            return redirect(url_for("painel.index"))

        # Mensagem genérica: não revela se o e-mail existe
        flash("E-mail ou senha inválidos.", "danger")
    elif request.method == "POST":
        flash("Preencha e-mail e senha para entrar.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Logout somente via POST (com token CSRF), evitando logout forçado por links."""
    if current_user.is_authenticated:
        logout_user()
        flash("Você saiu da sua conta.", "info")
    return redirect(url_for("main.home"))
