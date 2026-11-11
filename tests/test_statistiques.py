"""Tests des calculs statistiques (sans interface ni base)."""
import math
import unittest

import numpy as np

from core import comparaison_methodes as cm
from core import fidelite, incertitude, intervalle_reference, westgard
from core.formatage import date_fr, fmt, parse_date, parse_nombre
from core.stats import compute_stats


class TestWestgard(unittest.TestCase):
    def test_regles_individuelles(self):
        self.assertEqual(westgard.evaluer([0.5]), [[]])
        self.assertEqual(westgard.evaluer([2.5])[-1], ["1_2s"])
        self.assertEqual(westgard.evaluer([-3.2])[-1], ["1_3s"])          # 1-3s remplace 1-2s
        self.assertIn("2_2s", westgard.evaluer([2.1, 2.2])[-1])
        self.assertNotIn("2_2s", westgard.evaluer([2.1, -2.2])[-1])
        self.assertIn("R_4s", westgard.evaluer([2.1, -2.2])[-1])
        self.assertIn("4_1s", westgard.evaluer([1.1, 1.2, 1.5, 1.1])[-1])
        self.assertNotIn("4_1s", westgard.evaluer([1.1, 1.2, 0.9, 1.1])[-1])
        self.assertIn("10_x", westgard.evaluer([0.1] * 10)[-1])
        self.assertNotIn("10_x", westgard.evaluer([0.1] * 9 + [-0.1])[-1])

    def test_tendance_uniquement_si_active(self):
        z = [-1.5, -1, -0.5, 0, 0.5, 1, 1.5]
        self.assertNotIn("7_T", westgard.evaluer(z)[-1])
        self.assertIn("7_T", westgard.evaluer(z, westgard.REGLES_INTRA)[-1])

    def test_regle_desactivee(self):
        self.assertEqual(westgard.evaluer([2.5], ["1_3s"])[-1], [])

    def test_statut(self):
        self.assertEqual(westgard.statut([]), westgard.OK)
        self.assertEqual(westgard.statut(["1_2s"]), westgard.ALERTE)
        self.assertEqual(westgard.statut(["1_2s", "2_2s"]), westgard.REJET)

    def test_inter_niveaux(self):
        r = westgard.evaluer_inter_niveaux({"a": {1: 2.3, 2: 2.1}, "b": {1: 2.3, 2: -2.4}, "c": {1: 5.0}})
        self.assertEqual(r["a"], ["2_2s_inter"])
        self.assertEqual(r["b"], ["R_4s_inter"])
        self.assertNotIn("c", r)                     # un seul niveau : jamais concerné

    def test_cles_de_serie(self):
        self.assertEqual(westgard.cles_de_serie(["2026-01-01 08:00", "2026-01-01 14:00", "2026-01-02 08:00"]),
                         [("2026-01-01", 0), ("2026-01-01", 1), ("2026-01-02", 0)])

    def test_scores_z(self):
        self.assertEqual(westgard.scores_z([12, 8], 10, 2), [1.0, -1.0])
        with self.assertRaises(ValueError):
            westgard.scores_z([1], 0, 0)


