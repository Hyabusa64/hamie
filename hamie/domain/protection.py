"""Protected-domain/keyword classification (mission Part 4).

No prior keyword/domain protection list existed anywhere in this
codebase before this module (checked ``duplicate_classifier.py``,
``unavailable_entities.py``, ``orphaned_definitions.py``,
``domain/security.py`` -- none of them classify a *subject* as
safety/security-sensitive; ``domain/security.py`` only evaluates HAMIE's
own connector configuration, a different question entirely). This is
net-new, single-source-of-truth infrastructure every analyzer that needs
"is this subject too safety-sensitive for an unattended-strength
recommendation" should import from here rather than growing its own
keyword list.

Pure and I/O-free, like every other ``domain/`` module. Deliberately
conservative in both directions: a false negative (missing a protected
subject) is worse than a false positive (an ordinary subject
occasionally over-flagged as sensitive) for anything that gates
``RemediationSafetyGate.SAFE_TO_REMOVE_REGISTRY`` -- see
``domain/findings.py``.
"""

from __future__ import annotations

from .findings import RemediationSafetyGate

# Domains where nearly every entity is safety/security load-bearing
# regardless of naming.
PROTECTED_DOMAINS = frozenset(
    {
        "alarm_control_panel",
        "lock",
        "siren",
    }
)

# device_class values (cross-domain: binary_sensor/sensor/cover/switch
# all reuse the same device_class vocabulary for their real-world
# meaning) that mark a subject safety-relevant independent of its
# domain.
PROTECTED_DEVICE_CLASSES = frozenset(
    {
        "smoke",
        "co",
        "carbon_monoxide",
        "gas",
        "moisture",  # leak sensors
        "safety",
        "lock",
        "door",
        "garage_door",
        "window",
        "opening",
        "battery_charging",  # UPS/critical-power charge-state sensors
    }
)

# Substrings checked against entity_id/friendly_name/unique_id/source
# file name -- domain alone cannot catch a security-relevant `cover`
# (garage) vs an ordinary one (a blind), or an exterior security light
# that is just a `light.*`/`switch.*` entity with no distinguishing
# device_class. Deliberately generous (over-inclusive) rather than
# narrow: see module docstring on false-negative vs false-positive cost
# asymmetry. Matches this session's real naming evidence
# (``automation.house_empty_*``, ``backyard_loitering``) plus the
# broader categories Part 4 names.
PROTECTED_KEYWORDS = frozenset(
    {
        "garage",
        "security",
        "alarm",
        "intrusion",
        "loitering",
        "house_empty",
        "away_mode",
        "perimeter",
        "exterior",
        "outdoor_light",
        "porch_light",
        "flood_light",
        "motion_light",
        "camera",
        "doorbell",
        "leak",
        "shutoff",
        "shut_off",
        "valve",
        "water_main",
        "furnace",
        "hvac_protect",
        "freeze_protect",
        "freeze_warning",
        "ups",
        "battery_backup",
        "critical_power",
        "smoke",
        "co_detector",
        "gas_leak",
        "evacuation",
    }
)

PROTECTED_DOMAIN_HINT_DOMAINS = frozenset({"cover", "light", "switch", "binary_sensor", "sensor"})


def _normalize(text: str | None) -> str:
    return (text or "").strip().casefold()


def is_protected_subject(
    *,
    entity_id: str,
    domain: str | None = None,
    device_class: str | None = None,
    friendly_name: str | None = None,
    unique_id: str | None = None,
    source_file: str | None = None,
) -> bool:
    """Return whether a subject is safety/security-sensitive enough to
    cap any recommendation at ``RemediationSafetyGate.PROTECTED`` /
    ``RECOMMEND_REVIEW`` -- never ``SAFE_TO_REMOVE_REGISTRY`` (see
    ``domain/findings.py``'s ``RemediationSafetyGate`` and
    ``cap_safety_gate_for_protection`` below).

    Domain alone gates ``PROTECTED_DOMAINS``. ``device_class`` alone
    gates ``PROTECTED_DEVICE_CLASSES``. Everything else (entity_id,
    friendly_name, unique_id, the source file name it is defined in)
    is checked for a substring match against ``PROTECTED_KEYWORDS`` --
    deliberately keyword-based since domain/device_class alone cannot
    catch "this `cover` is a garage door" or "this plain `light` is
    exterior security lighting" (mission Part 4).
    """
    resolved_domain = domain or entity_id.partition(".")[0]
    if resolved_domain in PROTECTED_DOMAINS:
        return True
    if _normalize(device_class) in PROTECTED_DEVICE_CLASSES:
        return True
    haystacks = (
        _normalize(entity_id),
        _normalize(friendly_name),
        _normalize(unique_id),
        _normalize(source_file),
    )
    return any(
        keyword in haystack for haystack in haystacks for keyword in PROTECTED_KEYWORDS if haystack
    )


def cap_safety_gate_for_protection(
    otherwise: RemediationSafetyGate, *, protected: bool
) -> RemediationSafetyGate:
    """Return ``PROTECTED`` when ``protected``, else ``otherwise`` unchanged.

    The single centralizing enforcement point ``domain/findings.py``'s
    ``RemediationSafetyGate`` docstring and this module's own
    ``is_protected_subject`` docstring already named, but which did not
    previously exist as code -- every protection-aware analyzer
    (``wrong_domain_action.py``, ``functional_self_reference.py``,
    ``automation_migration_residue.py``, ``removed_integration_orphan.py``,
    ``abandoned_bugfix_fork.py``) independently inlined the identical
    ``RemediationSafetyGate.PROTECTED if protected else <gate>``
    conditional at its own call site instead. Behavior is unchanged by
    centralizing it here -- this is a pure refactor removing five
    duplicated copies of the same one-line rule, not a policy change.
    """
    return RemediationSafetyGate.PROTECTED if protected else otherwise
