"""
Journalisation de l'application : toute erreur inattendue est enregistrée dans
un fichier de log, exploitable pour diagnostiquer à distance un problème
signalé par l'utilisatrice — elle travaille seule, sans le développeur à côté.
"""
import logging
import sys
import traceback

from core.database import get_data_dir

LOG_PATH = get_data_dir() / "biocentral.log"


def configurer_logs() -> None:
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )
    logging.info("=== Démarrage de BioCentral ===")


def installer_gestionnaire_erreurs_global() -> None:
    """
    Capture toute exception non gérée qui remonterait n'importe où dans
    l'application (Qt appelle sys.excepthook pour les exceptions levées dans
    un slot/callback), l'enregistre dans le fichier de log, et affiche un
    message clair plutôt qu'une trace Python illisible ou un plantage
    silencieux qui laisserait l'utilisatrice sans recours.
    """
    def gestionnaire(type_exc, valeur_exc, tb):
        message = "".join(traceback.format_exception(type_exc, valeur_exc, tb))
        logging.error("Erreur non gérée :\n%s", message)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return  # pas de fenêtre possible avant la création de QApplication : le log suffira
            QMessageBox.critical(
                None, "Une erreur est survenue",
                "Une erreur inattendue s'est produite.\n\n"
                f"Les détails ont été enregistrés dans :\n{LOG_PATH}\n\n"
                "Vous pouvez transmettre ce fichier pour obtenir de l'aide.",
            )
        except Exception:
            pass  # si même l'affichage du message échoue, au moins le log est écrit

    sys.excepthook = gestionnaire
