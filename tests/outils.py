"""Aides communes aux tests : base temporaire isolée (jamais celle de l'utilisateur)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TestAvecBase(unittest.TestCase):
    """Chaque test dispose d'un dossier de données vide et d'une connexion neuve."""

    def setUp(self):
        self._dossier = Path(tempfile.mkdtemp(prefix="biocentral_test_"))
        self._ancien = os.environ.get("BIOCENTRAL_DATA_DIR")
        os.environ["BIOCENTRAL_DATA_DIR"] = str(self._dossier)
        from core import database
        self.database = database
        self.conn = database.get_connection()

    def tearDown(self):
        self.conn.close()
        if self._ancien is None:
            os.environ.pop("BIOCENTRAL_DATA_DIR", None)
        else:
            os.environ["BIOCENTRAL_DATA_DIR"] = self._ancien
        shutil.rmtree(self._dossier, ignore_errors=True)

    @property
    def dossier(self) -> Path:
        return self._dossier
