#!/usr/bin/env bash
# Bootstrap der Projekt-venv fuer QLInux.
#
# - legt ./.venv an (eigene venv, die bestehende Web-venv bleibt unangetastet)
# - installiert die gepinnten Abhaengigkeiten (brother_ql==0.9.4)
# - wendet den idempotenten Pillow-10-Patch an (Image.ANTIALIAS -> Image.LANCZOS)
#
# Aufruf:  bash scripts/bootstrap_venv.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON="${PYTHON:-python3}"

echo ">> Projekt:   ${REPO_ROOT}"
echo ">> venv:      ${VENV_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    "${PYTHON}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip wheel >/dev/null

echo ">> installiere Abhaengigkeiten (gepinnt)"
pip install -r "${REPO_ROOT}/requirements-dev.txt"

echo ">> wende brother_ql-Patch an"
python "${REPO_ROOT}/scripts/patch_brother_ql.py"

echo ">> Selbsttest"
python - <<'PY'
import brother_ql
from brother_ql.labels import LabelsManager, FormFactor
from brother_ql.models import ModelsManager
print("brother_ql:", brother_ql.__file__)
print("Labels:", len(list(LabelsManager().iter_elements())))
print("Models:", len(list(ModelsManager().iter_elements())))
import PySide6, qrcode, barcode
print("PySide6:", PySide6.__version__)
print("OK")
PY

echo ">> fertig. venv aktivieren mit: source ${VENV_DIR}/bin/activate"
