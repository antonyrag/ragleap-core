#!/usr/bin/env bash
# RagLeap Core installer: checks Docker, downloads the code, creates .env with fresh secrets,
# starts everything and prints a one-click link to the dashboard.
#
#   curl -fsSL https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.sh | bash -s -- --ollama
#
# Unattended: RAGLEAP_PROVIDER=gemini|ollama|skip  GEMINI_API_KEY=...  RAGLEAP_DIR=...  RAGLEAP_NONINTERACTIVE=1
# An existing .env is never modified.
set -euo pipefail

REPO_URL="${RAGLEAP_REPO:-https://github.com/antonyrag/ragleap-core.git}"
DIR="${RAGLEAP_DIR:-ragleap-core}"
PROVIDER="${RAGLEAP_PROVIDER:-}"
CHAT_MODEL="${RAGLEAP_OLLAMA_MODEL:-qwen2.5:3b}"
EMBED_MODEL="nomic-embed-text"
WAIT_TRIES="${RAGLEAP_WAIT_TRIES:-90}"
BASE_URL="http://localhost:8000"

say() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --ollama) PROVIDER=ollama ;;
    --gemini) PROVIDER=gemini ;;
    --skip-ai) PROVIDER=skip ;;
    -h|--help)
      say "Usage: install.sh [--gemini | --ollama | --skip-ai]"
      say "Unattended: RAGLEAP_PROVIDER=gemini|ollama|skip GEMINI_API_KEY=... RAGLEAP_DIR=... RAGLEAP_NONINTERACTIVE=1"
      exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

say "RagLeap Core installer (Windows: run this in Git Bash)"

command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Desktop first: https://www.docker.com/products/docker-desktop"
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker, wait for it to load, then run this again."
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  die "Docker Compose was not found. Install Docker Desktop, or the docker compose plugin."
fi

if [ -f "$DIR/docker-compose.yml" ]; then
  say "Using the existing folder: $DIR"
else
  command -v git >/dev/null 2>&1 || die "Git is not installed (it is needed to download RagLeap)."
  git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"

interactive() {
  [ "${RAGLEAP_NONINTERACTIVE:-}" != "1" ] && [ -r /dev/tty ] && [ -w /dev/tty ] && ( : </dev/tty ) 2>/dev/null
}
ask() {
  local a
  printf '%s' "$1" >/dev/tty
  IFS= read -r a </dev/tty || a=""
  printf '%s' "${a:-$2}"
}
ask_secret() {
  local a
  printf '%s' "$1" >/dev/tty
  IFS= read -rs a </dev/tty || a=""
  printf '\n' >/dev/tty
  printf '%s' "$a"
}
rand_hex() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
fernet_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }
set_env() {
  K="$1" V="$2" awk 'BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"] }
    index($0, k "=") == 1 { print k "=" v; d = 1; next }
    { print }
    END { if (!d) print k "=" v }' .env > .env.tmp && mv .env.tmp .env
}
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2- | tr -d '\r\n' || true; }

USE_OLLAMA=0
API_KEY=""
if [ -f .env ]; then
  say "Keeping your existing .env (it is not changed). Change the AI provider any time in the dashboard: Settings tab."
  if [ -n "$PROVIDER" ]; then say "(The AI choice you passed is ignored because .env already exists.)"; fi
  API_KEY="$(env_value RAGLEAP_API_KEY)"
  if [ -z "$API_KEY" ]; then say "WARNING: your .env has no RAGLEAP_API_KEY, so the API has no password. Set one."; fi
  if grep -q '^OLLAMA_BASE_URL=http://ollama:' .env; then USE_OLLAMA=1; fi
