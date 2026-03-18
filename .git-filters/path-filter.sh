#!/bin/bash
# Git filter for cross-platform home directory path substitution
# Usage: smudge replaces @HOME@ with actual home dir
#        clean replaces actual home dir with @HOME@

HOME_DIR="$HOME"

case "$1" in
  smudge)
    # Replace @HOME@ placeholder with actual home directory
    sed "s|@HOME@|$HOME_DIR|g"
    ;;
  clean)
    # Replace actual home directory with @HOME@ placeholder
    sed "s|$HOME_DIR|@HOME@|g"
    ;;
  *)
    echo "Usage: $0 {smudge|clean}" >&2
    exit 1
    ;;
esac
