## What does this change, and why?

<!-- Link the issue it addresses, if any. -->

## Checklist

- [ ] Tests added or updated for this change
- [ ] `python -m pytest` passes locally
- [ ] `python tools/secret_scan.py --all` passes — no real credentials,
      entity ids, hostnames, or IPs from an actual Home Assistant instance
      anywhere in this diff (see [SECURITY.md](../SECURITY.md))
- [ ] If this touches `hamie/domain/investigation.py`,
      `hamie/domain/protection.py`, `hamie/domain/protected_dependencies.py`,
      or the remediation lifecycle: I've described the safety-boundary
      impact below
- [ ] If this changes a public API, config-flow behavior, or the
      incident/finding schema: I've noted backward-compatibility impact
      below
- [ ] Docs updated if behavior visible to users or contributors changed

## Safety-boundary impact (if applicable)

<!-- Does this change what an AI provider can see or do? Does it add,
     remove, or alter a protected-dependency chain or a remediation
     capability? -->

## Backward compatibility (if applicable)
