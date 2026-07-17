"""Guida in linea della dashboard Server.

Pagina statica di documentazione d'uso dell'applicazione Pulse: e' protetta
dalla sola autenticazione (nessun permesso speciale) ed e' quindi accessibile a
TUTTI gli utenti autenticati. Non consuma alcuna API del backend: il contenuto
descrive le funzionalita' realmente implementate ed e' interamente reso dal
template ``guida/index.html``.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from pulse_fe_common.auth import login_required

bp = Blueprint("guida", __name__)


@bp.route("/guida")
@login_required
def index():
    return render_template("guida/index.html")