else
  [ -f .env.example ] || die ".env.example is missing in $DIR."
  if [ -z "$PROVIDER" ]; then
    if interactive; then
      {
        echo
        echo "Which AI do you want to use?"
        echo "  1) Google Gemini  (free key, best quality, needs internet)"
        echo "  2) Ollama         (runs on this computer, no key, slower and less accurate on a CPU)"
        echo "  3) Skip           (choose later in the dashboard: Settings tab)"
      } >/dev/tty
      case "$(ask 'Choose 1, 2 or 3 [1]: ' 1)" in
        2) PROVIDER=ollama ;;
        3) PROVIDER=skip ;;
        *) PROVIDER=gemini ;;
      esac
    else
      PROVIDER=skip
      say "No AI provider chosen (non-interactive). Pick one later in the dashboard: Settings tab."
    fi
  fi
  case "$PROVIDER" in gemini|ollama|skip) ;; *) die "RAGLEAP_PROVIDER must be gemini, ollama or skip." ;; esac

  GEMINI_KEY="${GEMINI_API_KEY:-}"
  if [ "$PROVIDER" = gemini ] && [ -z "$GEMINI_KEY" ] && interactive; then
    printf '%s\n' "Get a free Gemini key at https://aistudio.google.com/apikey" >/dev/tty
    GEMINI_KEY="$(ask_secret 'Paste your Gemini API key (hidden; press Enter to skip): ')"
  fi
  if [ "$PROVIDER" = gemini ] && [ -z "$GEMINI_KEY" ]; then
    say "No Gemini key given: add it later in the dashboard (Settings tab)."
  fi

  OLD_UMASK="$(umask)"
  umask 077
  cp .env.example .env
  API_KEY="$(rand_hex 24)"
  set_env RAGLEAP_API_KEY "$API_KEY"
  set_env ADDON_ENCRYPTION_KEY "$(fernet_key)"
  set_env SANDBOX_TOKEN "$(rand_hex 24)"
  if docker volume ls -q 2>/dev/null | grep -q 'ragleap_core_data'; then
    say "An earlier RagLeap database exists, so its database password is left as it was."
  else
    set_env POSTGRES_PASSWORD "$(rand_hex 12)"
  fi
  case "$PROVIDER" in
    gemini)
      set_env GEMINI_API_KEY "$GEMINI_KEY" ;;
    ollama)
      USE_OLLAMA=1
      set_env GEMINI_API_KEY ""
      set_env LLM_PROVIDER ollama
      set_env OLLAMA_MODEL "$CHAT_MODEL"
      set_env OLLAMA_BASE_URL "http://ollama:11434/v1"
      set_env EMBEDDING_PROVIDER ollama
      set_env OLLAMA_EMBEDDING_MODEL "$EMBED_MODEL"
      set_env EMBEDDING_DIMENSIONS 768 ;;
    skip)
      set_env GEMINI_API_KEY "" ;;
  esac
  chmod 600 .env
  umask "$OLD_UMASK"
  say "Created .env with a fresh API key and secrets."
fi

PROFILE=""
if [ "$USE_OLLAMA" = 1 ]; then PROFILE="--profile ollama"; fi

if [ "$USE_OLLAMA" = 1 ]; then
  say "Starting the local Ollama service first (the models must be ready before RagLeap starts)..."
  $COMPOSE $PROFILE up -d ollama
  say "Waiting for the local Ollama service..."
  n=0
  until $COMPOSE $PROFILE exec -T ollama ollama list >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge 60 ]; then die "The Ollama service did not start. Check: $COMPOSE $PROFILE logs ollama"; fi
    sleep 2
  done
  m="$(env_value OLLAMA_MODEL)"; m="${m:-$CHAT_MODEL}"
  e="$(env_value OLLAMA_EMBEDDING_MODEL)"; e="${e:-$EMBED_MODEL}"
  say "Downloading local models (a few GB, once). Small models on a CPU answer slowly and less accurately than Gemini."
  $COMPOSE $PROFILE exec -T ollama ollama pull "$m" || say "Could not download $m. Retry: $COMPOSE $PROFILE exec ollama ollama pull $m"
  $COMPOSE $PROFILE exec -T ollama ollama pull "$e" || say "Could not download $e. Retry: $COMPOSE $PROFILE exec ollama ollama pull $e"
fi

say "Building and starting RagLeap (the first run takes a few minutes)..."
$COMPOSE $PROFILE up --build -d

n=0
until curl -sf "$BASE_URL/health" >/dev/null 2>&1; do
  n=$((n + 1))
  if [ "$n" -ge "$WAIT_TRIES" ]; then
    say "RagLeap did not become healthy in time. Check: $COMPOSE logs app"
    exit 1
  fi
  sleep 2
done

say ""
say "RagLeap is running."
if [ -n "$API_KEY" ]; then
  say "Open your dashboard (one click; the key stays in your browser tab):"
  say "  $BASE_URL/office#key=$API_KEY"
  say "Keep that link private: it contains your API key. The key is also in $PWD/.env"
else
  say "Open your dashboard: $BASE_URL/office"
fi
say "API docs: $BASE_URL/docs"


SHIM_DIR="${HOME:-.}/.local/bin"
if mkdir -p "$SHIM_DIR" 2>/dev/null && printf '#!/bin/sh\nRAGLEAP_HOME=%s exec bash %s/scripts/ragleap "$@"\n' "$(printf '%q' "$PWD")" "$(printf '%q' "$PWD")" > "$SHIM_DIR/ragleap" && chmod 755 "$SHIM_DIR/ragleap"; then
  say "Installed the ragleap command: $SHIM_DIR/ragleap (ragleap launch | stop | status | logs | update | key)"
  case ":$PATH:" in *":$SHIM_DIR:"*) ;; *) say "Add it to your PATH to use it from anywhere: export PATH=\"$SHIM_DIR:\$PATH\"" ;; esac
else
  say "Could not install the ragleap command (optional). You can run: bash $PWD/scripts/ragleap"
fi
