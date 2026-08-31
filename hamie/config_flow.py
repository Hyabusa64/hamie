"""Configuration and complete native Options Flow for HAMIE."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

try:
    import voluptuous as vol
except ModuleNotFoundError:  # Dependency-free contract tests do not load HA deps.
    vol = None  # type: ignore[assignment]
from homeassistant import config_entries

try:
    from homeassistant.core import callback
except ModuleNotFoundError:  # Dependency-free flow harness.

    def callback(function: Any) -> Any:
        return function


from .configuration import (
    CONNECTOR_IDS,
    PANEL_SECTIONS,
    SECTION_FIELDS,
    ConfigurationError,
    normalize_section,
    section_value,
)
from .connectors.base import classify_connector_failure
from .connectors.mcp import ALLOWED_CAPABILITIES
from .connectors.n8n import ALLOWED_INBOUND_COMMANDS, ALLOWED_OUTBOUND_EVENTS
from .const import DOMAIN, NAME
from .domain.intelligence import SuppressionAction

OPTIONS_MENU = (*PANEL_SECTIONS,)
FORM_ACTIONS = ("save", "test")
SUPPRESSION_MENU = (
    "suppression_list",
    "suppression_create",
    "suppression_edit",
    "suppression_toggle",
    "suppression_delete",
)
SUPPRESSION_ACTIONS = tuple(item.value for item in SuppressionAction)
INBOUND_ENDPOINT = "/api/hamie/n8n"


def _password_selector() -> Any:
    from homeassistant.helpers import selector

    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _csv(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(
        dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
    )


def _aware_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _failure_category(err: Exception) -> str:
    """Map failures to fixed non-sensitive UI categories."""
    return classify_connector_failure(err)


class HamieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Create HAMIE's single, local configuration entry."""

    VERSION = 5
    MINOR_VERSION = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the no-field user setup step."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            return self.async_create_entry(
                title=NAME, data={"installation_id": uuid4().hex}
            )
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create HAMIE's native options menu."""
        return HamieOptionsFlow()


OptionsFlowBase = getattr(config_entries, "OptionsFlow", object)


