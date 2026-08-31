"""Home Assistant LLM platform contract.

Production logged, on every Assist conversation:

    ERROR homeassistant.components.llm
    Error getting tools from LLM platform hamie
    AttributeError: module 'custom_components.hamie.llm' has no attribute
    'async_get_tools'

Root cause, verified against home-assistant/core 2026.8.3: the `llm`
component discovers integration platforms *by module name*. Any loaded
integration exposing `<integration>.llm` is treated as an LLM tools platform
and has `async_get_tools(hass, llm_context, api_id)` called on it. HAMIE's
module is called `llm.py` because it holds HAMIE's LLM integration, which
made it a platform by accident.

These tests run Home Assistant's own dispatcher loop (reproduced in
tests/ha_stubs.py from the verified source) over HAMIE's real module.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from tests.ha_stubs import install

install()

import hamie.llm as hamie_llm  # noqa: E402
from homeassistant.components import llm as ha_llm  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers.llm import LLMContext  # noqa: E402

from hamie.domain.investigation import EXECUTION_TOOLS, INVESTIGATION_TOOLS  # noqa: E402

ASSIST_API_ID = "assist"


class _Entry:
    """The parts of a config entry this code path touches."""

    def __init__(self, entry_id: str = "entry-1") -> None:
        self.entry_id = entry_id
        self.options: dict = {}
        self._unloads: list = []

    def async_on_unload(self, func) -> None:
        self._unloads.append(func)

    def run_unloads(self) -> None:
        for func in reversed(self._unloads):
            func()
        self._unloads.clear()


@pytest.fixture
def hass() -> HomeAssistant:
    ha_llm.logged_errors.clear()
    install().clear()
    return HomeAssistant()


# ------------------------------------------------- the original failure


@pytest.mark.asyncio
async def test_home_assistant_dispatcher_no_longer_errors_on_hamie(hass) -> None:
    """Run HA's own loop over the real module. This is the regression."""
    result = await ha_llm.async_get_tools(
        hass, LLMContext(), ASSIST_API_ID, {"hamie": hamie_llm}
    )
    assert ha_llm.logged_errors == [], ha_llm.logged_errors
    assert result.tools == []
    assert result.prompt is None


@pytest.mark.asyncio
async def test_the_test_would_have_caught_the_original_defect(hass) -> None:
    """A platform module without the hook must still produce the log line.

    Without this, the test above could pass for the wrong reason.
    """
    import types

    broken = types.ModuleType("broken_platform")
    result = await ha_llm.async_get_tools(
        hass, LLMContext(), ASSIST_API_ID, {"hamie": broken}
    )
    assert len(ha_llm.logged_errors) == 1
    assert "Error getting tools from LLM platform hamie" in ha_llm.logged_errors[0]
    assert "AttributeError" in ha_llm.logged_errors[0]
    assert result.tools == []


# ------------------------------------------------------- hook semantics


def test_hook_matches_the_verified_signature() -> None:
    signature = inspect.signature(hamie_llm.async_get_tools)
    assert list(signature.parameters) == ["hass", "llm_context", "api_id"]


def test_hook_is_an_event_loop_callback_not_a_coroutine() -> None:
    """The caller runs this on the event loop; it must never do I/O."""
    assert not inspect.iscoroutinefunction(hamie_llm.async_get_tools)
    assert getattr(hamie_llm.async_get_tools, "_hass_callback", False)


def test_hook_contributes_nothing_to_the_builtin_assist_api(hass) -> None:
    """House-wide diagnostic tools must not land in every voice conversation."""
    assert hamie_llm.async_get_tools(hass, LLMContext(), ASSIST_API_ID) is None


def test_hook_contributes_nothing_to_hamies_own_api_either(hass) -> None:
    """HAMIE's tools reach the model through its registered API, not this hook."""
    api_id = hamie_llm.api_id_for("entry-1")
    assert hamie_llm.async_get_tools(hass, LLMContext(), api_id) is None


@pytest.mark.parametrize("api_id", ["assist", "", "anything", "hamie-investigation-x"])
def test_hook_never_raises_for_any_api_id(hass, api_id: str) -> None:
    assert hamie_llm.async_get_tools(hass, LLMContext(), api_id) is None


