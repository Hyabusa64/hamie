#!/usr/bin/env python3
"""Worked example: registering a custom protected dependency.

Run from the repository root: python examples/protected_dependency_example.py

Every id below is synthetic. `switch.example_nas_plug` and
`192.0.2.20` describe no real device — 192.0.2.0/24 is reserved for
documentation by RFC 5737, the same convention this repository's own
sanitized fixtures and tests use.

The scenario: a household NAS hosts the Home Assistant recorder database.
An automation that (helpfully) powers down "unused" network gear during a
house-empty sweep must never be allowed to take the NAS down, because that
would break Home Assistant's own history/logbook. This mirrors the shape of
HAMIE's own shipped default in hamie/domain/protected_dependencies.py
(where the protected resource is HAMIE's own local AI inference host)
without any of that installation's specifics.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hamie.domain.protected_dependencies import (
    AliasAuthority,
    AliasEvidence,
    DependencyLink,
    ProtectedDependency,
    ProtectedDependencyRegistry,
    ProtectedEndpoint,
    ProtectionSeverity,
    ProtectionVerdict,
    default_registry,
)

NAS_DEPENDENCY = ProtectedDependency(
    id="recorder-database-depends-on-nas",
    name="Home Assistant's recorder database depends on the NAS",
    severity=ProtectionSeverity.CRITICAL,
    endpoints=(
        ProtectedEndpoint(
            endpoint_id="example-nas:power-outlet",
            description="Smart outlet powering the NAS running the recorder database",
            alias_evidence=(
                AliasEvidence(
                    entity_id="switch.example_nas_plug",
                    integration="example_smart_plug",
                    unique_id="EXAMPLE0000000000000000000000000000000001",
                    authority=AliasAuthority.REGISTRY_PROVEN,
                    rationale="The only entity id this outlet is registered under.",
                ),
            ),
        ),
    ),
    rule=(
        "No automatic action may power off, delete, or disable "
        "switch.example_nas_plug. Doing so would take down the machine "
        "hosting Home Assistant's recorder database."
    ),
    chain=(
        DependencyLink(
            subject="switch.example_nas_plug",
            provides="mains power to the NAS",
            rationale="The NAS has no battery; losing power halts it immediately.",
            evidence=("entity_registry:switch.example_nas_plug",),
        ),
        DependencyLink(
            subject="the NAS",
            provides="the Home Assistant recorder database, hosted on it",
            rationale="Recorder is configured to write to a database on this host.",
            evidence=("configuration.yaml:recorder.db_url",),
        ),
    ),
)


def main() -> None:
    # Start from HAMIE's own shipped defaults and add this one.
    registry: ProtectedDependencyRegistry = default_registry().register(NAS_DEPENDENCY)

    # A "turn everything off" sweep that would sever the chain is blocked...
    result = registry.evaluate(
        entity_ids=("switch.example_nas_plug",),
        action_type="turn_off",
        intent="house empty sweep: power off unused network gear",
    )
    assert result.verdict is ProtectionVerdict.BLOCKED
    print("severing action:", result.verdict, "-", result.reason)

    # ...but merely reading its state is not blocked. It still comes back
    # as REQUIRES_APPROVAL rather than a bare ALLOWED: touching protected
    # infrastructure is always surfaced, even when it isn't severing it.
    result = registry.evaluate(
        entity_ids=("switch.example_nas_plug",),
        action_type="read_state",
    )
    assert result.verdict is not ProtectionVerdict.BLOCKED
    print("read-only action:", result.verdict, "-", result.reason)


if __name__ == "__main__":
    main()
