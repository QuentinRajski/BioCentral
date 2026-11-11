"""
Estimation de l'incertitude de mesure par l'approche « CIQ + EEQ » (dite
descendante), telle que décrite dans le guide Nordtest TR 537 et reprise dans
son principe par le SH GTA 14 :

    u(Rw)    = CV de fidélité intermédiaire, tiré du contrôle interne (CIQ)
    u(biais) = √( RMS_biais² + u(Cref)² )
               RMS_biais = √( Σ biais_i² / n )   biais relatifs observés aux EEQ
               u(Cref)   = incertitude moyenne des valeurs assignées des EEQ
    u_c      = √( u(Rw)² + u(biais)² )
    U        = k · u_c            (k = 2 : niveau de confiance d'environ 95 %)

Toutes les grandeurs sont relatives, exprimées en %.
Ce module ne dépend ni de PySide6 ni de la base.
"""
import math
from dataclasses import dataclass


@dataclass
class ResultatIncertitude:
    u_fidelite: float          # u(Rw), %
    rms_biais: float           # %
    u_cref: float              # %
    u_biais: float             # %
    u_composee: float          # %
    k: float
    u_elargie: float           # %
    n_eeq: int


def incertitude_ciq_eeq(
    cv_fidelite: float, biais_eeq: list[float], u_cref: float = 0.0, k: float = 2.0,
) -> ResultatIncertitude:
    """
    cv_fidelite : CV de fidélité intermédiaire (%), idéalement sur plusieurs mois de CIQ.
    biais_eeq   : biais relatifs (%) observés à chaque EEQ = 100 × (résultat - cible) / cible.
    u_cref      : incertitude-type moyenne (%) des valeurs assignées (0 si inconnue).
    """
    if cv_fidelite is None or cv_fidelite < 0:
        raise ValueError("Le CV de fidélité intermédiaire doit être un nombre positif.")
    if u_cref is None or u_cref < 0:
        raise ValueError("L'incertitude des valeurs assignées doit être un nombre positif ou nul.")
    if k <= 0:
        raise ValueError("Le facteur d'élargissement k doit être strictement positif.")
    biais = [float(b) for b in biais_eeq if b is not None]
    rms = math.sqrt(sum(b * b for b in biais) / len(biais)) if biais else 0.0
    u_biais = math.sqrt(rms ** 2 + u_cref ** 2)
    u_c = math.sqrt(cv_fidelite ** 2 + u_biais ** 2)
    return ResultatIncertitude(
        u_fidelite=cv_fidelite, rms_biais=rms, u_cref=u_cref, u_biais=u_biais,
        u_composee=u_c, k=k, u_elargie=k * u_c, n_eeq=len(biais),
    )


def sigma(erreur_totale_admissible: float | None, biais_pourcent: float | None, cv: float | None) -> float | None:
    """Nombre de sigma d'une méthode : (ETa - |biais|) / CV, toutes grandeurs en %."""
    if erreur_totale_admissible is None or cv is None or cv <= 0:
        return None
    return (erreur_totale_admissible - abs(biais_pourcent or 0.0)) / cv


def erreur_totale(biais_pourcent: float | None, cv: float | None, z: float = 1.65) -> float | None:
    """Erreur totale observée : |biais| + 1.65 × CV (en %)."""
    if cv is None:
        return None
    return abs(biais_pourcent or 0.0) + z * cv
