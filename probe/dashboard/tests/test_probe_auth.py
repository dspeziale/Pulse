"""Test diretti degli helper di sessione/credenziali locali (probe_auth)."""
import probe_auth


def test_verify_credentials(app):
    with app.test_request_context():
        assert probe_auth.verify_credentials("probe", "secret") is True
        assert probe_auth.verify_credentials("probe", "x") is False
        assert probe_auth.verify_credentials("altro", "secret") is False
        assert probe_auth.verify_credentials("", "") is False


def test_session_helpers(app):
    with app.test_request_context():
        assert probe_auth.is_authenticated() is False
        probe_auth.store_session("op")
        assert probe_auth.is_authenticated() is True
        assert probe_auth.current_user() == "op"
        probe_auth.clear_session()
        assert probe_auth.is_authenticated() is False


def test_template_helpers_registered(app):
    with app.test_request_context():
        procs = app.template_context_processors[None]
        merged = {}
        for p in procs:
            merged.update(p())
        assert "is_authenticated" in merged
        assert "current_user" in merged
