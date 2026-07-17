"""Test della configurazione da variabili d'ambiente."""
import pulse_fe_common.config as cfgmod
from pulse_fe_common.config import ProbeDashboardConfig, ServerDashboardConfig


def test_server_defaults(monkeypatch):
    for k in ("PULSE_SERVER_API_BASE", "PULSE_SERVER_SECRET_KEY",
              "PULSE_HTTP_TIMEOUT", "PULSE_VERIFY_TLS", "PULSE_SERVER_DASH_PORT",
              "PULSE_SERVER_SESSION_COOKIE_NAME",
              "PULSE_SERVER_SESSION_COOKIE_SECURE"):
        monkeypatch.delenv(k, raising=False)
    cfg = ServerDashboardConfig.from_env()
    assert cfg.api_base_url == "http://localhost:8000/api/v1"
    assert cfg.secret_key == "dev-server-secret"
    assert cfg.request_timeout == 10.0
    assert cfg.verify_tls is True
    assert cfg.port == 5000
    assert cfg.session_cookie_name == "pulse_server_session"
    assert cfg.session_cookie_secure is False


def test_server_from_env_overrides(monkeypatch):
    monkeypatch.setenv("PULSE_SERVER_API_BASE", "https://api.example/api/v1/")
    monkeypatch.setenv("PULSE_HTTP_TIMEOUT", "3.5")
    monkeypatch.setenv("PULSE_VERIFY_TLS", "false")
    monkeypatch.setenv("PULSE_SERVER_DASH_PORT", "8080")
    monkeypatch.setenv("PULSE_SERVER_SESSION_COOKIE_NAME", "custom_server_sess")
    monkeypatch.setenv("PULSE_SERVER_SESSION_COOKIE_SECURE", "true")
    cfg = ServerDashboardConfig.from_env()
    assert cfg.api_base_url == "https://api.example/api/v1"  # trailing slash rimosso
    assert cfg.request_timeout == 3.5
    assert cfg.verify_tls is False
    assert cfg.port == 8080
    assert cfg.session_cookie_name == "custom_server_sess"
    assert cfg.session_cookie_secure is True


def test_probe_defaults(monkeypatch):
    for k in ("PULSE_PROBE_API_BASE", "PULSE_PROBE_AGENT_TOKEN",
              "PULSE_PROBE_DASH_USER", "PULSE_PROBE_DASH_PASSWORD",
              "PULSE_PROBE_SECRET_KEY", "PULSE_PROBE_DASH_PORT",
              "PULSE_PROBE_SESSION_COOKIE_NAME",
              "PULSE_PROBE_SESSION_COOKIE_SECURE", "PULSE_PROBE_TIMEZONE"):
        monkeypatch.delenv(k, raising=False)
    cfg = ProbeDashboardConfig.from_env()
    assert cfg.agent_base_url == "http://localhost:8444/api/v1"
    assert cfg.dash_user == "probe"
    assert cfg.port == 5001
    assert cfg.session_cookie_name == "pulse_probe_session"
    assert cfg.session_cookie_secure is False
    assert cfg.timezone == "Europe/Rome"


def test_probe_timezone_env_override(monkeypatch):
    monkeypatch.setenv("PULSE_PROBE_TIMEZONE", "America/New_York")
    assert ProbeDashboardConfig.from_env().timezone == "America/New_York"


def test_probe_session_cookie_env_overrides(monkeypatch):
    monkeypatch.setenv("PULSE_PROBE_SESSION_COOKIE_NAME", "custom_probe_sess")
    monkeypatch.setenv("PULSE_PROBE_SESSION_COOKIE_SECURE", "yes")
    cfg = ProbeDashboardConfig.from_env()
    assert cfg.session_cookie_name == "custom_probe_sess"
    assert cfg.session_cookie_secure is True


def test_dashboard_session_cookie_names_differ():
    """I nomi cookie di default DEVONO differire (bug sessione condivisa)."""
    assert (ServerDashboardConfig.from_env().session_cookie_name
            != ProbeDashboardConfig.from_env().session_cookie_name)


def test_bool_parsing_variants(monkeypatch):
    monkeypatch.setenv("X", "YES")
    assert cfgmod._get_bool("X", False) is True
    monkeypatch.setenv("X", "0")
    assert cfgmod._get_bool("X", True) is False
    monkeypatch.delenv("X", raising=False)
    assert cfgmod._get_bool("X", True) is True


def test_int_float_parsing(monkeypatch):
    monkeypatch.delenv("Y", raising=False)
    assert cfgmod._get_int("Y", 7) == 7
    assert cfgmod._get_float("Y", 1.5) == 1.5
    monkeypatch.setenv("Y", "42")
    assert cfgmod._get_int("Y", 0) == 42
