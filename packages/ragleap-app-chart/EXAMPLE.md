# Worked example: a non-RagLeap app

This walks through deploying a genuinely different stack -- not
RagLeap Core -- to prove this chart is actually generic, not just
RagLeap-in-disguise. Same design proposal requirement the default
example (`web` + `postgres`) already satisfies; this is a second,
deliberately different proof point.

**Fully live-tested end-to-end against a real kind cluster** (Docker
Desktop, Windows) -- both pods reached `Running`, and functionality
was independently verified (real HTTP response, real Redis
`SET`/`GET` roundtrip, real confirmation data persists to the mounted
volume), not just `helm template` output.

## The scenario

A tiny two-service stack:

- **`api`** -- a small HTTP service (`hashicorp/http-echo`),
  stateless, 2 replicas
- **`cache`** -- Redis (`redis:7-alpine`), persistent, 1 replica

Chosen deliberately to be a *different* case than the default `web` +
`postgres` example already shipped with this chart:

| | `postgres` (default example) | `redis` (this example) |
|---|---|---|
| Default image user | root | non-root (`redis`, uid 999) -- but only when started via its real entrypoint, not when overridden |
| Default data directory | `/var/lib/postgresql/data` -- needs an explicit `PGDATA` override to match this chart's hardcoded `/data` mount | `/data` -- already matches, **zero mount-path override needed** |
| `initChown` needed? | Yes | Yes (for the UID, not the mount path) |

The `api` service adds a third proof point: a stateless service using
`args` (not `env`) to configure itself -- see "A real bug we found"
below for why this distinction matters.

## The values file

```yaml
services:
  - name: api
    image: hashicorp/http-echo
    port: 5678
    replicaCount: 2
    persistent: false
    dependsOn:
      - cache
    expose: false
    args:
      - "-text=hello from ragleap-app-chart"

  - name: cache
    image: redis:7-alpine
    port: 6379
    replicaCount: 1
    persistent: true
    storage: 1Gi
    dependsOn: []
    expose: false
    securityContext:
      runAsNonRoot: true
      runAsUser: 999
      allowPrivilegeEscalation: false
    initChown: true
```

Full file: `values-example.yaml` in this directory.

## Deploy it

```bash
helm install my-example ./ragleap-app-chart -f values-example.yaml --namespace my-example --create-namespace
kubectl get pods -n my-example
```

Both pods should reach `1/1 Running` within about 30-45 seconds.

## A real bug we found while building this example

The first version of this example used `env: [{name: HTTP_ECHO_TEXT, value: "hello from ragleap-app-chart"}]`
instead of `args`. It deployed successfully -- `helm lint`, `helm
template`, and the live pod all looked completely correct. But
curling the actual service returned `hello-world` (the image's
built-in default), not our text.

**Root cause:** `http-echo` is configured via a command-line flag
(`-text=...`), not an environment variable. Setting `env:` did
nothing, because the container's baked-in default command never reads
that variable at all.

**The deeper problem:** this chart's `deployment.yaml` had **no way to
override a container's `command`/`args` at all**, for any service, for
any reason. That's a real, structural gap -- not specific to
`http-echo`. Fixed by adding `command`/`args` support, mirroring the
exact pattern already used in `ragleap-ops` for its `voice` service.

**Lesson for anyone using this chart:** if a service's behavior is
controlled by CLI flags rather than environment variables, you need
`args:` (or `command:` to replace the entrypoint entirely), not `env:`.
Setting `env:` alone will deploy without error and give no indication
anything is wrong -- the only way to catch it is to actually test the
running service's real behavior, not just check that the pod is
`Running`.

## Verify it actually works

Don't just trust `kubectl get pods` -- confirm real behavior, same
discipline as everywhere else in this repo.

```bash
kubectl port-forward -n my-example svc/my-example-api 5678:5678
```

In another terminal:

```bash
curl http://localhost:5678/
# should print: hello from ragleap-app-chart
```

Confirm Redis is genuinely working, and genuinely persisting to the
real mounted volume:

```bash
kubectl exec -n my-example -it deploy/my-example-cache -- redis-cli SET test-key "hello"
kubectl exec -n my-example -it deploy/my-example-cache -- redis-cli GET test-key
kubectl exec -n my-example -it deploy/my-example-cache -- redis-cli CONFIG GET dir
# should show: /data -- confirming Redis is writing to the real PVC mount,
# not the container's ephemeral filesystem
```

## Clean up

```bash
helm uninstall my-example -n my-example
kubectl delete namespace my-example
```
