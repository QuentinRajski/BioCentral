"""Tests de la base, des migrations et des imports (base temporaire isolée)."""
import sqlite3
from datetime import datetime
from pathlib import Path

import openpyxl

from tests.outils import TestAvecBase

FIXTURES = Path(__file__).parent / "fixtures"


def _structure(conn) -> dict:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    structure = {t: sorted((c[1], c[2].upper(), c[3], c[5]) for c in conn.execute(f"PRAGMA table_info({t})"))
                 for t in tables}
    structure["__index__"] = sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"))
    return structure


class TestBase(TestAvecBase):
    def test_base_neuve_et_base_migree_identiques(self):
        """schema.sql (base neuve) et migrations (base v1 mise à niveau) doivent concorder."""
        ancienne = sqlite3.connect(":memory:")
        ancienne.executescript((FIXTURES / "schema_v1.sql").read_text(encoding="utf-8"))
        self.database.run_migrations(ancienne)
        self.assertEqual(_structure(ancienne), _structure(self.conn))
        versions = dict(ancienne.execute("SELECT cle, valeur FROM app_metadata"))
        self.assertEqual(versions, dict(self.conn.execute("SELECT cle, valeur FROM app_metadata")))
        ancienne.close()

    def test_migration_conserve_les_donnees_et_sauvegarde(self):
        self.conn.close()
        chemin = self.database.get_db_path()
        chemin.unlink()
        v1 = sqlite3.connect(chemin)
        v1.executescript((FIXTURES / "schema_v1.sql").read_text(encoding="utf-8"))
        v1.execute("INSERT INTO qc_parametres (nom) VALUES ('LH')")
        v1.commit()
        v1.close()
        self.conn = self.database.get_connection()
        self.assertEqual(self.conn.execute("SELECT nom FROM qc_parametres").fetchall(), [("LH",)])
        self.assertTrue(any("avant_migration" in p.name for p in self.database.get_backup_dir().iterdir()))

    def test_export_puis_verification(self):
        cible = self.dossier / "copie.db"
        self.database.export_database(cible, self.conn)
        self.database.verifier_fichier_base(cible)       # ne lève pas

    def test_import_refuse_un_fichier_quelconque(self):
        faux = self.dossier / "faux.db"
        faux.write_bytes(b"ceci n'est pas une base")
        with self.assertRaises(ValueError):
            self.database.import_database(faux)
        autre = self.dossier / "autre.db"
        c = sqlite3.connect(autre)
        c.execute("CREATE TABLE t (x)")
        c.commit()
        c.close()
        with self.assertRaises(ValueError):
            self.database.verifier_fichier_base(autre)

    def test_sauvegarde_quotidienne_une_seule_fois(self):
        self.assertIsNotNone(self.database.sauvegarde_quotidienne(self.conn))
        self.assertIsNone(self.database.sauvegarde_quotidienne(self.conn))


def _classeur(chemin: Path, feuilles: dict[str, list[list]]):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nom, lignes in feuilles.items():
        ws = wb.create_sheet(nom)
        for l in lignes:
            ws.append(l)
    wb.save(chemin)


ENTETE = ["Patient", "Né(e) le", "Sexe", "N° demande", "Date de prél.", "Corres.", "Docteur", "TSH"]


