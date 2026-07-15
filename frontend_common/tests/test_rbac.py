"""Test delle utilità RBAC lato UI."""
from pulse_fe_common.rbac import has_any, has_permission


def test_has_permission_true():
    assert has_permission(["users.read", "roles.read"], "users.read") is True


def test_has_permission_false():
    assert has_permission(["users.read"], "users.create") is False


def test_has_permission_empty_or_none():
    assert has_permission([], "users.read") is False
    assert has_permission(None, "users.read") is False


def test_has_any_true():
    assert has_any(["a", "b"], ["x", "b"]) is True


def test_has_any_false():
    assert has_any(["a"], ["x", "y"]) is False


def test_has_any_empty():
    assert has_any(None, ["x"]) is False
    assert has_any([], ["x"]) is False
