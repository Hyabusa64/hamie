"""Controlled remediation tools: the deterministic layer the model cannot cross.

The model may *request* an operation. Nothing here trusts what it says about
that operation. Every gate below re-derives the facts itself:

  * targets come from parsing the actual configuration, not from the model's
    ``affected_objects`` field. A proposal described as "update an automation"
    that in fact adds ``switch.turn_off`` on a protected plug is detected as
    what it does, not as what it is called. This is the exact defect the live
    AI-PC test exposed;
  * risk is classified from the operation type, never from a model field;
  * the authorization policy is a table, not a negotiation;
  * ambiguous targets refuse rather than guess -- three entities in this
    installation contain "printer" and are different physical devices;
  * dry-run and execution are the SAME code path with one flag, so a preview
    cannot drift from what later runs.

Encodes the repair methodology used successfully on this installation:
hash-verified timestamped backup, structural (not textual) understanding of
what is being changed, HA config validation before reload, targeted reload in
preference to restart, post-change verification, and automatic rollback with
re-validation when verification fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..domain.protected_dependencies import (
    ProtectedDependencyRegistry,
    ProtectionEvaluation,
    ProtectionVerdict,
    default_registry,
)


class ToolRisk(StrEnum):
    """Risk class of an operation. Derived from the operation, never claimed."""

    READ_ONLY = "read_only"
    SAFE_REVERSIBLE = "safe_reversible"
    CONFIG_MUTATION = "config_mutation"
    RESTART_REQUIRED = "restart_required"
    PHYSICAL_STATE_CHANGE = "physical_state_change"
    SECURITY_CRITICAL = "security_critical"
    DESTRUCTIVE = "destructive"


class AuthorizationDecision(StrEnum):
    AUTOMATIC = "automatic"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"


#: The policy table. Deliberately a constant: the LLM has no route to alter it.
AUTHORIZATION_POLICY: dict[ToolRisk, AuthorizationDecision] = {
    ToolRisk.READ_ONLY: AuthorizationDecision.AUTOMATIC,
    ToolRisk.SAFE_REVERSIBLE: AuthorizationDecision.AUTOMATIC,
    ToolRisk.CONFIG_MUTATION: AuthorizationDecision.REQUIRES_APPROVAL,
    ToolRisk.RESTART_REQUIRED: AuthorizationDecision.REQUIRES_APPROVAL,
    ToolRisk.PHYSICAL_STATE_CHANGE: AuthorizationDecision.BLOCKED,
    ToolRisk.SECURITY_CRITICAL: AuthorizationDecision.BLOCKED,
    ToolRisk.DESTRUCTIVE: AuthorizationDecision.BLOCKED,
}

#: SAFE_REVERSIBLE only runs unattended with real deterministic backing.
MINIMUM_AUTOMATIC_CONFIDENCE = 0.9

#: Domains whose entities are physical/safety control surfaces. Configuration
#: remediation never needs to command these, so a mutation that would is
#: reclassified upward rather than argued about.
SECURITY_DOMAINS = frozenset({"lock", "alarm_control_panel", "siren"})
PHYSICAL_DOMAINS = frozenset(
    {"switch", "light", "cover", "climate", "fan", "vacuum", "water_heater", "valve"}
)

#: Service calls capable of removing power/availability from their target.
OFF_CAPABLE_SERVICES = frozenset(
    {
        "turn_off",
        "toggle",
        "homeassistant.turn_off",
        "switch.turn_off",
        "light.turn_off",
        "cover.close_cover",
        "lock.unlock",
        "alarm_control_panel.alarm_disarm",
        "vacuum.stop",
        "climate.turn_off",
        "valve.close_valve",
    }
)

_ENTITY_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")
_BACKUP_STAMP_RE = re.compile(r"\d{8}T\d{6}Z")


class RemediationRefused(Exception):
    """Raised when deterministic policy forbids an operation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PathPolicy:
    """Explicit allowlist. Traversal is rejected on the resolved path."""

    allowed_roots: tuple[str, ...] = ("/config",)
    denied_names: tuple[str, ...] = ("secrets.yaml", ".storage", ".ssh", ".git")

    def check(self, path: str) -> str:
        import os

        resolved = os.path.realpath(path)
        if not any(
            resolved == root or resolved.startswith(root.rstrip("/") + "/")
            for root in self.allowed_roots
        ):
            raise RemediationRefused(
                "path_outside_allowlist", f"{resolved} is outside the allowed roots"
            )
        for denied in self.denied_names:
            if denied in resolved.split("/"):
                raise RemediationRefused(
                    "path_denied", f"{resolved} touches a protected path segment"
                )
        if not resolved.endswith((".yaml", ".yml")):
            raise RemediationRefused(
                "unsupported_file_type",
                "only YAML configuration may be mutated by these tools",
            )
        return resolved


