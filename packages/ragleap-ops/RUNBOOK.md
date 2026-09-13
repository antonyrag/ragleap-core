# ragleap-ops — Incident Runbook

Operational playbooks for the 4 minimum incident scenarios flagged in
the DevOps maturity plan: db-down, neo4j-crash-loop,
backup-failure-detected, ingress-cert-expired.

**Status: written from real config in this repo, not yet independently
live-tested against a deliberately broken cluster.** Every command
below references real resource names verified against the actual
manifests (see file paths cited in each section) -- but "the runbook
reads correctly" and "the runbook works when someone is stressed at
3am" are different claims. Treat this as a strong first draft, not a
drilled-and-proven procedure. A live incident drill (deliberately
breaking each scenario on a test cluster and following these exact
steps) is the natural next step before trusting this fully -- same
discipline as everything else in this repo.

---

## 1. db-down

**Symptom:** `ragleap-app`/`ragleap-voice` failing to connect, or
`kubectl get pods -n ragleap-core` shows `ragleap-db` not `Running`.

### Triage

```bash
kubectl get pods -n ragleap-core -l app=ragleap-db
kubectl describe pod -n ragleap-core -l app=ragleap-db
kubectl logs -n ragleap-core -l app=ragleap-db --tail=100
```

Check `Events` in the describe output first -- most failures show up
there before you need full logs.

### Common causes (from real testing this session)

- **`CrashLoopBackOff` with `Liveness probe failed: command "pg_isready -U ragleap" timed out`**
  -- seen this session after a laptop/Docker Desktop sleep interruption
  caused sustained resource starvation. Not a data problem. Fix:
```bash
  kubectl delete pod -n ragleap-core -l app=ragleap-db
```
  Kubernetes will recreate it via the Deployment. Confirm the underlying
  host (VM, laptop, node) isn't itself under resource pressure before
  assuming this is a code/config issue.

- **`chmod: Operation not permitted` in early startup logs** -- this is
  expected, non-fatal noise from `readOnlyRootFilesystem`, not the
  actual failure. If the pod reaches `Running` afterward, this line is
  not the incident.

- **`FATAL: database "ragleap" does not exist` repeating in logs** --
  also expected noise: the liveness probe's `pg_isready -U ragleap`
  checks for a database matching the *username*, not the real
  configured database (`ragleap_core`). Harmless as long as
  `pg_isready` itself reports `accepting connections`.

- **Init container stuck (`Init:CreateContainerConfigError`)** -- check
  `securityContext`. Confirmed live-tested bug pattern this session:
  `runAsNonRoot: true` without a matching `runAsUser` fails outright
  against root-default images. Confirm the real UID before assuming a
  fix: `docker run --rm <image> id <user>` -- never guess.

### If genuinely down (not just restarting)

1. Check the PVC is bound: `kubectl get pvc -n ragleap-core ragleap-db-data`
2. If the PVC itself is the problem (rare, but possible on `kind` or
   dev clusters), see the restore procedure in the Backup/DR section
   of the root README -- this is the last resort, not step one.

---

## 2. neo4j-crash-loop

**Symptom:** `ragleap-neo4j` pod in `CrashLoopBackOff` or repeatedly
restarting.

### Triage

```bash
kubectl get pods -n ragleap-core -l app=ragleap-neo4j
kubectl logs -n ragleap-core -l app=ragleap-neo4j --tail=100
kubectl describe pod -n ragleap-core -l app=ragleap-neo4j
```

### Common causes

- **Slow startup being mistaken for a crash.** Neo4j is genuinely
  slower to start than Postgres -- this session it took roughly 90
  seconds to reach `1/1 Running` on a real kind cluster. Check the
  `readinessProbe`/`livenessProbe` `initialDelaySeconds` in
  `k8s/neo4j-deployment.yaml` before assuming a real failure; a
  too-aggressive probe timeout on a slow node will kill a
  genuinely-still-starting pod.

- **Permission errors on `/data`.** The `fix-permissions` init
  container (`chown -R 7474:7474 /data`) must complete successfully
  first. Check its logs specifically:
```bash
  kubectl logs -n ragleap-core -l app=ragleap-neo4j -c fix-permissions
```

- **If `readOnlyRootFilesystem` is ever enabled on this service in the
  future:** this repo's own testing found Neo4j's entrypoint rewrites
  `/var/lib/neo4j/conf` on every startup. If that flag gets enabled
  without first confirming `/var/lib/neo4j/conf` is writable, this is
  the first thing to suspect -- see CHANGELOG.md's "Known limitations"
  for the exact unresolved question.

### If genuinely down (not just restarting)

Same PVC-check-first principle as db-down. See the root README's
Backup/DR section for the neo4j restore procedure
(`neo4j-admin database load`) if data-level recovery is needed --
confirmed via real live testing to be cleaner than the Postgres
restore path (zero errors on load, vs. expected-but-harmless
`already exists` noise for Postgres).

---

## 3. backup-failure-detected

**Symptom:** A scheduled backup CronJob run failed, or hasn't produced
a new file when expected.

### Triage

```bash
kubectl get cronjob -n ragleap-core ragleap-db-backup ragleap-neo4j-backup
kubectl get jobs -n ragleap-core -l job-name
kubectl logs -n ragleap-core -l job-name=<failed-job-name>
```

