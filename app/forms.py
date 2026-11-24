"""Formulários (Flask-WTF). Todos incluem proteção CSRF automaticamente."""

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    AnyOf,
    DataRequired,
    EqualTo,
    Length,
    Regexp,
    ValidationError,
)

from app.extensions import db
from app.models import CATEGORIA_LABELS, PRIORIDADE_LABELS, PRIORIDADE_MEDIA, User
from app.utils import EMAIL_REGEX


def _limpar(valor):
    return valor.strip() if isinstance(valor, str) else valor


def _email_normalizado(valor):
    return valor.strip().lower() if isinstance(valor, str) else valor


class RegistrationForm(FlaskForm):
    """Cadastro público de funcionários.

    IMPORTANTE: não existe campo "tipo" aqui de propósito. Todo cadastro
    público vira funcionário (definido na rota), e qualquer valor extra
    enviado manualmente na requisição é simplesmente ignorado.
    """

    nome = StringField(
        "Nome completo",
        validators=[
            DataRequired(message="Informe seu nome."),
            Length(min=2, max=100, message="O nome deve ter entre 2 e 100 caracteres."),
        ],
        filters=[_limpar],
    )
    email = StringField(
        "E-mail",
        validators=[
            DataRequired(message="Informe seu e-mail."),
            Length(max=120, message="O e-mail deve ter no máximo 120 caracteres."),
            Regexp(EMAIL_REGEX, message="Informe um e-mail válido."),
        ],
        filters=[_email_normalizado],
    )
    senha = PasswordField(
        "Senha",
        validators=[
            DataRequired(message="Informe uma senha."),
            Length(min=8, max=128, message="A senha deve ter entre 8 e 128 caracteres."),
        ],
    )
    confirmar_senha = PasswordField(
        "Confirmar senha",
        validators=[
            DataRequired(message="Confirme a senha."),
            EqualTo("senha", message="As senhas não coincidem."),
        ],
    )
    submit = SubmitField("Criar conta")

    def validate_email(self, field):
        existente = db.session.execute(
            db.select(User).filter_by(email=field.data)
        ).scalar_one_or_none()
        if existente is not None:
            raise ValidationError("Este e-mail já está cadastrado.")


class LoginForm(FlaskForm):
    """Login de usuários."""

    email = StringField(
        "E-mail",
        validators=[DataRequired(message="Informe seu e-mail.")],
        filters=[_email_normalizado],
    )
    senha = PasswordField(
        "Senha",
        validators=[DataRequired(message="Informe sua senha.")],
    )
    lembrar = BooleanField("Manter conectado")
    submit = SubmitField("Entrar")


# ---------------------------------------------------------------------
# Etapa 3 - Chamados
# ---------------------------------------------------------------------
class ChamadoForm(FlaskForm):
    """Abertura de chamado pelo funcionário.

    Não há campos de status, técnico ou solicitante: esses valores são
    definidos pelo servidor e nunca pelo formulário.
    """

    titulo = StringField(
        "Título",
        validators=[
            DataRequired(message="Informe o título do chamado."),
            Length(min=5, max=150, message="O título deve ter entre 5 e 150 caracteres."),
        ],
        filters=[_limpar],
    )
    categoria = SelectField(
        "Categoria",
        choices=[("", "Selecione...")] + list(CATEGORIA_LABELS.items()),
        validators=[AnyOf(list(CATEGORIA_LABELS), message="Selecione uma categoria.")],
        validate_choice=False,
    )
    prioridade = SelectField(
        "Prioridade",
        choices=list(PRIORIDADE_LABELS.items()),
        default=PRIORIDADE_MEDIA,
        validators=[AnyOf(list(PRIORIDADE_LABELS), message="Selecione uma prioridade.")],
        validate_choice=False,
    )
    descricao = TextAreaField(
        "Descrição do problema",
        validators=[
            DataRequired(message="Descreva o problema."),
            Length(min=10, max=5000, message="A descrição deve ter entre 10 e 5000 caracteres."),
        ],
        filters=[_limpar],
    )
    submit = SubmitField("Abrir chamado")


class ComentarioForm(FlaskForm):
    """Comentário do técnico sobre o atendimento."""

    texto = TextAreaField(
        "Comentário",
        validators=[
            DataRequired(message="Escreva o comentário."),
            Length(min=2, max=2000, message="O comentário deve ter entre 2 e 2000 caracteres."),
        ],
        filters=[_limpar],
    )


class ConclusaoForm(FlaskForm):
    """Solução registrada pelo técnico ao concluir o chamado."""

    solucao = TextAreaField(
        "Solução aplicada",
        validators=[
            DataRequired(message="Descreva a solução aplicada."),
            Length(min=5, max=5000, message="A solução deve ter entre 5 e 5000 caracteres."),
        ],
        filters=[_limpar],
    )