# ---------------------------------------------------------------------------
# Effect analysis -- what a change ACTUALLY does
# ---------------------------------------------------------------------------


def extract_off_targets(config_text: str) -> frozenset[str]:
    """Entity ids that this configuration can turn off / disable.

    Deliberately structural-ish and conservative: it walks service/action
    blocks and collects entity ids that appear under an off-capable call.
    Used to judge a mutation by its effect rather than its description.
    """
    targets: set[str] = set()
    lines = config_text.splitlines()
    armed = False
    arm_indent = 0
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        m = re.match(r"-?\s*(?:action|service):\s*([\w.]+)", stripped)
        if m:
            call = m.group(1)
            tail = call.split(".")[-1]
            armed = call in OFF_CAPABLE_SERVICES or tail in OFF_CAPABLE_SERVICES
            arm_indent = indent
            continue
        if armed:
            # leaving the block
            if indent <= arm_indent and re.match(r"-?\s*(?:action|service):", stripped):
                armed = False
                continue
            if indent <= arm_indent and stripped.startswith("- ") and ":" in stripped:
                armed = False
            for dom, obj in _ENTITY_RE.findall(stripped):
                if dom in PHYSICAL_DOMAINS | SECURITY_DOMAINS:
                    targets.add(f"{dom}.{obj}")
    return frozenset(targets)


def classify_risk(
    operation: str, *, added_off_targets: frozenset[str] = frozenset()
) -> ToolRisk:
    """Risk from the operation itself plus its measured effects."""
    for entity in added_off_targets:
        domain = entity.split(".", 1)[0]
        if domain in SECURITY_DOMAINS:
            return ToolRisk.SECURITY_CRITICAL
    if added_off_targets:
        return ToolRisk.PHYSICAL_STATE_CHANGE
    return {
        "read_config": ToolRisk.READ_ONLY,
        "search_config": ToolRisk.READ_ONLY,
        "resolve_entity": ToolRisk.READ_ONLY,
        "reverse_references": ToolRisk.READ_ONLY,
        "check_config": ToolRisk.READ_ONLY,
        "replace_entity_reference": ToolRisk.CONFIG_MUTATION,
        "update_automation": ToolRisk.CONFIG_MUTATION,
        "reload_domain": ToolRisk.SAFE_REVERSIBLE,
        "restart_core": ToolRisk.RESTART_REQUIRED,
        "call_service": ToolRisk.PHYSICAL_STATE_CHANGE,
        "delete_entity": ToolRisk.DESTRUCTIVE,
        "delete_file": ToolRisk.DESTRUCTIVE,
        "remove_config_entry": ToolRisk.DESTRUCTIVE,
    }.get(operation, ToolRisk.DESTRUCTIVE)  # unknown operations are never safe


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    risk: ToolRisk
    reason: str
    protection: dict[str, Any] = field(default_factory=dict)

    @property
    def permitted(self) -> bool:
        return self.decision is not AuthorizationDecision.BLOCKED

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "risk": self.risk.value,
            "reason": self.reason,
            "protection": self.protection,
        }


