"""ragleap-app-chart: generic, reusable Helm chart for arbitrary services.

Unlike ragleap-ops (hardcoded to RagLeap Core's own 4 services), this
chart takes an arbitrary list of services via a `services:` values.yaml
key and renders Deployment/Service/Ingress/NetworkPolicy resources for
each via range loops — any developer can point this at their own app,
not just RagLeap.

It contains almost no importable Python — its purpose is to let the
existing PyPI/git-tag release automation version and ship the helm/
chart alongside this src/ tree, matching the release discipline of
ragleap-ops, ragleap-rag, ragleap-graph, and ragleap-vectorstores.
"""

__version__ = "0.1.0"
