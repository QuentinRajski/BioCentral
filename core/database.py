"""
Gestion de la base de données SQLite partagée par toute l'application.

Principe : la base vit toujours dans le dossier de données utilisateur (AppData),
jamais à côté de l'exécutable, jamais dans un dossier remplacé par une mise à jour.
Voir schema.sql pour la structure complète et la convention de nommage par module.

Version 2 — ce qui change par rapport à la v1 :
  - la v2 a son PROPRE dossier de données (%APPDATA%\\BioCentral_v2). Au tout
    premier lancement, la base de la v1 (%APPDATA%\\BioCentral) est recopiée
    telle quelle si elle existe : la v1 et ses données ne sont jamais modifiées,
    les deux versions peuvent cohabiter sur le même poste ;
  - une sauvegarde est faite automatiquement avant toute migration de schéma,
    et une fois par jour au lancement (les plus anciennes sont purgées) ;
  - l'extraction passe par l'API de sauvegarde de SQLite (copie cohérente même
    si une écriture est en cours), et un fichier importé est vérifié AVANT de
    remplacer la base active.

La variable d'environnement BIOCENTRAL_DATA_DIR permet de forcer un autre
dossier de données (tests automatiques, base de démonstration...).
"""
import logging
import os
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

APP_NAME = "BioCentral"
DATA_DIR_NAME = "BioCentral_v2"        # dossier de données de cette version
LEGACY_DATA_DIR_NAME = "BioCentral"    # dossier de la v1 : lu une seule fois, jamais modifié
ENV_DATA_DIR = "BIOCENTRAL_DATA_DIR"
DB_FILENAME = "biocentral.db"
BACKUP_DIRNAME = "sauvegardes"
NOMBRE_SAUVEGARDES_CONSERVEES = 10
SCHEMA_FILE = Path(__file__).parent.parent / "schema.sql"

log = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Dossier de données persistant, indépendant de l'emplacement de l'exécutable."""
    force = os.getenv(ENV_DATA_DIR)
    if force:
        data_dir = Path(force)
    else:
        base = os.getenv("APPDATA") or str(Path.home())
        data_dir = Path(base) / DATA_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / DB_FILENAME


def get_backup_dir() -> Path:
    dossier = get_data_dir() / BACKUP_DIRNAME
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _chemin_base_v1() -> Path | None:
    """Base de la v1, si elle existe sur ce poste. Ignorée quand le dossier de
    données est forcé (tests) : on ne veut alors aucune dépendance au poste."""
    if os.getenv(ENV_DATA_DIR):
        return None
    base = os.getenv("APPDATA") or str(Path.home())
    chemin = Path(base) / LEGACY_DATA_DIR_NAME / DB_FILENAME
    return chemin if chemin.exists() else None


def _ouvrir_lecture_seule(chemin: Path) -> sqlite3.Connection:
    """Connexion strictement en lecture seule : le fichier ne peut pas être modifié."""
    return sqlite3.connect(f"{Path(chemin).resolve().as_uri()}?mode=ro", uri=True)


def _copier_base(source: Path, destination: Path) -> None:
    """Copie cohérente d'une base SQLite via l'API de sauvegarde (la source est
    ouverte en lecture seule : elle ne peut pas être modifiée par cette copie)."""
    src = _ouvrir_lecture_seule(source)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _ouvrir(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_connection() -> sqlite3.Connection:
    """Retourne une connexion prête à l'emploi. Initialise le schéma au premier
    lancement (ou reprend une copie de la base v1), puis applique les migrations."""
    db_path = get_db_path()
    if not db_path.exists():
        base_v1 = _chemin_base_v1()
        if base_v1 is not None:
            _copier_base(base_v1, db_path)
            log.info("Première utilisation de la v2 : base de la v1 recopiée depuis %s", base_v1)
            conn = _ouvrir(db_path)
            run_migrations(conn)
            set_setting(conn, "reprise_v1", datetime.now().isoformat(timespec="seconds"))
            return conn
        conn = _ouvrir(db_path)
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
        return conn

    conn = _ouvrir(db_path)
    if _migrations_en_attente(conn):
        conn.close()
        sauvegarder_base("avant_migration")
        conn = _ouvrir(db_path)
    run_migrations(conn)
    return conn


# ------------------------------------------------------------------
# Migrations : chaque module déclare ses propres étapes de migration,
# indexées par version cible. Ajouter une entrée ici quand un futur
# changement de schéma doit s'appliquer sans perdre les données existantes.
# IMPORTANT : toute table ajoutée ici doit l'être aussi dans schema.sql
# (utilisé pour une base neuve) — tests/test_database.py vérifie que les
# deux chemins aboutissent exactement à la même structure.
# ------------------------------------------------------------------
MIGRATIONS = {
    "qc_schema_version": {
        2: "ALTER TABLE qc_parametres ADD COLUMN notes TEXT;",
        3: """
            ALTER TABLE qc_parametres ADD COLUMN unite TEXT;
            CREATE TABLE qc_intervalles_reference (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                parametre_id    INTEGER NOT NULL REFERENCES qc_parametres(id) ON DELETE CASCADE,
                tranche_libelle TEXT NOT NULL DEFAULT '',
                sexe            TEXT NOT NULL DEFAULT '',
                borne_basse     REAL,
                borne_haute     REAL,
                source          TEXT,
                UNIQUE (parametre_id, tranche_libelle, sexe)
            );
        """,
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
    "ciq_schema_version": {
        1: """
            CREATE TABLE ciq_analytes (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                nom                      TEXT NOT NULL,
                unite                    TEXT NOT NULL DEFAULT '',
                automate                 TEXT NOT NULL DEFAULT '',
                erreur_totale_admissible REAL,
                regles                   TEXT,
                notes                    TEXT,
                date_creation            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (nom, automate)
            );
            CREATE TABLE ciq_lots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                analyte_id       INTEGER NOT NULL REFERENCES ciq_analytes(id) ON DELETE CASCADE,
                niveau           TEXT NOT NULL,
                numero_lot       TEXT NOT NULL DEFAULT '',
                cible_moyenne    REAL,
                cible_ecart_type REAL,
                origine_cible    TEXT,
                date_peremption  DATE,
                actif            INTEGER NOT NULL DEFAULT 1,
                date_creation    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE ciq_mesures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id      INTEGER NOT NULL REFERENCES ciq_lots(id) ON DELETE CASCADE,
                date_mesure TEXT NOT NULL,
                valeur      REAL NOT NULL,
                operateur   TEXT,
                commentaire TEXT,
                exclue      INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX idx_ciq_lots_analyte ON ciq_lots(analyte_id);
            CREATE INDEX idx_ciq_mesures_lot  ON ciq_mesures(lot_id, date_mesure);
        """,
    },
    "vm_schema_version": {
        1: """
            CREATE TABLE vm_etudes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                type          TEXT NOT NULL CHECK (type IN ('comparaison','precision')),
                titre         TEXT NOT NULL,
                analyte       TEXT NOT NULL DEFAULT '',
                unite         TEXT NOT NULL DEFAULT '',
                methode_x     TEXT NOT NULL DEFAULT '',
                methode_y     TEXT NOT NULL DEFAULT '',
                parametres    TEXT,
                notes         TEXT,
                date_creation TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE vm_donnees (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                etude_id    INTEGER NOT NULL REFERENCES vm_etudes(id) ON DELETE CASCADE,
                ordre       INTEGER NOT NULL,
                identifiant TEXT,
                x           REAL,
                y           REAL
            );
            CREATE INDEX idx_vm_donnees_etude ON vm_donnees(etude_id, ordre);
        """,
    },
}


def _version_courante(conn: sqlite3.Connection, version_key: str) -> int:
    row = conn.execute("SELECT valeur FROM app_metadata WHERE cle = ?", (version_key,)).fetchone()
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def _migrations_en_attente(conn: sqlite3.Connection) -> bool:
    return any(
        any(v > _version_courante(conn, version_key) for v in steps)
        for version_key, steps in MIGRATIONS.items()
    )


def run_migrations(conn: sqlite3.Connection) -> None:
    for version_key, steps in MIGRATIONS.items():
        current = _version_courante(conn, version_key)
        for target_version in sorted(v for v in steps if v > current):
            conn.executescript(steps[target_version])
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata (cle, valeur) VALUES (?, ?)",
                (version_key, str(target_version)),
            )
            conn.commit()
            log.info("Migration appliquée : %s -> %s", version_key, target_version)


# ------------------------------------------------------------------
# Réglages simples (clé/valeur) stockés dans app_metadata
# ------------------------------------------------------------------
def get_setting(conn: sqlite3.Connection, cle: str, defaut: str | None = None) -> str | None:
    row = conn.execute("SELECT valeur FROM app_metadata WHERE cle = ?", (cle,)).fetchone()
    return row[0] if row and row[0] is not None else defaut


def set_setting(conn: sqlite3.Connection, cle: str, valeur: str | None) -> None:
    conn.execute("INSERT OR REPLACE INTO app_metadata (cle, valeur) VALUES (?, ?)", (cle, valeur))
    conn.commit()


def get_theme_preference(conn: sqlite3.Connection) -> str:
    """Thème choisi par l'utilisateur ('light' ou 'dark'), 'light' par défaut."""
    valeur = get_setting(conn, "theme")
    return valeur if valeur in ("light", "dark") else "light"


