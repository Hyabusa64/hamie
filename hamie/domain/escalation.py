"""Escalation packet: what HAMIE hands off when it cannot repair something.

Repair-orchestration Phase 23. HAMIE's deterministic rediscovery already
does most of the work a human (or Claude) would otherwise spend the
first 30 minutes doing by hand -- confirming what's actually stale,
finding candidate successors, checking protected-dependency status.
This module packages that evidence into one secret-sanitized artifact
so a genuine escalation starts from proven facts instead of starting
over.

Pure and I/O-free like every other ``domain/`` module: it takes
already-computed pieces (an incident's public dict, a rediscovery/
investigation result, protected-dependency names, version strings) and
produces a structured, redacted packet. It does not itself query
anything live.
"""

from __future__ import annotations

from dataclasses import dataclass

from .common import redact_secret_looking_text, require_non_empty, require_utc


def _sanitize(text: str) -> str:
    return redact_secret_looking_text(text) or ""


@dataclass(frozen=True, slots=True)
class EscalationPacket:
    """Everything a human (or another AI) needs to pick up where HAMIE stopped."""

    incident_id: str
    disposition: str
    unresolved_question: str
    generated_at: str
    evidence_ids: tuple[str, ...] = ()
    deterministic_facts: tuple[tuple[str, str], ...] = ()
    config_excerpts: tuple[str, ...] = ()
    attempted_classification: str = ""
    ambiguity_reason: str = ""
    protected_dependencies: tuple[str, ...] = ()
    ha_version: str = ""
    hamie_version: str = ""
    hamie_build_commit: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.incident_id, "incident_id")
        require_non_empty(self.disposition, "disposition")
        require_non_empty(self.unresolved_question, "unresolved_question")
        require_non_empty(self.generated_at, "generated_at")

    def as_dict(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "disposition": self.disposition,
            "unresolved_question": self.unresolved_question,
            "generated_at": self.generated_at,
            "evidence_ids": list(self.evidence_ids),
            "deterministic_facts": [list(pair) for pair in self.deterministic_facts],
            "config_excerpts": list(self.config_excerpts),
            "attempted_classification": self.attempted_classification,
            "ambiguity_reason": self.ambiguity_reason,
            "protected_dependencies": list(self.protected_dependencies),
            "environment": {
                "ha_version": self.ha_version,
                "hamie_version": self.hamie_version,
                "hamie_build_commit": self.hamie_build_commit,
            },
        }

    def as_markdown(self) -> str:
        """A ready-to-paste escalation document.

        Never claims more than the packet actually carries: a blank
        section prints "(none recorded)" rather than being silently
        omitted, so a reader can tell "HAMIE found nothing here" apart
        from "this section was forgotten."
        """
        lines = [
            f"# Escalation: {self.incident_id}",
            "",
            f"**Disposition:** {self.disposition}",
            f"**Generated:** {self.generated_at}",
            f"**Home Assistant:** {self.ha_version or '(unknown)'}  "
            f"**HAMIE:** {self.hamie_version or '(unknown)'}"
            + (f" @ {self.hamie_build_commit}" if self.hamie_build_commit else ""),
            "",
            "## The unresolved question",
            "",
            self.unresolved_question,
            "",
            "## What HAMIE already determined deterministically",
            "",
        ]
        if self.deterministic_facts:
            lines.extend(f"- **{key}:** {value}" for key, value in self.deterministic_facts)
        else:
            lines.append("(none recorded)")
        lines.extend(["", "## Attempted classification", ""])
        lines.append(self.attempted_classification or "(none recorded)")
        lines.extend(["", "## Why this needs a human/AI decision", ""])
        lines.append(self.ambiguity_reason or "(none recorded)")
        lines.extend(["", "## Protected dependencies in scope", ""])
        if self.protected_dependencies:
            lines.extend(f"- {name}" for name in self.protected_dependencies)
        else:
            lines.append("(none)")
        lines.extend(["", "## Relevant config excerpts (sanitized)", ""])
        if self.config_excerpts:
            for excerpt in self.config_excerpts:
                lines.extend(["```yaml", excerpt, "```", ""])
        else:
            lines.append("(none recorded)")
        lines.extend(["", "## Evidence ids", ""])
        lines.append(", ".join(self.evidence_ids) if self.evidence_ids else "(none recorded)")
        return "\n".join(lines)


def build_escalation_packet(
    *,
    incident_id: str,
    disposition: str,
    unresolved_question: str,
    generated_at,
    evidence_ids: tuple[str, ...] = (),
    deterministic_facts: tuple[tuple[str, str], ...] = (),
    config_excerpts: tuple[str, ...] = (),
    attempted_classification: str = "",
    ambiguity_reason: str = "",
    protected_dependencies: tuple[str, ...] = (),
    ha_version: str = "",
    hamie_version: str = "",
    hamie_build_commit: str = "",
) -> EscalationPacket:
    """Build a sanitized escalation packet.

    Every free-text field is run through the same secret-looking-text
    redaction the rest of HAMIE uses for diagnostic/log-adjacent text --
    an escalation packet is exactly the kind of artifact someone might
    paste into an external tool or issue tracker, so it gets the same
    treatment as any other outbound diagnostic text, not a lighter one.
    """
    at = require_utc(generated_at, "generated_at")
    return EscalationPacket(
        incident_id=incident_id,
        disposition=disposition,
        unresolved_question=_sanitize(unresolved_question),
        generated_at=at.isoformat(),
        evidence_ids=tuple(evidence_ids),
        deterministic_facts=tuple(
            (str(key), _sanitize(str(value))) for key, value in deterministic_facts
        ),
        config_excerpts=tuple(_sanitize(excerpt) for excerpt in config_excerpts),
        attempted_classification=_sanitize(attempted_classification),
        ambiguity_reason=_sanitize(ambiguity_reason),
        protected_dependencies=tuple(protected_dependencies),
        ha_version=ha_version,
        hamie_version=hamie_version,
        hamie_build_commit=hamie_build_commit,
    )
