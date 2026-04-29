#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DISPLAY_START="${DISPLAY_START:-20}"
DISPLAY_END="${DISPLAY_END:-29}"
WORKER_PREFIX="${WORKER_PREFIX:-notebook-visual}"
WORKER_ROOT="${WORKER_ROOT:-/DATA/notebooklm-workers}"
DATA_ROOT="${DATA_ROOT:-/DATA/patients}"
PROXY_URL="${PROXY_URL:-http://localhost:7890}"
NOTEBOOKLM_URL="${NOTEBOOKLM_URL:-https://notebooklm.google.com}"
CONFIG_JSON="${CONFIG_JSON:-$PROJECT_ROOT/config.json}"
VNC_GEOMETRY="${VNC_GEOMETRY:-1920x1200}"
VNC_DEPTH="${VNC_DEPTH:-24}"

read_config_value() {
  local key="$1"
  "$PYTHON_BIN" - "$CONFIG_JSON" "$key" <<'PY'
import json
import sys

path = sys.argv[1]
key = sys.argv[2]

try:
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
except FileNotFoundError:
    raise SystemExit(0)
except Exception:
    raise SystemExit(0)

paths = {
    "mongo_uri": [
        ("mongo", "uri"),
        ("mongo", "mongo_uri"),
        ("mongodb", "uri"),
        ("database", "uri"),
        ("mongo_uri",),
        ("MONGO_URI",),
    ],
    "database_name": [
        ("mongo", "database"),
        ("mongo", "database_name"),
        ("mongodb", "database"),
        ("database", "name"),
        ("database_name",),
        ("DATABASE_NAME",),
    ],
}

for path_parts in paths.get(key, []):
    value = config
    for part in path_parts:
        if not isinstance(value, dict) or part not in value:
            break
        value = value[part]
    else:
        if value:
            print(value)
            raise SystemExit(0)
PY
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "missing required command: $command_name" >&2
    exit 1
  fi
}

is_worker_running() {
  local worker_id="$1"
  pgrep -f "app.worker.main --worker-id ${worker_id} " >/dev/null 2>&1
}

display_is_active() {
  local display="$1"
  DISPLAY="$display" xdpyinfo >/dev/null 2>&1
}

start_display_worker() {
  local display_number="$1"
  local display=":$display_number"
  local worker_id="${WORKER_PREFIX}-${display_number}"
  local vnc_port=$((5900 + display_number))
  local remote_debugging_port=$((9220 + display_number))
  local worker_dir="${WORKER_ROOT}/${worker_id}"
  local log_file="${worker_dir}/worker.log"

  mkdir -p "$worker_dir"

  if is_worker_running "$worker_id"; then
    echo "${worker_id} already running on ${display}; log=${log_file}"
    return
  fi

  if ! display_is_active "$display"; then
    vncserver "$display" -localhost no -geometry "$VNC_GEOMETRY" -depth "$VNC_DEPTH"
  fi

  (
    cd "$PROJECT_ROOT"
    setsid -f env \
      MONGO_URI="$MONGO_URI" \
      DATABASE_NAME="$DATABASE_NAME" \
      DATA_ROOT="$DATA_ROOT" \
      WORKER_ROOT="$WORKER_ROOT" \
      WORKER_ID="$worker_id" \
      DISPLAY="$display" \
      VNC_PORT="$vnc_port" \
      VNC_LOCALHOST="false" \
      AUTOMATION_MODE="visual" \
      NOTEBOOKLM_URL="$NOTEBOOKLM_URL" \
      CHROME_REMOTE_DEBUGGING_PORT="$remote_debugging_port" \
      all_proxy="$PROXY_URL" \
      http_proxy="$PROXY_URL" \
      https_proxy="$PROXY_URL" \
      ALL_PROXY="$PROXY_URL" \
      HTTP_PROXY="$PROXY_URL" \
      HTTPS_PROXY="$PROXY_URL" \
      PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" -m app.worker.main --worker-id "$worker_id" --display "$display" \
      >>"$log_file" 2>&1 </dev/null
  )

  echo "started ${worker_id} display=${display} vnc_port=${vnc_port} chrome_debug=${remote_debugging_port} log=${log_file}"
}

require_command "$PYTHON_BIN"
require_command vncserver
require_command xdpyinfo
require_command pgrep
require_command setsid

if [[ -z "${MONGO_URI:-}" ]]; then
  MONGO_URI="$(read_config_value mongo_uri || true)"
fi
if [[ -z "${DATABASE_NAME:-}" ]]; then
  DATABASE_NAME="$(read_config_value database_name || true)"
fi

export MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
export DATABASE_NAME="${DATABASE_NAME:-patient_records}"

for display_number in $(seq "$DISPLAY_START" "$DISPLAY_END"); do
  start_display_worker "$display_number"
done
