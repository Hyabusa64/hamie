"""Source-definition index for automation/script/scene entities (mission
Part 3a).

Answers, independently of any precomputed benchmark field, "does this
automation/script/scene entity's backing YAML/UI-editor definition
still exist in the live configuration tree?" -- the exact question
``EntityRecord.source_definition_missing`` names but that nothing in
this codebase has ever actually computed against real configuration
before this module (see ``analysis/analyzers/orphaned_definitions.py``'s
module docstring and ``benchmark/run_validation.py``, which populated
that field from the benchmark's own precomputed answer rather than
deriving it).

Deliberately takes already-read file contents rather than a live
``hass`` object -- ``SourceDefinitionIndex.build`` is a pure function
over already-read text, exactly the shape needed both for real offline
testing (see ``tests/test_source_definition_index.py``) and for the
thin live adapter below. ``async_read_config_source_files`` is that
adapter: written to the same lazy-import, executor-safe pattern
``infrastructure/dependency_source.py`` already uses for other
Store/file reads, and now actually wired into
``infrastructure/ha_source.py``'s ``HomeAssistantOperationalSource``
(``_build_source_definition_index``), which calls it once per capture,
feeds the result into ``SourceDefinitionIndex.build`` unchanged, and
populates ``EntityRecord.source_definition_missing`` from
``SourceDefinitionResult.source_definition_missing`` for every
automation/script/scene entity. This module's own parsing/matching
logic was not changed to do that wiring -- only a caller was added.

Parses each of ``automations.yaml``/``scripts.yaml``/``scenes.yaml``/
every ``packages/*.yaml`` file exactly once per index build (never
per-entity -- ``SourceDefinitionIndex.build`` is called once per scan
and then queried many times via ``lookup``), and maps each parsed
definition's identity onto Home Assistant's own real unique_id
convention (verified directly against a live installation's pulled
``core.entity_registry`` snapshot as part of this task -- see
``benchmark/live_snapshot_*/``, not guessed):

- **automation**: the registry ``unique_id`` is always exactly the
  YAML/package ``id:`` field's string value, whether the automation was
  created via the UI (an epoch-millisecond id) or hand-authored in a
  package (an arbitrary string id) -- confirmed against both cases in
  the live registry snapshot.
- **script**: the registry ``unique_id`` is always exactly the script's
  top-level mapping key (its "object_id") in ``scripts.yaml`` or a
  package's ``script:`` mapping.
- **scene**: only entities whose registry ``platform`` is exactly
  ``"homeassistant"`` are in scope at all -- confirmed against the live
  registry that every other scene platform (``tuya``, ``mqtt``,
  ``lutron_caseta``, ``lutron_caseta_pro`` were the ones actually
  observed) is a cloud/local-integration-managed scene with no local
  YAML definition to look for; asking "is its definition missing from
  scenes.yaml" is a meaningless question for those and must never be
  answered "missing". For the in-scope ``homeassistant``-platform
  scenes, the registry ``unique_id`` is the YAML/package ``id:`` field,
  exactly like automations.

Never claims ``MISSING_CONFIRMED`` when a relevant file failed to
parse: a definition could legitimately live in exactly the file that
failed, so a parse failure anywhere among the domain's config files
degrades every *not-found* answer in that domain to
``SOURCE_UNAVAILABLE`` (a *found* answer is unaffected -- if the
definition was already located in a file that parsed fine, a different
file failing to parse cannot retroactively make it not exist).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml

# Additive capability id for AnalyzerDescriptor/AnalysisPartition wiring,
# alongside orphaned_definitions.py's existing
# "home_assistant.definition_presence@1" -- kept distinct because this
# module's actual coverage (which files parsed, which ids were found)
# is richer than that boolean-signal capability and may be consumed on
# its own (e.g. by the duplicate/migration analyzer in Part 3c).
CAPABILITY_ID = "home_assistant.source_definition_index@1"

COVERED_DOMAINS = ("automation", "script", "scene")
# HA's own scene *editor* persists to scenes.yaml/packages under
# platform "homeassistant" -- every other scene platform is
# integration-managed and out of scope for this index (see module
# docstring).
SCENE_YAML_PLATFORM = "homeassistant"

_TOP_LEVEL_FILES = ("automations.yaml", "scripts.yaml", "scenes.yaml")
_PACKAGE_PREFIX = "packages/"
# HAMIE never fabricates a "reasonable-looking" retry count for a
# runaway/corrupt config tree -- an installation with more package
# files than this is refused outright rather than silently truncated.
MAX_PACKAGE_FILES = 2_000


class SourceDefinitionStatus(StrEnum):
    """Every automation/script/scene lookup lands in exactly one of these."""

    PRESENT = "present"
    MISSING_CONFIRMED = "missing_confirmed"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    SOURCE_UNAVAILABLE = "source_unavailable"


@dataclass(frozen=True, slots=True)
class ConfigSourceFile:
    """One config file's raw text, already read by a caller.

    ``path`` is a stable label, not necessarily a real filesystem path:
    ``"automations.yaml"``, ``"scripts.yaml"``, ``"scenes.yaml"``, or
    ``"packages/<name>.yaml"``. Any other path is silently ignored by
    ``SourceDefinitionIndex.build`` (this index only ever looks at the
    include tree the mission verified live: ``automation:``/``script:``/
    ``scene:``/``packages:``) -- never a reason to fail the whole build.
    """

    path: str
    content: str

    def __post_init__(self) -> None:
        if not self.path or not self.path.strip():
            raise ValueError("path must be non-empty")


@dataclass(frozen=True, slots=True)
class SourceDefinitionResult:
    """One entity's independently-derived source-definition status."""

    entity_id: str
    status: SourceDefinitionStatus
    rationale: str
    defining_files: tuple[str, ...] = ()

    @property
    def source_definition_missing(self) -> bool | None:
        """Project onto ``EntityRecord.source_definition_missing``'s tri-state.

        Only a clean, single-file ``PRESENT``/``MISSING_CONFIRMED``
        answer is ever collapsed to ``False``/``True`` -- every other
        status (ambiguous, unsupported, or genuinely unavailable) stays
        ``None`` ("not evaluated / not confidently known"), matching
        that field's own documented contract: never guess either
        answer.
        """
        if self.status is SourceDefinitionStatus.PRESENT:
            return False
        if self.status is SourceDefinitionStatus.MISSING_CONFIRMED:
            return True
        return None


