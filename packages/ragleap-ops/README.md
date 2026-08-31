# ragleap-ops

Kubernetes deployment manifests for RagLeap Core.

Ships Deployment + Service manifests for all four `docker-compose.yml`
services (`db`, `app`, `voice`, `neo4j`), translated from the real
compose file and live-tested end-to-end on a `kind` cluster — all four
pods reached `1/1 Running` with zero restarts after a probe-timing bug
was found and fixed via live testing.

<img src="https://mermaid.ink/svg/Zmxvd2NoYXJ0IFRECiAgICBjbGFzc0RlZiBzb3VyY2UgZmlsbDojMWUzYTVmLHN0cm9rZTojNGE5MGQ5LGNvbG9yOiNmZmYKICAgIGNsYXNzRGVmIG1hbmlmZXN0IGZpbGw6IzRkMzMxOSxzdHJva2U6I2Y1OWUwYixjb2xvcjojZmZmCiAgICBjbGFzc0RlZiBjaGFydCBmaWxsOiMzZDI2NDUsc3Ryb2tlOiNhODU1ZjcsY29sb3I6I2ZmZgogICAgY2xhc3NEZWYgY2x1c3RlciBmaWxsOiMxYTRkM2Esc3Ryb2tlOiMyMmM1NWUsY29sb3I6I2ZmZgoKICAgIENvbXBvc2VbImRvY2tlci1jb21wb3NlLnltbDxici8+cmVhbCBkYi9hcHAvdm9pY2UvbmVvNGogc2VydmljZXMiXTo6OnNvdXJjZSAtLT4gVHJhbnNsYXRlWyJGaWVsZC1ieS1maWVsZCB0cmFuc2xhdGlvbjxici8+bm8gaW52ZW50ZWQgdmFsdWVzIl06Ojpzb3VyY2UKCiAgICBUcmFuc2xhdGUgLS0+IE1hbmlmZXN0c1siazhzLyByYXcgbWFuaWZlc3RzPGJyLz5EZXBsb3ltZW50ICsgU2VydmljZSArIFBWQyArIFNlY3JldCJdOjo6bWFuaWZlc3QKICAgIFRyYW5zbGF0ZSAtLT4gQ2hhcnRbImhlbG0vcmFnbGVhcC1vcHMvIGNoYXJ0PGJyLz5jb25maWd1cmFibGUgdmFsdWVzLnlhbWwiXTo6OmNoYXJ0CgogICAgTWFuaWZlc3RzIC0tPiBPcmRlclsiQXBwbHkgb3JkZXI8YnIvPlNlY3JldHMvQ29uZmlnTWFwIOKGkiBQVkNzIOKGkiBkYiDihpIgYXBwL3ZvaWNlL25lbzRqIl06OjptYW5pZmVzdAogICAgQ2hhcnQgLS0+IEhlbG1JbnN0YWxsWyJoZWxtIGluc3RhbGwgLyBoZWxtIHVwZ3JhZGUiXTo6OmNoYXJ0CgogICAgT3JkZXIgLS0+IEtpbmRUZXN0WyJMaXZlIGtpbmQgY2x1c3RlciB0ZXN0Il06OjpjbHVzdGVyCiAgICBIZWxtSW5zdGFsbCAtLT4gS2luZFRlc3QKCiAgICBLaW5kVGVzdCAtLT4gVmVyaWZ5WyJBbGwgNCBwb2RzIDEvMSBSdW5uaW5nPGJyLz4wIHJlc3RhcnRzLCByZWFsIGJ1Z3MgZm91bmQgJiBmaXhlZCJdOjo6Y2x1c3Rlcgo=" alt="ragleap-ops translation and verification flow" width="100%">

## Contents

- `k8s/` — raw Deployment, Service, PVC, Secret, and ConfigMap manifests
- Apply order: Secrets/ConfigMap → PVCs → `db` → everything else
  (`app`/`voice` depend on `db` via an init container that polls
  `pg_isready`)

## Regenerating local-only files

Two files are intentionally **not** committed (see `.gitignore`) since
they'd otherwise bake real secret values into git history:

```bash
kubectl create secret generic ragleap-app-env \
  --from-env-file=$HOME/ragleap-core/.env \
  --dry-run=client -o yaml > k8s/app-env-secret.yaml
```

## Status

Both the raw manifests (v0.1.0) and the Helm chart (v0.2.0, `helm/ragleap-ops/`) are live-verified end-to-end on a real kind cluster — see CHANGELOG.md for the specific bugs found and fixed.