# ------------------------------------------------ registration lifecycle


@pytest.mark.asyncio
async def test_setup_registers_a_stable_config_entry_bound_api(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    assert list(registry) == ["hamie-investigation-abc"]
    assert registry["hamie-investigation-abc"].name == "HAMIE Investigation"


@pytest.mark.asyncio
async def test_unload_releases_the_registration(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    entry.run_unloads()
    assert registry == {}


@pytest.mark.asyncio
async def test_reload_cycle_leaves_exactly_one_registration(hass) -> None:
    registry = install()
    for _ in range(3):
        entry = _Entry("abc")
        await hamie_llm.async_setup_api(hass, entry)
        assert len(registry) == 1
        entry.run_unloads()
        assert registry == {}


@pytest.mark.asyncio
async def test_duplicate_setup_without_unload_does_not_raise(hass) -> None:
    """The stub registry raises on a duplicate id, exactly as HA does."""
    registry = install()
    first, second = _Entry("abc"), _Entry("abc")
    await hamie_llm.async_setup_api(hass, first)
    await hamie_llm.async_setup_api(hass, second)  # must not raise
    assert len(registry) == 1
    second.run_unloads()
    assert registry == {}


@pytest.mark.asyncio
async def test_two_config_entries_register_independently(hass) -> None:
    registry = install()
    a, b = _Entry("aaa"), _Entry("bbb")
    await hamie_llm.async_setup_api(hass, a)
    await hamie_llm.async_setup_api(hass, b)
    assert set(registry) == {"hamie-investigation-aaa", "hamie-investigation-bbb"}
    a.run_unloads()
    assert set(registry) == {"hamie-investigation-bbb"}


# ------------------------------------------------------ tool enumeration


@pytest.mark.asyncio
async def test_api_instance_exposes_exactly_the_allowlisted_tools(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    api = registry["hamie-investigation-abc"]
    instance = await api.async_get_api_instance(LLMContext())
    names = {tool.name for tool in instance.tools}
    assert names == INVESTIGATION_TOOLS
    assert EXECUTION_TOOLS == frozenset()


@pytest.mark.asyncio
async def test_every_tool_has_a_stable_name_description_and_schema(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    instance = await registry["hamie-investigation-abc"].async_get_api_instance(LLMContext())
    for tool in instance.tools:
        assert tool.name.startswith("hamie_"), tool.name
        assert tool.name == tool.name.lower()
        assert tool.description and len(tool.description) > 20, tool.name
        assert tool.parameters is not None, tool.name


@pytest.mark.asyncio
async def test_tool_names_are_stable_across_enumerations(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    api = registry["hamie-investigation-abc"]
    first = [t.name for t in (await api.async_get_api_instance(LLMContext())).tools]
    second = [t.name for t in (await api.async_get_api_instance(LLMContext())).tools]
    assert first == second


@pytest.mark.asyncio
async def test_no_tool_exposes_shell_filesystem_or_service_execution(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    instance = await registry["hamie-investigation-abc"].async_get_api_instance(LLMContext())
    forbidden = ("shell", "exec", "python", "eval", "http", "request", "call_service",
                 "service", "write", "delete", "remove", "mutate", "apply", "deploy")
    for tool in instance.tools:
        blob = f"{tool.name} {tool.description}".lower()
        assert not tool.name.startswith(tuple(f"hamie_{w}" for w in forbidden)), tool.name
        assert "arbitrary" not in blob, tool.name


@pytest.mark.asyncio
async def test_api_prompt_states_the_authority_boundary(hass) -> None:
    registry = install()
    entry = _Entry("abc")
    await hamie_llm.async_setup_api(hass, entry)
    instance = await registry["hamie-investigation-abc"].async_get_api_instance(LLMContext())
    prompt = instance.api_prompt.lower()
    assert "cannot approve or execute" in prompt


# ------------------------------------------------------- tool behaviour


async def _tools(hass, entry_id: str = "abc") -> dict:
    registry = install()
    entry = _Entry(entry_id)
    await hamie_llm.async_setup_api(hass, entry)
    instance = await registry[f"hamie-investigation-{entry_id}"].async_get_api_instance(
        LLMContext()
    )
    return {tool.name: tool for tool in instance.tools}


@pytest.mark.asyncio
async def test_tool_schemas_reject_unknown_and_missing_arguments(hass) -> None:
    import voluptuous as vol

    tools = await _tools(hass)
    entity_tool = tools["hamie_get_entity"]
    with pytest.raises(vol.Invalid):
        entity_tool.parameters({"entity_id": "light.x", "sneaky": "rm -rf /"})
    with pytest.raises(vol.Invalid):
        entity_tool.parameters({})


@pytest.mark.asyncio
async def test_a_tool_removed_from_the_allowlist_cannot_be_constructed(hass) -> None:
    """The catalog is the boundary, not the constructor's caller."""
    import voluptuous as vol

    with pytest.raises(PermissionError):
        hamie_llm._InvestigationTool(
            name="hamie_execute_anything",
            description="x" * 40,
            parameters=vol.Schema({}),
            handler=lambda *a: None,
            entry_id="abc",
        )


@pytest.mark.asyncio
async def test_handler_failure_becomes_a_home_assistant_error(hass) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.llm import ToolInput

    tools = await _tools(hass)
    tool = tools["hamie_get_entity"]

    async def boom(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    tool._handler = boom
    with pytest.raises(HomeAssistantError):
        await tool.async_call(
            hass, ToolInput("hamie_get_entity", {"entity_id": "light.x"}), LLMContext()
        )


@pytest.mark.asyncio
async def test_oversized_tool_output_is_refused_not_truncated_silently(hass) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.llm import ToolInput

    tools = await _tools(hass)
    tool = tools["hamie_get_entity"]

    async def huge(*_args, **_kwargs):
        return {"blob": "x" * (hamie_llm.MAX_TOOL_CHARACTERS + 1000)}

    tool._handler = huge
    with pytest.raises(HomeAssistantError, match="output budget"):
        await tool.async_call(
            hass, ToolInput("hamie_get_entity", {"entity_id": "light.x"}), LLMContext()
        )


@pytest.mark.asyncio
async def test_cancellation_propagates_and_is_not_swallowed(hass) -> None:
    """A cancelled investigation must not look like a failed-but-handled call."""
    from homeassistant.helpers.llm import ToolInput

    tools = await _tools(hass)
    tool = tools["hamie_get_entity"]

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    tool._handler = cancelled
    with pytest.raises(asyncio.CancelledError):
        await tool.async_call(
            hass, ToolInput("hamie_get_entity", {"entity_id": "light.x"}), LLMContext()
        )


@pytest.mark.asyncio
async def test_audit_failure_does_not_replace_the_real_failure(hass) -> None:
    """Diagnosing the wrong fault is worse than a gap in the ledger."""
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.llm import ToolInput

    tools = await _tools(hass)
    tool = tools["hamie_get_entity"]

    async def huge(*_args, **_kwargs):
        return {"blob": "x" * (hamie_llm.MAX_TOOL_CHARACTERS + 1000)}

    tool._handler = huge
    # No HAMIE runtime is registered, so every audit write raises.
    with pytest.raises(HomeAssistantError, match="output budget"):
        await tool.async_call(
            hass, ToolInput("hamie_get_entity", {"entity_id": "light.x"}), LLMContext()
        )


@pytest.mark.asyncio
async def test_successful_investigation_still_requires_a_ledger_entry(hass) -> None:
    """The strict rule survives on the path where evidence was produced."""
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.llm import ToolInput

    tools = await _tools(hass)
    tool = tools["hamie_get_entity"]

    async def fine(*_args, **_kwargs):
        return {"evidence_status": "not_found", "entity_id": "light.x"}

    tool._handler = fine
    # No HAMIE runtime is registered, so the ledger write cannot happen. The
    # call must fail rather than return evidence that was never recorded --
    # the exact message differs by which step fails first, and asserting on
    # it would pin an implementation detail rather than the invariant.
    with pytest.raises(HomeAssistantError):
        await tool.async_call(
            hass, ToolInput("hamie_get_entity", {"entity_id": "light.x"}), LLMContext()
        )
