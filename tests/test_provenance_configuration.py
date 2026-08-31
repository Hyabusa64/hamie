"""Provenance options store roles and labels, never embedded credentials."""

import pytest

from hamie.configuration import ConfigurationError, normalize_section


def test_provenance_configuration_normalizes_host_labels() -> None:
    result = normalize_section(
        "provenance",
        {
            "authoritative_source_repository": "/source/HAMIE",
            "deployment_target": "ha:/config/custom_components/hamie",
            "optional_remote_development_hosts": "um890, staging-1",
            "deployment_adapter_mode": "preview_only",
        },
        {},
    )

    assert result["optional_remote_development_hosts"] == "um890,staging-1"
    assert result["deployment_adapter_mode"] == "preview_only"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("authoritative_source_repository", "https://user:password@example.test/repo"),
        ("deployment_target", "https://example.test/deploy?token=secret-value"),
    ),
)
def test_provenance_configuration_rejects_embedded_credentials(
    field: str, value: str
) -> None:
    values = {
        "authoritative_source_repository": "/source/HAMIE",
        "deployment_target": "ha:/config/custom_components/hamie",
        field: value,
    }

    with pytest.raises(ConfigurationError) as captured:
        normalize_section("provenance", values, {})

    assert captured.value.code == "embedded_credential"
    assert captured.value.field == field


def test_remote_development_hosts_are_labels_not_ssh_targets() -> None:
    with pytest.raises(ConfigurationError) as captured:
        normalize_section(
            "provenance",
            {"optional_remote_development_hosts": "user@um890"},
            {},
        )

    assert captured.value.code == "invalid_host_label"
