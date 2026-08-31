"""Deterministic source/deployment provenance contracts.

The domain layer never walks a filesystem or chooses a repository by mtime.
Adapters may supply bounded observations, but this module only accepts an
authoritative source that exactly matches explicit configuration and reports
why evidence is complete or blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import require_non_empty, stable_digest


class ArtifactRole(StrEnum):
    SOURCE = "source"
    WORKTREE = "worktree"
    STAGING = "staging"
    DEPLOYMENT = "deployment"
    BACKUP = "backup"
    UNKNOWN = "unknown"


class ProvenanceStatus(StrEnum):
    VERIFIED = "verified"
    DIVERGED = "diverged"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    """One caller-observed repository or deployment artifact."""

    artifact_id: str
    location: str
    role: ArtifactRole
    content_hash: str
    git_head: str | None = None
    git_tree: str | None = None
    working_tree_clean: bool | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.location, "location"),
            (self.content_hash, "content_hash"),
        ):
            require_non_empty(value, name)
        if self.git_head is not None:
            require_non_empty(self.git_head, "git_head")
        if self.git_tree is not None:
            require_non_empty(self.git_tree, "git_tree")


@dataclass(frozen=True, slots=True)
class ProvenanceDecision:
    """Explicit source-of-truth conclusion used by remediation preflight."""

    status: ProvenanceStatus
    authoritative_source_id: str | None
    deployment_id: str | None
    source_hash: str | None
    deployment_hash: str | None
    parity: bool | None
    rationale: str
    evidence_digest: str

    @property
    def source_backed_change_allowed(self) -> bool:
        """Return whether provenance is strong enough to plan, not execute."""
        return self.status in {ProvenanceStatus.VERIFIED, ProvenanceStatus.DIVERGED}

    def public_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "authoritative_source_id": self.authoritative_source_id,
            "deployment_id": self.deployment_id,
            "source_hash": self.source_hash,
            "deployment_hash": self.deployment_hash,
            "parity": self.parity,
            "rationale": self.rationale,
            "evidence_digest": self.evidence_digest,
            "source_backed_change_allowed": self.source_backed_change_allowed,
        }


def establish_provenance(
    artifacts: tuple[ArtifactEvidence, ...],
    *,
    authoritative_source_repository: str,
    deployment_target: str,
) -> ProvenanceDecision:
    """Select only explicitly configured roles and compare content hashes."""
    configured_source = authoritative_source_repository.strip()
    configured_deployment = deployment_target.strip()
    digest = stable_digest(
        tuple(
            sorted(
                (
                    item.artifact_id,
                    item.location,
                    item.role.value,
                    item.content_hash,
                    item.git_head or "",
                    item.git_tree or "",
                    item.working_tree_clean,
                )
                for item in artifacts
            )
        )
    )
    if not configured_source or not configured_deployment:
        return ProvenanceDecision(
            status=ProvenanceStatus.BLOCKED,
            authoritative_source_id=None,
            deployment_id=None,
            source_hash=None,
            deployment_hash=None,
            parity=None,
            rationale="Authoritative source repository and deployment target must both be configured.",
            evidence_digest=digest,
        )
    source = next(
        (
            item
            for item in artifacts
            if item.location == configured_source and item.role is ArtifactRole.SOURCE
        ),
        None,
    )
    deployment = next(
        (
            item
            for item in artifacts
            if item.location == configured_deployment
            and item.role is ArtifactRole.DEPLOYMENT
        ),
        None,
    )
    if source is None or deployment is None:
        return ProvenanceDecision(
            status=ProvenanceStatus.BLOCKED,
            authoritative_source_id=source.artifact_id if source else None,
            deployment_id=deployment.artifact_id if deployment else None,
            source_hash=source.content_hash if source else None,
            deployment_hash=deployment.content_hash if deployment else None,
            parity=None,
            rationale="Configured source/deployment roles were not both observed; no filesystem candidate was substituted.",
            evidence_digest=digest,
        )
    parity = source.content_hash == deployment.content_hash
    return ProvenanceDecision(
        status=ProvenanceStatus.VERIFIED if parity else ProvenanceStatus.DIVERGED,
        authoritative_source_id=source.artifact_id,
        deployment_id=deployment.artifact_id,
        source_hash=source.content_hash,
        deployment_hash=deployment.content_hash,
        parity=parity,
        rationale=(
            "Configured authoritative source and deployment hashes match."
            if parity
            else "Configured source and deployment are proven but their content hashes differ."
        ),
        evidence_digest=digest,
    )
