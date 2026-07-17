"""Test della Guida in linea (rotta /guida e voce di menu).

La Guida e' protetta dalla sola autenticazione: nessun permesso speciale. Deve
essere accessibile a QUALSIASI utente autenticato e mostrare le sezioni
principali; l'utente anonimo viene reindirizzato al login. La voce "Guida" deve
comparire nella sidebar per l'utente autenticato.
"""
from __future__ import annotations


def test_guida_requires_login_redirects(client):
    r = client.get("/guida")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_guida_renders_for_authenticated_user_without_permissions(client, login):
    # Nessun permesso: la Guida deve comunque rendersi (accesso a tutti gli
    # utenti autenticati).
    login([])
    r = client.get("/guida")
    assert r.status_code == 200
    assert b"Guida a Pulse" in r.data
    # Indice (table of contents) con ancore.
    assert b'href="#sec-panoramica"' in r.data


def test_guida_contains_main_sections(client, login):
    login([])
    r = client.get("/guida")
    assert r.status_code == 200
    body = r.data
    for anchor in (
        b'id="sec-panoramica"',
        b'id="sec-architettura"',
        b'id="sec-accesso"',
        b'id="sec-sonde"',
        b'id="sec-sistemi"',
        b'id="sec-heartbeat"',
        b'id="sec-dashboard"',
        b'id="sec-query"',
        b'id="sec-notifiche"',
        b'id="sec-config"',
        b'id="sec-report"',
        b'id="sec-tabelle"',
        b'id="sec-faq"',
    ):
        assert anchor in body, anchor
    # Contenuti chiave accurati.
    assert b"heartbeat" in body.lower()
    assert b"token di enrollment" in body
    assert b"Europe/Rome" in body


def test_guida_menu_item_in_sidebar_for_authenticated_user(client, login, fake):
    # Su un'altra pagina interna (Profilo) la sidebar deve contenere la voce
    # "Guida" che punta a /guida: la voce non e' legata alla pagina corrente.
    login(["profile.read"])
    fake.set("GET", "/auth/me",
             {"username": "u", "full_name": "U", "email": "u@x",
              "roles": [], "permissions": ["profile.read"]})
    r = client.get("/profile")
    assert r.status_code == 200
    assert b'href="/guida"' in r.data
    assert b"Guida" in r.data


def test_guida_menu_visible_even_without_any_permission(client, login):
    # La voce Guida non e' condizionata da alcun permesso: appare anche per un
    # utente senza permessi (a differenza delle altre sezioni del menu).
    login([])
    r = client.get("/guida")
    assert r.status_code == 200
    assert b'href="/guida"' in r.data
