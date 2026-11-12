# -*- mode: python ; coding: utf-8 -*-
"""
Configuration PyInstaller de BioCentral — un seul fichier pour les deux systèmes.

    Windows : dist\BioCentral.exe        (exécutable unique, sans console)
    macOS   : dist/BioCentral.app        (application à glisser dans Applications)

Construire avec  construire_windows.bat  ou  ./construire_mac.sh
(PyInstaller ne sait PAS construire l'application Mac depuis Windows, ni l'inverse :
chaque version se construit sur son propre système — voir README, section Empaquetage.)

La Base de connaissances (PyTorch + sentence-transformers, plusieurs Go) est volontairement
exclue : l'exécutable reste léger et le module affiche un message clair s'il est ouvert.
"""
import re
import sys
from pathlib import Path

RACINE = Path(SPECPATH)
VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', (RACINE / "core" / "version.py").read_text(encoding="utf-8")).group(1)
MAC = sys.platform == "darwin"

EXCLUSIONS = [
    # Base de connaissances (voir ci-dessus) et tout ce qu'elle entraîne
    "torch", "torchvision", "torchaudio", "sentence_transformers", "transformers", "tokenizers",
    "huggingface_hub", "safetensors", "sklearn", "accelerate",
    # Bibliothèques présentes sur le poste de développement mais inutiles ici
    "tensorflow", "keras", "matplotlib", "pandas", "IPython", "jupyter", "notebook", "tkinter",
    "PyQt5", "PyQt6", "cv2", "numba", "sympy", "pytest",
    # Moteurs de calcul optionnels que scipy sait utiliser s'ils sont installés :
    # jax/jaxlib seuls ajoutaient 227 Mo à l'exécutable sans rien apporter.
    "jax", "jaxlib", "cupy", "dask", "sparse", "array_api_strict",
    # Dépendances optionnelles de pypdf / openpyxl (PDF chiffrés, accélération XML, images)
    "cryptography", "lxml", "PIL",
]

a = Analysis(
    ["main.py"],
    pathex=[str(RACINE)],
    binaries=[],
    datas=[(str(RACINE / "schema.sql"), "."), (str(RACINE / "assets"), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUSIONS,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if MAC:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="BioCentral",
        debug=False, strip=False, upx=False,
        console=False,
        argv_emulation=False,
        target_arch=None,           # architecture de la machine de construction (arm64 ou x86_64)
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BioCentral")
    app = BUNDLE(
        coll,
        name="BioCentral.app",
        icon=str(RACINE / "assets" / "icon.icns"),
        bundle_identifier="fr.biocentral.app",
        version=VERSION,
        info_plist={
            "CFBundleName": "BioCentral",
            "CFBundleDisplayName": "BioCentral",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "BioCentral",
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="BioCentral",
        debug=False, strip=False,
        upx=False,                  # UPX déclenche des faux positifs d'antivirus
        runtime_tmpdir=None,
        console=False,              # application fenêtrée, pas de console noire
        icon=str(RACINE / "assets" / "icon.ico"),
        version=str(RACINE / "outils" / "version_windows.txt"),
    )
