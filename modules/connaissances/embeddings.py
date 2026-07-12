"""
Chargement du modèle d'embeddings multilingue partagé par l'import et la
recherche (module Base de connaissances). Chargé une seule fois par
processus — l'initialisation prend une à deux secondes, à ne pas répéter à
chaque passage importé ou à chaque recherche.

Le modèle est téléchargé une seule fois (~120 Mo) et mis en cache par
sentence-transformers/huggingface_hub dans le dossier utilisateur ; les
lancements suivants le rechargent depuis ce cache, sans connexion réseau.
"""
import numpy as np

MODELE_NOM = "paraphrase-multilingual-MiniLM-L12-v2"

_modele = None


def get_modele():
    global _modele
    if _modele is None:
        from sentence_transformers import SentenceTransformer
        _modele = SentenceTransformer(MODELE_NOM)
    return _modele


def encoder(textes: list[str]) -> np.ndarray:
    """Encode une liste de textes en vecteurs (n, dim) float32, normalisés
    (norme L2) : la similarité cosinus se calcule alors par simple produit
    scalaire, sans division supplémentaire au moment de la recherche."""
    vecteurs = get_modele().encode(textes, normalize_embeddings=True, convert_to_numpy=True)
    return vecteurs.astype(np.float32)
