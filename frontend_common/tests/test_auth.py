"""Test di sessione, decoratori e helper template (auth.py)."""
import pytest
from flask import Blueprint, Flask

from pulse_fe_common import auth


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    auth.register_template_helpers(app)

    bp = Blueprint("auth", __name__)

    @bp.route("/login")
    def login():
        return "login-page"

    app.register_blueprint(bp)

    @app.route("/needs-login")
    @auth.login_required
    def needs_login():
        return "ok"

    @app.route("/needs-perm")
    @auth.permission_required("users.read")
    def needs_perm():
        return "ok"

    return app


def _login(client, permissions):
    with client.session_transaction() as s:
        s[auth.SESSION_ACCESS] = "acc"
        s[auth.SESSION_USER] = {"username": "u", "permissions": permissions}


def test_session_helpers(app):
    with app.test_request_context():
        from flask import session
        auth.store_session("acc", "ref", {"username": "u", "permissions": ["a"]})
        assert auth.is_authenticated() is True
        assert auth.access_token() == "acc"
        assert auth.current_user()["username"] == "u"
        assert auth.user_permissions() == ["a"]
        assert auth.can("a") is True
        assert auth.can("b") is False
        auth.clear_session()
        assert auth.is_authenticated() is False
        assert session.get(auth.SESSION_ACCESS) is None


def test_store_session_without_refresh(app):
    with app.test_request_context():
        auth.store_session("acc", None, {"permissions": []})
        assert auth.access_token() == "acc"
        assert auth.user_permissions() == []


def test_login_required_redirects_anonymous(app):
    c = app.test_client()
    r = c.get("/needs-login")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_required_allows_authenticated(app):
    c = app.test_client()
    _login(c, [])
    assert c.get("/needs-login").data == b"ok"


def test_permission_required_redirects_anonymous(app):
    c = app.test_client()
    r = c.get("/needs-perm")
    assert r.status_code == 302


def test_permission_required_forbidden_without_permission(app):
    c = app.test_client()
    _login(c, ["other"])
    assert c.get("/needs-perm").status_code == 403


def test_permission_required_ok_with_permission(app):
    c = app.test_client()
    _login(c, ["users.read"])
    assert c.get("/needs-perm").data == b"ok"


def test_template_helpers_injected(app):
    with app.test_request_context():
        procs = app.template_context_processors[None]
        merged = {}
        for p in procs:
            merged.update(p())
        assert "can" in merged and callable(merged["can"])
        assert "is_authenticated" in merged
