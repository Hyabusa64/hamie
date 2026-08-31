"""A protected dependency must protect the THING, not one of its names.

Live incident 2026-08-29T12:31:20Z. The Example Smart Plug X1 strip is integrated
twice -- tplink and matter -- so one physical outlet carries two entity ids:

    outlet 1 (...EXAMPLE00) = switch.example_inference_host_plug            (tplink)
                           = switch.example_inference_host_plug_matter  (matter)

A house-empty sweep had already been taught, on 2026-08-27, to exclude
`switch.example_inference_host_plug`. It still cut AI-PC power -- through the matter
twin, which nobody had connected to the protection. HAMIE's own registry had
the same blind spot: it guarded one id and believed the dependency was safe.
"""

from __future__ import annotations

import pytest

from hamie.domain.protected_dependencies import (
    HAMIE_INFERENCE_DEPENDENCY,
    ProtectionVerdict,
    default_registry,
)

TPLINK_ID = "switch.example_inference_host_plug"
MATTER_ID = "switch.example_inference_host_plug_matter"
#: Outlet 2 on the same strip. Explicitly NOT protected -- the house-empty
#: sweep is supposed to keep turning this one off.
SIBLING_ID = "switch.example_sibling_outlet"


@pytest.mark.parametrize("entity_id", [TPLINK_ID, MATTER_ID])
def test_both_identities_of_the_outlet_are_protected(entity_id: str) -> None:
    assert entity_id in HAMIE_INFERENCE_DEPENDENCY.protected_entities
    assert default_registry().protecting(entity_id)


@pytest.mark.parametrize("entity_id", [TPLINK_ID, MATTER_ID])
def test_turning_either_identity_off_is_refused(entity_id: str) -> None:
    result = default_registry().evaluate(
        entity_ids=(entity_id,),
        action_type="turn_off",
        intent="house empty sweep: power off non-essential plugs",
    )
    assert result.verdict is ProtectionVerdict.BLOCKED


def test_a_sweep_naming_only_the_matter_twin_is_still_refused() -> None:
    # The exact shape of the incident: the sweep never mentions the tplink id.
    result = default_registry().evaluate(
        entity_ids=("switch.office_e_plug", "switch.printer_outlet", MATTER_ID),
        action_type="turn_off",
        intent="tier 60 plugs and fans off",
    )
    assert result.verdict is ProtectionVerdict.BLOCKED


def test_the_unprotected_sibling_outlet_is_still_sweepable() -> None:
    # Over-protecting the whole strip would break legitimate power saving.
    result = default_registry().evaluate(
        entity_ids=("switch.office_e_plug", SIBLING_ID),
        action_type="turn_off",
        intent="tier 60 plugs and fans off",
    )
    assert result.verdict is not ProtectionVerdict.BLOCKED


def test_reading_the_protected_outlet_is_not_blocked() -> None:
    result = default_registry().evaluate(
        entity_ids=(MATTER_ID,), action_type="read_state", intent="scan"
    )
    assert result.verdict is not ProtectionVerdict.BLOCKED


def test_the_chain_records_why_the_matter_id_counts() -> None:
    subjects = {link.subject for link in HAMIE_INFERENCE_DEPENDENCY.chain}
    assert MATTER_ID in subjects, "the alias must carry its own evidence link"


# ------------------------------------------- endpoint model, not device model
#
# The protection unit is the physical ENDPOINT. The Example Smart Plug X1 is one
# Home Assistant device with six independently switched outlets, so protecting
# by device_id would block five unrelated loads; protecting by a single entity
# id is what let the 2026-08-29 sweep through. Both failure modes are pinned.

from hamie.domain.protected_dependencies import (
    AliasAuditClass,
    AliasAuthority,
    AliasEvidence,
    ProtectedEndpoint,
    audit_alias_candidates,
)

STRIP_DEVICE = "685adca92d707a8aed412274f69ecba1"
MATTER_DEVICE = "3d15e4ecea691380fb8b82baa3c9763b"