class TestImportPopulation(TestAvecBase):
    def setUp(self):
        super().setUp()
        from modules.qualite import import_logic
        self.il = import_logic
        self.fichier = self.dossier / "export.xlsx"
        donnees = [
            ["Titre de l'export"],
            ENTETE,
            ["X", datetime(1980, 5, 1), "Féminin", "1001", datetime(2025, 3, 1, 9, 0), "c", "d", 2.5],
            ["X", "01/05/1990", "F", 1002.0, "02/03/2025", "c", "d", "3,4"],        # texte : date, nombre
            ["X", datetime(2015, 1, 1), "M", "1003", datetime(2025, 3, 3), "c", "d", "<0.3"],
            ["X", datetime(1970, 1, 1), "Homme", "1004", datetime(2025, 3, 4), "c", "d", 300],  # hors domaine
            ["X", datetime(1960, 1, 1), "Masculin", "1005", datetime(2025, 3, 5), "c", "d", "Res annulé"],
            [None, None, None, "CTRL", datetime(2025, 3, 5), None, None, 1.0],      # contrôle machine
            ["X", datetime(1960, 1, 1), "Inconnu", "1006", datetime(2025, 3, 5), "c", "d", 4.0],  # sexe illisible
        ]
        # Feuille parasite en premier, pas de « Total » : la v1 plantait sur ce cas.
        _classeur(self.fichier, {"Notes": [["rien"]], "Données": donnees})

    def test_apercu_et_import(self):
        # sans feuille « Total », c'est la première feuille qui est lue : ici, illisible
        with self.assertRaises(ValueError):
            self.il.apercu_fichier(self.fichier)
        _classeur(self.fichier, {"Total": openpyxl.load_workbook(self.fichier)["Données"].values,
                                 "Autre": [["x"]]})
        apercu = self.il.apercu_fichier(self.fichier)
        self.assertEqual(apercu.parametre, "TSH")
        self.assertEqual((apercu.n_patients, apercu.n_controle_machine, apercu.n_incomplets), (5, 1, 1))

        resume = self.il.import_file(self.conn, self.fichier, 0.3, 250, [(0, 18, "Enfants"), (18, 120, "Adultes")])
        self.assertEqual(resume.n_importes, 5)
        statuts = dict(self.conn.execute("SELECT numero_demande, statut FROM qc_echantillons"))
        self.assertEqual(statuts, {"1001": "valide", "1002": "valide", "1003": "sous_seuil",
                                   "1004": "sur_seuil", "1005": "exclu"})
        valeur = self.conn.execute("SELECT valeur_numerique FROM qc_echantillons WHERE numero_demande='1002'").fetchone()
        self.assertEqual(valeur, (3.4,))

    def test_echec_ne_laisse_rien_en_base(self):
        _classeur(self.fichier, {"Total": [ENTETE]})  # aucun échantillon
        with self.assertRaises(ValueError):
            self.il.import_file(self.conn, self.fichier, 0, 10, [(0, 120, "Tous")])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM qc_parametres").fetchone(), (0,))

    def test_tranches_invalides_refusees(self):
        self.assertTrue(self.il.valider_tranches([(0, 18, "A"), (10, 30, "B")]))   # chevauchement
        self.assertTrue(self.il.valider_tranches([(5, 5, "A")]))                   # tranche vide
        self.assertEqual(self.il.valider_tranches([(0, 18, "A"), (18, 120, "B")]), [])
        self.assertEqual(self.il.ages_non_couverts([3, 17, 40], [(0, 18, "A")]), [40])

    def test_classification(self):
        c = self.il.classify_value
        self.assertEqual(c("<0,3", 0.3, 250), ("sous_seuil", 0.3))
        self.assertEqual(c("≥ 250", 0.3, 250), ("sur_seuil", 250.0))
        self.assertEqual(c("VCOM", 0.3, 250), ("exclu", None))
        self.assertEqual(c(0.1, 0.3, 250), ("sous_seuil", 0.1))
        self.assertEqual(c(0.1, 0, 0), ("valide", 0.1))       # domaine non renseigné : pas de reclassement

    def test_reimport_conserve_notes_et_intervalles(self):
        _classeur(self.fichier, {"Total": openpyxl.load_workbook(self.fichier)["Données"].values})
        self.il.import_file(self.conn, self.fichier, 0.3, 250, [(0, 120, "Tous")], unite="mUI/L")
        pid = self.conn.execute("SELECT id FROM qc_parametres").fetchone()[0]
        self.conn.execute("UPDATE qc_parametres SET notes = 'à garder' WHERE id = ?", (pid,))
        self.il.enregistrer_intervalles_reference(self.conn, pid, [("", "", 0.4, 4.0, "notice")])
        self.il.import_file(self.conn, self.fichier, 0.3, 250, [(0, 120, "Tous")], replace_existing=True)
        notes, unite = self.conn.execute("SELECT notes, unite FROM qc_parametres").fetchone()
        self.assertEqual((notes, unite), ("à garder", "mUI/L"))
        pid = self.conn.execute("SELECT id FROM qc_parametres").fetchone()[0]
        self.assertEqual(len(self.il.lister_intervalles_reference(self.conn, pid)), 1)

    def test_intervalle_le_plus_specifique(self):
        _classeur(self.fichier, {"Total": openpyxl.load_workbook(self.fichier)["Données"].values})
        self.il.import_file(self.conn, self.fichier, 0.3, 250, [(0, 120, "Tous")])
        pid = self.conn.execute("SELECT id FROM qc_parametres").fetchone()[0]
        self.il.enregistrer_intervalles_reference(self.conn, pid, [("", "", 1, 2, None), ("", "Féminin", 3, 4, None)])
        self.assertEqual(self.il.get_intervalle_reference(self.conn, pid, "Tous", "Féminin")[:2], (3, 4))
        self.assertEqual(self.il.get_intervalle_reference(self.conn, pid, "Tous", "Masculin")[:2], (1, 2))


