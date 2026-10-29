#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${PYTHON:-python3}" -m scripts.start_stack "$@"
