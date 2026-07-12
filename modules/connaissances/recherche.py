"""
Écran de recherche du module Base de connaissances. Aucune génération de
texte : la recherche vectorielle sert uniquement à retrouver les passages
les plus proches sémantiquement de la question posée, affichés tels quels
avec leur source exacte (titre du document + page).
"""
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QTextBrowser
from PySide6.QtCore import Qt

from .embeddings import encoder

SCORE_MINIMAL = 0.35
NOMBRE_RESULTATS_MAX = 15


def rechercher(conn, question: str, document_ids: set[int] | None = None) -> list[dict]:
    """Retourne les passages les plus proches de la question, triés par score
    de similarité cosinus décroissant, limités à NOMBRE_RESULTATS_MAX et
    filtrés sous SCORE_MINIMAL (évite d'afficher des passages hors-sujet
    juste pour remplir la liste). document_ids=None = tous les documents ;
    un ensemble vide (tous décochés) ne retourne volontairement rien."""
    if document_ids is not None and not document_ids:
        return []

    if document_ids is None:
        rows = conn.execute(
            "SELECT p.page, p.texte, p.embedding, d.titre "
            "FROM kb_passages p JOIN kb_documents d ON d.id = p.document_id"
        ).fetchall()
    else:
        placeholders = ",".join("?" * len(document_ids))
        rows = conn.execute(
            f"SELECT p.page, p.texte, p.embedding, d.titre "
            f"FROM kb_passages p JOIN kb_documents d ON d.id = p.document_id "
            f"WHERE p.document_id IN ({placeholders})",
            tuple(document_ids),
        ).fetchall()

    if not rows:
        return []

    vecteur_question = encoder([question])[0]
    embeddings = np.stack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    scores = embeddings @ vecteur_question

    resultats = [
        {"titre": titre, "page": page, "texte": texte, "score": float(score)}
        for (page, texte, _, titre), score in zip(rows, scores)
        if score >= SCORE_MINIMAL
    ]
    resultats.sort(key=lambda r: r["score"], reverse=True)
    return resultats[:NOMBRE_RESULTATS_MAX]


def _construire_texte_resultats(resultats: list[dict]) -> str:
    if not resultats:
        return "Aucun extrait suffisamment pertinent trouvé pour cette question."
    lignes = ["Voici mes extraits trouvés :", ""]
    for r in resultats:
        lignes.append(f"📖 {r['titre']} — page {r['page']}")
        lignes.append(f"\"{r['texte']}\"")
        lignes.append("")
    return "\n".join(lignes).rstrip()


class RechercheWidget(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.document_ids_filtre: set[int] | None = None  # None = tous les documents

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        titre = QLabel("Base de connaissances")
        titre.setObjectName("TitrePage")
        layout.addWidget(titre)

        ligne_recherche = QHBoxLayout()
        self.champ_recherche = QLineEdit()
        self.champ_recherche.setPlaceholderText("Poser une question ou entrer des mots-clés…")
        self.champ_recherche.returnPressed.connect(self.lancer_recherche)
        ligne_recherche.addWidget(self.champ_recherche, stretch=1)
        btn_rechercher = QPushButton("Rechercher")
        btn_rechercher.setObjectName("PrimaryButton")
        btn_rechercher.clicked.connect(self.lancer_recherche)
        ligne_recherche.addWidget(btn_rechercher)
        layout.addLayout(ligne_recherche)

        self.resultats = QTextBrowser()
        self.resultats.setObjectName("Card")
        layout.addWidget(self.resultats, stretch=1)

    def definir_filtre_documents(self, document_ids: set[int] | None) -> None:
        self.document_ids_filtre = document_ids

    def lancer_recherche(self):
        question = self.champ_recherche.text().strip()
        if not question:
            return
        resultats = rechercher(self.conn, question, self.document_ids_filtre)
        self.resultats.setPlainText(_construire_texte_resultats(resultats))