class TestCIQ(TestAvecBase):
    def setUp(self):
        super().setUp()
        from modules.ciq import logic
        self.ciq = logic

    def test_carte_et_regles(self):
        aid = self.ciq.enregistrer_analyte(self.conn, "Glucose", "mmol/L", "A", 6.9)
        lot = self.ciq.enregistrer_lot(self.conn, aid, "N1", "L1", 5.0, 0.1)
        for jour, valeur in enumerate([5.0, 5.05, 4.95, 5.35, 5.0, 5.22, 5.23]):
            self.ciq.ajouter_mesure(self.conn, lot, f"2026-01-{jour + 1:02d} 08:00", valeur)
        analyte = self.ciq.get_analyte(self.conn, aid)
        carte = self.ciq.calculer_cartes(self.conn, analyte)[0]
        regles = [m.regles for m in carte.mesures]
        self.assertEqual(regles[3], ["1_3s"])
        self.assertIn("2_2s", regles[6])
        self.assertEqual(carte.stats.n, 7)
        self.assertFalse(carte.cibles_provisoires)

    def test_mesure_exclue_ignoree(self):
        aid = self.ciq.enregistrer_analyte(self.conn, "Na", "mmol/L")
        lot = self.ciq.enregistrer_lot(self.conn, aid, "N1", "", 140, 1)
        mid = self.ciq.ajouter_mesure(self.conn, lot, "2026-01-01 08:00", 150)
        self.ciq.definir_exclusion(self.conn, mid, True, "erreur de pipetage")
        carte = self.ciq.calculer_cartes(self.conn, self.ciq.get_analyte(self.conn, aid))[0]
        self.assertEqual(carte.stats.n, 0)
        self.assertEqual(carte.mesures[0].statut, "exclue")

    def test_cibles_provisoires(self):
        aid = self.ciq.enregistrer_analyte(self.conn, "K", "mmol/L")
        lot = self.ciq.enregistrer_lot(self.conn, aid, "N1")
        for i, v in enumerate([4.0, 4.2, 4.1]):
            self.ciq.ajouter_mesure(self.conn, lot, f"2026-01-0{i + 1} 08:00", v)
        carte = self.ciq.calculer_cartes(self.conn, self.ciq.get_analyte(self.conn, aid))[0]
        self.assertTrue(carte.cibles_provisoires)
        self.assertAlmostEqual(carte.moyenne, 4.1)
        m, s, n = self.ciq.cibles_depuis_donnees(self.conn, lot)
        self.assertEqual(n, 3)

    def test_inter_niveaux(self):
        aid = self.ciq.enregistrer_analyte(self.conn, "TSH", "mUI/L")
        l1 = self.ciq.enregistrer_lot(self.conn, aid, "N1", "", 1.0, 0.1)
        l2 = self.ciq.enregistrer_lot(self.conn, aid, "N2", "", 10.0, 1.0)
        self.ciq.ajouter_mesure(self.conn, l1, "2026-02-01 08:00", 1.25)   # z = +2.5
        self.ciq.ajouter_mesure(self.conn, l2, "2026-02-01 08:05", 12.3)   # z = +2.3
        cartes = self.ciq.calculer_cartes(self.conn, self.ciq.get_analyte(self.conn, aid))
        self.assertIn("2_2s_inter", cartes[0].mesures[0].regles)
        self.assertEqual(cartes[1].mesures[0].statut, "rejet")

    def test_import_lignes(self):
        aid = self.ciq.enregistrer_analyte(self.conn, "Ca", "mmol/L")
        lot = self.ciq.enregistrer_lot(self.conn, aid, "N1", "", 2.5, 0.05)
        bilan = self.ciq.importer_lignes(self.conn, lot, [["Date", "Valeur"], ["01/03/2026 08:00", "2,51"],
                                                          ["02/03/2026", "abc"], ["pas une date", "2.4"]])
        self.assertEqual(bilan.n_importees, 1)
        self.assertEqual(len(bilan.erreurs), 2)

    def test_doublon_analyte_refuse(self):
        self.ciq.enregistrer_analyte(self.conn, "Urée", "", "A")
        with self.assertRaises(ValueError):
            self.ciq.enregistrer_analyte(self.conn, "Urée", "", "A")

    def test_demo(self):
        self.assertIsNotNone(self.ciq.creer_donnees_demo(self.conn))
        lignes = self.ciq.synthese(self.conn, None)
        self.assertEqual(len(lignes), 4)
        self.assertTrue(any(l.n_rejets_periode for l in lignes))


class TestEtudesValidation(TestAvecBase):
    def test_enregistrement_et_rechargement(self):
        from modules.validation import logic
        etude = logic.Etude(None, logic.TYPE_COMPARAISON, "Essai", "Créat", "µmol/L", "A", "B",
                            {"limite": 5.0}, donnees=[("e1", 1.0, 1.1), ("e2", None, 2.0)])
        eid = logic.enregistrer_etude(self.conn, etude)
        relue = logic.charger_etude(self.conn, eid)
        self.assertEqual(relue.donnees, [("e1", 1.0, 1.1), ("e2", None, 2.0)])
        self.assertEqual(relue.parametres, {"limite": 5.0})
        etude.donnees = [("e3", 3.0, 3.0)]
        logic.enregistrer_etude(self.conn, etude)
        self.assertEqual(len(logic.charger_etude(self.conn, eid).donnees), 1)
        logic.supprimer_etude(self.conn, eid)
        self.assertEqual(logic.lister_etudes(self.conn), [])


class TestChemins(TestAvecBase):
    def test_ressources_livrees_presentes(self):
        """Fichiers que biocentral.spec embarque dans l'exécutable : ils doivent exister."""
        from core.chemins import ressource
        for morceaux in (("schema.sql",), ("assets", "icon.png"), ("assets", "icon.ico"), ("assets", "icon.icns")):
            self.assertTrue(ressource(*morceaux).exists(), morceaux)

    def test_dossier_de_donnees_force(self):
        self.assertEqual(self.database.get_data_dir(), self.dossier)
