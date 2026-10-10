#!/usr/bin/env bash
# Runs the roles twice inside a throwaway Ubuntu 22.04 container.
# Never touches the host. Usage: bash tests/container_test.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm -v "$HERE":/pkg:ro ubuntu:22.04 bash /pkg/tests/inside_container.sh