class _TolerantSafeLoader(yaml.SafeLoader):
    """SafeLoader that never aborts a parse over an unresolved custom tag.

    Home Assistant's own YAML tags (``!secret``, ``!include``,
    ``!include_dir_named``, ...) are not registered with plain
    ``yaml.safe_load`` and would otherwise raise
    ``yaml.constructor.ConstructorError`` for a syntactically valid,
    real production config file. This module never needs a secret's
    resolved value or an included file's content -- only the id/key
    identity fields it already reads from plain scalars/mappings/lists
    -- so every unrecognised ``!tag`` is represented as an inert
    placeholder rather than crashing the whole file's parse.
    """


def _opaque_tag_constructor(
    loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node
) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return f"__hamie_unresolved_tag__:{tag_suffix}"
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return None


_TolerantSafeLoader.add_multi_constructor("!", _opaque_tag_constructor)


def _parse_yaml(content: str) -> Any:
    """Parse one file's content, raising ``yaml.YAMLError`` on real syntax errors."""
    return yaml.load(content, Loader=_TolerantSafeLoader)


def parse_config_yaml(content: str) -> Any | None:
    """Public, never-raising wrapper around ``_parse_yaml`` (mission Part
    2, Analyzer 3): the wrong-domain action-target scanner
    (``domain/action_target_scanner.py``) needs to parse the same
    already-read raw config text a second time, structurally (not just
    substring-search it) -- reusing this module's already-validated
    tolerant loader rather than a second, possibly-drifting parser.
    Returns ``None`` on a real syntax error instead of raising: one
    malformed file must never abort scanning every other file (mirrors
    ``SourceDefinitionIndex.build``'s own per-file degradation).
    """
    try:
        return _parse_yaml(content)
    except yaml.YAMLError:
        return None


def _as_list_of_dicts(node: Any) -> list[dict]:
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    if isinstance(node, dict):
        # A package may define a single automation/scene as one mapping
        # rather than a one-item list -- Home Assistant's own package
        # merge accepts both shapes.
        return [node]
    return []


def _as_dict_of_dicts(node: Any) -> dict[str, dict]:
    if isinstance(node, dict):
        return {
            str(key): value for key, value in node.items() if isinstance(value, dict)
        }
    return {}