def authorize(
    *,
    operation: str,
    targets: tuple[str, ...],
    added_off_targets: frozenset[str] = frozenset(),
    confidence: float = 0.0,
    evidence_ids: tuple[str, ...] = (),
    approved_by: str | None = None,
    registry: ProtectedDependencyRegistry | None = None,
    intent: str = "",
) -> AuthorizationResult:
    """The single deterministic gate. No model field can reach past it."""
    reg = registry if registry is not None else default_registry()
    risk = classify_risk(operation, added_off_targets=added_off_targets)

    # Protected chains are evaluated against measured effects AND stated
    # targets -- whichever is broader.
    considered = tuple(set(targets) | set(added_off_targets))
    protection: ProtectionEvaluation = reg.evaluate(
        entity_ids=considered,
        action_type="turn_off" if added_off_targets else operation,
        intent=intent,
    )
    if protection.verdict is ProtectionVerdict.BLOCKED:
        return AuthorizationResult(
            AuthorizationDecision.BLOCKED,
            risk,
            protection.reason,
            protection.as_dict(),
        )

    policy = AUTHORIZATION_POLICY[risk]
    if policy is AuthorizationDecision.BLOCKED:
        return AuthorizationResult(
            AuthorizationDecision.BLOCKED,
            risk,
            f"{risk.value} operations are blocked by policy",
            protection.as_dict(),
        )

    if policy is AuthorizationDecision.AUTOMATIC and risk is ToolRisk.SAFE_REVERSIBLE:
        if confidence < MINIMUM_AUTOMATIC_CONFIDENCE or not evidence_ids:
            return AuthorizationResult(
                AuthorizationDecision.REQUIRES_APPROVAL,
                risk,
                "insufficient deterministic backing for unattended execution",
                protection.as_dict(),
            )

    if policy is AuthorizationDecision.REQUIRES_APPROVAL and approved_by:
        return AuthorizationResult(
            AuthorizationDecision.AUTOMATIC,
            risk,
            f"explicitly approved by {approved_by}",
            protection.as_dict(),
        )

    return AuthorizationResult(
        policy, risk, f"policy for {risk.value}", protection.as_dict()
    )


# ---------------------------------------------------------------------------
# Entity resolution -- refuse ambiguity rather than guess
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    entity_id: str
    unique_id: str | None = None
    platform: str | None = None
    device_id: str | None = None
    exists: bool = True


def resolve_unique_entity(
    query: str, candidates: tuple[EntityCandidate, ...]
) -> EntityCandidate:
    """Exactly one match, or refuse.

    Three entities here contain 'printer' and are different physical devices;
    guessing between them would be a plausible-looking way to break a house.
    """
    exact = [c for c in candidates if c.entity_id == query]
    if len(exact) == 1:
        return exact[0]
    if not candidates:
        raise RemediationRefused("entity_not_found", f"no entity matches {query!r}")
    if len(candidates) > 1:
        raise RemediationRefused(
            "ambiguous_entity",
            f"{query!r} matches {len(candidates)} entities "
            f"({', '.join(sorted(c.entity_id for c in candidates))}); "
            "deterministic evidence cannot identify one",
        )
    return candidates[0]


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RemediationTransaction:
    transaction_id: str
    created_at: str
    request: str
    operation: str
    root_cause: str = ""
    evidence_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    affected_objects: tuple[str, ...] = ()
    source_files: tuple[str, ...] = ()
    measured_off_targets: tuple[str, ...] = ()
    authorization: dict[str, Any] = field(default_factory=dict)
    pre_hash: str | None = None
    post_hash: str | None = None
    backup_path: str | None = None
    diff: str = ""
    validation: list[dict[str, Any]] = field(default_factory=list)
    executed: bool = False
    rolled_back: bool = False
    outcome: str = "proposed"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "created_at": self.created_at,
            "request": self.request,
            "operation": self.operation,
            "root_cause": self.root_cause,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "affected_objects": list(self.affected_objects),
            "source_files": list(self.source_files),
            "measured_off_targets": list(self.measured_off_targets),
            "authorization": self.authorization,
            "pre_hash": self.pre_hash,
            "post_hash": self.post_hash,
            "backup_path": self.backup_path,
            "diff": self.diff,
            "validation": self.validation,
            "executed": self.executed,
            "rolled_back": self.rolled_back,
            "outcome": self.outcome,
            "error": self.error,
        }


