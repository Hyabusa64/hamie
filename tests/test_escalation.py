"""The Claude-escalation packet must never leak a secret and must never
claim more evidence than it was actually given.

secret-scan: allow-credential-shaped-literals
  These fixtures must contain real credential-shaped values (a
  connection-URI password, a bearer token) to prove the packet's own
  sanitization actually strips them. The pragma suppresses only the
  value-shape class and only under tests/.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hamie.domain.escalation import EscalationPacket, build_escalation_packet

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def test_requires_a_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError):
        build_escalation_packet(
            incident_id="inc_1",
            disposition="operator_decision_required",
            unresolved_question="which successor is correct?",
            generated_at=datetime(2026, 8, 31),  # naive
        )


def test_minimal_packet_round_trips_through_as_dict() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="operator_decision_required",
        unresolved_question="which of two candidates is the real successor?",
        generated_at=NOW,
    )
    as_dict = packet.as_dict()
    assert as_dict["incident_id"] == "inc_1"
    assert as_dict["disposition"] == "operator_decision_required"
    assert as_dict["evidence_ids"] == []
    assert as_dict["environment"] == {
        "ha_version": "",
        "hamie_version": "",
        "hamie_build_commit": "",
    }


def test_incident_id_disposition_and_question_are_required() -> None:
    with pytest.raises(ValueError):
        EscalationPacket(
            incident_id="",
            disposition="x",
            unresolved_question="y",
            generated_at=NOW.isoformat(),
        )
    with pytest.raises(ValueError):
        EscalationPacket(
            incident_id="inc_1",
            disposition="x",
            unresolved_question="",
            generated_at=NOW.isoformat(),
        )


def test_secret_looking_text_in_the_unresolved_question_is_redacted() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="blocked",
        unresolved_question="config had password: hunter2 embedded, what now?",
        generated_at=NOW,
    )
    assert "hunter2" not in packet.unresolved_question
    assert "redacted" in packet.unresolved_question


def test_secret_looking_text_in_config_excerpts_is_redacted() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="blocked",
        unresolved_question="q",
        generated_at=NOW,
        config_excerpts=("password: hunter2\ndb_url: mysql://host/db",),
    )
    assert "hunter2" not in packet.config_excerpts[0]
    assert "redacted" in packet.config_excerpts[0]


def test_connection_uri_credential_in_config_excerpts_is_redacted() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="blocked",
        unresolved_question="q",
        generated_at=NOW,
        config_excerpts=("db_url: mysql://user:realpassword@host/db",),
    )
    assert "realpassword" not in packet.config_excerpts[0]
    assert "redacted" in packet.config_excerpts[0]


def test_secret_looking_text_in_deterministic_facts_is_redacted() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="blocked",
        unresolved_question="q",
        generated_at=NOW,
        deterministic_facts=(("api_response", "Authorization: Bearer abc123def"),),
    )
    _, value = packet.deterministic_facts[0]
    assert "abc123def" not in value


def test_ordinary_text_mentioning_token_as_an_identifier_is_not_redacted() -> None:
    """This codebase's own idempotency machinery uses "token" as a plain
    identifier name -- redaction must not be a bare substring check.
    """
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="blocked",
        unresolved_question="the idempotency_token field was empty on retry",
        generated_at=NOW,
    )
    assert "idempotency_token" in packet.unresolved_question


def test_full_packet_carries_every_field() -> None:
    packet = build_escalation_packet(
        incident_id="inc_42",
        disposition="operator_decision_required",
        unresolved_question="two plausible successors exist; which is canonical?",
        generated_at=NOW,
        evidence_ids=("ev_1", "ev_2"),
        deterministic_facts=(
            ("stale_entity", "sensor.example_old"),
            ("candidate_successor", "sensor.example_new"),
        ),
        config_excerpts=("trigger:\n  - platform: state\n    entity_id: sensor.example_old",),
        attempted_classification="stale_entity_reference, ambiguous successor",
        ambiguity_reason="both sensor.example_new and sensor.example_new_2 are live",
        protected_dependencies=("hamie-local-inference-power",),
        ha_version="2026.8.3",
        hamie_version="0.7.0-beta.1",
        hamie_build_commit="abc123def456",
    )
    as_dict = packet.as_dict()
    assert as_dict["evidence_ids"] == ["ev_1", "ev_2"]
    assert as_dict["environment"]["ha_version"] == "2026.8.3"
    assert as_dict["environment"]["hamie_build_commit"] == "abc123def456"
    assert as_dict["protected_dependencies"] == ["hamie-local-inference-power"]


def test_markdown_never_silently_omits_an_empty_section() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="insufficient_evidence",
        unresolved_question="nothing conclusive found",
        generated_at=NOW,
    )
    markdown = packet.as_markdown()
    assert markdown.count("(none recorded)") >= 3
    assert "(none)" in markdown  # protected dependencies section


def test_markdown_includes_the_incident_id_and_disposition() -> None:
    packet = build_escalation_packet(
        incident_id="inc_99",
        disposition="operator_decision_required",
        unresolved_question="q",
        generated_at=NOW,
    )
    markdown = packet.as_markdown()
    assert "inc_99" in markdown
    assert "operator_decision_required" in markdown


def test_markdown_renders_every_deterministic_fact() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="operator_decision_required",
        unresolved_question="q",
        generated_at=NOW,
        deterministic_facts=(("stale_entity", "sensor.a"), ("candidate", "sensor.b")),
    )
    markdown = packet.as_markdown()
    assert "sensor.a" in markdown
    assert "sensor.b" in markdown


def test_markdown_config_excerpts_are_fenced_as_yaml() -> None:
    packet = build_escalation_packet(
        incident_id="inc_1",
        disposition="operator_decision_required",
        unresolved_question="q",
        generated_at=NOW,
        config_excerpts=("trigger: []",),
    )
    markdown = packet.as_markdown()
    assert "```yaml" in markdown
    assert "trigger: []" in markdown