def _rows():
    return (
        {"entity_id": TPLINK_ID, "unique_id": "TPLINKEXAMPLE00000000000000000000000000001",
         "device_id": STRIP_DEVICE, "platform": "tplink"},
        {"entity_id": "switch.example_office_outlet_2", "unique_id": "…D401",
         "device_id": STRIP_DEVICE, "platform": "tplink"},
        {"entity_id": "switch.example_printer_plug", "unique_id": "…D405",
         "device_id": STRIP_DEVICE, "platform": "tplink"},
        {"entity_id": MATTER_ID,
         "unique_id": "MATTEREXAMPLE001-0000000000000001-MatterNodeDevice-1-MatterPlug-6-0",
         "device_id": MATTER_DEVICE, "platform": "matter"},
        {"entity_id": SIBLING_ID, "unique_id": "…MatterNodeDevice-2-MatterPlug-6-0",
         "device_id": MATTER_DEVICE, "platform": "matter"},
    )


def test_both_aliases_resolve_to_one_endpoint() -> None:
    a = HAMIE_INFERENCE_DEPENDENCY.endpoint_for(TPLINK_ID)
    b = HAMIE_INFERENCE_DEPENDENCY.endpoint_for(MATTER_ID)
    assert a is not None and b is not None
    assert a.endpoint_id == b.endpoint_id


def test_sibling_outlets_belong_to_no_protected_endpoint() -> None:
    for entity_id in (SIBLING_ID, "switch.example_office_outlet_2",
                      "switch.example_printer_plug"):
        assert HAMIE_INFERENCE_DEPENDENCY.endpoint_for(entity_id) is None


def test_endpoint_aliases_are_unioned_into_the_authorization_surface() -> None:
    # Adding an alias must be impossible to forget at the authorization call.
    endpoint = HAMIE_INFERENCE_DEPENDENCY.endpoints[0]
    assert endpoint.entity_aliases <= HAMIE_INFERENCE_DEPENDENCY.protected_entities


def test_an_endpoint_cannot_rest_only_on_observed_synchronisation() -> None:
    # Two outlets switched by one sweep also move together.
    with pytest.raises(ValueError):
        ProtectedEndpoint(
            endpoint_id="guess", description="inferred from movement",
            alias_evidence=(
                AliasEvidence(entity_id="switch.a", integration="x", unique_id="1",
                              authority=AliasAuthority.OBSERVED, rationale="moved together"),
            ),
        )


def test_audit_confirms_live_aliases_and_never_promotes_siblings() -> None:
    findings = audit_alias_candidates(HAMIE_INFERENCE_DEPENDENCY, _rows())
    confirmed = {f.entity_id for f in findings if f.audit_class is AliasAuditClass.CONFIRMED}
    siblings = {f.entity_id for f in findings if f.audit_class is AliasAuditClass.SIBLING_NOT_ALIAS}
    assert confirmed == {TPLINK_ID, MATTER_ID}
    assert SIBLING_ID in siblings and "switch.example_printer_plug" in siblings
    # A sibling is reported for context, never added to the protected set.
    assert not siblings & HAMIE_INFERENCE_DEPENDENCY.protected_entities


def test_audit_flags_a_renamed_or_missing_alias_as_stale() -> None:
    rows = tuple(r for r in _rows() if r["entity_id"] != MATTER_ID)
    findings = audit_alias_candidates(HAMIE_INFERENCE_DEPENDENCY, rows)
    stale = [f for f in findings if f.audit_class is AliasAuditClass.STALE]
    assert [f.entity_id for f in stale] == [MATTER_ID]


def test_audit_flags_a_changed_unique_id_as_stale() -> None:
    rows = tuple(
        {**r, "unique_id": "CHANGED"} if r["entity_id"] == TPLINK_ID else r
        for r in _rows()
    )
    findings = audit_alias_candidates(HAMIE_INFERENCE_DEPENDENCY, rows)
    stale = {f.entity_id for f in findings if f.audit_class is AliasAuditClass.STALE}
    assert TPLINK_ID in stale
