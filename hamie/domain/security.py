"""Deterministic security findings derived only from observed HAMIE configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from .common import stable_digest


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """One evidence-backed security decision; never contains a credential value."""

    finding_id: str
    title: str
    affected_object: str
    risk: str
    confidence: str
    exposure: str
    evidence: tuple[str, ...]
    recommended_action: str
    execution_capability: str
    manual_steps: tuple[str, ...]
    verification_plan: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        value["manual_steps"] = list(self.manual_steps)
        value["verification_plan"] = list(self.verification_plan)
        return value


def _finding(
    code: str,
    *,
    title: str,
    affected_object: str,
    risk: str,
    confidence: str,
    exposure: str,
    evidence: tuple[str, ...],
    recommended_action: str,
    manual_steps: tuple[str, ...],
    verification_plan: tuple[str, ...],
) -> SecurityFinding:
    return SecurityFinding(
        finding_id=f"security_{stable_digest(code, affected_object)[:20]}",
        title=title,
        affected_object=affected_object,
        risk=risk,
        confidence=confidence,
        exposure=exposure,
        evidence=evidence,
        recommended_action=recommended_action,
        execution_capability="Manual repair available",
        manual_steps=manual_steps,
        verification_plan=verification_plan,
    )


def security_findings(options: dict[str, Any]) -> tuple[SecurityFinding, ...]:
    """Return only findings supported by current configuration evidence.

    Absence of evidence never becomes a finding. Secret values are checked only
    for presence and are never copied into the result.
    """

    findings: list[SecurityFinding] = []
    connector_specs = (
        (
            "Ollama",
            bool(options.get("ollama_enabled")),
            str(options.get("ollama_base_url", "")),
            bool(options.get("ollama_api_key")),
            bool(options.get("ollama_verify_tls", True)),
        ),
        (
            "n8n",
            bool(options.get("n8n_enabled")),
            str(options.get("n8n_base_url", "")),
            bool(options.get("n8n_outbound_credential")),
            bool(options.get("n8n_verify_tls", True)),
        ),
        (
            "MCP",
            bool(options.get("mcp_enabled")),
            str(options.get("mcp_base_url", "")),
            bool(options.get("mcp_credential")),
            bool(options.get("mcp_verify_tls", True)),
        ),
        (
            "HKG",
            bool(options.get("hkg_enabled")),
            str(options.get("hkg_base_url", "")),
            bool(options.get("hkg_credential")),
            bool(options.get("hkg_verify_tls", True)),
        ),
    )
    for name, enabled, endpoint, credential_present, verify_tls in connector_specs:
        if not enabled or not endpoint:
            continue
        scheme = urlsplit(endpoint).scheme.lower()
        if credential_present and scheme == "http":
            findings.append(
                _finding(
                    "credential_over_cleartext",
                    title=f"{name} credentials may cross an unencrypted connection",
                    affected_object=f"{name} connector",
                    risk="high",
                    confidence="high",
                    exposure="Credential configured with an HTTP endpoint",
                    evidence=(
                        "Connector is enabled",
                        "A credential is configured (value redacted)",
                        "Endpoint scheme is HTTP",
                    ),
                    recommended_action=(
                        "Use a trusted HTTPS endpoint before sending credentials."
                    ),
                    manual_steps=(
                        "Open Settings > Connectors.",
                        f"Change the {name} endpoint to HTTPS or remove the "
                        "credential.",
                        "Test the connector after saving.",
                    ),
                    verification_plan=(
                        "Confirm the saved endpoint uses HTTPS.",
                        "Confirm the connector test succeeds with TLS "
                        "verification enabled.",
                    ),
                )
            )
        if scheme == "https" and not verify_tls:
            findings.append(
                _finding(
                    "tls_verification_disabled",
                    title=f"{name} TLS certificate verification is disabled",
                    affected_object=f"{name} connector",
                    risk="high",
                    confidence="high",
                    exposure=(
                        "An active HTTPS connection accepts unverified certificates"
                    ),
                    evidence=(
                        "Connector is enabled",
                        "Endpoint scheme is HTTPS",
                        "TLS verification is disabled",
                    ),
                    recommended_action=(
                        "Enable TLS verification and use a trusted certificate."
                    ),
                    manual_steps=(
                        "Open Settings > Connectors.",
                        f"Enable TLS verification for {name}.",
                        "Test the connector after saving.",
                    ),
                    verification_plan=(
                        "Confirm TLS verification remains enabled.",
                        "Confirm the connector test succeeds.",
                    ),
                )
            )

    if (
        options.get("n8n_inbound_commands_enabled")
        and options.get("n8n_inbound_authentication_mode", "none") == "none"
    ):
        findings.append(
            _finding(
                "unauthenticated_inbound",
                title="n8n inbound commands allow unauthenticated requests",
                affected_object="n8n inbound command endpoint",
                risk="critical",
                confidence="high",
                exposure=(
                    "A state-changing inbound surface is enabled without authentication"
                ),
                evidence=(
                    "Inbound commands are enabled",
                    "Inbound authentication mode is none",
                ),
                recommended_action="Require a bearer token or shared secret.",
                manual_steps=(
                    "Open Settings > Connectors > n8n.",
                    "Select bearer token or shared secret authentication.",
                    "Regenerate and store the credential securely.",
                ),
                verification_plan=(
                    "Confirm unauthenticated requests are rejected.",
                    "Confirm a valid authenticated request is accepted.",
                ),
            )
        )

    allowed_hosts = str(options.get("n8n_allowed_hosts", ""))
    if options.get("n8n_inbound_commands_enabled") and any(
        marker in {item.strip() for item in allowed_hosts.split(",")}
        for marker in ("*", "0.0.0.0/0", "::/0")
    ):
        findings.append(
            _finding(
                "broad_inbound_hosts",
                title="n8n inbound host policy is overly broad",
                affected_object="n8n inbound command endpoint",
                risk="high",
                confidence="high",
                exposure="Inbound requests are not restricted to known hosts",
                evidence=(
                    "Inbound commands are enabled",
                    "Allowed-host policy contains a wildcard or all-network range",
                ),
                recommended_action=(
                    "Restrict inbound requests to explicit trusted hosts."
                ),
                manual_steps=(
                    "Open Settings > Connectors > n8n.",
                    "Replace broad ranges with explicit trusted host names "
                    "or addresses.",
                ),
                verification_plan=(
                    "Confirm a trusted host remains accepted.",
                    "Confirm an unlisted host is rejected.",
                ),
            )
        )

    return tuple(sorted(findings, key=lambda item: (item.risk, item.finding_id)))
