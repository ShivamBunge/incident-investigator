"""Redaction tests: obvious secrets must not leave the process (spec 12)."""

from app.redaction import redact_mapping, redact_text


def test_api_key_assignment_redacted():
    out = redact_text("config uses api_key=abcd1234efgh5678 internally")
    assert "abcd1234efgh5678" not in out
    assert "api_key=<redacted>" in out


def test_bearer_token_redacted():
    out = redact_text("Authorization: Bearer abcdef1234567890abcdef")
    assert "abcdef1234567890" not in out
    assert "Bearer <redacted>" in out


def test_prefixed_token_redacted():
    out = redact_text("key sk-or-v1-abcdef1234567890abcdef1234 leaked in log")
    assert "sk-or-v1-abcdef1234567890" not in out


def test_private_key_redacted():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN\n-----END PRIVATE KEY-----"
    out = redact_text(pem)
    assert "MIIEvQIBADAN" not in out


def test_normal_operational_text_untouched():
    text = "error_rate rose from 0.004 to 0.091 at 2026-09-22T14:05:00Z"
    assert redact_text(text) == text


def test_mapping_redacted_recursively():
    data = {
        "message": "token=supersecret123",
        "nested": {"log": "password=hunter2"},
        "list": ["api_key=xyz123456789"],
        "count": 3,
    }
    cleaned = redact_mapping(data)
    assert "supersecret123" not in cleaned["message"]
    assert "hunter2" not in cleaned["nested"]["log"]
    assert "xyz123456789" not in cleaned["list"][0]
    assert cleaned["count"] == 3