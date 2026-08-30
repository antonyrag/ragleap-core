# ragleap-ops

Kubernetes deployment manifests for RagLeap Core.

Ships Deployment + Service manifests for all four `docker-compose.yml`
services (`db`, `app`, `voice`, `neo4j`), translated from the real
compose file and live-tested end-to-end on a `kind` cluster — all four
pods reached `1/1 Running` with zero restarts after a probe-timing bug
was found and fixed via live testing.

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

Raw manifests are live-verified. A Helm chart wrapping these is not
yet built.
