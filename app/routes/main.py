"""Rotas gerais do sistema (páginas públicas e institucionais)."""

from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Página inicial do HelpDesk."""
    return render_template("home.html")