def set_theme_preference(conn: sqlite3.Connection, valeur: str) -> None:
    set_setting(conn, "theme", valeur)


# ------------------------------------------------------------------
# Sauvegardes, extraction et import de la base complète
# ------------------------------------------------------------------
def sauvegarder_base(etiquette: str = "auto") -> Path | None:
    """Copie horodatée de la base dans le sous-dossier « sauvegardes », puis purge
    des plus anciennes. Ne lève jamais : une sauvegarde ratée ne doit pas empêcher
    l'application de démarrer (elle est seulement consignée dans le log)."""
    db_path = get_db_path()
    if not db_path.exists():
        return None
    try:
        destination = get_backup_dir() / f"biocentral_{etiquette}_{datetime.now():%Y%m%d_%H%M%S}.db"
        _copier_base(db_path, destination)
        _purger_sauvegardes()
        return destination
    except Exception:
        log.exception("Sauvegarde automatique impossible")
        return None


def sauvegarde_quotidienne(conn: sqlite3.Connection) -> Path | None:
    """Une sauvegarde automatique par jour d'utilisation, au lancement."""
    aujourdhui = date.today().isoformat()
    if get_setting(conn, "derniere_sauvegarde") == aujourdhui:
        return None
    conn.commit()
    chemin = sauvegarder_base("auto")
    if chemin is not None:
        set_setting(conn, "derniere_sauvegarde", aujourdhui)
    return chemin


def _purger_sauvegardes() -> None:
    fichiers = sorted(get_backup_dir().glob("biocentral_*.db"), key=lambda p: p.stat().st_mtime)
    for ancien in fichiers[:-NOMBRE_SAUVEGARDES_CONSERVEES]:
        try:
            ancien.unlink()
        except OSError:
            pass


def export_database(destination: Path, conn: sqlite3.Connection | None = None) -> None:
    """Copie de la base vers `destination` — utilisé par « Extraire la BDD »."""
    if conn is not None:
        conn.commit()
    destination = Path(destination)
    if destination.resolve() == get_db_path().resolve():
        raise ValueError("Choisissez un autre emplacement que celui de la base active.")
    if destination.exists():
        destination.unlink()
    _copier_base(get_db_path(), destination)


def verifier_fichier_base(source: Path) -> None:
    """Lève ValueError (message lisible) si `source` n'est pas une base BioCentral
    exploitable. Appelé AVANT de toucher à la base active."""
    source = Path(source)
    if not source.exists():
        raise ValueError("Le fichier choisi n'existe pas.")
    if source.resolve() == get_db_path().resolve():
        raise ValueError("Ce fichier est déjà la base de données active.")
    try:
        conn = _ouvrir_lecture_seule(source)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            integrite = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        raise ValueError("Ce fichier n'est pas une base de données SQLite lisible.") from None
    if integrite != "ok":
        raise ValueError("Ce fichier de base de données est endommagé.")
    if not {"app_metadata", "qc_parametres", "qc_echantillons"} <= tables:
        raise ValueError("Ce fichier n'est pas une base de données BioCentral.")


def import_database(source: Path) -> Path:
    """Remplace la base active par un fichier importé, après vérification du
    fichier et sauvegarde de l'ancienne base. Retourne le chemin de la sauvegarde.
    La connexion active doit avoir été fermée par l'appelant."""
    source = Path(source)
    verifier_fichier_base(source)
    db_path = get_db_path()
    backup_path = get_backup_dir() / f"biocentral_avant_import_{datetime.now():%Y%m%d_%H%M%S}.db"
    if db_path.exists():
        shutil.copy2(db_path, backup_path)
    shutil.copy2(source, db_path)
    return backup_path