@dataclass(frozen=True, slots=True)
class _DomainIndex:
    """Id -> defining file(s), plus which files in this domain failed to parse."""

    ids_to_files: dict[str, tuple[str, ...]]
    failed_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceDefinitionIndex:
    """Built once per scan; queried once per automation/script/scene entity.

    ``raw_files`` (mission Part 2, Analyzers 1/3/5) is additive: a plain
    ``path -> content`` map of every file this build actually considered
    (the same set as ``files_considered``), retained alongside the
    structured automation/script/scene id index above rather than
    discarded after parsing. Structured parsing only ever covers
    automation/script/scene's own ``id:``/mapping-key convention (see
    module docstring); an arbitrary package-defined platform entity
    (``sensor``/``switch``/``template``/... under ``packages/*.yaml``)
    has no equivalent structural index anywhere in this codebase, and
    building a full generic-platform YAML-to-unique_id parser was judged
    out of scope for this pass -- ``raw_files`` is the honest, minimal
    capability that lets a caller run its own bounded text search
    (``domain/duplicate_classifier.py::detect_self_reference_regression``,
    the wrong-domain action-target scanner) without this index silently
    claiming structured coverage it does not have for those domains.
    """

    automation: _DomainIndex
    script: _DomainIndex
    scene: _DomainIndex
    files_considered: tuple[str, ...]
    raw_files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, files: tuple[ConfigSourceFile, ...]) -> SourceDefinitionIndex:
        """Parse the whole config tree exactly once."""
        if len(files) > MAX_PACKAGE_FILES + len(_TOP_LEVEL_FILES):
            raise ValueError(
                f"refusing to parse {len(files)} config files "
                f"(bounded at {MAX_PACKAGE_FILES + len(_TOP_LEVEL_FILES)})"
            )
        automation_ids: dict[str, list[str]] = {}
        automation_failed: list[str] = []
        script_ids: dict[str, list[str]] = {}
        script_failed: list[str] = []
        scene_ids: dict[str, list[str]] = {}
        scene_failed: list[str] = []
        considered: list[str] = []

        for source_file in files:
            is_package = source_file.path.startswith(_PACKAGE_PREFIX)
            is_top_automations = source_file.path == "automations.yaml"
            is_top_scripts = source_file.path == "scripts.yaml"
            is_top_scenes = source_file.path == "scenes.yaml"
            if not (
                is_package or is_top_automations or is_top_scripts or is_top_scenes
            ):
                continue
            considered.append(source_file.path)

            try:
                document = _parse_yaml(source_file.content)
            except yaml.YAMLError:
                if is_package or is_top_automations:
                    automation_failed.append(source_file.path)
                if is_package or is_top_scripts:
                    script_failed.append(source_file.path)
                if is_package or is_top_scenes:
                    scene_failed.append(source_file.path)
                continue

            if is_top_automations:
                automation_entries = _as_list_of_dicts(document)
            elif is_package and isinstance(document, dict) and "automation" in document:
                automation_entries = _as_list_of_dicts(document["automation"])
            else:
                automation_entries = []
            for entry in automation_entries:
                automation_id = entry.get("id")
                if isinstance(automation_id, str | int):
                    automation_ids.setdefault(str(automation_id), []).append(
                        source_file.path
                    )

            if is_top_scripts:
                script_entries = _as_dict_of_dicts(document)
            elif is_package and isinstance(document, dict) and "script" in document:
                script_entries = _as_dict_of_dicts(document["script"])
            else:
                script_entries = {}
            for object_id in script_entries:
                script_ids.setdefault(object_id, []).append(source_file.path)

            if is_top_scenes:
                scene_entries = _as_list_of_dicts(document)
            elif is_package and isinstance(document, dict) and "scene" in document:
                scene_entries = _as_list_of_dicts(document["scene"])
            else:
                scene_entries = []
            for entry in scene_entries:
                scene_id = entry.get("id")
                if isinstance(scene_id, str | int):
                    scene_ids.setdefault(str(scene_id), []).append(source_file.path)

        return cls(
            automation=_DomainIndex(
                ids_to_files={k: tuple(v) for k, v in automation_ids.items()},
                failed_files=tuple(sorted(set(automation_failed))),
            ),
            script=_DomainIndex(
                ids_to_files={k: tuple(v) for k, v in script_ids.items()},
                failed_files=tuple(sorted(set(script_failed))),
            ),
            scene=_DomainIndex(
                ids_to_files={k: tuple(v) for k, v in scene_ids.items()},
                failed_files=tuple(sorted(set(scene_failed))),
            ),
            files_considered=tuple(sorted(set(considered))),
            raw_files={
                source_file.path: source_file.content
                for source_file in files
                if source_file.path in considered
            },
        )

    def lookup(
        self,
        *,
        entity_id: str,
        domain: str,
        platform: str | None,
        unique_id: str | None,
    ) -> SourceDefinitionResult:
        """Independently determine one entity's source-definition status."""
        if domain == "automation":
            domain_index = self.automation
        elif domain == "script":
            domain_index = self.script
        elif domain == "scene":
            if platform != SCENE_YAML_PLATFORM:
                return SourceDefinitionResult(
                    entity_id=entity_id,
                    status=SourceDefinitionStatus.UNSUPPORTED,
                    rationale=(
                        f"scene platform {platform!r} is integration-managed, "
                        "not a scenes.yaml/package/editor scene -- "
                        "source-definition presence does not apply"
                    ),
                )
            domain_index = self.scene
        else:
            return SourceDefinitionResult(
                entity_id=entity_id,
                status=SourceDefinitionStatus.UNSUPPORTED,
                rationale=(
                    f"domain {domain!r} is not covered by the "
                    "source-definition index (only automation/script/scene are)"
                ),
            )

        if not unique_id:
            return SourceDefinitionResult(
                entity_id=entity_id,
                status=SourceDefinitionStatus.SOURCE_UNAVAILABLE,
                rationale=(
                    "entity has no unique_id in the registry snapshot -- "
                    "cannot cross-reference against configuration"
                ),
            )

        matches = domain_index.ids_to_files.get(unique_id, ())
        if len(matches) > 1:
            return SourceDefinitionResult(
                entity_id=entity_id,
                status=SourceDefinitionStatus.AMBIGUOUS,
                rationale=(
                    f"id {unique_id!r} is defined in {len(matches)} separate "
                    f"config files ({', '.join(matches)}) -- cannot pick one "
                    "definitively"
                ),
                defining_files=matches,
            )
        if matches:
            return SourceDefinitionResult(
                entity_id=entity_id,
                status=SourceDefinitionStatus.PRESENT,
                rationale="definition found in the scanned configuration tree",
                defining_files=matches,
            )
        if domain_index.failed_files:
            return SourceDefinitionResult(
                entity_id=entity_id,
                status=SourceDefinitionStatus.SOURCE_UNAVAILABLE,
                rationale=(
                    "no matching definition found among successfully parsed "
                    f"files, but {len(domain_index.failed_files)} file(s) in "
                    "this domain failed to parse and cannot be ruled out: "
                    f"{', '.join(domain_index.failed_files)}"
                ),
            )
        return SourceDefinitionResult(
            entity_id=entity_id,
            status=SourceDefinitionStatus.MISSING_CONFIRMED,
            rationale=(
                "no matching definition found in any successfully parsed "
                "automations.yaml/scripts.yaml/scenes.yaml/packages file"
            ),
        )


