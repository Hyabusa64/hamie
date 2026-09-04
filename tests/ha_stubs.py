"""Minimal stand-ins for the Home Assistant APIs HAMIE's llm module uses.

Home Assistant is not a test dependency of this repository -- pulling it in
would add hundreds of megabytes and pin the Python version. But the defect
these stubs exist to pin was a *contract* defect: HAMIE did not implement a
hook Home Assistant calls on it.

So rather than mocking HAMIE's behaviour, these stubs reproduce the parts of
the contract that were verified against the installed Home Assistant 2026.8.3
source, including `homeassistant/components/llm/__init__.py::async_get_tools`
verbatim in structure -- the sorted platform iteration, the bare
`except Exception` that swallowed the failure into a log line, and the
`None` short-circuit. A test can then run Home Assistant's own dispatcher
loop over HAMIE's real module and prove the AttributeError cannot recur.

If Home Assistant changes this contract, these stubs go stale and the live
validation in production is what catches it. That tradeoff is recorded here
on purpose.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any, Protocol


def _module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def install() -> dict[str, Any]:
    """Install the stub tree into sys.modules. Idempotent."""
    if "homeassistant" in sys.modules and getattr(
        sys.modules["homeassistant"], "_hamie_stub", False
    ):
        return sys.modules["homeassistant"]._registry  # type: ignore[attr-defined]

    ha = _module("homeassistant")
    ha._hamie_stub = True  # type: ignore[attr-defined]

    # -- homeassistant.core -------------------------------------------------
    core = _module("homeassistant.core")

    def callback(func):  # HA's @callback marks event-loop-safe callables.
        func._hass_callback = True
        return func

    class HomeAssistant:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.states = _States()
            self.config = types.SimpleNamespace(config_dir="/config", path=lambda *a: "/config")
            self.services = _Services()

    class _States:
        def __init__(self) -> None:
            self._states: dict[str, Any] = {}

        def get(self, entity_id: str):
            return self._states.get(entity_id)

        def async_all(self, domain: str | None = None):
            return [
                s for eid, s in self._states.items()
                if domain is None or eid.startswith(f"{domain}.")
            ]

    class _Services:
        async def async_call(self, *args, **kwargs):
            return True

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    # -- homeassistant.exceptions -------------------------------------------
    exceptions = _module("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    exceptions.HomeAssistantError = HomeAssistantError

    # -- homeassistant.helpers.llm ------------------------------------------
    _module("homeassistant.helpers")
    helpers_llm = _module("homeassistant.helpers.llm")

    @dataclass(slots=True)
    class LLMContext:
        platform: str = "test"
        context: Any = None
        language: str = "en"
        assistant: str | None = None
        device_id: str | None = None

    @dataclass(slots=True)
    class ToolInput:
        tool_name: str
        tool_args: dict[str, Any] = field(default_factory=dict)
        id: str | None = None

    class Tool:
        name: str
        description: str
        parameters: Any

        async def async_call(self, hass, tool_input, llm_context) -> Any:
            raise NotImplementedError

    @dataclass(slots=True)
    class APIInstance:
        api: Any
        api_prompt: str
        llm_context: LLMContext
        tools: list[Tool]

    class API:
        def __init__(self, *, hass, id, name) -> None:  # noqa: A002
            self.hass, self.id, self.name = hass, id, name

        async def async_get_api_instance(self, llm_context) -> APIInstance:
            raise NotImplementedError

    registry: dict[str, API] = {}

    def async_register_api(hass, api: API):
        if api.id in registry:
            raise ValueError(f"API {api.id} is already registered")
        registry[api.id] = api

        def unregister() -> None:
            registry.pop(api.id, None)

        return unregister

    helpers_llm.LLMContext = LLMContext
    helpers_llm.ToolInput = ToolInput
    helpers_llm.Tool = Tool
    helpers_llm.APIInstance = APIInstance
    helpers_llm.API = API
    helpers_llm.async_register_api = async_register_api

    # -- homeassistant.components.llm ---------------------------------------
    # Structure verified against home-assistant/core 2026.8.3.
    _module("homeassistant.components")
    comp_llm = _module("homeassistant.components.llm")

    @dataclass(slots=True)
    class LLMTools:
        tools: list[Tool]
        prompt: str | None = None

    class LLMToolsPlatformProtocol(Protocol):
        def async_get_tools(
            self, hass, llm_context: LLMContext, api_id: str
        ) -> LLMTools | None: ...

    logged_errors: list[str] = []

    async def component_async_get_tools(hass, llm_context, api_id, platforms):
        """Home Assistant's own dispatcher, reproduced.

        The bare `except Exception` is the whole reason the original defect
        was a recurring log line instead of a crash, so it is preserved.
        """
        tools: list[Tool] = []
        prompts: list[str] = []
        for domain, platform in sorted(platforms.items()):
            try:
                result = platform.async_get_tools(hass, llm_context, api_id)
            except Exception as err:  # noqa: BLE001 - mirrors HA
                logged_errors.append(f"Error getting tools from LLM platform {domain}: {err!r}")
                continue
            if result is None:
                continue
            tools.extend(result.tools)
            if result.prompt:
                prompts.append(result.prompt)
        return LLMTools(tools=tools, prompt="\n".join(prompts) if prompts else None)

    comp_llm.LLMTools = LLMTools
    comp_llm.LLMToolsPlatformProtocol = LLMToolsPlatformProtocol
    comp_llm.async_get_tools = component_async_get_tools
    comp_llm.logged_errors = logged_errors

    # -- voluptuous ---------------------------------------------------------
    if "voluptuous" not in sys.modules:
        vol = _module("voluptuous")

        class Invalid(Exception):
            pass

        class Marker:
            def __init__(self, schema, **kw) -> None:
                self.schema = schema

            def __str__(self) -> str:
                return str(self.schema)

            def __hash__(self) -> int:
                return hash(str(self.schema))

            def __eq__(self, other) -> bool:
                return str(self) == str(other)

        class Required(Marker):
            pass

        class Optional(Marker):
            pass

        class Schema:
            def __init__(self, schema, **kw) -> None:
                self.schema = schema

            def __call__(self, data):
                if not isinstance(self.schema, dict):
                    return data
                if not isinstance(data, dict):
                    raise Invalid("expected a mapping")
                known = {str(k) for k in self.schema}
                required = {str(k) for k in self.schema if isinstance(k, Required)}
                missing = required - set(data)
                if missing:
                    raise Invalid(f"required key not provided: {sorted(missing)}")
                extra = set(data) - known
                if extra:
                    raise Invalid(f"extra keys not allowed: {sorted(extra)}")
                return data

        class All:
            def __init__(self, *validators) -> None:
                self.validators = validators

            def __call__(self, value):
                return value

        def Coerce(t):  # noqa: N802 - mirrors voluptuous
            return t

        class Length:
            def __init__(self, min=None, max=None) -> None:  # noqa: A002
                self.min, self.max = min, max

            def __call__(self, value):
                return value

        class In:
            def __init__(self, container) -> None:
                self.container = container

            def __call__(self, value):
                return value

        class Range:
            def __init__(self, min=None, max=None) -> None:  # noqa: A002
                self.min, self.max = min, max

            def __call__(self, value):
                if self.min is not None and value < self.min:
                    raise Invalid(f"value must be at least {self.min}")
                if self.max is not None and value > self.max:
                    raise Invalid(f"value must be at most {self.max}")
                return value

        class Equal:
            def __init__(self, target) -> None:
                self.target = target

            def __call__(self, value):
                if value != self.target:
                    raise Invalid(f"value must be {self.target}")
                return value

        class Exclusive(Marker):
            def __init__(self, schema, group=None, **kw) -> None:
                super().__init__(schema, **kw)
                self.group = group

        vol.Range = Range
        vol.Equal = Equal
        vol.Exclusive = Exclusive
        vol.Invalid = Invalid
        vol.Required = Required
        vol.Optional = Optional
        vol.Schema = Schema
        vol.All = All
        vol.Coerce = Coerce
        vol.Length = Length
        vol.In = In
        vol.Marker = Marker

    ha._registry = registry  # type: ignore[attr-defined]
    return registry