class HamieOptionsFlow(OptionsFlowBase):  # type: ignore[misc, valid-type]
    """Configure bounded HAMIE behavior and optional finite connectors."""

    def __init__(self) -> None:
        self._pending_suppression: dict[str, Any] | None = None
        self._editing_rule_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the complete top-level Options Flow menu."""
        return self.async_show_menu(step_id="init", menu_options=list(OPTIONS_MENU))

    def _schema(self, fields: dict[Any, Any]) -> Any:
        return vol.Schema(fields)

    def _suggested(self, key: str, fallback: Any) -> dict[str, Any]:
        return {"suggested_value": self.config_entry.options.get(key, fallback)}

    def _runtime(self) -> Any:
        entries = self.hass.data.get(DOMAIN, {})
        runtime = entries.get(self.config_entry.entry_id)
        if runtime is None:
            raise RuntimeError("HAMIE runtime is unavailable")
        return runtime

    def _save_options(self, options: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Persist through HA without returning write-only options to the client."""
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        return self.async_abort(reason="options_saved")

    def _save_section(
        self, section: str, values: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Use the same authoritative normalizer as the panel API."""
        options = normalize_section(section, values, dict(self.config_entry.options))
        return self._save_options(options)

    def _section_schema(self, section: str, values: dict[str, Any]) -> Any:
        """Build a native form from the shared field specifications."""
        fields: dict[Any, Any] = {}
        for spec in SECTION_FIELDS[section]:
            if spec.key.endswith("_allowed_hosts"):
                continue
            suggested = section_value(values, spec)
            description = {} if spec.secret else {"suggested_value": suggested}
            marker = (
                vol.Optional(spec.key, default="", description=description)
                if spec.secret
                else vol.Optional(spec.key, description=description)
            )
            if spec.secret:
                validator = _password_selector()
            elif spec.kind == "boolean":
                validator = bool
            elif spec.kind == "integer":
                validator = vol.All(
                    vol.Coerce(int),
                    vol.Range(min=spec.minimum, max=spec.maximum),
                )
            elif spec.kind == "number":
                validator = vol.All(
                    vol.Coerce(float),
                    vol.Range(min=spec.minimum, max=spec.maximum),
                )
            elif spec.choices and spec.kind == "select":
                validator = vol.In(spec.choices)
            else:
                validator = str
                if spec.kind in {"multiselect", "csv"} and isinstance(suggested, list):
                    description = {"suggested_value": ",".join(suggested)}
                    marker = vol.Optional(spec.key, description=description)
                if spec.kind == "json" and not isinstance(suggested, str):
                    import json

                    description = {"suggested_value": json.dumps(suggested)}
                    marker = vol.Optional(spec.key, description=description)
            fields[marker] = validator
        return self._schema(fields)

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            try:
                return self._save_section("general", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="general",
                    data_schema=self._section_schema("general", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="general",
            data_schema=self._section_schema("general", self.config_entry.options),
        )

    async def async_step_provenance(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure explicit source/deployment roles; never test credentials."""
        if user_input is not None:
            try:
                return self._save_section("provenance", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="provenance",
                    data_schema=self._section_schema("provenance", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="provenance",
            data_schema=self._section_schema("provenance", self.config_entry.options),
        )

    async def async_step_findings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure future scan and findings projection policy."""
        if user_input is not None:
            try:
                return self._save_section("findings", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="findings",
                    data_schema=self._section_schema("findings", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="findings",
            data_schema=self._section_schema("findings", self.config_entry.options),
        )

    async def async_step_grouping(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure deterministic grouping policy."""
        if user_input is not None:
            try:
                return self._save_section("grouping", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="grouping",
                    data_schema=self._section_schema("grouping", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="grouping",
            data_schema=self._section_schema("grouping", self.config_entry.options),
        )

    async def async_step_findings_grouping(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_grouping(user_input)

    async def async_step_suppression_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="suppression_rules", menu_options=list(SUPPRESSION_MENU)
        )

    async def async_step_suppression(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Expose the full HAMIE policy editor under the shared section name."""
        return await self.async_step_suppression_rules(user_input)

    async def async_step_safety(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show enforced safety invariants without creating mutable controls."""
        if user_input is not None:
            try:
                for spec in SECTION_FIELDS["safety"]:
                    if user_input.get(spec.key, spec.default) != spec.default:
                        raise ConfigurationError("locked_policy", spec.key)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="safety",
                    data_schema=self._section_schema("safety", {}),
                    errors={err.field or "base": err.code},
                )
            return await self.async_step_init()
        return self.async_show_form(
            step_id="safety", data_schema=self._section_schema("safety", {})
        )

    async def async_step_ai_control(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure the AI cleanup-engine operating mode and policy.

        Setting ``ai_operating_mode`` to ``ai_control`` here only
        expresses intent -- the cleanup engine's actual automatic-
        execution behavior additionally requires a separate, explicit
        acknowledgement (``hamie/ai_control/acknowledge``), never
        granted by this form alone. See ``domain/ai_control.py``.
        """
        if user_input is not None:
            try:
                return self._save_section("ai_control", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="ai_control",
                    data_schema=self._section_schema("ai_control", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="ai_control",
            data_schema=self._section_schema("ai_control", self.config_entry.options),
        )

    async def async_step_audit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure bounded audit retention and event categories."""
        if user_input is not None:
            try:
                return self._save_section("audit", user_input)
            except ConfigurationError as err:
                return self.async_show_form(
                    step_id="audit",
                    data_schema=self._section_schema("audit", user_input),
                    errors={err.field or "base": err.code},
                )
        return self.async_show_form(
            step_id="audit",
            data_schema=self._section_schema("audit", self.config_entry.options),
        )

    def _rules(self) -> tuple[dict[str, Any], ...]:
        return self._runtime().operations.suppression_rules()

    def _rule_choices(self) -> dict[str, str]:
        return {
            item["rule_id"]: (
                f"{item['name']} — {item['action']} — "
                f"{'enabled' if item['enabled'] else 'disabled'}"
            )
            for item in self._rules()
        }

    async def async_step_suppression_list(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_suppression_rules()
        summaries = [
            (
                f"{item['name']}: {item['action']}; "
                f"matches={item['last_match_count']}; "
                f"expiration={item['expiration'] or 'none'}"
            )
            for item in self._rules()
        ]
        return self.async_show_form(
            step_id="suppression_list",
            data_schema=vol.Schema({}),
            description_placeholders={
                "rules": "\n".join(summaries) if summaries else "No suppression rules."
            },
        )

    async def async_step_suppression_create(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            try:
                expiration = _aware_datetime(user_input.get("expiration"))
                if user_input["action"] == "snooze" and expiration is None:
                    raise ValueError("snooze requires expiration")
                matcher = ((user_input["matcher_field"], user_input["matcher_value"]),)
                preview = self._runtime().operations.preview_suppression(matcher)
            except Exception:
                return self.async_show_form(
                    step_id="suppression_create",
                    data_schema=self._suppression_create_schema(user_input),
                    errors={"base": "invalid_suppression_rule"},
                )
            self._pending_suppression = {
                **user_input,
                "preview": preview,
                "expiration_value": expiration,
            }
            return await self.async_step_suppression_confirm()
        return self.async_show_form(
            step_id="suppression_create",
            data_schema=self._suppression_create_schema({}),
        )

    def _suppression_create_schema(self, values: dict[str, Any]) -> Any:
        return self._schema(
            {
                vol.Required(
                    "name", description={"suggested_value": values.get("name", "")}
                ): vol.All(str, vol.Length(min=1, max=128)),
                vol.Required(
                    "matcher_field",
                    description={
                        "suggested_value": values.get("matcher_field", "entity_id")
                    },
                ): vol.In(
                    [
                        "integration_domain",
                        "config_entry_id",
                        "device_id",
                        "entity_domain",
                        "entity_id",
                        "entity_id_prefix",
                        "area_id",
                        "analyzer_id",
                        "condition_key",
                        "category",
                        "group_id",
                        "source_provider",
                        "name_prefix",
                        "failure_condition",
                        "dependency_root",
                        "severity",
                    ]
                ),
                vol.Required(
                    "matcher_value",
                    description={"suggested_value": values.get("matcher_value", "")},
                ): vol.All(str, vol.Length(min=1, max=256)),
                vol.Required(
                    "reason", description={"suggested_value": values.get("reason", "")}
                ): vol.All(str, vol.Length(min=1, max=256)),
                vol.Required(
                    "action",
                    description={
                        "suggested_value": values.get(
                            "action", "hide_from_default_view"
                        )
                    },
                ): vol.In(SUPPRESSION_ACTIONS),
                vol.Optional(
                    "expiration",
                    description={"suggested_value": values.get("expiration", "")},
                ): str,
            }
        )

    async def async_step_suppression_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if self._pending_suppression is None:
            return await self.async_step_suppression_create()
        if user_input is not None:
            if not user_input["confirm"]:
                self._pending_suppression = None
                return await self.async_step_suppression_rules()
            pending = self._pending_suppression
            await self._runtime().operations.async_create_suppression_rule(
                preview=pending["preview"],
                name=pending["name"],
                reason=pending["reason"],
                action=SuppressionAction(pending["action"]),
                expiration=pending["expiration_value"],
                token=uuid4().hex,
                actor="home_assistant_options_flow",
            )
            self._pending_suppression = None
            return await self.async_step_suppression_rules()
        preview = self._pending_suppression["preview"]
        return self.async_show_form(
            step_id="suppression_confirm",
            data_schema=self._schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={
                "match_count": str(preview["count"]),
                "action": self._pending_suppression["action"],
                "expiration": self._pending_suppression.get("expiration") or "none",
            },
        )

    async def async_step_suppression_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        choices = self._rule_choices()
        if not choices:
            return self.async_show_form(
                step_id="suppression_edit",
                data_schema=vol.Schema({}),
                errors={"base": "no_suppression_rules"},
                description_placeholders={
                    "matcher": "none",
                    "match_count": "0",
                },
            )
        if self._editing_rule_id is None:
            if user_input is not None:
                self._editing_rule_id = user_input["rule_id"]
                return await self.async_step_suppression_edit()
            return self.async_show_form(
                step_id="suppression_edit",
                data_schema=self._schema({vol.Required("rule_id"): vol.In(choices)}),
                description_placeholders={
                    "matcher": "select a rule",
                    "match_count": "unknown",
                },
            )
        current = next(
            item for item in self._rules() if item["rule_id"] == self._editing_rule_id
        )
        if user_input is not None:
            try:
                expiration = _aware_datetime(user_input.get("expiration"))
                if user_input["action"] == "snooze" and expiration is None:
                    raise ValueError("snooze requires expiration")
                await self._runtime().operations.async_update_suppression_rule(
                    current["rule_id"],
                    expected_revision=current["revision"],
                    enabled=user_input["enabled"],
                    reason=user_input["reason"],
                    action=SuppressionAction(user_input["action"]),
                    expiration=expiration,
                    actor="home_assistant_options_flow",
                )
            except Exception:
                return self.async_show_form(
                    step_id="suppression_edit",
                    data_schema=self._suppression_edit_schema(current, user_input),
                    errors={"base": "invalid_suppression_rule"},
                )
            self._editing_rule_id = None
            return await self.async_step_suppression_rules()
        return self.async_show_form(
            step_id="suppression_edit",
            data_schema=self._suppression_edit_schema(current, current),
            description_placeholders={
                "match_count": str(current["last_match_count"]),
                "matcher": str(current["matcher"]),
            },
        )

    def _suppression_edit_schema(
        self, current: dict[str, Any], values: dict[str, Any]
    ) -> Any:
        return self._schema(
            {
                vol.Required(
                    "enabled",
                    description={"suggested_value": values.get("enabled", True)},
                ): bool,
                vol.Required(
                    "reason",
                    description={"suggested_value": values.get("reason", "")},
                ): vol.All(str, vol.Length(min=1, max=256)),
                vol.Required(
                    "action",
                    description={
                        "suggested_value": values.get(
                            "action", "hide_from_default_view"
                        )
                    },
                ): vol.In(SUPPRESSION_ACTIONS),
                vol.Optional(
                    "expiration",
                    description={
                        "suggested_value": values.get("expiration")
                        or current.get("expiration")
                        or ""
                    },
                ): str,
            }
        )

    async def async_step_suppression_toggle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        choices = self._rule_choices()
        if user_input is not None:
            current = next(
                item
                for item in self._rules()
                if item["rule_id"] == user_input["rule_id"]
            )
            if not user_input["confirm"]:
                return await self.async_step_suppression_rules()
            await self._runtime().operations.async_update_suppression_rule(
                current["rule_id"],
                expected_revision=current["revision"],
                enabled=not current["enabled"],
                reason=current["reason"],
                action=SuppressionAction(current["action"]),
                expiration=_aware_datetime(current["expiration"]),
                actor="home_assistant_options_flow",
            )
            return await self.async_step_suppression_rules()
        return self.async_show_form(
            step_id="suppression_toggle",
            data_schema=self._schema(
                {
                    vol.Required("rule_id"): vol.In(choices),
                    vol.Required("confirm", default=False): bool,
                }
            ),
            errors={"base": "no_suppression_rules"} if not choices else {},
        )

    async def async_step_suppression_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        choices = self._rule_choices()
        if user_input is not None:
            current = next(
                item
                for item in self._rules()
                if item["rule_id"] == user_input["rule_id"]
            )
            if not user_input["confirm"]:
                return await self.async_step_suppression_rules()
            await self._runtime().operations.async_delete_suppression_rule(
                current["rule_id"],
                expected_revision=current["revision"],
                actor="home_assistant_options_flow",
            )
            return await self.async_step_suppression_rules()
        return self.async_show_form(
            step_id="suppression_delete",
            data_schema=self._schema(
                {
                    vol.Required("rule_id"): vol.In(choices),
                    vol.Required("confirm", default=False): bool,
                }
            ),
            errors={"base": "no_suppression_rules"} if not choices else {},
        )

    async def async_step_ollama(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self._connector_step("ollama", user_input)

    async def async_step_n8n(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self._connector_step("n8n", user_input)

    async def async_step_mcp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self._connector_step("mcp", user_input)

    async def async_step_hkg(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self._connector_step("hkg", user_input)

    async def _connector_step(
        self, connector_id: str, user_input: dict[str, Any] | None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = self._connector_placeholders(connector_id)
        values = dict(self.config_entry.options)
        if user_input is not None:
            values.update(user_input)
            try:
                candidate = self._prepare_connector_options(
                    connector_id,
                    user_input,
                    for_test=user_input["connector_action"] == "test",
                )
                self._validate_connector_options(connector_id, candidate)
                if user_input["connector_action"] == "test":
                    if not candidate.get(f"{connector_id}_enabled"):
                        raise PermissionError("configure_before_testing")
                    tested = await self._test_unsaved_connector(connector_id, candidate)
                    placeholders["connection_result"] = "connected"
                    details = tested.get("details", {})
                    if connector_id == "mcp" and isinstance(details, dict):
                        placeholders["accepted_capabilities"] = (
                            ", ".join(details.get("accepted_capabilities", ()))
                            or "none"
                        )
                        placeholders["rejected_capabilities"] = (
                            ", ".join(details.get("rejected_capabilities", ()))
                            or "none"
                        )
                    values = candidate
                else:
                    return self._save_options(candidate)
            except PermissionError:
                errors["base"] = "configure_before_testing"
            except ConfigurationError as err:
                errors[err.field or "base"] = err.code
            except ValueError as err:
                code = str(err)
                errors["base"] = (
                    code
                    if code
                    in {
                        "credential_required",
                        "credential_removal_not_confirmed",
                        "credential_regeneration_not_confirmed",
                        "invalid_url",
                        "invalid_capabilities",
                        "invalid_events",
                        "invalid_authentication",
                    }
                    else "invalid_connector_configuration"
                )
            except Exception as err:
                errors["base"] = _failure_category(err)
        return self.async_show_form(
            step_id=connector_id,
            data_schema=self._connector_schema(connector_id, values),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _prepare_connector_options(
        self,
        connector_id: str,
        user_input: dict[str, Any],
        *,
        for_test: bool = False,
    ) -> dict[str, Any]:
        values = dict(user_input)
        values.pop("connector_action", None)
        return normalize_section(
            connector_id,
            values,
            dict(self.config_entry.options),
            for_test=for_test,
        )

    def _validate_connector_options(
        self, connector_id: str, options: dict[str, Any]
    ) -> None:
        # normalize_section performs the authoritative connector validation.
        if connector_id not in CONNECTOR_IDS or not isinstance(options, dict):
            raise ValueError("invalid_connector_configuration")

    async def _test_unsaved_connector(
        self, connector_id: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        from .connectors.manager import ConnectorManager

        manager = ConnectorManager(
            options=options,
            hass=self.hass,
            installation_id=self.config_entry.data.get(
                "installation_id", self.config_entry.entry_id
            ),
        )
        try:
            result = await manager.async_test(connector_id)
            await self._record_connector_test_audit(connector_id, succeeded=True)
            return result
        except Exception:
            await self._record_connector_test_audit(connector_id, succeeded=False)
            raise
        finally:
            await manager.async_close()

    async def _record_connector_test_audit(
        self, connector_id: str, *, succeeded: bool
    ) -> None:
        """Best-effort audit without persisting unsaved connector values."""
        try:
            runtime = self._runtime()
            await runtime.operations.async_record_audit(
                ("connector_test_succeeded" if succeeded else "connector_test_failed"),
                actor="home_assistant_options_flow",
                target_ids=(connector_id,),
            )
        except Exception:
            return

    def _connector_schema(self, connector_id: str, values: dict[str, Any]) -> Any:
        shared = self._section_schema(connector_id, values)
        fields = dict(shared.schema)
        fields[vol.Required("connector_action", default="save")] = vol.In(FORM_ACTIONS)
        return self._schema(fields)

    def _connector_placeholders(self, connector_id: str) -> dict[str, str]:
        placeholders = {
            "connection_result": "not tested",
            "inbound_endpoint": INBOUND_ENDPOINT,
            "supported_inbound_commands": ", ".join(sorted(ALLOWED_INBOUND_COMMANDS)),
            "supported_outbound_events": ", ".join(sorted(ALLOWED_OUTBOUND_EVENTS)),
            "mcp_allowlist": ", ".join(sorted(ALLOWED_CAPABILITIES)),
            "accepted_capabilities": "not tested",
            "rejected_capabilities": "not tested",
        }
        try:
            status = next(
                item
                for item in self._runtime().operations.connector_status()
                if item["connector_id"] == connector_id
            )
            placeholders["connection_result"] = str(status["status"])
        except Exception:
            pass
        return placeholders

    async def async_step_connector_status(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_init()
        statuses = []
        try:
            for item in self._runtime().operations.connector_status():
                statuses.append(
                    f"{item['connector_id']}: enabled={item['enabled']}; "
                    f"state={item['status']}; last_success={item['last_success']}; "
                    f"last_failure={item['last_failure']}; "
                    f"latency_ms={item['latency_ms']}; "
                    f"failure={item['error_code'] or 'none'}; "
                    f"mode={item['capability_mode']}"
                )
        except Exception:
            statuses.append("HAMIE runtime status is unavailable.")
        return self.async_show_form(
            step_id="connector_status",
            data_schema=vol.Schema({}),
            description_placeholders={"statuses": "\n".join(statuses)},
        )

    async def async_step_test_connections(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        result = "No test run."
        if user_input is not None:
            connector_id = user_input["connector_id"]
            try:
                if not self.config_entry.options.get(f"{connector_id}_enabled", False):
                    raise PermissionError("configure_before_testing")
                status = next(
                    item
                    for item in self._runtime().operations.connector_status()
                    if item["connector_id"] == connector_id
                )
                if not status["enabled"]:
                    raise PermissionError("configure_before_testing")
                tested = await self._runtime().operations.async_test_connector(
                    connector_id, actor="home_assistant_options_flow"
                )
                result = f"{connector_id}: connected; latency_ms={tested['latency_ms']}"
            except PermissionError:
                errors["base"] = "configure_before_testing"
            except Exception as err:
                errors["base"] = _failure_category(err)
                result = f"{connector_id}: {errors['base']}"
        return self.async_show_form(
            step_id="test_connections",
            data_schema=self._schema(
                {vol.Required("connector_id"): vol.In(CONNECTOR_IDS)}
            ),
            errors=errors,
            description_placeholders={"latest_result": result},
        )
