#!/bin/bash
# Construit dist/BioCentral.app puis dist/BioCentral-mac.zip. À lancer SUR UN MAC :
#     chmod +x construire_mac.sh && ./construire_mac.sh
# Prérequis : Python 3.11 ou plus récent (python.org ou Homebrew).
# L'application produite tourne sur l'architecture du Mac qui la construit
# (Apple Silicon M1/M2/M3… ou Intel).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --noconfirm --clean biocentral.spec

echo "Vérification automatique (ouvre chaque module puis se ferme)…"
BIOCENTRAL_DATA_DIR="$(mktemp -d)" ./dist/BioCentral.app/Contents/MacOS/BioCentral --autotest

# Signature « ad hoc » : sans certificat Apple Developer, évite au moins le
# message « application endommagée » sur Apple Silicon.
codesign --force --deep --sign - dist/BioCentral.app

(cd dist && ditto -c -k --keepParent BioCentral.app BioCentral-mac.zip)
echo "Terminé : dist/BioCentral.app et dist/BioCentral-mac.zip"
