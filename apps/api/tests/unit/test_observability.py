from munych_api.shared.observability import REDACTED, redact_sensitive


def test_redacts_sensitive_keys_recursively() -> None:
    event = {
        "event": "request",
        "authorization": "Bearer abc",
        "headers": {"Authorization": "Bearer abc", "x-request-id": "1"},
        "payload": [{"full_name": "Ana Pérez", "value": 3}],
        "supabase_service_role_key": "sk",
    }
    out = redact_sensitive(None, "info", event)
    assert out["authorization"] == REDACTED
    assert out["headers"] == {"Authorization": REDACTED, "x-request-id": "1"}
    assert out["payload"] == [{"full_name": REDACTED, "value": 3}]
    assert out["supabase_service_role_key"] == REDACTED
    assert out["event"] == "request"