async def async_read_config_source_files(hass: Any) -> tuple[ConfigSourceFile, ...]:
    """Read the live config tree's automation/script/scene source files.

    Written to the same lazy-import, executor-offloaded pattern
    ``infrastructure/dependency_source.py`` already uses for other
    Store/file reads (e.g. ``capture_dashboard_references``'s
    ``dashboard.async_load``): every blocking file read is dispatched
    through ``hass.async_add_executor_job``, never called directly on
    the event loop. Called once per capture by
    ``infrastructure/ha_source.py``'s ``HomeAssistantOperationalSource``
    (``_build_source_definition_index``), which hands the result to
    ``SourceDefinitionIndex.build`` (pure, already covered by
    ``tests/test_source_definition_index.py``) and populates
    ``EntityRecord.source_definition_missing`` from
    ``SourceDefinitionResult.source_definition_missing`` above -- see
    that method's docstring for how a read failure here degrades
    honestly (every entity's field stays ``None``) instead of aborting
    the scan.
    """
    import os

    def _read_all() -> tuple[ConfigSourceFile, ...]:
        config_dir = hass.config.path()
        files: list[ConfigSourceFile] = []
        for name in _TOP_LEVEL_FILES:
            full_path = os.path.join(config_dir, name)
            if os.path.isfile(full_path):
                with open(full_path, encoding="utf-8") as handle:
                    files.append(ConfigSourceFile(path=name, content=handle.read()))
        packages_dir = os.path.join(config_dir, "packages")
        if os.path.isdir(packages_dir):
            for entry in sorted(os.listdir(packages_dir))[:MAX_PACKAGE_FILES]:
                if not entry.endswith((".yaml", ".yml")):
                    continue
                full_path = os.path.join(packages_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                with open(full_path, encoding="utf-8") as handle:
                    files.append(
                        ConfigSourceFile(
                            path=f"{_PACKAGE_PREFIX}{entry}", content=handle.read()
                        )
                    )
        return tuple(files)

    return await hass.async_add_executor_job(_read_all)
