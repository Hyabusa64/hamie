"""Authoritative versioned HAMIE config-entry options contract.

This module is deliberately Home Assistant independent.  The native Options
Flow and the authenticated panel API both use these field specifications and
normalizers so validation and secret handling cannot drift.
"""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .connectors.base import validate_endpoint
from .connectors.mcp import ALLOWED_CAPABILITIES
from .connectors.n8n import ALLOWED_INBOUND_COMMANDS, ALLOWED_OUTBOUND_EVENTS

CONFIGURATION_SCHEMA_VERSION = 2
MAX_CONFIGURATION_PAYLOAD_BYTES = 65_536
CONNECTOR_IDS = ("ollama", "n8n", "mcp", "hkg")
EDITABLE_SECTIONS = (
    "general",
    "provenance",
    "findings",
    "grouping",
    "ollama",
    "n8n",
    "mcp",
    "hkg",
    "audit",
    "ai_control",
)
PANEL_SECTIONS = (
    "general",
    "provenance",
    "findings",
    "grouping",
    "suppression",
    "ollama",
    "n8n",
    "mcp",
    "hkg",
    "safety",
    "audit",
    "ai_control",
    "connector_status",
    "test_connections",
)
GROUPING_DIMENSIONS = (
    "integration_domain",
    "config_entry_id",
    "device_id",
    "entity_domain",
    "area_id",
    "source_provider",
    "name_prefix",
    "failure_condition",
    "dependency_root",
    "analyzer_id",
    "category",
    "severity",
)
FINDING_SORTS = (
    "priority",
    "severity",
    "dependency_risk",
    "affected_objects",
    "confidence",
    "age",
    "recurrence",
    "newness",
    "group_size",
    "user_priority",
    "ai_advisory_priority",
)
SEVERITIES = ("info", "warning", "error")
LIFECYCLES = ("open", "resolved")
OLLAMA_CAPABILITIES = (
    "explain_findings",
    "explain_groups",
    "prioritize",
    "troubleshooting_steps",
    "non_executing_repair_plans",
)
AUTOMATIC_ANALYSIS_MODES = (
    "disabled",
    "highest_priority_only",
    "scan_summary",
    "selected_events",
)
AI_OPERATING_MODES = ("observe", "assisted_cleanup", "ai_control")
MINIMUM_UNAVAILABLE_DURATION_DAYS_CHOICES = ("0.5", "1", "3", "5", "7", "14", "30")
AUTO_SCAN_INTERVAL_MINUTES_CHOICES = (
    "15",
    "30",
    "60",
    "120",
    "240",
    "360",
    "720",
    "1440",
)
CONNECTOR_HEARTBEAT_INTERVAL_SECONDS_CHOICES = ("30", "60", "120", "300")
MINIMUM_AI_CONFIDENCE_CHOICES = ("medium", "high")
DEPENDENCY_COVERAGE_REQUIREMENT_CHOICES = ("complete", "partial_allowed")
CREDENTIAL_ACTIONS = ("keep", "replace", "remove")
N8N_CREDENTIAL_ACTIONS = (*CREDENTIAL_ACTIONS, "regenerate")
INBOUND_ENDPOINT = "/api/hamie/n8n"


