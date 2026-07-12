"""
Pipeline d'import d'un PDF pour le module Base de connaissances : extraction
du texte page par page, découpage en passages, calcul des embeddings, puis
insertion en base. Pas de génération de texte ici — ce module ne fait que
préparer les passages pour une recherche par similarité (voir recherche.py).
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pypdf import PdfReader

from .embeddings import encoder

MOTS_PAR_PASSAGE_MIN = 300
MOTS_PAR_PASSAGE_MAX = 500

ProgressCallback = Optional[Callable[[str, float], None]]


@dataclass
class ImportSummary:
    titre: str
    nombre_pages: int
    nombre_passages: int


def _decouper_en_passages(pages_texte: list[str]) -> list[tuple[int, str]]:
    """Retourne une liste de (numéro_page, texte_du_passage). Regroupe les
    paragraphes consécutifs d'une même page jusqu'à ~500 mots (jamais moins
    de 300 sauf en fin de page), sans jamais couper un paragraphe en deux —
    donc jamais de phrase coupée."""
    passages = []
    for numero_page, texte_page in enumerate(pages_texte, start=1):
        paragraphes = [p.strip() for p in re.split(r"\n\s*\n", texte_page) if p.strip()]
        courant: list[str] = []
        mots_courant = 0
        for paragraphe in paragraphes:
            mots_paragraphe = len(paragraphe.split())
            if courant and mots_courant + mots_paragraphe > MOTS_PAR_PASSAGE_MAX:
                passages.append((numero_page, " ".join(courant)))
                courant, mots_courant = [], 0
            courant.append(paragraphe)
            mots_courant += mots_paragraphe
            if mots_courant >= MOTS_PAR_PASSAGE_MIN:
                passages.append((numero_page, " ".join(courant)))
                courant, mots_courant = [], 0
        if courant:
            passages.append((numero_page, " ".join(courant)))
    return passages


def import_pdf(
    conn: sqlite3.Connection, filepath: Path, titre: str, on_progress: ProgressCallback = None,
) -> ImportSummary:
    """Exécuté sur le thread principal (la connexion SQLite n'est pas
    partageable entre threads) : on_progress permet à l'écran d'import de
    rafraîchir une barre de progression entre chaque étape plutôt que de
    recourir à un thread séparé."""
    def progress(etape: str, fraction: float) -> None:
        if on_progress:
            on_progress(etape, fraction)

    progress("Lecture du PDF…", 0.0)
    reader = PdfReader(str(filepath))
    nombre_pages = len(reader.pages)
    pages_texte = []
    for i, page in enumerate(reader.pages):
        pages_texte.append(page.extract_text() or "")
        progress(f"Lecture du PDF… (page {i + 1}/{nombre_pages})", 0.4 * (i + 1) / max(nombre_pages, 1))

    progress("Découpage en passages…", 0.4)
    passages = _decouper_en_passages(pages_texte)
    if not passages:
        raise ValueError("Aucun texte n'a pu être extrait de ce PDF (scan sans OCR ?).")

    # Premier appel : charge le modèle d'embeddings (quelques secondes, plus
    # un éventuel téléchargement unique la toute première fois).
    progress("Calcul des embeddings…", 0.5)
    embeddings = encoder([texte for _, texte in passages])

    curseur = conn.execute(
        "INSERT INTO kb_documents (titre, fichier_source, nombre_pages) VALUES (?, ?, ?)",
        (titre, filepath.name, nombre_pages),
    )
    document_id = curseur.lastrowid

    for ordre, ((numero_page, texte), vecteur) in enumerate(zip(passages, embeddings)):
        conn.execute(
            "INSERT INTO kb_passages (document_id, page, ordre, texte, embedding) VALUES (?, ?, ?, ?, ?)",
            (document_id, numero_page, ordre, texte, vecteur.tobytes()),
        )
        if ordre % 20 == 0:
            progress(f"Enregistrement… ({ordre + 1}/{len(passages)})", 0.6 + 0.4 * ordre / len(passages))
    conn.commit()

    progress("Terminé", 1.0)
    return ImportSummary(titre=titre, nombre_pages=nombre_pages, nombre_passages=len(passages))
