"""
Comparaison de deux méthodes de dosage sur des échantillons appariés.

Convention : x = méthode de comparaison (référence, ancienne méthode),
             y = méthode évaluée (nouvelle méthode). Différence = y - x.

Analyses proposées (celles attendues dans un dossier de vérification/validation
de méthode, cf. CLSI EP09 et SH GTA 04) :
  - régression de Passing-Bablok (non paramétrique, robuste aux valeurs
    extrêmes, erreurs sur x ET y) avec IC à 95 % et test de linéarité Cusum ;
  - régression de Deming (erreurs sur x ET y, IC par jackknife) ;
  - régression linéaire simple des moindres carrés (à titre indicatif) ;
  - diagramme de Bland-Altman : biais moyen, limites d'agrément et leurs IC ;
  - corrélations de Pearson et de Spearman ;
  - tests appariés (t de Student, Wilcoxon).

Ce module ne dépend ni de PySide6 ni de la base.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as sps

EFFECTIF_MINIMAL = 3
EFFECTIF_RECOMMANDE = 40          # CLSI EP09
SEUIL_CUSUM_5_POURCENT = 1.36     # valeur critique de Kolmogorov-Smirnov à 5 %


@dataclass
class Estimation:
    """Une valeur estimée et son intervalle de confiance."""
    valeur: float
    ic_bas: float | None = None
    ic_haut: float | None = None

    def contient(self, reference: float) -> bool | None:
        if self.ic_bas is None or self.ic_haut is None:
            return None
        return self.ic_bas <= reference <= self.ic_haut


@dataclass
class ResultatRegression:
    methode: str
    pente: Estimation
    ordonnee: Estimation
    n: int
    # Passing-Bablok uniquement : test de linéarité Cusum
    cusum_statistique: float | None = None
    cusum_p: float | None = None
    lineaire: bool | None = None
    # Moindres carrés uniquement
    r2: float | None = None
    ecart_type_residuel: float | None = None

    def predire(self, x: float) -> float:
        return self.ordonnee.valeur + self.pente.valeur * x


@dataclass
class ResultatBlandAltman:
    mode: str                       # "absolu" (unités) ou "pourcent"
    n: int
    biais: Estimation
    ecart_type: float
    limite_basse: Estimation        # biais - 1.96 s
    limite_haute: Estimation        # biais + 1.96 s
    moyennes: list[float]
    differences: list[float]
    pente_tendance: float | None = None   # régression des différences sur les moyennes
    p_tendance: float | None = None
    p_normalite: float | None = None      # Shapiro-Wilk sur les différences


@dataclass
class ResultatCorrelation:
    pearson: Estimation
    p_pearson: float
    spearman: float
    p_spearman: float


@dataclass
class ResultatTestsApparies:
    difference_moyenne: float
    p_student: float | None
    p_wilcoxon: float | None


@dataclass
class AnalyseComparaison:
    n: int
    x: list[float]
    y: list[float]
    passing_bablok: ResultatRegression | None
    deming: ResultatRegression | None
    moindres_carres: ResultatRegression | None
    bland_altman: ResultatBlandAltman
    bland_altman_pourcent: ResultatBlandAltman | None
    correlation: ResultatCorrelation | None
    tests: ResultatTestsApparies
    avertissements: list[str] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# Préparation des données
# ------------------------------------------------------------------
def preparer_paires(xs, ys) -> tuple[np.ndarray, np.ndarray]:
    """Ne garde que les paires complètes (deux valeurs numériques finies)."""
    paires = []
    for a, b in zip(xs, ys):
        if a is None or b is None:
            continue
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fa) and math.isfinite(fb):
            paires.append((fa, fb))
    if len(paires) < EFFECTIF_MINIMAL:
        raise ValueError(
            f"Il faut au moins {EFFECTIF_MINIMAL} paires de résultats complètes pour comparer deux méthodes."
        )
    tableau = np.array(paires, dtype=float)
    return tableau[:, 0], tableau[:, 1]


# ------------------------------------------------------------------
# Régressions
# ------------------------------------------------------------------
def passing_bablok(x, y, alpha: float = 0.05) -> ResultatRegression:
    """
    Régression de Passing & Bablok (1983). Pente = médiane décalée des pentes de
    toutes les paires de points ; ordonnée = médiane des y - pente·x. Les IC
    sont ceux de la publication d'origine (rangs autour de la médiane).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < EFFECTIF_MINIMAL:
        raise ValueError("Effectif insuffisant pour la régression de Passing-Bablok.")

    i, j = np.triu_indices(n, k=1)
    dx = x[j] - x[i]
    dy = y[j] - y[i]
    with np.errstate(divide="ignore", invalid="ignore"):
        pentes = dy / dx                      # dx = 0 et dy != 0 -> ±inf ; 0/0 -> nan
    pentes = pentes[~np.isnan(pentes)]        # points confondus : pente indéfinie
    pentes = pentes[pentes != -1]             # pentes de -1 exclues (publication d'origine)
    nombre = len(pentes)
    if nombre == 0:
        raise ValueError("Les données ne permettent pas de calculer une pente (valeurs toutes identiques).")
    pentes.sort()
    decalage = int(np.sum(pentes < -1))       # K : nombre de pentes inférieures à -1

    def rang(k: int) -> float:
        """Pente de rang k (numérotation à partir de 1), décalée de K, bornée au tableau."""
        return float(pentes[min(max(k + decalage, 1), nombre) - 1])

    if nombre % 2:
        pente = rang((nombre + 1) // 2)
    else:
        pente = 0.5 * (rang(nombre // 2) + rang(nombre // 2 + 1))
    if not math.isfinite(pente) or pente == 0:
        raise ValueError("Les données ne permettent pas d'estimer une pente exploitable "
                         "(trop d'ex æquo ou résultats sans relation entre les deux méthodes).")

    quantile = sps.norm.ppf(1 - alpha / 2)
    c = quantile * math.sqrt(n * (n - 1) * (2 * n + 5) / 18)
    m1 = int(round((nombre - c) / 2))
    m2 = nombre - m1 + 1
    pente_bas, pente_haut = rang(m1), rang(m2)

    ordonnee = float(np.median(y - pente * x))
    ordonnee_bas = float(np.median(y - pente_haut * x)) if math.isfinite(pente_haut) else None
    ordonnee_haut = float(np.median(y - pente_bas * x)) if math.isfinite(pente_bas) else None

    statistique, p_cusum, lineaire = _test_cusum(x, y, pente, ordonnee)

    return ResultatRegression(
        methode="Passing-Bablok",
        pente=Estimation(pente,
                         pente_bas if math.isfinite(pente_bas) else None,
                         pente_haut if math.isfinite(pente_haut) else None),
        ordonnee=Estimation(ordonnee, ordonnee_bas, ordonnee_haut),
        n=n, cusum_statistique=statistique, cusum_p=p_cusum, lineaire=lineaire,
    )


def _test_cusum(x: np.ndarray, y: np.ndarray, pente: float, ordonnee: float):
    """Test de linéarité de Passing-Bablok : somme cumulée des signes des résidus,
    les points étant ordonnés le long de la droite. Retourne (statistique, p, linéaire)."""
    residus = y - (ordonnee + pente * x)
    au_dessus = int(np.sum(residus > 0))
    en_dessous = int(np.sum(residus < 0))
    if au_dessus == 0 or en_dessous == 0:
        return None, None, None
    scores = np.where(residus > 0, math.sqrt(en_dessous / au_dessus),
                      np.where(residus < 0, -math.sqrt(au_dessus / en_dessous), 0.0))
    projection = (y + x / pente) / math.sqrt(1 + 1 / pente ** 2)
    ordre = np.argsort(projection, kind="stable")
    cumul = np.cumsum(scores[ordre])
    statistique = float(np.max(np.abs(cumul)) / math.sqrt(en_dessous + 1))
    p = float(sps.kstwobign.sf(statistique))
    return statistique, p, statistique < SEUIL_CUSUM_5_POURCENT


def _deming_ponctuel(x: np.ndarray, y: np.ndarray, rapport: float) -> tuple[float, float]:
    mx, my = x.mean(), y.mean()
    sxx = float(np.sum((x - mx) ** 2))
    syy = float(np.sum((y - my) ** 2))
    sxy = float(np.sum((x - mx) * (y - my)))
    if sxy == 0:
        raise ValueError("Covariance nulle entre les deux méthodes : régression de Deming impossible.")
    pente = (syy - rapport * sxx + math.sqrt((syy - rapport * sxx) ** 2 + 4 * rapport * sxy ** 2)) / (2 * sxy)
    return pente, my - pente * mx


def deming(x, y, rapport_variances: float = 1.0, alpha: float = 0.05) -> ResultatRegression:
    """
    Régression de Deming. `rapport_variances` = variance d'erreur de y / variance
    d'erreur de x (1 = les deux méthodes ont la même imprécision : régression
    orthogonale). IC par jackknife (Linnet), loi de Student à n - 2 ddl.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < EFFECTIF_MINIMAL:
        raise ValueError("Effectif insuffisant pour la régression de Deming.")
    if rapport_variances <= 0:
        raise ValueError("Le rapport des variances d'erreur doit être strictement positif.")
    pente, ordonnee = _deming_ponctuel(x, y, rapport_variances)

    ic_pente = ic_ordonnee = (None, None)
    if n > 3:
        masque = np.ones(n, dtype=bool)
        pseudo_pente, pseudo_ordonnee = [], []
        try:
            for k in range(n):
                masque[k] = False
                b_k, a_k = _deming_ponctuel(x[masque], y[masque], rapport_variances)
                masque[k] = True
                pseudo_pente.append(n * pente - (n - 1) * b_k)
                pseudo_ordonnee.append(n * ordonnee - (n - 1) * a_k)
            t = sps.t.ppf(1 - alpha / 2, n - 2)
            es_pente = float(np.std(pseudo_pente, ddof=1) / math.sqrt(n))
            es_ordonnee = float(np.std(pseudo_ordonnee, ddof=1) / math.sqrt(n))
            ic_pente = (pente - t * es_pente, pente + t * es_pente)
            ic_ordonnee = (ordonnee - t * es_ordonnee, ordonnee + t * es_ordonnee)
        except ValueError:
            pass  # un sous-échantillon dégénéré : on garde l'estimation ponctuelle sans IC

    return ResultatRegression(
        methode="Deming",
        pente=Estimation(float(pente), *ic_pente),
        ordonnee=Estimation(float(ordonnee), *ic_ordonnee),
        n=n,
    )


def moindres_carres(x, y, alpha: float = 0.05) -> ResultatRegression:
    """Régression linéaire simple (suppose x sans erreur : à titre indicatif seulement)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < EFFECTIF_MINIMAL or np.all(x == x[0]):
        raise ValueError("Effectif ou étendue insuffisants pour une régression linéaire.")
    res = sps.linregress(x, y)
    t = sps.t.ppf(1 - alpha / 2, n - 2)
    residus = y - (res.intercept + res.slope * x)
    return ResultatRegression(
        methode="Moindres carrés",
        pente=Estimation(float(res.slope), float(res.slope - t * res.stderr), float(res.slope + t * res.stderr)),
        ordonnee=Estimation(float(res.intercept),
                            float(res.intercept - t * res.intercept_stderr),
                            float(res.intercept + t * res.intercept_stderr)),
        n=n,
        r2=float(res.rvalue ** 2),
        ecart_type_residuel=float(math.sqrt(np.sum(residus ** 2) / (n - 2))),
    )


# ------------------------------------------------------------------
# Bland-Altman, corrélation, tests appariés
# ------------------------------------------------------------------
def bland_altman(x, y, mode: str = "absolu", alpha: float = 0.05) -> ResultatBlandAltman:
    """
    Différences (y - x) en fonction de la moyenne des deux méthodes.
    mode="pourcent" : différences exprimées en % de la moyenne (les paires de
    moyenne nulle sont écartées). IC des limites d'agrément : approximation de
    Bland & Altman (1999), Var(limite) ≈ s² · (1/n + 1.96² / (2(n - 1))).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    moyennes = (x + y) / 2
    differences = y - x
    if mode == "pourcent":
        garde = moyennes != 0
        moyennes, differences = moyennes[garde], 100 * differences[garde] / moyennes[garde]
    elif mode != "absolu":
        raise ValueError("mode doit valoir 'absolu' ou 'pourcent'.")
    n = len(differences)
    if n < EFFECTIF_MINIMAL:
        raise ValueError("Effectif insuffisant pour un diagramme de Bland-Altman.")

    biais = float(differences.mean())
    s = float(differences.std(ddof=1))
    t = float(sps.t.ppf(1 - alpha / 2, n - 1))
    es_biais = s / math.sqrt(n)
    es_limite = s * math.sqrt(1 / n + 1.96 ** 2 / (2 * (n - 1)))
    basse, haute = biais - 1.96 * s, biais + 1.96 * s

    pente_tendance = p_tendance = None
    if not np.all(moyennes == moyennes[0]) and s > 0:
        tendance = sps.linregress(moyennes, differences)
        pente_tendance, p_tendance = float(tendance.slope), float(tendance.pvalue)

    p_normalite = None
    if 3 <= n <= 5000 and s > 0:
        p_normalite = float(sps.shapiro(differences).pvalue)

    return ResultatBlandAltman(
        mode=mode, n=n,
        biais=Estimation(biais, biais - t * es_biais, biais + t * es_biais),
        ecart_type=s,
        limite_basse=Estimation(basse, basse - t * es_limite, basse + t * es_limite),
        limite_haute=Estimation(haute, haute - t * es_limite, haute + t * es_limite),
        moyennes=[float(v) for v in moyennes],
        differences=[float(v) for v in differences],
        pente_tendance=pente_tendance, p_tendance=p_tendance, p_normalite=p_normalite,
    )


def correlation(x, y, alpha: float = 0.05) -> ResultatCorrelation | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < EFFECTIF_MINIMAL or np.all(x == x[0]) or np.all(y == y[0]):
        return None
    r, p = sps.pearsonr(x, y)
    r = float(r)
    ic = (None, None)
    if n > 3 and abs(r) < 1:
        z = math.atanh(r)
        demi = sps.norm.ppf(1 - alpha / 2) / math.sqrt(n - 3)
        ic = (math.tanh(z - demi), math.tanh(z + demi))
    rho, p_rho = sps.spearmanr(x, y)
    return ResultatCorrelation(Estimation(r, *ic), float(p), float(rho), float(p_rho))


def tests_apparies(x, y) -> ResultatTestsApparies:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    differences = y - x
    p_student = p_wilcoxon = None
    if len(differences) >= 2 and differences.std(ddof=1) > 0:
        p_student = float(sps.ttest_rel(y, x).pvalue)
    if np.any(differences != 0):
        try:
            p_wilcoxon = float(sps.wilcoxon(differences).pvalue)
        except ValueError:
            p_wilcoxon = None
    return ResultatTestsApparies(float(differences.mean()), p_student, p_wilcoxon)


# ------------------------------------------------------------------
# Analyse complète + interprétation
# ------------------------------------------------------------------
def analyser(xs, ys, rapport_variances: float = 1.0) -> AnalyseComparaison:
    """Lance toutes les analyses sur les paires fournies. Une analyse impossible
    sur ces données (ex. régression sur des valeurs toutes identiques) est
    simplement absente du résultat et signalée dans `avertissements`."""
    x, y = preparer_paires(xs, ys)
    n = len(x)
    avertissements: list[str] = []
    if n < EFFECTIF_RECOMMANDE:
        avertissements.append(
            f"Effectif de {n} paires : au moins {EFFECTIF_RECOMMANDE} échantillons répartis sur "
            "l'étendue de mesure sont recommandés (CLSI EP09) ; les intervalles de confiance sont larges."
        )

    def tenter(fonction, *args):
        try:
            return fonction(*args)
        except ValueError as e:
            avertissements.append(str(e))
            return None

    pb = tenter(passing_bablok, x, y)
    dem = tenter(deming, x, y, rapport_variances)
    mc = tenter(moindres_carres, x, y)
    ba = bland_altman(x, y, "absolu")
    ba_pct = tenter(bland_altman, x, y, "pourcent")
    corr = correlation(x, y)
    tests = tests_apparies(x, y)

    if corr is not None and corr.pearson.valeur < 0.975:
        avertissements.append(
            f"r = {corr.pearson.valeur:.3f} (< 0.975) : l'étendue des concentrations est peut-être trop "
            "étroite pour une régression fiable — privilégier Passing-Bablok ou Deming aux moindres carrés."
        )

    analyse = AnalyseComparaison(
        n=n, x=[float(v) for v in x], y=[float(v) for v in y],
        passing_bablok=pb, deming=dem, moindres_carres=mc,
        bland_altman=ba, bland_altman_pourcent=ba_pct, correlation=corr, tests=tests,
        avertissements=avertissements,
    )
    analyse.conclusions = _conclure(analyse)
    return analyse


def _conclure(a: AnalyseComparaison) -> list[str]:
    """Phrases d'interprétation, dans l'ordre où un biologiste lit un dossier."""
    lignes: list[str] = []
    reg = a.passing_bablok or a.deming
    if reg is not None:
        pente_ok = reg.pente.contient(1.0)
        ordonnee_ok = reg.ordonnee.contient(0.0)
        if pente_ok is True:
            lignes.append(f"{reg.methode} — l'IC à 95 % de la pente contient 1 : "
                          "pas de biais proportionnel significatif.")
        elif pente_ok is False:
            lignes.append(f"{reg.methode} — l'IC à 95 % de la pente ne contient pas 1 : "
                          "biais proportionnel significatif entre les deux méthodes.")
        if ordonnee_ok is True:
            lignes.append(f"{reg.methode} — l'IC à 95 % de l'ordonnée à l'origine contient 0 : "
                          "pas de biais constant significatif.")
        elif ordonnee_ok is False:
            lignes.append(f"{reg.methode} — l'IC à 95 % de l'ordonnée à l'origine ne contient pas 0 : "
                          "biais constant significatif entre les deux méthodes.")
    if a.passing_bablok is not None and a.passing_bablok.lineaire is not None:
        if a.passing_bablok.lineaire:
            lignes.append("Test de linéarité (Cusum) non significatif : la relation entre les deux "
                          "méthodes peut être considérée comme linéaire.")
        else:
            lignes.append("Test de linéarité (Cusum) significatif : la relation n'est pas linéaire, "
                          "la droite de Passing-Bablok ne doit pas être utilisée telle quelle.")
    biais_ok = a.bland_altman.biais.contient(0.0)
    if biais_ok is True:
        lignes.append("Bland-Altman — l'IC à 95 % du biais moyen contient 0 : "
                      "pas de différence systématique significative.")
    elif biais_ok is False:
        sens = "plus hauts" if a.bland_altman.biais.valeur > 0 else "plus bas"
        lignes.append("Bland-Altman — l'IC à 95 % du biais moyen ne contient pas 0 : la méthode évaluée "
                      f"donne des résultats significativement {sens} que la méthode de comparaison.")
    if a.bland_altman.p_tendance is not None and a.bland_altman.p_tendance < 0.05:
        lignes.append("Bland-Altman — les différences varient avec la concentration (tendance "
                      "significative) : interpréter plutôt le diagramme en pourcentage.")
    return lignes


def conformite_limite(ba: ResultatBlandAltman, limite: float) -> tuple[int, int, bool]:
    """
    Compare les différences à une limite d'acceptation ± `limite` (dans l'unité
    du diagramme : unités ou %). Retourne (nombre de différences dans la limite,
    effectif total, True si les limites d'agrément sont entièrement dans ±limite).
    """
    dans = sum(1 for d in ba.differences if abs(d) <= limite)
    agrement_ok = ba.limite_basse.valeur >= -limite and ba.limite_haute.valeur <= limite
    return dans, ba.n, agrement_ok
