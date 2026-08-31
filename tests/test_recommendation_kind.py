"""Backward-compatibility guard for the extended RecommendationKind (mission Part 2/5).

The extension must be strictly additive: every pre-existing member and
its exact string value must survive unchanged, since already-persisted
``Finding``/``Recommendation`` records serialize this value to disk
(``domain/serialization.py``).
"""

from __future__ import annotations

from hamie.domain.findings import RecommendationKind

_ORIGINAL_VALUES = {
    "REPAIR": "repair",
    "RETAIN": "retain",
    "DISABLE": "disable",
    "MONITOR": "monitor",
    "NEEDS_EVIDENCE": "needs_evidence",
    "REVIEW_CONFIGURATION": "review_configuration",
}

_NEW_MEMBERS = {
    "KEEP",
    "INVESTIGATE",
    "REVIEW_DUPLICATE",
    "DISABLE_CANDIDATE",
    "DELETE_CANDIDATE",
    "NO_ACTION",
}


def test_original_members_and_values_unchanged() -> None:
    for name, value in _ORIGINAL_VALUES.items():
        member = getattr(RecommendationKind, name)
        assert member.value == value


def test_new_members_exist_with_expected_values() -> None:
    assert RecommendationKind.KEEP.value == "keep"
    assert RecommendationKind.INVESTIGATE.value == "investigate"
    assert RecommendationKind.REVIEW_DUPLICATE.value == "review_duplicate"
    assert RecommendationKind.DISABLE_CANDIDATE.value == "disable_candidate"
    assert RecommendationKind.DELETE_CANDIDATE.value == "delete_candidate"
    assert RecommendationKind.NO_ACTION.value == "no_action"


def test_no_member_was_removed() -> None:
    names = {member.name for member in RecommendationKind}
    assert names == set(_ORIGINAL_VALUES) | _NEW_MEMBERS


def test_every_value_is_unique() -> None:
    values = [member.value for member in RecommendationKind]
    assert len(values) == len(set(values))