class TestComparaison(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.x = rng.uniform(5, 200, 60)
        self.y = 1.04 * self.x + 1.5 + rng.normal(0, 2, 60)

    def test_passing_bablok_relation_exacte(self):
        r = cm.passing_bablok([1, 2, 3, 4, 5, 6], [3, 5, 7, 9, 11, 13])
        self.assertAlmostEqual(r.pente.valeur, 2.0)
        self.assertAlmostEqual(r.ordonnee.valeur, 1.0)

    def test_passing_bablok_symetrie(self):
        """Propriété de la méthode : échanger X et Y inverse la pente."""
        directe = cm.passing_bablok(self.x, self.y).pente.valeur
        inverse = cm.passing_bablok(self.y, self.x).pente.valeur
        self.assertAlmostEqual(directe * inverse, 1.0, places=6)

    def test_passing_bablok_ic_contient_estimation(self):
        r = cm.passing_bablok(self.x, self.y)
        self.assertLess(r.pente.ic_bas, r.pente.valeur)
        self.assertLess(r.pente.valeur, r.pente.ic_haut)
        self.assertTrue(r.pente.contient(1.04))

    def test_deming_lambda_1_est_la_composante_principale(self):
        r = cm.deming(self.x, self.y, 1.0)
        valeurs, vecteurs = np.linalg.eigh(np.cov(self.x, self.y))
        v = vecteurs[:, -1]
        self.assertAlmostEqual(r.pente.valeur, v[1] / v[0], places=8)

    def test_bland_altman(self):
        x = [10, 20, 30, 40]
        y = [11, 22, 29, 42]
        r = cm.bland_altman(x, y)
        diff = [1, 2, -1, 2]
        moyenne = sum(diff) / 4
        s = math.sqrt(sum((d - moyenne) ** 2 for d in diff) / 3)
        self.assertAlmostEqual(r.biais.valeur, moyenne)
        self.assertAlmostEqual(r.ecart_type, s)
        self.assertAlmostEqual(r.limite_haute.valeur, moyenne + 1.96 * s)
        self.assertEqual(r.moyennes, [10.5, 21, 29.5, 41])

    def test_analyse_complete_et_conclusions(self):
        a = cm.analyser(self.x, self.y)
        self.assertEqual(a.n, 60)
        self.assertIsNotNone(a.passing_bablok)
        self.assertTrue(any("biais" in c for c in a.conclusions))

    def test_paires_incompletes_ignorees(self):
        x, y = cm.preparer_paires([1, None, 3, "a", 5, 6], [1, 2, None, 4, 5, 6])
        self.assertEqual(list(x), [1.0, 5.0, 6.0])

    def test_effectif_insuffisant(self):
        with self.assertRaises(ValueError):
            cm.analyser([1, 2], [1, 2])

    def test_conformite_limite(self):
        ba = cm.bland_altman([10, 20, 30, 40], [10.5, 20, 31, 40])
        dans, n, _ = cm.conformite_limite(ba, 0.6)
        self.assertEqual((dans, n), (3, 4))


class TestFidelite(unittest.TestCase):
    def test_anova_exemple_calcule_a_la_main(self):
        r = fidelite.composantes_variance({"j1": [1, 2, 3], "j2": [2, 3, 4], "j3": [3, 4, 5]})
        # CM intra = 1 ; CM inter = 3 ; n0 = 3 -> s_inter² = (3 - 1) / 3
        self.assertAlmostEqual(r.s_repetabilite, 1.0)
        self.assertAlmostEqual(r.s_inter_series, math.sqrt(2 / 3))
        self.assertAlmostEqual(r.s_fidelite_intermediaire, math.sqrt(1 + 2 / 3))
        self.assertAlmostEqual(r.cv_repetabilite, 100 / 3)

    def test_inter_series_negatif_ramene_a_zero(self):
        r = fidelite.composantes_variance({"a": [1, 5], "b": [1, 5], "c": [1, 5]})
        self.assertEqual(r.s_inter_series, 0.0)

    def test_serie_unique(self):
        r = fidelite.statistiques_serie([10, 10.2, 9.8, 10.1, 9.9])
        self.assertAlmostEqual(r.moyenne, 10.0)
        self.assertAlmostEqual(r.ecart_type, math.sqrt(0.025))
        lo, hi = r.ecart_type_ic
        self.assertLess(lo, r.ecart_type)
        self.assertLess(r.ecart_type, hi)

    def test_justesse(self):
        j = fidelite.justesse([102, 98, 104, 100], 100)
        self.assertAlmostEqual(j.biais, 1.0)
        self.assertAlmostEqual(j.biais_pourcent, 1.0)


class TestIntervalleReference(unittest.TestCase):
    def test_rangs_clsi_n120(self):
        """Pour n = 120, le CLSI EP28-A3c donne les rangs 1 et 7 pour l'IC à 90 % de la limite basse."""
        r = intervalle_reference.estimer(range(1, 121))
        self.assertEqual(r.methode_ic, "rangs")
        self.assertEqual(r.ic_basse, (1.0, 7.0))
        self.assertEqual(r.ic_haute, (114.0, 120.0))
        self.assertAlmostEqual(r.limite_basse, 3.025)     # rang 0.025 × 121 = 3.025

    def test_bootstrap_entre_40_et_119(self):
        r = intervalle_reference.estimer(range(1, 61))
        self.assertEqual(r.methode_ic, "bootstrap")
        self.assertTrue(r.avertissements)

    def test_effectif_insuffisant(self):
        r = intervalle_reference.estimer(range(10))
        self.assertIsNone(r.limite_basse)

    def test_verification(self):
        v = intervalle_reference.verifier(list(range(1, 21)), 2, 19)
        self.assertEqual((v.n_sous, v.n_sur), (1, 1))
        self.assertTrue(v.verdict)                        # 10 % hors : accepté
        v = intervalle_reference.verifier(list(range(1, 21)), 3, 19)
        self.assertFalse(v.verdict)                       # 15 % hors : refusé
        self.assertIsNone(intervalle_reference.verifier([1, 2], 0, 3).verdict)


class TestIncertitude(unittest.TestCase):
    def test_nordtest(self):
        r = incertitude.incertitude_ciq_eeq(3.0, [3.0, -4.0], u_cref=0.0, k=2)
        rms = math.sqrt((9 + 16) / 2)
        self.assertAlmostEqual(r.rms_biais, rms)
        self.assertAlmostEqual(r.u_elargie, 2 * math.sqrt(9 + rms ** 2))

    def test_sigma(self):
        self.assertAlmostEqual(incertitude.sigma(10, 1, 1.5), 6.0)
        self.assertIsNone(incertitude.sigma(None, 1, 1.5))


class TestStatsV1(unittest.TestCase):
    """Les règles validées en v1 sont inchangées."""
    def test_sous_seuil_exclu_de_la_moyenne_mais_pas_des_rangs(self):
        r = compute_stats([(0.3, "sous_seuil"), (2.0, "valide"), (4.0, "valide")])
        self.assertEqual(r.n, 3)
        self.assertEqual(r.moyenne, 3.0)
        self.assertEqual(r.mediane, 2.0)
        self.assertEqual(r.minimum, 0.3)


class TestFormatage(unittest.TestCase):
    def test_parse_nombre(self):
        self.assertEqual(parse_nombre("4,8"), 4.8)
        self.assertEqual(parse_nombre("1 234,5"), 1234.5)
        self.assertEqual(parse_nombre("1.234,5"), 1234.5)
        self.assertEqual(parse_nombre("1,234.5"), 1234.5)
        self.assertIsNone(parse_nombre("<0.3"))
        self.assertIsNone(parse_nombre(""))
        self.assertIsNone(parse_nombre(True))

    def test_fmt(self):
        self.assertEqual(fmt(5.123456), "5.123")
        self.assertEqual(fmt(0.00123456), "0.001235")
        self.assertEqual(fmt(2.0), "2")
        self.assertEqual(fmt(None), "—")

    def test_dates(self):
        self.assertEqual(date_fr("2026-03-04"), "04/03/2026")
        self.assertEqual(parse_date("04/03/2026 08:15").hour, 8)
        self.assertEqual(parse_date("2026-03-04").day, 4)
        self.assertIsNone(parse_date("n'importe quoi"))


if __name__ == "__main__":
    unittest.main()
