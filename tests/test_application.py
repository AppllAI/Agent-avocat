"""Tests de la partie « application de bureau » (sans ouvrir de fenêtre)."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_avocat.app import reglages  # noqa: E402


class Reglages(unittest.TestCase):
    def test_formulaire_gmail(self):
        v = reglages.reglages_depuis_formulaire(" Alex.Juriste@gmail.com ", "abcd efgh ijkl mnop", " sk-ant-x ",
                                                "whatsapp", "0470 12 34 56")
        self.assertEqual(v["EMAIL_MOT_DE_PASSE"], "abcdefghijklmnop")
        self.assertEqual((v["SMTP_HOTE"], v["SMTP_PORT"], v["IMAP_HOTE"]), ("smtp.gmail.com", 465, "imap.gmail.com"))
        self.assertEqual(v["WHATSAPP_MON_NUMERO"], "32470123456")
        self.assertEqual(v["ANTHROPIC_API_KEY"], "sk-ant-x")

    def test_numero_international(self):
        v = reglages.reglages_depuis_formulaire("a@outlook.com", "x", "k", "whatsapp", "+32 470 12 34 56")
        self.assertEqual(v["WHATSAPP_MON_NUMERO"], "32470123456")
        self.assertEqual(v["SMTP_PORT"], 587)

    def test_env_aller_retour(self):
        d = Path(tempfile.mkdtemp())
        reglages.ecrire_env(d, {"EMAIL_ADRESSE": "a@gmail.com", "EMAIL_MOT_DE_PASSE": "p#ss word"})
        reglages.ecrire_env(d, {"CANAL": "telegram"})
        e = reglages.lire_env(d)
        self.assertEqual((e["EMAIL_ADRESSE"], e["CANAL"]), ("a@gmail.com", "telegram"))

    def test_dossier(self):
        d = tempfile.mkdtemp()
        os.environ["AGENT_AVOCAT_RACINE"] = d
        self.assertEqual(reglages.preparer_dossier(), Path(d))
        self.assertTrue((Path(d) / "profil").is_dir())

    def test_cle_mal_formee(self):
        self.assertIn("sk-ant-", reglages.tester_cle("abc"))

    def test_fournisseur_inconnu(self):
        self.assertIsNotNone(reglages.tester_email("a@inconnu.be", "x", "", 465, ""))

    @unittest.skipUnless(importlib.util.find_spec("qrcode"), "qrcode non installé")
    def test_qr(self):
        m = reglages.matrice_qr("2@abc,def,ghi")
        self.assertGreater(len(m), 20)

    @unittest.skipUnless(importlib.util.find_spec("tkinter"), "tkinter absent")
    def test_fenetre_importable(self):
        import agent_avocat.app.fenetre as f
        self.assertTrue(hasattr(f, "Application"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
