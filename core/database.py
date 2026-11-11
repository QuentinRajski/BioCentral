"""
Gestion de la base de données SQLite partagée par toute l'application.

Principe : la base vit toujours dans le dossier de données utilisateur (AppData),
jamais à côté de l'exécutable, jamais dans un dossier remplacé par une mise à jour.
Voir schema.sql pour la structure complète et la convention de nommage par module.
"""
import sqlite3
import os
from pathlib import Path

APP_NAME = "BioCentral"
DB_FILENAME = "biocentral.db"
SCHEMA_FILE = Path(__file__).parent.parent / "schema.sql"


def get_data_dir() -> Path:
    """Dossier de données persistant, indépendant de l'emplacement de l'exécutable."""
    base = os.getenv("APPDATA") or str(Path.home())
    data_dir = Path(base) / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / DB_FILENAME


def get_connection() -> sqlite3.Connection:
    """Retourne une connexion prête à l'emploi. Initialise le schéma au premier lancement."""
    db_path = get_db_path()
    is_new = not db_path.exists()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    if is_new:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
    else:
        run_migrations(conn)
    return conn


# ------------------------------------------------------------------
# Migrations : chaque module déclare ses propres étapes de migration,
# indexées par version cible. Ajouter une entrée ici quand un futur
# changement de schéma doit s'appliquer sans perdre les données existantes.
# ------------------------------------------------------------------
MIGRATIONS = {
    "qc_schema_version": {
        2: "ALTER TABLE qc_parametres ADD COLUMN notes TEXT;",
    },
    "kb_schema_version": {
        1: """
            CREATE TABLE kb_documents (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                titre          TEXT NOT NULL,
                fichier_source TEXT NOT NULL,
                nombre_pages   INTEGER,
                date_import    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE kb_passages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id  INTEGER NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                page         INTEGER NOT NULL,
                ordre        INTEGER NOT NULL,
                texte        TEXT NOT NULL,
                embedding    BLOB NOT NULL
            );
            CREATE INDEX idx_kb_passages_document ON kb_passages(document_id);
        """,
    },
}


def run_migrations(conn: sqlite3.Connection) -> None:
    for version_key, steps in MIGRATIONS.items():
        row = conn.execute("SELECT valeur FROM app_metadata WHERE cle = ?", (version_key,)).fetchone()
        current = int(row[0]) if row else 0
        for target_version in sorted(v for v in steps if v > current):
            conn.executescript(steps[target_version])
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata (cle, valeur) VALUES (?, ?)",
                (version_key, str(target_version)),
            )
        conn.commit()


def get_theme_preference(conn: sqlite3.Connection) -> str:
    """Thème choisi par l'utilisateur ('light' ou 'dark'), 'light' par défaut."""
    row = conn.execute("SELECT valeur FROM app_metadata WHERE cle = 'theme'").fetchone()
    return row[0] if row and row[0] in ("light", "dark") else "light"


def set_theme_preference(conn: sqlite3.Connection, valeur: str) -> None:
    conn.execute("INSERT OR REPLACE INTO app_metadata (cle, valeur) VALUES ('theme', ?)", (valeur,))
    conn.commit()


def export_database(destination: Path) -> None:
    """Copie brute du fichier .db — utilisé par « Extraire la BDD »."""
    import shutil
    shutil.copy2(get_db_path(), destination)


def import_database(source: Path) -> Path:
    """Remplace la base active par un fichier importé, après sauvegarde de l'ancienne."""
    import shutil
    from datetime import datetime
    db_path = get_db_path()
    backup_path = db_path.with_name(f"biocentral_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    if db_path.exists():
        shutil.copy2(db_path, backup_path)
    shutil.copy2(source, db_path)
    return backup_path
