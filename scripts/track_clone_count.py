"""
Accumulates a lifetime-ish GitHub repo clone count.

GitHub's traffic API (/repos/{owner}/{repo}/traffic/clones) only ever returns a
rolling 14-day window -- there is no history endpoint, and this cannot be
backfilled for dates before this script started running. So the "total" this
produces is real and accurate, but it is a running total STARTING FROM WHEN
THIS WORKFLOW WAS ADDED, not a true all-time count since the repo's creation.
The badge label says so explicitly ("clones since <date>") so it is never
presented as more than it is.

State file (JSON): {"total": int, "counted_dates": [ "YYYY-MM-DD", ... ], "since": "YYYY-MM-DD"}
Each date from the API is added to `total` at most once, keyed by its calendar
date, so re-running on overlapping windows (this runs daily against a 14-day
window) never double-counts a day already seen.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

MAX_KEPT_DATES = 60  # keep state file small; well over the 14-day API window


def fetch_clones(repo: str, token: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/traffic/clones",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ragleap-core-clone-counter",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"total": 0, "counted_dates": [], "since": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("total", 0)
    state.setdefault("counted_dates", [])
    state.setdefault("since", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return state


def apply_new_days(state: dict, clones_payload: dict) -> dict:
    """Adds count from each day in the API response not already in counted_dates.
    Returns the same state dict, mutated, for convenience."""
    counted = set(state["counted_dates"])
    for day in clones_payload.get("clones", []):
        date_str = day["timestamp"][:10]  # "2026-09-20T00:00:00Z" -> "2026-09-20"
        if date_str in counted:
            continue
        state["total"] += int(day.get("count", 0))
        counted.add(date_str)
    state["counted_dates"] = sorted(counted)[-MAX_KEPT_DATES:]
    return state


def format_message(total: int) -> str:
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f}m"
    if total >= 1_000:
        return f"{total / 1_000:.1f}k"
    return str(total)


def write_badge(badge_path: str, total: int, since: str) -> None:
    badge = {
        "schemaVersion": 1,
        "label": f"clones since {since}",
        "message": format_message(total),
        "color": "blue",
    }
    os.makedirs(os.path.dirname(badge_path) or ".", exist_ok=True)
    with open(badge_path, "w", encoding="utf-8") as f:
        json.dump(badge, f, indent=2)
        f.write("\n")


def write_state(state_path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def main() -> int:
    repo = os.environ.get("REPO", "antonyrag/ragleap-core")
    token = os.environ.get("GH_TRAFFIC_TOKEN", "")
    state_path = os.environ.get("STATE_PATH", ".github/badges/clone-history.json")
    badge_path = os.environ.get("BADGE_PATH", ".github/badges/clone-count.json")

    if not token:
        print("GH_TRAFFIC_TOKEN is not set; skipping (non-fatal, keeps last known badge)")
        return 0

    state = load_state(state_path)
    try:
        payload = fetch_clones(repo, token)
    except Exception as e:
        print(f"Traffic API call failed (non-fatal, keeping last known total): {e}")
        write_badge(badge_path, state["total"], state["since"])
        return 0

    before = state["total"]
    state = apply_new_days(state, payload)
    write_state(state_path, state)
    write_badge(badge_path, state["total"], state["since"])
    print(f"Total clones: {before} -> {state['total']} (since {state['since']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
