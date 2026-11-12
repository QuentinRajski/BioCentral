"""
Emplacements des fichiers de l'application, identiques que BioCentral soit lancé
depuis les sources (python main.py) ou depuis l'exécutable empaqueté.

Une fois empaqueté par PyInstaller, les fichiers livrés avec l'application
(schema.sql, assets/) ne sont plus à côté des modules Python : ils sont dans le
dossier d'extraction sys._MEIPASS (Windows, .exe unique) ou dans
BioCentral.app/Contents/Frameworks (macOS). `ressource()` masque cette différence.
"""
import sys
from pathlib import Path

RACINE_SOURCES = Path(__file__).resolve().parent.parent


def est_empaquete() -> bool:
    return bool(getattr(sys, "frozen", False))


def racine_ressources() -> Path:
    if est_empaquete():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return RACINE_SOURCES


def ressource(*morceaux: str) -> Path:
    """Chemin d'un fichier livré avec l'application, ex. ressource("assets", "icon.png")."""
    return racine_ressources().joinpath(*morceaux)
