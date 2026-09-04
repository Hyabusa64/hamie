"""redact_secret_looking_text must catch the shapes it claims to, and
leave ordinary non-secret text (including the word "token" used as a
plain identifier) alone.

secret-scan: allow-credential-shaped-literals
  These fixtures must contain real credential-shaped values (a
  connection-URI password, a bearer token) to prove the redactor
  actually catches them. The pragma suppresses only the value-shape
  class and only under tests/.
"""

from __future__ import annotations

from hamie.domain.common import redact_secret_looking_text


def test_none_passes_through_as_none() -> None:
    assert redact_secret_looking_text(None) is None


def test_plain_text_is_unchanged() -> None:
    text = "the automation failed because the entity was unavailable"
    assert redact_secret_looking_text(text) == text


def test_password_key_value_is_redacted() -> None:
    result = redact_secret_looking_text("password: hunter2")
    assert result is not None
    assert "hunter2" not in result
    assert "redacted" in result


def test_bearer_token_is_redacted() -> None:
    result = redact_secret_looking_text("Authorization: Bearer sk-abc123def456")
    assert result is not None
    assert "sk-abc123def456" not in result


def test_idempotency_token_as_a_plain_identifier_is_not_redacted() -> None:
    """This codebase's own idempotency/replay machinery uses "token" as
    an ordinary identifier name -- redaction must not be a bare
    substring check on that word.
    """
    text = "the idempotency_token field was empty on retry"
    assert redact_secret_looking_text(text) == text


def test_connection_uri_with_embedded_credential_is_redacted() -> None:
    result = redact_secret_looking_text("db_url: mysql://user:realpassword@host/db")
    assert result is not None
    assert "realpassword" not in result
    assert "redacted" in result


def test_connection_uri_using_secret_reference_is_not_redacted() -> None:
    """Matches tools/secret_scan.py's own exemption: a !secret-referenced
    URI has already been remediated and must not be flagged forever.
    """
    text = "db_url: mysql://user:!secret db_password@host/db"
    assert redact_secret_looking_text(text) == text


def test_connection_uri_with_no_password_is_not_redacted() -> None:
    text = "db_url: postgresql://readonly@host/db"
    assert redact_secret_looking_text(text) == text


def test_non_credential_scheme_url_is_not_redacted() -> None:
    text = "see https://user:notasecret@example.com/docs for reference"
    # Not one of the recognized database/queue schemes -- left alone.
    assert redact_secret_looking_text(text) == text
