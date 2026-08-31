# Examples

HAMIE is configured through Home Assistant's own config-flow UI (Settings →
Devices & Services), not a static YAML file, so there isn't a
`configuration.yaml` snippet to show here. What *is* useful to see worked
through is extending HAMIE's declarative data — the shape CONTRIBUTING.md
points to for a new protected dependency or a new analyzer.

- [`protected_dependency_example.py`](protected_dependency_example.py) —
  a complete, runnable example of registering a custom protected dependency
  chain, using entirely synthetic entity ids and a documentation-range IP
  (see [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737)). This mirrors the
  shape of HAMIE's own shipped default in
  `hamie/domain/protected_dependencies.py`, minus the specifics of any real
  installation.

Run it with:

```bash
python examples/protected_dependency_example.py
```