@dataclass(slots=True)
class LocationChange:
    """One file's part in a multi-location repair, and the proof it worked.

    Every boolean here is set from a read-back hash comparison, never from
    "the call did not raise".
    """

    path: str
    occurrences: int = 0
    pre_hash: str = ""
    post_hash: str = ""
    backup_path: str | None = None
    backup_verified: bool = False
    written: bool = False
    write_verified: bool = False
    restored: bool | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "occurrences": self.occurrences,
            "pre_hash": self.pre_hash,
            "post_hash": self.post_hash,
            "backup_path": self.backup_path,
            "backup_verified": self.backup_verified,
            "written": self.written,
            "write_verified": self.write_verified,
            "restored": self.restored,
            "error": self.error,
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return "HAMIE-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")[:-3]


# ---------------------------------------------------------------------------
# Gateways (injected, so tests never touch a real filesystem or HA)
# ---------------------------------------------------------------------------


class FileGateway:
    """Narrow filesystem surface. No model input reaches os.* directly.

    These methods are deliberately synchronous and must never be awaited
    directly from Home Assistant's event loop -- RemediationExecutor calls
    them through asyncio.to_thread(). Home Assistant detects and warns about
    blocking I/O in the loop, and a stalled loop is a house-wide problem.
    """

    def __init__(self, policy: PathPolicy | None = None) -> None:
        self.policy = policy or PathPolicy()

    def read(self, path: str) -> str:
        with open(self.policy.check(path), encoding="utf-8") as fh:
            return fh.read()

    def write(self, path: str, content: str) -> None:
        with open(self.policy.check(path), "w", encoding="utf-8") as fh:
            fh.write(content)

    def backup(self, path: str, stamp: str) -> str:
        real = self.policy.check(path)
        target = f"{real}.hamie_bak_{stamp}"
        with open(real, encoding="utf-8") as src, open(
            target, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        return target

    def _checked_backup(self, path: str, backup_path: str) -> str:
        """Resolve a backup path that must belong to exactly this file.

        A backup name ends in ``.hamie_bak_<stamp>`` and therefore fails
        PathPolicy's YAML suffix rule on purpose -- backups are not
        configuration and must not be reachable through the ordinary
        read/write surface. This is the only door, and it opens only for
        a backup of the very file being restored.
        """
        real = self.policy.check(path)
        expected_prefix = f"{real}.hamie_bak_"
        if not backup_path.startswith(expected_prefix) or not _BACKUP_STAMP_RE.fullmatch(
            backup_path[len(expected_prefix) :]
        ):
            raise RemediationRefused(
                "invalid_backup_path",
                "a backup may only be read back for the exact file it backs up",
            )
        return real

    def read_backup(self, path: str, backup_path: str) -> str:
        """Read a backup's bytes so its integrity can be proven before use."""
        self._checked_backup(path, backup_path)
        with open(backup_path, encoding="utf-8") as fh:
            return fh.read()

    def restore(self, path: str, backup_path: str) -> str:
        """Restore one file from its own verified backup; returns the content."""
        real = self._checked_backup(path, backup_path)
        with open(backup_path, encoding="utf-8") as src:
            content = src.read()
        with open(real, "w", encoding="utf-8") as dst:
            dst.write(content)
        return content


@dataclass(frozen=True, slots=True)
class HaGateway:
    """Injected HA operations. Each is a narrow, named capability.

    The four original capabilities stay required and positional so every
    existing construction keeps working unchanged. The three added below
    default to ``None``: a deployment that cannot supply one degrades to
    recorded "capability unavailable" evidence, which pushes a repair
    towards INCONCLUSIVE. An absent capability must never be allowed to
    look like a passed check.
    """

    check_config: Callable[[], Awaitable[dict[str, Any]]]
    reload_domain: Callable[[str], Awaitable[bool]]
    entity_state: Callable[[str], Awaitable[str | None]]
    recent_errors: Callable[[], Awaitable[int]]
    #: Stable signatures of currently-recorded ERROR log entries. Counting
    #: errors cannot tell a pre-existing error from one this repair caused;
    #: set difference can.
    error_signatures: Callable[[], Awaitable[tuple[str, ...]]] | None = None
    #: domain -> {state: count}. Used to detect availability regressions
    #: without ever treating a global count drop as proof of success.
    domain_state_counts: Callable[[str], Awaitable[dict[str, int]]] | None = None
    #: config file paths -> the automation/script entity ids those files
    #: actually define. This is the affected scope regression checks
    #: correlate against, derived from configuration, never guessed.
    config_scope_entities: (
        Callable[[tuple[str, ...]], Awaitable[tuple[str, ...]]] | None
    ) = None


# ---------------------------------------------------------------------------
# The executor: dry-run and execute are one path
# ---------------------------------------------------------------------------


class RemediationExecutor:
    """Backup -> mutate -> validate -> verify -> rollback-on-failure."""

    def __init__(
        self,
        files: FileGateway,
        ha: HaGateway,
        *,
        registry: ProtectedDependencyRegistry | None = None,
    ) -> None:
        self._files = files
        self._ha = ha
        self._registry = registry if registry is not None else default_registry()

    async def async_replace_entity_reference(
        self,
        *,
        request: str,
        path: str,
        old_entity: str,
        new_entity: str,
        root_cause: str = "",
        evidence_ids: tuple[str, ...] = (),
        confidence: float = 0.0,
        dry_run: bool = True,
        approved_by: str | None = None,
        reload_domain: str | None = None,
    ) -> RemediationTransaction:
        """Replace one stale entity reference in one YAML file."""
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        txn = RemediationTransaction(
            transaction_id=_new_id(),
            created_at=datetime.now(UTC).isoformat(),
            request=request,
            operation="replace_entity_reference",
            root_cause=root_cause,
            evidence_ids=evidence_ids,
            confidence=confidence,
            affected_objects=(old_entity, new_entity),
            source_files=(path,),
        )
        try:
            before = await asyncio.to_thread(self._files.read, path)
        except RemediationRefused as err:
            txn.outcome, txn.error = "refused", f"{err.code}: {err.message}"
            return txn

        occurrences = before.count(old_entity)
        if occurrences == 0:
            txn.outcome = "no_action_needed"
            txn.error = f"{old_entity} not present in {path}"
            return txn

        after = before.replace(old_entity, new_entity)
        txn.pre_hash, txn.post_hash = _sha256(before), _sha256(after)
        txn.diff = f"{occurrences} occurrence(s): {old_entity} -> {new_entity}"

        # EFFECT-AWARE: judge the resulting config, not the description.
        added = extract_off_targets(after) - extract_off_targets(before)
        txn.measured_off_targets = tuple(sorted(added))

        auth = authorize(
            operation="replace_entity_reference",
            targets=(old_entity, new_entity),
            added_off_targets=added,
            confidence=confidence,
            evidence_ids=evidence_ids,
            approved_by=approved_by,
            registry=self._registry,
            intent=request,
        )
        txn.authorization = auth.as_dict()

        if not auth.permitted:
            txn.outcome = "blocked"
            txn.error = auth.reason
            return txn
        if auth.decision is AuthorizationDecision.REQUIRES_APPROVAL and not dry_run:
            txn.outcome = "awaiting_approval"
            txn.error = auth.reason
            return txn
        if dry_run:
            txn.outcome = "dry_run"
            return txn

        # ---- execute -------------------------------------------------------
        txn.backup_path = await asyncio.to_thread(self._files.backup, path, stamp)
        await asyncio.to_thread(self._files.write, path, after)
        txn.executed = True

        ok, failures = await self._async_validate(txn, reload_domain, new_entity)
        if ok:
            txn.outcome = "success"
            return txn

        # ---- rollback ------------------------------------------------------
        await asyncio.to_thread(self._files.write, path, before)
        txn.rolled_back = True
        restored = _sha256(await asyncio.to_thread(self._files.read, path)) == txn.pre_hash
        txn.validation.append(
            {"check": "rollback_restored_original", "passed": restored}
        )
        if reload_domain:
            await self._ha.reload_domain(reload_domain)
        revalidate = await self._ha.check_config()
        txn.validation.append(
            {"check": "post_rollback_config_valid",
             "passed": revalidate.get("result") == "valid"}
        )
        txn.outcome = "rolled_back"
        txn.error = "; ".join(failures)
        return txn

    async def _async_validate(
        self, txn: RemediationTransaction, reload_domain: str | None, expect_entity: str
    ) -> tuple[bool, list[str]]:
        failures: list[str] = []

        cfg = await self._ha.check_config()
        passed = cfg.get("result") == "valid"
        txn.validation.append(
            {"check": "ha_config_valid", "passed": passed, "detail": cfg.get("errors")}
        )
        if not passed:
            failures.append("HA configuration validation failed")
            return False, failures

        if reload_domain:
            reloaded = await self._ha.reload_domain(reload_domain)
            txn.validation.append(
                {"check": f"reload_{reload_domain}", "passed": bool(reloaded)}
            )
            if not reloaded:
                failures.append(f"{reload_domain} reload failed")

        state = await self._ha.entity_state(expect_entity)
        available = state not in (None, "unavailable")
        txn.validation.append(
            {"check": "replacement_entity_available", "passed": available,
             "detail": state}
        )
        if not available:
            failures.append(f"{expect_entity} is not available after change")

        errors = await self._ha.recent_errors()
        clean = errors == 0
        txn.validation.append(
            {"check": "no_new_errors", "passed": clean, "detail": errors}
        )
        if not clean:
            failures.append(f"{errors} new error(s) after change")

        return not failures, failures

    # ------------------------------------------------------------------
    # Multi-location primitives.
    #
    # One stale reference can live in ten files at once -- the live repair
    # candidate this was built for spans 27 occurrences across 10 real
    # package files. Applying that as ten independent single-file
    # transactions would leave a partially-repaired configuration on the
    # first failure, which is a worse state than either endpoint. So the
    # steps are exposed separately (plan / backup / apply / restore) and
    # sequenced transactionally by application/remediation_lifecycle.py:
    # back every file up first, mutate only then, and restore all of them
    # together if anything fails.
    #
    # These are primitives, not a second execution path: the same
    # PathPolicy, the same authorize() table, the same effect analysis and
    # the same validation routine as the single-file method above.
    # ------------------------------------------------------------------

    async def async_plan_locations(
        self, paths: tuple[str, ...], old_entity: str, new_entity: str
    ) -> tuple[tuple[LocationChange, ...], frozenset[str]]:
        """Read-only. Per-file occurrence counts, hashes and measured effect."""
        changes: list[LocationChange] = []
        added: set[str] = set()
        for path in sorted(set(paths)):
            change = LocationChange(path=path)
            try:
                before = await asyncio.to_thread(self._files.read, path)
            except (RemediationRefused, OSError) as err:
                change.error = getattr(err, "code", "unreadable")
                changes.append(change)
                continue
            after = before.replace(old_entity, new_entity)
            change.occurrences = before.count(old_entity)
            change.pre_hash = _sha256(before)
            change.post_hash = _sha256(after)
            added |= extract_off_targets(after) - extract_off_targets(before)
            changes.append(change)
        return tuple(changes), frozenset(added)

    async def async_backup_locations(
        self, changes: tuple[LocationChange, ...], stamp: str
    ) -> bool:
        """Create and PROVE a backup for every file before anything mutates.

        Verification is a read-back and hash comparison, not the absence of
        an exception: a backup that exists but does not match the file it
        claims to preserve is worse than no backup, because it would be
        trusted during rollback.
        """
        all_ok = True
        for change in changes:
            try:
                change.backup_path = await asyncio.to_thread(
                    self._files.backup, change.path, stamp
                )
                content = await asyncio.to_thread(
                    self._files.read_backup, change.path, change.backup_path
                )
                change.backup_verified = _sha256(content) == change.pre_hash
                if not change.backup_verified:
                    change.error = "backup_content_mismatch"
            except (RemediationRefused, OSError) as err:
                change.backup_verified = False
                change.error = getattr(err, "code", None) or str(err)[:200]
            all_ok = all_ok and change.backup_verified
        return all_ok

    async def async_apply_locations(
        self,
        changes: tuple[LocationChange, ...],
        old_entity: str,
        new_entity: str,
        *,
        added_off_targets: frozenset[str] = frozenset(),
        approved_by: str | None,
        request: str = "",
        confidence: float = 0.0,
        evidence_ids: tuple[str, ...] = (),
    ) -> bool:
        """Mutate every planned file, proving each write landed as planned.

        Re-authorizes here rather than trusting the caller: this is the last
        point before bytes change, so the gate lives here too. No approver,
        no write.
        """
        auth = authorize(
            operation="replace_entity_reference",
            targets=(old_entity, new_entity),
            added_off_targets=added_off_targets,
            confidence=confidence,
            evidence_ids=evidence_ids,
            approved_by=approved_by,
            registry=self._registry,
            intent=request,
        )
        if not auth.permitted or auth.decision is AuthorizationDecision.REQUIRES_APPROVAL:
            raise RemediationRefused(
                "not_authorized_for_execution",
                auth.reason or "execution requires explicit approval",
            )
        if not all(change.backup_verified for change in changes):
            raise RemediationRefused(
                "unverified_backup",
                "every affected file needs a proven backup before mutation",
            )
        applied = True
        for change in changes:
            try:
                before = await asyncio.to_thread(self._files.read, change.path)
                after = before.replace(old_entity, new_entity)
                await asyncio.to_thread(self._files.write, change.path, after)
                change.written = True
                readback = await asyncio.to_thread(self._files.read, change.path)
                change.write_verified = _sha256(readback) == change.post_hash
                if not change.write_verified:
                    change.error = "post_write_hash_mismatch"
            except (RemediationRefused, OSError) as err:
                change.write_verified = False
                change.error = getattr(err, "code", None) or str(err)[:200]
            applied = applied and change.write_verified
        return applied

    async def async_restore_locations(
        self, changes: tuple[LocationChange, ...]
    ) -> bool:
        """Restore every touched file and PROVE each one is back.

        A restore call that returns without raising proves nothing. Every
        file is read back and hashed against its pre-mutation digest, and a
        file whose backup never verified is reported unrestorable rather
        than quietly skipped.
        """
        all_restored = True
        for change in changes:
            if not change.written:
                change.restored = None
                continue
            if not change.backup_path or not change.backup_verified:
                change.restored = False
                change.error = "no_verified_backup_to_restore_from"
                all_restored = False
                continue
            try:
                await asyncio.to_thread(
                    self._files.restore, change.path, change.backup_path
                )
                readback = await asyncio.to_thread(self._files.read, change.path)
                change.restored = _sha256(readback) == change.pre_hash
                if not change.restored:
                    change.error = "restored_content_hash_mismatch"
            except (RemediationRefused, OSError) as err:
                change.restored = False
                change.error = getattr(err, "code", None) or str(err)[:200]
            all_restored = all_restored and bool(change.restored)
        return all_restored

    async def async_check_config(self) -> dict[str, Any]:
        """Expose the injected configuration check without widening HaGateway."""
        return await self._ha.check_config()

    async def async_reload_domain(self, domain: str) -> bool:
        return await self._ha.reload_domain(domain)

    async def async_entity_state(self, entity_id: str) -> str | None:
        return await self._ha.entity_state(entity_id)

    @property
    def ha(self) -> HaGateway:
        """The injected capabilities, for callers that compose them."""
        return self._ha

    @property
    def registry(self) -> ProtectedDependencyRegistry:
        return self._registry