Both backup CronJobs run daily at `0 3 * * *` UTC
(`k8s/db-backup-cronjob.yaml`, `k8s/neo4j-backup-cronjob.yaml`).

### Postgres backup (`ragleap-db-backup`)

- Straightforward `pg_dump` to a PVC-backed file
  (`/backups/db-<timestamp>.sql`). Failure usually means either the
  `ragleap-db-secret` credentials are wrong/rotated, or the
  `ragleap-backup-data` PVC is full or unbound.
- Check disk space first:
```bash
  kubectl exec -n ragleap-core -it deploy/ragleap-db -- df -h /backups 2>/dev/null || \
  kubectl run -n ragleap-core debug-pvc --rm -it --image=busybox --overrides='{"spec":{"containers":[{"name":"debug-pvc","image":"busybox","command":["df","-h","/backups"],"volumeMounts":[{"name":"b","mountPath":"/backups"}]}],"volumes":[{"name":"b","persistentVolumeClaim":{"claimName":"ragleap-backup-data"}}]}}'
```

### Neo4j backup (`ragleap-neo4j-backup`)

More involved -- this job **scales `ragleap-neo4j` to 0 replicas
first** (via a dedicated `ragleap-neo4j-backup` ServiceAccount/Role),
takes the dump, and does not automatically scale it back up (the job
only scales down; nothing in this CronJob restores replicas). **If a
neo4j backup job fails partway through, this is now handled
automatically -- see below -- but it's still worth knowing how to
check manually:**

```bash
kubectl get deployment -n ragleap-core ragleap-neo4j
# if REPLICAS shows 0/0 unexpectedly:
kubectl scale deployment -n ragleap-core ragleap-neo4j --replicas=1
```

**Fixed, live-tested on a real kind cluster (both success and failure
paths):** the CronJob now includes a `scale-up-watcher` native sidecar
container (`restartPolicy: Always`) that is only terminated after the
`dump` container finishes, success or failure. `dump` uses
`trap 'touch /signal/backup-done' EXIT` to always signal completion;
the sidecar waits for that signal, then scales `ragleap-neo4j` back to
1. Verified live: a deliberately-broken dump (nonexistent database
name) correctly reported the Job as `Failed`, while `ragleap-neo4j`
was still confirmed `1/1 Running` afterward -- the manual recovery
command above should now only be needed if the sidecar itself is
somehow prevented from running (e.g. the whole pod being forcibly
deleted), not for an ordinary dump failure.

### General backup verification

Don't just trust "the CronJob succeeded" -- per this repo's own
discipline, verify the actual file:

```bash
kubectl exec -n ragleap-core -it deploy/ragleap-db -- ls -la /backups/  # if db pod still has the mount
```

or run a debug pod against the `ragleap-backup-data` PVC directly if
the primary pods aren't available.

---

## 4. ingress-cert-expired

**Symptom:** TLS errors on the real hostname, or
`kubectl get certificate -n ragleap-core ragleap-app-tls` shows
`Ready: False`.

### Triage

```bash
kubectl get certificate -n ragleap-core ragleap-app-tls
kubectl describe certificate -n ragleap-core ragleap-app-tls
kubectl get certificaterequest -n ragleap-core
kubectl describe clusterissuer <your-configured-clusterIssuer-name>
```

The Certificate resource name (`ragleap-app-tls`) and Secret name
(`ragleap-app-tls-secret`) are fixed in
`helm/ragleap-ops/templates/ingress.yaml` -- not configurable via
`values.yaml`, only the hostname and issuer name are.

### Common causes

- **`ClusterIssuer` itself is broken** (rate-limited by Let's Encrypt,
  misconfigured DNS-01/HTTP-01 solver, expired issuer credentials).
  Check `kubectl describe clusterissuer` for real error messages before
  assuming the Certificate resource itself is at fault.
- **DNS not actually pointing at the Ingress controller.** cert-manager
  cannot complete an HTTP-01 challenge if the hostname doesn't resolve
  to the real ingress IP. Verify with `dig`/`nslookup` against the real
  hostname in `values.yaml`'s `ingress.hostname`.
- **Automatic renewal didn't fire in time.** cert-manager renews
  ~30 days before expiry by default; if a Certificate is close to
  expiring with no recent `CertificateRequest`, something is blocking
  the renewal attempt itself, not just the cert.

### Manual force-renewal (last resort)

```bash
kubectl delete secret -n ragleap-core ragleap-app-tls-secret
kubectl delete certificate -n ragleap-core ragleap-app-tls
kubectl apply -f - <<EOF
# Re-apply via helm upgrade instead of hand-editing -- ensures the
# Certificate resource matches the real values.yaml, not a stale copy
EOF
helm upgrade ragleap-ops ./helm/ragleap-ops -f <your-values-file>
```

Deleting the Secret and Certificate forces cert-manager to request a
fresh certificate on the next reconcile. This is disruptive (brief TLS
outage while the new cert issues) -- only use if the automatic renewal
path is confirmed broken, not as a routine fix.

---

## Standing principle for all four scenarios

Per this repo's own operating discipline: don't assume a fix worked
because a command completed without error. Confirm the actual
end state -- pod `Running` with 0 new restarts, backup file genuinely
present and non-empty, certificate `Ready: True`, real connectivity
confirmed -- the same way every fix in this repo's CHANGELOGs has been
independently re-verified after being applied, not just trusted.
