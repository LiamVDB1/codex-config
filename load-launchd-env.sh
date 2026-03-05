#!/bin/bash
set -euo pipefail

ENV_FILE="${HOME}/.codex/.env"

if [ ! -f "$ENV_FILE" ]; then
  exit 0
fi

declare -a keys=()

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "" | \#*)
      continue
      ;;
  esac

  if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]]; then
    keys+=("${BASH_REMATCH[1]}")
  fi
done < "$ENV_FILE"

set -a
. "$ENV_FILE"
set +a

for key in "${keys[@]}"; do
  if [ -n "${!key+x}" ]; then
    launchctl setenv "$key" "${!key}"
  fi
done