class ConfigurationError(ValueError):
    """A stable non-sensitive configuration validation failure."""

    def __init__(self, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One shared panel and Options Flow field definition."""

    key: str
    label: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    required: bool = False
    secret: bool = False
    locked: bool = False
    description: str = ""

    def public(self) -> dict[str, Any]:
        """Return a JSON-safe field descriptor without a credential value."""
        result: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "secret": self.secret,
            "locked": self.locked,
            "description": self.description,
        }
        if not self.secret:
            result["default"] = self.default
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.choices:
            result["choices"] = list(self.choices)
        return result


def _field(
    key: str,
    label: str,
    kind: str,
    default: Any,
    **kwargs: Any,
) -> FieldSpec:
    return FieldSpec(key, label, kind, default, **kwargs)


SECTION_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "general": (
        _field("initial_scan_enabled", "Initial scan enabled", "boolean", True),
        _field(
            "initial_scan_delay",
            "Initial scan delay seconds",
            "integer",
            30,
            minimum=0,
            maximum=300,
        ),
        _field(
            "runtime_profile",
            "Runtime profile",
            "select",
            "conservative",
            choices=("conservative",),
            locked=True,
        ),
        _field(
            "default_findings_page_size",
            "Default findings page size",
            "integer",
            25,
            minimum=10,
            maximum=100,
        ),
        _field(
            "default_findings_sort",
            "Default findings sort",
            "select",
            "priority",
            choices=FINDING_SORTS,
        ),
        _field(
            "maximum_projected_groups",
            "Maximum projected groups",
            "integer",
            500,
            minimum=10,
            maximum=2_000,
        ),
        _field(
            "maximum_audit_records",
            "Maximum audit records",
            "integer",
            500,
            minimum=50,
            maximum=500,
        ),
        _field(
            "maximum_ai_recommendations",
            "Maximum AI recommendations",
            "integer",
            64,
            minimum=1,
            maximum=64,
        ),
        _field(
            "default_suppression_visibility",
            "Default suppression visibility",
            "select",
            "default",
            choices=("default", "visible", "suppressed", "snoozed"),
        ),
        _field("sidebar_panel_enabled", "Sidebar panel enabled", "boolean", True),
        _field("auto_scan_enabled", "Automatic scanning enabled", "boolean", True),
        _field(
            "auto_scan_interval_minutes",
            "Automatic scan interval minutes",
            "select",
            "60",
            choices=AUTO_SCAN_INTERVAL_MINUTES_CHOICES,
        ),
        _field(
            "connector_heartbeat_interval_seconds",
            "Connector heartbeat interval seconds",
            "select",
            "60",
            choices=CONNECTOR_HEARTBEAT_INTERVAL_SECONDS_CHOICES,
        ),
    ),
    "provenance": (
        _field(
            "authoritative_source_repository",
            "Authoritative source repository",
            "text",
            "",
            description=(
                "Exact configured source-of-truth location. HAMIE never selects a "
                "repository from timestamps or discovery order."
            ),
        ),
        _field(
            "deployment_target",
            "Deployment target",
            "text",
            "",
            description="Exact Home Assistant deployment location.",
        ),
        _field(
            "optional_remote_development_hosts",
            "Optional remote development hosts",
            "csv",
            "",
            description=(
                "Comma-separated host labels available to provenance adapters; "
                "credentials are never stored in this field."
            ),
        ),
        _field(
            "deployment_adapter_mode",
            "Deployment adapter mode",
            "select",
            "disabled",
            choices=("disabled", "preview_only"),
            description=(
                "Preview-only records deterministic source/target/hash plans. "
                "Execution remains unavailable until a separately validated adapter exists."
            ),
        ),
    ),
    "findings": (
        _field(
            "duplicate_collapsing_enabled",
            "Duplicate collapsing enabled",
            "boolean",
            True,
        ),
        _field(
            "default_severity_filters",
            "Default severity filters",
            "multiselect",
            list(SEVERITIES),
            choices=SEVERITIES,
        ),
        _field(
            "default_lifecycle_filters",
            "Default lifecycle filters",
            "multiselect",
            ["open"],
            choices=LIFECYCLES,
        ),
        _field(
            "show_suppressed_findings_by_default",
            "Show suppressed findings by default",
            "boolean",
            False,
        ),
        _field(
            "show_snoozed_findings_by_default",
            "Show snoozed findings by default",
            "boolean",
            False,
        ),
        _field(
            "minimum_finding_age_seconds",
            "Minimum finding age before reporting",
            "integer",
            300,
            minimum=0,
            maximum=86_400,
        ),
        _field(
            "transient_unavailable_grace_seconds",
            "Transient unavailable grace period",
            "integer",
            300,
            minimum=0,
            maximum=86_400,
        ),
        _field(
            "include_diagnostic_entities",
            "Include diagnostic entities",
            "boolean",
            False,
        ),
        _field(
            "include_disabled_entities", "Include disabled entities", "boolean", False
        ),
        _field(
            "exclude_hamie_owned_entities",
            "Exclude HAMIE-owned entities",
            "boolean",
            True,
            locked=True,
        ),
        _field(
            "maximum_evidence_items_displayed",
            "Maximum evidence items displayed",
            "integer",
            8,
            minimum=1,
            maximum=8,
        ),
        _field(
            "maximum_supporting_objects_displayed",
            "Maximum supporting objects displayed",
            "integer",
            32,
            minimum=1,
            maximum=32,
        ),
    ),
    "grouping": (
        _field(
            "enabled_grouping_dimensions",
            "Enabled grouping dimensions",
            "multiselect",
            list(GROUPING_DIMENSIONS),
            choices=GROUPING_DIMENSIONS,
        ),
        _field(
            "primary_grouping_preference",
            "Primary grouping preference",
            "select",
            "device_id",
            choices=GROUPING_DIMENSIONS,
        ),
        _field(
            "minimum_group_size",
            "Minimum group size",
            "integer",
            1,
            minimum=1,
            maximum=100,
        ),
        _field(
            "maximum_visible_group_members",
            "Maximum visible group members",
            "integer",
            100,
            minimum=1,
            maximum=500,
        ),
        _field(
            "grouping_confidence_threshold",
            "Grouping confidence threshold",
            "number",
            0.75,
            minimum=0,
            maximum=1,
        ),
        _field(
            "collapse_common_mobile_app_findings",
            "Collapse common mobile-app findings",
            "boolean",
            True,
        ),
        _field(
            "collapse_same_device_unavailable_entities",
            "Collapse same-device unavailable entities",
            "boolean",
            True,
        ),
        _field(
            "collapse_same_integration_failures",
            "Collapse same-integration failures",
            "boolean",
            True,
        ),
        _field(
            "user_defined_grouping_rules",
            "User-defined grouping rules",
            "json",
            [],
            description=(
                "Declarative exact-match rules only; executable expressions "
                "are rejected."
            ),
        ),
    ),
    "ollama": (
        _field("ollama_enabled", "Enabled", "boolean", False),
        _field(
            "ai_connection_method",
            "Connection method",
            "select",
            "direct",
            choices=("ha_ai_task", "direct"),
            description=(
                "Prefer an existing Home Assistant AI Task entity; "
                "Direct is a deprecated legacy fallback. Conversation "
                "entities are never used for background analysis."
            ),
        ),
        _field(
            "ai_task_entity_id",
            "AI Task provider",
            "text",
            "",
            description="A discovered ai_task.* entity from this Home Assistant.",
        ),
        _field(
            "ollama_provider_type",
            "Provider type",
            "select",
            "ollama",
            choices=("ollama", "openai_compatible"),
        ),
        _field(
            "ollama_base_url",
            "Base URL",
            "url",
            "http://127.0.0.1:11434",
        ),
        _field("ollama_model", "Model", "text", ""),
        _field("ollama_api_key", "API key", "password", "", secret=True),
        _field(
            "ollama_credential_action",
            "Credential action",
            "select",
            "keep",
            choices=CREDENTIAL_ACTIONS,
        ),
        _field(
            "ollama_confirm_remove_credential",
            "Confirm credential removal",
            "boolean",
            False,
        ),
        _field(
            "ollama_timeout", "Timeout seconds", "number", 30, minimum=1, maximum=60
        ),
        _field(
            "ollama_maximum_input_characters",
            "Maximum input characters",
            "integer",
            16_000,
            minimum=1_000,
            maximum=64_000,
        ),
        _field(
            "ai_maximum_advisory_groups_per_run",
            "Maximum advisory groups per run",
            "integer",
            20,
            minimum=1,
            maximum=20,
        ),
        _field(
            "ai_maximum_findings_per_group",
            "Maximum findings per advisory group",
            "integer",
            # Measured against the live provider, not chosen for tidiness.
            # At 20 findings a group generates ~1200-1390 output tokens and
            # passes schema and semantic validation 5/5. At 24 it truncates.
            # At 30 it fails identically -- eval_count 432, done_reason
            # "length" -- at num_predict 2048, 3072 AND 4096, so a larger
            # output budget cannot rescue it; the group itself is too large
            # for this model to answer in one structured response.
            #
            # Findings beyond the bound are not discarded: plan_ai_evidence
            # records them in skipped_finding_ids and coverage reports them
            # as pending, so the next run picks them up.
            20,
            minimum=1,
            maximum=50,
        ),
        _field(
            "ai_maximum_estimated_tokens",
            "Maximum estimated input tokens",
            "integer",
            4_000,
            minimum=250,
            maximum=16_000,
        ),
        _field(
            "ai_minimum_confidence_threshold",
            "Minimum advisory confidence",
            "select",
            "low",
            choices=("low", "medium", "high"),
        ),
        _field(
            "ollama_maximum_output_tokens",
            "Maximum output tokens",
            "integer",
            # Measured, not guessed. A 20-finding group -- the production
            # maximum (ai_maximum_findings_per_group) -- generated 1201-1388
            # output tokens across five runs against qwen3.5:4b-q4_K_M. At the
            # previous default of 1024 every one of those responses came back
            # done_reason="length" with unparseable JSON, which is the
            # `ai_response_truncated` production was hitting. 1536 clears the
            # worst observed run by only 10%; 2048 clears it by ~48% and
            # passed 5/5. 4096 is not chosen because nothing measured
            # justifies it and a larger budget only widens worst-case latency
            # and runaway generation.
            2_048,
            minimum=16,
            maximum=4_096,
        ),
        _field(
            "ollama_temperature", "Temperature", "number", 0.2, minimum=0, maximum=1
        ),
        _field(
            "ollama_think",
            "Model thinking",
            "boolean",
            False,
            description=(
                "Advanced/debugging only. A hybrid-reasoning model (e.g. "
                "Qwen3) can spend its entire output-token budget on an "
                "internal reasoning phase and return an empty analysis, "
                "confirmed live against a real configured model. Leave "
                "disabled for HAMIE's structured JSON output; only the "
                "Ollama request format supports this option."
            ),
        ),
        _field("ollama_verify_tls", "TLS verification", "boolean", True),
        _field(
            "ollama_allowed_hosts",
            "Allowed-host policy",
            "csv",
            "localhost,127.0.0.1,::1",
        ),
        _field(
            "ollama_approve_host",
            "Allow connection to this local-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector on your private network."
            ),
        ),
        _field(
            "ollama_approve_remote_host",
            "Allow connection to this remote-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector at a public, "
                "non-private network address."
            ),
        ),
        _field("ollama_analyze_findings", "Analyze findings", "boolean", True),
        _field("ollama_analyze_groups", "Analyze groups", "boolean", True),
        _field("ollama_prioritize_findings", "Prioritize findings", "boolean", True),
        _field(
            "ollama_suggest_troubleshooting_checks",
            "Suggest troubleshooting checks",
            "boolean",
            True,
        ),
        _field(
            "ollama_suggest_non_executing_repair_plans",
            "Suggest non-executing repair plans",
            "boolean",
            True,
        ),
        _field(
            "ollama_automatic_analysis",
            "Automatic analysis mode",
            "select",
            "disabled",
            choices=AUTOMATIC_ANALYSIS_MODES,
        ),
    ),
    "n8n": (
        _field("n8n_enabled", "Enabled", "boolean", False),
        _field("n8n_base_url", "Base URL", "url", "http://127.0.0.1:5678"),
        _field(
            "n8n_outbound_webhook_url",
            "Outbound webhook URL",
            "url",
            "",
        ),
        _field(
            "n8n_authentication_type",
            "Outbound authentication",
            "select",
            "api_key",
            choices=("api_key", "username_and_password", "none"),
            description=(
                "How HAMIE authenticates itself to n8n's webhook. Separate "
                "from how n8n authenticates itself back to HAMIE below."
            ),
        ),
        _field("n8n_username", "Username", "text", ""),
        _field(
            "n8n_outbound_credential", "API key / password", "password", "", secret=True
        ),
        _field(
            "n8n_outbound_credential_action",
            "Outbound credential action",
            "select",
            "keep",
            choices=CREDENTIAL_ACTIONS,
        ),
        _field(
            "n8n_outbound_confirm_remove_credential",
            "Confirm outbound credential removal",
            "boolean",
            False,
        ),
        _field(
            "n8n_inbound_credential",
            "Inbound shared secret / token",
            "password",
            "",
            secret=True,
        ),
        _field(
            "n8n_inbound_credential_action",
            "Inbound credential action",
            "select",
            "keep",
            choices=N8N_CREDENTIAL_ACTIONS,
        ),
        _field(
            "n8n_inbound_confirm_remove_credential",
            "Confirm inbound credential removal",
            "boolean",
            False,
        ),
        _field(
            "n8n_inbound_confirm_regenerate_credential",
            "Confirm shared-secret regeneration",
            "boolean",
            False,
        ),
        _field("n8n_timeout", "Timeout seconds", "number", 15, minimum=1, maximum=60),
        _field("n8n_verify_tls", "TLS verification", "boolean", True),
        _field("n8n_retry_count", "Retry count", "integer", 1, minimum=0, maximum=3),
        _field(
            "n8n_retry_backoff",
            "Retry backoff seconds",
            "number",
            0.5,
            minimum=0,
            maximum=5,
        ),
        _field(
            "n8n_maximum_payload_size",
            "Maximum payload size",
            "integer",
            32_000,
            minimum=1_000,
            maximum=64_000,
        ),
        _field(
            "n8n_selected_events",
            "Selected outbound events",
            "multiselect",
            [],
            choices=tuple(sorted(ALLOWED_OUTBOUND_EVENTS)),
        ),
        _field(
            "n8n_inbound_commands_enabled", "Inbound commands enabled", "boolean", False
        ),
        _field(
            "n8n_inbound_authentication_mode",
            "Inbound authentication mode",
            "select",
            "none",
            choices=("none", "bearer_token", "shared_secret"),
        ),
        _field(
            "n8n_allowed_hosts", "Allowed-host policy", "csv", "localhost,127.0.0.1,::1"
        ),
        _field(
            "n8n_approve_host",
            "Allow connection to this local-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector on your private network."
            ),
        ),
        _field(
            "n8n_approve_remote_host",
            "Allow connection to this remote-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector at a public, "
                "non-private network address."
            ),
        ),
    ),
    "mcp": (
        _field("mcp_enabled", "Enabled", "boolean", False),
        _field(
            "mcp_endpoint",
            "Endpoint",
            "url",
            "http://127.0.0.1:8124/hamie",
        ),
        _field(
            "mcp_authentication_type",
            "Authentication type",
            "select",
            "none",
            choices=("none", "bearer_token"),
        ),
        _field("mcp_credential", "Credential", "password", "", secret=True),
        _field(
            "mcp_credential_action",
            "Credential action",
            "select",
            "keep",
            choices=CREDENTIAL_ACTIONS,
        ),
        _field(
            "mcp_confirm_remove_credential",
            "Confirm credential removal",
            "boolean",
            False,
        ),
        _field("mcp_timeout", "Timeout seconds", "number", 15, minimum=1, maximum=60),
        _field("mcp_verify_tls", "TLS verification", "boolean", True),
        _field(
            "mcp_mode",
            "Mode",
            "select",
            "read_only",
            choices=("read_only",),
            locked=True,
        ),
        _field(
            "mcp_allowed_hosts", "Allowed-host policy", "csv", "localhost,127.0.0.1,::1"
        ),
        _field(
            "mcp_approve_host",
            "Allow connection to this local-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector on your private network."
            ),
        ),
        _field(
            "mcp_approve_remote_host",
            "Allow connection to this remote-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector at a public, "
                "non-private network address."
            ),
        ),
    ),
    "hkg": (
        _field("hkg_enabled", "Enabled", "boolean", False),
        _field(
            "hkg_endpoint",
            "Endpoint",
            "url",
            "http://127.0.0.1:8080/query",
        ),
        _field(
            "hkg_authentication_type",
            "Authentication type",
            "select",
            "none",
            choices=("none", "bearer_token"),
        ),
        _field("hkg_credential", "Credential", "password", "", secret=True),
        _field(
            "hkg_credential_action",
            "Credential action",
            "select",
            "keep",
            choices=CREDENTIAL_ACTIONS,
        ),
        _field(
            "hkg_confirm_remove_credential",
            "Confirm credential removal",
            "boolean",
            False,
        ),
        _field("hkg_timeout", "Timeout seconds", "number", 15, minimum=1, maximum=60),
        _field("hkg_verify_tls", "TLS verification", "boolean", True),
        _field(
            "hkg_mode",
            "Mode",
            "select",
            "query_only",
            choices=("query_only",),
            locked=True,
        ),
        _field(
            "hkg_allowed_hosts", "Allowed-host policy", "csv", "localhost,127.0.0.1,::1"
        ),
        _field(
            "hkg_approve_host",
            "Allow connection to this local-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector on your private network."
            ),
        ),
        _field(
            "hkg_approve_remote_host",
            "Allow connection to this remote-network host",
            "boolean",
            False,
            description=(
                "Permit HAMIE to connect to this connector at a public, "
                "non-private network address."
            ),
        ),
        _field(
            "hkg_maximum_subjects",
            "Maximum subjects per request",
            "integer",
            32,
            minimum=1,
            maximum=32,
        ),
        _field(
            "hkg_maximum_relationships",
            "Maximum relationships per response",
            "integer",
            64,
            minimum=1,
            maximum=64,
        ),
        _field(
            "hkg_cache_duration",
            "Cache duration seconds",
            "integer",
            0,
            minimum=0,
            maximum=3_600,
        ),
    ),
    "audit": (
        _field(
            "maximum_audit_records",
            "Maximum retained audit records",
            "integer",
            500,
            minimum=50,
            maximum=500,
        ),
        _field(
            "audit_include_successful_connector_tests",
            "Include successful connector tests",
            "boolean",
            True,
        ),
        _field(
            "audit_include_failed_connector_tests",
            "Include failed connector tests",
            "boolean",
            True,
        ),
        _field(
            "audit_include_grouping_changes",
            "Include grouping changes",
            "boolean",
            True,
        ),
        _field(
            "audit_include_suppression_changes",
            "Include suppression changes",
            "boolean",
            True,
        ),
        _field(
            "audit_include_ai_request_metadata",
            "Include AI request metadata",
            "boolean",
            True,
        ),
        _field(
            "audit_include_n8n_delivery_metadata",
            "Include n8n delivery metadata",
            "boolean",
            True,
        ),
    ),
    "safety": (
        _field("read_only_mode", "Read-only mode", "boolean", True, locked=True),
        _field(
            "explicit_approval_required",
            "Explicit approval required",
            "boolean",
            True,
            locked=True,
        ),
        _field(
            "automatic_execution", "Automatic execution", "boolean", False, locked=True
        ),
        _field("ai_self_approval", "AI self-approval", "boolean", False, locked=True),
        _field("n8n_self_approval", "n8n self-approval", "boolean", False, locked=True),
        _field("mcp_writes", "MCP writes", "boolean", False, locked=True),
        _field(
            "automatic_deletion", "Automatic deletion", "boolean", False, locked=True
        ),
        _field("automatic_repair", "Automatic repair", "boolean", False, locked=True),
    ),
    "ai_control": (
        _field(
            "ai_operating_mode",
            "AI operating mode",
            "select",
            "observe",
            choices=AI_OPERATING_MODES,
            description=(
                "Observe: analyze and recommend only, never mutates Home "
                "Assistant. Assisted Cleanup: HAMIE may automatically "
                "execute allowlisted, reversible, low-risk cleanup after "
                "you enable it. AI Control: broader maintenance control; "
                "requires a separate one-time acknowledgement before any "
                "additional automatic power actually unlocks."
            ),
        ),
        _field(
            "ai_auto_execute_low_risk",
            "Auto-execute low-risk repairs",
            "boolean",
            True,
            description=(
                "Only takes effect outside Observe mode; Observe never "
                "auto-executes regardless of this setting."
            ),
        ),
        _field(
            "ai_auto_execute_medium_risk",
            "Auto-execute medium-risk repairs",
            "boolean",
            False,
            description="Only takes effect in AI Control mode, after acknowledgement.",
        ),
        _field(
            "require_backup_before_bulk_cleanup",
            "Require backup before bulk registry cleanup",
            "boolean",
            True,
        ),
        _field(
            "bulk_cleanup_threshold",
            "Bulk cleanup threshold (entity count)",
            "integer",
            25,
            minimum=1,
            maximum=1_000,
        ),
        _field(
            "disable_instead_of_delete",
            "Disable instead of delete",
            "boolean",
            True,
            locked=True,
            description=(
                "For stale/unused registry objects HAMIE always prefers "
                "disabling over deleting. Deletion is a separate, "
                "explicitly reviewed advanced capability and is never "
                "part of the automatic cleanup pipeline; this cannot be "
                "turned off."
            ),
        ),
        _field(
            "minimum_unavailable_duration_days",
            "Minimum unavailable duration before automatic cleanup",
            "select",
            "5",
            choices=MINIMUM_UNAVAILABLE_DURATION_DAYS_CHOICES,
        ),
        _field(
            "minimum_ai_confidence",
            "Minimum AI confidence",
            "select",
            "medium",
            choices=MINIMUM_AI_CONFIDENCE_CHOICES,
        ),
        _field(
            "dependency_coverage_requirement",
            "Dependency coverage requirement",
            "select",
            "complete",
            choices=DEPENDENCY_COVERAGE_REQUIREMENT_CHOICES,
        ),
        _field("cleanup_exclude_integrations", "Exclude integrations", "csv", ""),
        _field("cleanup_exclude_devices", "Exclude devices", "csv", ""),
        _field("cleanup_exclude_entity_domains", "Exclude entity domains", "csv", ""),
        _field("cleanup_exclude_entity_ids", "Exclude entity IDs", "csv", ""),
        _field("cleanup_exclude_areas", "Exclude areas", "csv", ""),
        _field("dry_run_first", "Dry run first", "boolean", True),
    ),
}


SECRET_KEYS = frozenset(
    {
        "ollama_api_key",
        "n8n_outbound_api_key",
        "n8n_password",
        "n8n_inbound_bearer_token",
        "n8n_shared_secret",
        "mcp_authentication",
        "hkg_authentication",
    }
)


def configuration_revision(options: dict[str, Any]) -> str:
    """Return a stable credential-sensitive revision without exposing values."""
    serializable = sorted((key, value) for key, value in options.items())
    return sha256(
        json.dumps(serializable, default=str, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def _csv(value: object) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        raw = value
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        raise ConfigurationError("invalid_type")
    return tuple(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))


def _bounded_payload(values: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(values, default=str).encode()
    except (TypeError, ValueError) as err:
        raise ConfigurationError("invalid_payload") from err
    if len(encoded) > MAX_CONFIGURATION_PAYLOAD_BYTES:
        raise ConfigurationError("payload_too_large")


def _normalize_field(spec: FieldSpec, value: Any) -> Any:
    try:
        if spec.kind in {"integer"}:
            if isinstance(value, bool):
                raise ValueError
            normalized: Any = int(value)
        elif spec.kind == "number":
            if isinstance(value, bool):
                raise ValueError
            normalized = float(value)
        elif spec.kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError
            normalized = value
        elif spec.kind in {"multiselect", "csv"}:
            selected = _csv(value)
            if spec.choices and any(item not in spec.choices for item in selected):
                raise ConfigurationError("invalid_choice", spec.key)
            normalized = ",".join(selected)
        elif spec.kind == "json":
            if isinstance(value, str):
                normalized = json.loads(value or "[]")
            else:
                normalized = value
            if not isinstance(normalized, list) or len(normalized) > 32:
                raise ConfigurationError("invalid_grouping_rules", spec.key)
            for rule in normalized:
                if not isinstance(rule, dict) or set(rule) != {
                    "name",
                    "dimension",
                    "value",
                }:
                    raise ConfigurationError("invalid_grouping_rules", spec.key)
                if rule["dimension"] not in GROUPING_DIMENSIONS:
                    raise ConfigurationError("invalid_grouping_rules", spec.key)
                if not all(
                    isinstance(rule[key], str) and 0 < len(rule[key]) <= 256
                    for key in rule
                ):
                    raise ConfigurationError("invalid_grouping_rules", spec.key)
        else:
            if not isinstance(value, str):
                raise ValueError
            normalized = value.strip()
            if len(normalized) > 2_048:
                raise ConfigurationError("value_too_long", spec.key)
        if spec.locked and normalized != spec.default:
            raise ConfigurationError("locked_policy", spec.key)
        if (
            spec.choices
            and spec.kind not in {"multiselect", "csv"}
            and normalized not in spec.choices
        ):
            raise ConfigurationError("invalid_choice", spec.key)
        if spec.required and normalized in {"", None}:
            raise ConfigurationError("required", spec.key)
        if spec.minimum is not None and normalized < spec.minimum:
            raise ConfigurationError("below_minimum", spec.key)
        if spec.maximum is not None and normalized > spec.maximum:
            raise ConfigurationError("above_maximum", spec.key)
        return normalized
    except ConfigurationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as err:
        raise ConfigurationError("invalid_type", spec.key) from err


def _secret_mapping(section: str) -> tuple[str, ...]:
    return {
        "ollama": ("ollama_api_key",),
        "n8n": (
            "n8n_outbound_api_key",
            "n8n_password",
            "n8n_inbound_bearer_token",
            "n8n_shared_secret",
        ),
        "mcp": ("mcp_authentication",),
        "hkg": ("hkg_authentication",),
    }[section]


def _apply_credential_action(
    section: str, normalized: dict[str, Any], result: dict[str, Any]
) -> None:
    """Apply one section's write-only credential lifecycle.

    n8n has two independent directions -- HAMIE's outbound call to n8n's
    webhook, and n8n's inbound call back to HAMIE -- each with its own
    field, action, and stored secret, so a single submitted value can
    never be silently duplicated into both.
    """
    if section == "n8n":
        _apply_n8n_outbound_credential_action(normalized, result)
        _apply_n8n_inbound_credential_action(normalized, result)
        return
    action = str(normalized.pop(f"{section}_credential_action"))
    confirm_remove = bool(normalized.pop(f"{section}_confirm_remove_credential"))
    input_key = "ollama_api_key" if section == "ollama" else f"{section}_credential"
    credential = str(normalized.pop(input_key, ""))
    secret_keys = _secret_mapping(section)
    if action == "keep":
        if credential:
            raise ConfigurationError("credential_action_required", input_key)
        return
    if action == "remove":
        if not confirm_remove:
            raise ConfigurationError("credential_removal_not_confirmed", input_key)
        for key in secret_keys:
            result.pop(key, None)
        return
    if action != "replace" or not credential:
        raise ConfigurationError("credential_required", input_key)
    for key in secret_keys:
        result.pop(key, None)
    result[secret_keys[0]] = credential


def _apply_n8n_outbound_credential_action(
    normalized: dict[str, Any], result: dict[str, Any]
) -> None:
    """Apply HAMIE -> n8n outbound webhook authentication only."""
    input_key = "n8n_outbound_credential"
    action = str(normalized.pop("n8n_outbound_credential_action"))
    confirm_remove = bool(normalized.pop("n8n_outbound_confirm_remove_credential"))
    credential = str(normalized.pop(input_key, ""))
    auth_type = str(normalized.get("n8n_authentication_type", ""))
    target_key = {
        "api_key": "n8n_outbound_api_key",
        "username_and_password": "n8n_password",
    }.get(auth_type)
    if action == "keep":
        if credential:
            raise ConfigurationError("credential_action_required", input_key)
        return
    if action == "remove":
        if not confirm_remove:
            raise ConfigurationError("credential_removal_not_confirmed", input_key)
        result.pop("n8n_outbound_api_key", None)
        result.pop("n8n_password", None)
        return
    if action != "replace" or not credential:
        raise ConfigurationError("credential_required", input_key)
    if target_key is None:
        raise ConfigurationError("invalid_authentication", input_key)
    result.pop("n8n_outbound_api_key", None)
    result.pop("n8n_password", None)
    result[target_key] = credential


def _apply_n8n_inbound_credential_action(
    normalized: dict[str, Any], result: dict[str, Any]
) -> None:
    """Apply n8n -> HAMIE inbound webhook authentication only."""
    input_key = "n8n_inbound_credential"
    action = str(normalized.pop("n8n_inbound_credential_action"))
    confirm_remove = bool(normalized.pop("n8n_inbound_confirm_remove_credential"))
    confirm_regenerate = bool(
        normalized.pop("n8n_inbound_confirm_regenerate_credential")
    )
    credential = str(normalized.pop(input_key, ""))
    inbound_mode = str(normalized.get("n8n_inbound_authentication_mode", ""))
    target_key = {
        "bearer_token": "n8n_inbound_bearer_token",
        "shared_secret": "n8n_shared_secret",
    }.get(inbound_mode)
    if action == "keep":
        if credential:
            raise ConfigurationError("credential_action_required", input_key)
        return
    if action == "remove":
        if not confirm_remove:
            raise ConfigurationError("credential_removal_not_confirmed", input_key)
        result.pop("n8n_inbound_bearer_token", None)
        result.pop("n8n_shared_secret", None)
        return
    if action == "regenerate":
        if not confirm_regenerate:
            raise ConfigurationError("credential_regeneration_not_confirmed", input_key)
        if inbound_mode != "shared_secret":
            raise ConfigurationError("invalid_authentication", input_key)
        result["n8n_shared_secret"] = secrets.token_urlsafe(32)
        return
    if action != "replace" or not credential:
        raise ConfigurationError("credential_required", input_key)
    if target_key is None:
        raise ConfigurationError("invalid_authentication", input_key)
    result.pop("n8n_inbound_bearer_token", None)
    result.pop("n8n_shared_secret", None)
    result[target_key] = credential


def normalize_connector_address(section: str, value: str) -> str:
    """Normalize a user-friendly connector address to a canonical base URL."""
    raw = value.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError as err:
        raise ConfigurationError("invalid_url") from err
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("invalid_url")
    hostname = parsed.hostname.casefold()
    port = parsed.port
    if port is None and section == "ollama":
        port = 11434
    elif port is None and section == "n8n":
        port = 5678
    host_text = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host_text}:{port}" if port is not None else host_text
    return urlunsplit(
        (parsed.scheme.casefold(), netloc, parsed.path.rstrip("/"), "", "")
    ).rstrip("/")


def connector_host_kind(hostname: str) -> str:
    """Classify a connector hostname without performing network I/O."""
    normalized = hostname.casefold().rstrip(".")
    if normalized == "localhost":
        return "loopback"
    if normalized.endswith(".local"):
        # mDNS/link-local hostnames (e.g. a device advertising itself as
        # "n8n-box.local") resolve only on the local network segment --
        # the same real-world "private" trust boundary as an RFC1918
        # address, never a genuinely public/remote one.
        return "private"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "remote"
    if address.is_loopback:
        return "loopback"
    if (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return "unsafe"
    if address.is_private:
        return "private"
    if address.is_global:
        return "remote"
    return "unsafe"


def _validate_approved_endpoint(
    section: str,
    field: str,
    options: dict[str, Any],
) -> None:
    try:
        normalized_url = normalize_connector_address(
            section, str(options.get(field, ""))
        )
    except ConfigurationError as err:
        raise ConfigurationError(err.code, field) from err
    if not normalized_url:
        raise ConfigurationError("required", field)
    options[field] = normalized_url
    hostname = urlsplit(normalized_url).hostname
    assert hostname is not None
    kind = connector_host_kind(hostname)
    if kind == "unsafe":
        raise ConfigurationError("unsafe_host", field)
    allowed_key = f"{section}_allowed_hosts"
    allowed = list(_csv(options.get(allowed_key, "")))
    approved = {item.casefold() for item in allowed}
    if hostname.casefold() not in approved:
        if kind == "loopback":
            allowed.append(hostname)
        elif kind == "private" and options.get(f"{section}_approve_host"):
            allowed.append(hostname)
        elif kind == "remote" and options.get(f"{section}_approve_remote_host"):
            allowed.append(hostname)
        else:
            raise ConfigurationError("host_not_allowed", field)
    options[allowed_key] = ",".join(dict.fromkeys(allowed))
    try:
        validate_endpoint(normalized_url, _csv(options[allowed_key]))
    except ValueError as err:
        raise ConfigurationError("invalid_url", field) from err


def _validate_connector(
    section: str, options: dict[str, Any], *, require_model: bool = True
) -> None:
    if not options.get(f"{section}_enabled", False):
        return
    if section == "ollama":
        method = options.get("ai_connection_method", "direct")
        if method == "ha_ai_task":
            if not str(options.get("ai_task_entity_id", "")).strip():
                raise ConfigurationError("required", "ai_task_entity_id")
        else:
            _validate_approved_endpoint(section, "ollama_base_url", options)
            if require_model and not options.get("ollama_model"):
                raise ConfigurationError("required", "ollama_model")
    elif section == "n8n":
        _validate_approved_endpoint(section, "n8n_base_url", options)
        outbound_url = str(options.get("n8n_outbound_webhook_url", "")).strip()
        # A blank outbound webhook URL is a legitimate, saveable state --
        # HAMIE never guesses a webhook path the user has not actually
        # registered in n8n. Event delivery and webhook-readiness testing
        # simply report "not configured" until the user supplies one.
        if outbound_url:
            _validate_approved_endpoint(section, "n8n_outbound_webhook_url", options)
        else:
            options["n8n_outbound_webhook_url"] = ""
        outbound = options.get("n8n_authentication_type")
        inbound = options.get("n8n_inbound_authentication_mode")
        if options.get("n8n_inbound_commands_enabled") and inbound == "none":
            raise ConfigurationError(
                "invalid_authentication", "n8n_inbound_authentication_mode"
            )
        if outbound == "api_key" and not options.get("n8n_outbound_api_key"):
            raise ConfigurationError("credential_required", "n8n_outbound_credential")
        if outbound == "username_and_password":
            if not str(options.get("n8n_username", "")).strip():
                raise ConfigurationError("required", "n8n_username")
            if not options.get("n8n_password"):
                raise ConfigurationError(
                    "credential_required", "n8n_outbound_credential"
                )
        if options.get("n8n_inbound_commands_enabled"):
            if inbound == "bearer_token" and not options.get(
                "n8n_inbound_bearer_token"
            ):
                raise ConfigurationError(
                    "credential_required", "n8n_inbound_credential"
                )
            if inbound == "shared_secret" and not options.get("n8n_shared_secret"):
                raise ConfigurationError(
                    "credential_required", "n8n_inbound_credential"
                )
    else:
        field = f"{section}_endpoint"
        _validate_approved_endpoint(section, field, options)
        auth_type = options.get(f"{section}_authentication_type")
        if auth_type == "bearer_token" and not options.get(_secret_mapping(section)[0]):
            raise ConfigurationError("credential_required", f"{section}_credential")


def normalize_section(
    section: str,
    values: dict[str, Any],
    existing_options: dict[str, Any],
    *,
    for_test: bool = False,
) -> dict[str, Any]:
    """Strictly validate one section and merge it into existing HA options."""
    if section not in EDITABLE_SECTIONS:
        raise ConfigurationError("section_not_editable")
    if not isinstance(values, dict):
        raise ConfigurationError("invalid_payload")
    _bounded_payload(values)
    specs = SECTION_FIELDS[section]
    allowed = {item.key for item in specs}
    unknown = set(values) - allowed
    if unknown:
        raise ConfigurationError("unknown_field", sorted(unknown)[0])
    normalized: dict[str, Any] = {}
    for spec in specs:
        value = values.get(spec.key, section_value(existing_options, spec))
        normalized[spec.key] = _normalize_field(spec, value)
    result = dict(existing_options)
    if section in CONNECTOR_IDS:
        _apply_credential_action(section, normalized, result)
    result.update(normalized)
    if section == "ollama":
        capability_flags = {
            "explain_findings": result.pop("ollama_analyze_findings"),
            "explain_groups": result.pop("ollama_analyze_groups"),
            "prioritize": result.pop("ollama_prioritize_findings"),
            "troubleshooting_steps": result.pop(
                "ollama_suggest_troubleshooting_checks"
            ),
            "non_executing_repair_plans": result.pop(
                "ollama_suggest_non_executing_repair_plans"
            ),
        }
        result["ollama_capabilities"] = ",".join(
            name for name in OLLAMA_CAPABILITIES if capability_flags[name]
        )
        if result["ollama_enabled"] and not result["ollama_capabilities"]:
            raise ConfigurationError("invalid_capabilities", "ollama_capabilities")
    if section in CONNECTOR_IDS:
        _validate_connector(section, result, require_model=not for_test)
        result.pop(f"{section}_approve_host", None)
        result.pop(f"{section}_approve_remote_host", None)
    if section == "grouping":
        dimensions = _csv(result["enabled_grouping_dimensions"])
        if not dimensions or result["primary_grouping_preference"] not in dimensions:
            raise ConfigurationError(
                "invalid_grouping_configuration", "primary_grouping_preference"
            )
    if section == "provenance":
        for field in ("authoritative_source_repository", "deployment_target"):
            value = str(result.get(field, ""))
            parsed = urlsplit(value)
            query_keys = {key.casefold() for key, _item in parse_qsl(parsed.query)}
            if parsed.password is not None or query_keys.intersection(
                {"access_token", "api_key", "key", "password", "secret", "token"}
            ):
                raise ConfigurationError("embedded_credential", field)
            if parsed.scheme in {"http", "https"} and parsed.username is not None:
                raise ConfigurationError("embedded_credential", field)
        for host in _csv(result.get("optional_remote_development_hosts", "")):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}", host):
                raise ConfigurationError(
                    "invalid_host_label", "optional_remote_development_hosts"
                )
    if section == "ai_control":
        if (
            result["ai_auto_execute_medium_risk"]
            and result["ai_operating_mode"] != "ai_control"
        ):
            raise ConfigurationError(
                "medium_risk_requires_ai_control_mode", "ai_auto_execute_medium_risk"
            )
    return result


def section_value(options: dict[str, Any], spec: FieldSpec) -> Any:
    """Resolve a sanitized display value, translating stored CSV values."""
    if spec.secret:
        return ""
    if spec.key.startswith("ollama_") and spec.key in {
        "ollama_analyze_findings",
        "ollama_analyze_groups",
        "ollama_prioritize_findings",
        "ollama_suggest_troubleshooting_checks",
        "ollama_suggest_non_executing_repair_plans",
    }:
        stored = _csv(options.get("ollama_capabilities", ",".join(OLLAMA_CAPABILITIES)))
        capability = {
            "ollama_analyze_findings": "explain_findings",
            "ollama_analyze_groups": "explain_groups",
            "ollama_prioritize_findings": "prioritize",
            "ollama_suggest_troubleshooting_checks": "troubleshooting_steps",
            "ollama_suggest_non_executing_repair_plans": "non_executing_repair_plans",
        }[spec.key]
        return capability in stored
    if spec.key.endswith("_credential_action"):
        return "keep"
    if spec.key.endswith("_confirm_remove_credential") or spec.key.endswith(
        "_confirm_regenerate_credential"
    ):
        return False
    value = options.get(spec.key, spec.default)
    if spec.kind == "multiselect":
        return list(_csv(value))
    if spec.kind == "json" and isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return spec.default
    return value


def sanitized_section(section: str, options: dict[str, Any]) -> dict[str, Any]:
    """Return one credential-free section for the authenticated panel."""
    specs = SECTION_FIELDS.get(section, ())
    values = {
        spec.key: section_value(options, spec) for spec in specs if not spec.secret
    }
    for connector in CONNECTOR_IDS:
        if section != connector:
            continue
        if connector == "n8n":
            values["n8n_outbound_credential"] = ""
            values["n8n_inbound_credential"] = ""
            values["n8n_outbound_credential_configured"] = any(
                bool(options.get(key))
                for key in ("n8n_outbound_api_key", "n8n_password")
            )
            values["n8n_inbound_credential_configured"] = any(
                bool(options.get(key))
                for key in ("n8n_inbound_bearer_token", "n8n_shared_secret")
            )
        else:
            input_key = (
                "ollama_api_key" if connector == "ollama" else f"{connector}_credential"
            )
            values[input_key] = ""
            values[f"{connector}_credential_configured"] = any(
                bool(options.get(key)) for key in _secret_mapping(connector)
            )
    metadata: dict[str, Any] = {}
    if section == "n8n":
        metadata = {
            "inbound_endpoint": INBOUND_ENDPOINT,
            "supported_inbound_commands": sorted(ALLOWED_INBOUND_COMMANDS),
            "supported_outbound_events": sorted(ALLOWED_OUTBOUND_EVENTS),
        }
    elif section == "mcp":
        metadata = {"read_only_capability_allowlist": sorted(ALLOWED_CAPABILITIES)}
    return {
        "section": section,
        "fields": [spec.public() for spec in specs],
        "values": values,
        "metadata": metadata,
    }


def sanitized_configuration(options: dict[str, Any]) -> dict[str, Any]:
    """Return every settings section without any stored credential material."""
    return {
        "schema_version": CONFIGURATION_SCHEMA_VERSION,
        "revision": configuration_revision(options),
        "sections": {
            section: sanitized_section(section, options) for section in PANEL_SECTIONS
        },
    }


def secret_keys() -> frozenset[str]:
    """Expose the fixed secret-key set for diagnostics/leak tests."""
    return SECRET_KEYS
