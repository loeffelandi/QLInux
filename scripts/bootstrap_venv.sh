#!/usr/bin/env bash
# Bootstrap der Projekt-venv fuer QLInux.
#
# Plattformneutral erledigt das Python-Skript; diese Datei bleibt der
# gewohnte Aufruf unter Linux und macOS.
#
# Aufruf:  bash scripts/bootstrap_venv.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

exec "${PYTHON}" "${REPO_ROOT}/scripts/bootstrap_venv.py"
