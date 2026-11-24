"""Modelos do banco de dados (tabelas)."""

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager

# Tipos de usuário aceitos pelo sistema
TIPO_FUNCIONARIO = "funcionario"
TIPO_TECNICO = "tecnico"
TIPOS_USUARIO = (TIPO_FUNCIONARIO, TIPO_TECNICO)

_NOMES_TIPO = {
    TIPO_FUNCIONARIO: "Funcionário",
    TIPO_TECNICO: "Técnico",
}


def _agora_utc():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    """Usuário do sistema (funcionário ou técnico)."""

    __tablename__ = "usuarios"
    __table_args__ = (
        # Garante no próprio banco que só existam os tipos válidos
        db.CheckConstraint("tipo IN ('funcionario', 'tecnico')", name="ck_usuarios_tipo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(256), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default=TIPO_FUNCIONARIO)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=_agora_utc)

    # --- Senha -------------------------------------------------------
    def set_password(self, senha):
        """Guarda apenas o hash da senha (nunca a senha em texto puro)."""
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

    # --- Tipo de usuário ---------------------------------------------
    @property
    def is_tecnico(self):
        return self.tipo == TIPO_TECNICO

    @property
    def is_funcionario(self):
        return self.tipo == TIPO_FUNCIONARIO

    @property
    def tipo_legivel(self):
        return _NOMES_TIPO.get(self.tipo, self.tipo)

    def __repr__(self):
        return f"<User {self.email} ({self.tipo})>"


@login_manager.user_loader
def load_user(user_id):
    """Usado pelo Flask-Login para recarregar o usuário a cada requisição."""
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


# =====================================================================
# Etapa 3 - Chamados
# As tabelas abaixo são NOVAS. A tabela "usuarios" não é alterada.
# =====================================================================

agora_utc = _agora_utc

# Status do chamado
STATUS_ABERTO = "aberto"
STATUS_EM_ANDAMENTO = "em_andamento"
STATUS_CONCLUIDO = "concluido"
STATUS_LABELS = {
    STATUS_ABERTO: "Aberto",
    STATUS_EM_ANDAMENTO: "Em andamento",
    STATUS_CONCLUIDO: "Concluído",
}

# Prioridades
PRIORIDADE_BAIXA = "baixa"
PRIORIDADE_MEDIA = "media"
PRIORIDADE_ALTA = "alta"
PRIORIDADE_LABELS = {
    PRIORIDADE_BAIXA: "Baixa",
    PRIORIDADE_MEDIA: "Média",
    PRIORIDADE_ALTA: "Alta",
}

# Categorias (validadas na aplicação; novas categorias não exigem migração)
CATEGORIA_LABELS = {
    "hardware": "Hardware (computador, monitor, periféricos)",
    "software": "Software e aplicativos",
    "rede": "Rede e internet",
    "impressora": "Impressora",
    "email": "E-mail e contas",
    "acesso": "Acesso e senhas",
    "outros": "Outros",
}

# Tipos de evento do histórico
EVENTO_ABERTURA = "abertura"
EVENTO_ASSUMIDO = "assumido"
EVENTO_COMENTARIO = "comentario"
EVENTO_CONCLUSAO = "conclusao"
EVENTO_LABELS = {
    EVENTO_ABERTURA: "Chamado aberto",
    EVENTO_ASSUMIDO: "Atendimento assumido",
    EVENTO_COMENTARIO: "Comentário do técnico",
    EVENTO_CONCLUSAO: "Chamado concluído",
}


class Chamado(db.Model):
    """Chamado de suporte técnico aberto por um funcionário."""

    __tablename__ = "chamados"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('aberto', 'em_andamento', 'concluido')", name="ck_chamados_status"
        ),
        db.CheckConstraint(
            "prioridade IN ('baixa', 'media', 'alta')", name="ck_chamados_prioridade"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(30), nullable=False)
    prioridade = db.Column(db.String(10), nullable=False, default=PRIORIDADE_MEDIA)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ABERTO, index=True)
    solucao = db.Column(db.Text, nullable=True)

    solicitante_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    tecnico_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True, index=True)

    criado_em = db.Column(db.DateTime, nullable=False, default=_agora_utc)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=_agora_utc)
    concluido_em = db.Column(db.DateTime, nullable=True)

    solicitante = db.relationship(
        "User",
        foreign_keys=[solicitante_id],
        backref=db.backref("chamados_abertos", lazy="select"),
    )
    tecnico = db.relationship(
        "User",
        foreign_keys=[tecnico_id],
        backref=db.backref("chamados_atendidos", lazy="select"),
    )
    historico = db.relationship(
        "HistoricoChamado",
        back_populates="chamado",
        cascade="all, delete-orphan",
        order_by=lambda: [HistoricoChamado.criado_em, HistoricoChamado.id],
    )

    @property
    def esta_disponivel(self):
        """Disponível = aberto e ainda sem técnico responsável."""
        return self.status == STATUS_ABERTO and self.tecnico_id is None

    @property
    def esta_concluido(self):
        return self.status == STATUS_CONCLUIDO

    @property
    def status_legivel(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def prioridade_legivel(self):
        return PRIORIDADE_LABELS.get(self.prioridade, self.prioridade)

    @property
    def categoria_legivel(self):
        return CATEGORIA_LABELS.get(self.categoria, self.categoria)

    def __repr__(self):
        return f"<Chamado #{self.id} {self.status}>"


class HistoricoChamado(db.Model):
    """Registro de cada alteração importante de um chamado."""

    __tablename__ = "historico_chamados"

    id = db.Column(db.Integer, primary_key=True)
    chamado_id = db.Column(
        db.Integer,
        db.ForeignKey("chamados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    status_anterior = db.Column(db.String(20), nullable=True)
    status_novo = db.Column(db.String(20), nullable=True)
    descricao = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=_agora_utc)

    chamado = db.relationship("Chamado", back_populates="historico")
    autor = db.relationship("User")

    @property
    def tipo_legivel(self):
        return EVENTO_LABELS.get(self.tipo, self.tipo)

    def __repr__(self):
        return f"<HistoricoChamado chamado={self.chamado_id} {self.tipo}>"
