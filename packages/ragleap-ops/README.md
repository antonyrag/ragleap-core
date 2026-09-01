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

## Secrets management for production (Sealed Secrets)

The kubectl create secret --from-env-file pattern above is fine for local
testing, but it leaves real credentials sitting as plaintext files and shell
history. For production, use Sealed Secrets instead (https://github.com/bitnami-labs/sealed-secrets) --
secrets get encrypted against your specific cluster's public key, so the
encrypted result is safe to commit to git. No other cluster can decrypt it.

One-time setup (per cluster):

```bash
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.39.1/controller.yaml
```

Sealing a secret (works offline once you have exported your cluster's public
cert -- no live cluster connection needed at seal-time, safe to run in CI):

```bash
kubeseal --controller-name sealed-secrets-controller \
  --controller-namespace kube-system --fetch-cert > sealed-secrets-pub-cert.pem

kubectl create secret generic ragleap-db-secret \
  --dry-run=client \
  --from-literal=POSTGRES_USER=ragleap \
  --from-literal=POSTGRES_PASSWORD=your-real-password \
  --from-literal=POSTGRES_DB=ragleap_core \
  -o yaml | kubeseal --format yaml --cert sealed-secrets-pub-cert.pem > db-secret-sealed.yaml

kubectl apply -f db-secret-sealed.yaml
```

Important: a sealed secret is tied to the exact cluster whose public key
encrypted it. A SealedSecret sealed for one cluster will not decrypt on a
different cluster -- never copy a sealed file between environments; reseal
against each target cluster's own cert instead.

## Status

Both the raw manifests (v0.1.0) and the Helm chart (v0.2.0, `helm/ragleap-ops/`) are live-verified end-to-end on a real kind cluster — see CHANGELOG.md for the specific bugs found and fixed.

## NetworkPolicies (restricting pod-to-pod traffic)

Both k8s/ and helm/ragleap-ops/ include NetworkPolicy resources restricting
which pods can reach ragleap-db (port 5432, from ragleap-app and
ragleap-voice only) and ragleap-neo4j (ports 7474/7687, from ragleap-app
only -- ragleap-voice does not use neo4j in the current codebase).

Important: kind's default CNI (kindnet) does not enforce NetworkPolicy at
all -- policies will apply without error but traffic will not actually be
blocked. Testing NetworkPolicy enforcement requires a CNI that supports it,
such as Calico:

```bash
kind create cluster --config kind-calico-config.yaml   # disableDefaultCNI: true
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/tigera-operator.yaml
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/custom-resources.yaml
```

Verification performed: the enforcement mechanism itself was live-tested end
to end on a real kind + Calico cluster (a labeled pod was correctly blocked
from an unlabeled target, then allowed once correctly labeled -- confirmed
via real timeout/success exit codes, not assumed). The real ragleap-db/
ragleap-neo4j label selectors were verified to match the actual Deployment
labels used elsewhere in this chart. A full live run of the complete
ragleap stack under Calico was not completed in this session due to
genuine memory constraints on the test VPS (which also runs unrelated
production services) -- Calico's own baseline overhead left too little
headroom for a 4-service stack reliably. This is an honest scope
boundary, not a claim that the policies were fully integration-tested
against the live application.
