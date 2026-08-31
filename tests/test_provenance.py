"""Source-of-truth selection never falls back to timestamps or discovery order."""

from hamie.domain.provenance import (
    ArtifactEvidence,
    ArtifactRole,
    ProvenanceStatus,
    establish_provenance,
)


def _artifact(identifier: str, location: str, role: ArtifactRole, digest: str):
    return ArtifactEvidence(
        artifact_id=identifier,
        location=location,
        role=role,
        content_hash=digest,
        git_head="abc123",
        working_tree_clean=True,
    )


def test_configured_source_wins_over_newer_or_other_worktrees() -> None:
    artifacts = (
        _artifact("configured", "/source/hamie", ArtifactRole.SOURCE, "aaa"),
        _artifact("other", "/newest/hamie", ArtifactRole.WORKTREE, "bbb"),
        _artifact("live", "/config/hamie", ArtifactRole.DEPLOYMENT, "aaa"),
    )
    result = establish_provenance(
        artifacts,
        authoritative_source_repository="/source/hamie",
        deployment_target="/config/hamie",
    )
    assert result.status is ProvenanceStatus.VERIFIED
    assert result.authoritative_source_id == "configured"
    assert result.parity is True


def test_missing_configured_role_blocks_instead_of_substituting() -> None:
    result = establish_provenance(
        (_artifact("other", "/other", ArtifactRole.SOURCE, "aaa"),),
        authoritative_source_repository="/expected",
        deployment_target="/config/hamie",
    )
    assert result.status is ProvenanceStatus.BLOCKED
    assert result.source_backed_change_allowed is False


def test_hash_divergence_is_explicit_not_assumed_parity() -> None:
    result = establish_provenance(
        (
            _artifact("source", "/source", ArtifactRole.SOURCE, "aaa"),
            _artifact("live", "/live", ArtifactRole.DEPLOYMENT, "bbb"),
        ),
        authoritative_source_repository="/source",
        deployment_target="/live",
    )
    assert result.status is ProvenanceStatus.DIVERGED
    assert result.parity is False
