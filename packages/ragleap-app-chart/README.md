# ragleap-app-chart

A generic, reusable Helm chart for deploying arbitrary services to
Kubernetes — built by RagLeap, but not specific to RagLeap.

Unlike `ragleap-ops` (which is hardcoded to RagLeap Core's own 4
services), this chart takes an arbitrary `services:` list in
`values.yaml` and renders resources for each service via range loops.
Point it at your own app; it doesn't know or care what RagLeap is.

<img src="https://mermaid.ink/svg/Zmxvd2NoYXJ0IFRECiAgICBjbGFzc0RlZiBzb3VyY2UgZmlsbDojMWUzYTVmLHN0cm9rZTojNGE5MGQ5LGNvbG9yOiNmZmYKICAgIGNsYXNzRGVmIG1hbmlmZXN0IGZpbGw6IzRkMzMxOSxzdHJva2U6I2Y1OWUwYixjb2xvcjojZmZmCiAgICBjbGFzc0RlZiBjaGFydCBmaWxsOiMzZDI2NDUsc3Ryb2tlOiNhODU1ZjcsY29sb3I6I2ZmZgogICAgY2xhc3NEZWYgY2x1c3RlciBmaWxsOiMxYTRkM2Esc3Ryb2tlOiMyMmM1NWUsY29sb3I6I2ZmZgoKICAgIFZhbHVlc1sidmFsdWVzLnlhbWw8YnIvPmFyYml0cmFyeSBzZXJ2aWNlczogbGlzdDxici8+bm90IGhhcmRjb2RlZCB0byBSYWdMZWFwIl06Ojpzb3VyY2UgLS0+IFJhbmdlWyJIZWxtIHJhbmdlIGxvb3BzPGJyLz5wZXItc2VydmljZSByZW5kZXJpbmciXTo6OmNoYXJ0CgogICAgUmFuZ2UgLS0+IERlcGxveVsiRGVwbG95bWVudCArIFNlcnZpY2U8YnIvPnBlciBzZXJ2aWNlIl06OjptYW5pZmVzdAogICAgUmFuZ2UgLS0+IFBWQ1siUFZDPGJyLz5pZiBwZXJzaXN0ZW50OiB0cnVlIl06OjptYW5pZmVzdAogICAgUmFuZ2UgLS0+IE5ldFBvbFsiTmV0d29ya1BvbGljeTxici8+ZGVueS1ieS1kZWZhdWx0LCBkZXJpdmVkIGZyb20gZGVwZW5kc09uIl06OjptYW5pZmVzdAogICAgUmFuZ2UgLS0+IEluZ3Jlc3NbIkluZ3Jlc3MgKyBUTFM8YnIvPmlmIGV4cG9zZTogdHJ1ZSJdOjo6bWFuaWZlc3QKCiAgICBEZXBsb3kgLS0+IEtpbmRUZXN0WyJMaXZlIGtpbmQgY2x1c3RlciB0ZXN0PGJyLz53ZWIgKyBwb3N0Z3JlcyBleGFtcGxlIl06OjpjbHVzdGVyCiAgICBQVkMgLS0+IEtpbmRUZXN0CiAgICBOZXRQb2wgLS0+IEtpbmRUZXN0CiAgICBJbmdyZXNzIC0tPiBLaW5kVGVzdAoKICAgIEtpbmRUZXN0IC0tPiBWZXJpZnlbInBvc3RncmVzIHJlYWNoZWQgMS8xIFJ1bm5pbmc8YnIvPjAgcmVzdGFydHMsIGRhdGEgdmVyaWZpZWQgcGVyc2lzdGVkPGJyLz50byAvZGF0YS9wZ2RhdGEgdmlhIFNIT1cgZGF0YV9kaXJlY3RvcnkiXTo6OmNsdXN0ZXIK" alt="ragleap-app-chart generic services rendering and verification flow" width="100%">

## Status

v0.2.0 published on PyPI. Generic `services:` schema and range-loop
Helm templates are live-tested end-to-end on a real kind cluster (not
just `helm lint`/`helm template`) -- see CHANGELOG.md for the real
bugs found and fixed via live testing. See
`GENERIC-K8S-CHART-PROPOSAL.md` at the repo root for the full design
rationale.

## Design principles (from the proposal doc)

- Arbitrary service list via `range` loops — not hardcoded names
- Secure-by-default: NetworkPolicy, SecurityContext, and resource
  limits apply automatically unless explicitly overridden
- Proven against a non-RagLeap toy app before calling any feature done
  — genericity is only real once demonstrated against something that
  isn't RagLeap itself

## Worked example (non-RagLeap app)

See `EXAMPLE.md` for a full walkthrough deploying a genuinely
different stack (Redis + a small HTTP service) end-to-end on a real
cluster -- including a real structural bug this chart had (no
command/args override support at all) that was found and fixed while
building it.

## Multi-environment values

`values-dev.yaml`, `values-staging.yaml`, and `values-prod.yaml` are
available, ported from the same pattern proven in `ragleap-ops`:

```bash
helm install my-release ./ragleap-app-chart -f values-dev.yaml
```

**This works differently from `ragleap-ops`'s version.** `ragleap-ops`
overrides simple scalar fields (`app.replicaCount: 3`), which Helm
deep-merges cleanly. This chart's `services:` field is a *list*, and
Helm does not merge list entries by key — an environment file that
redefines `services:` **replaces the entire list**, not just the
fields that differ. Each `values-{env}.yaml` here is therefore a full
override of the example `services:` list, not a partial one. If you
add or change services in your own `values.yaml`, you'll need to keep
your own `values-{env}.yaml` files' `services:` lists in sync manually
— this chart does not (yet) merge list entries automatically.
