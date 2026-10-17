"""Test de bout en bout en SIMULATION : de la recherche d'offres jusqu'au rendez-vous confirmé.
Lancer :  python -m unittest discover tests -v"""
import os
import shutil
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

RACINE_PROJET = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agent_avocat_test_"))
os.environ.update({"AGENT_AVOCAT_RACINE": str(TMP), "SIMULATION": "1", "ANTHROPIC_API_KEY": ""})
(TMP / "config").mkdir()
shutil.copy(RACINE_PROJET / "config" / "objectif.exemple.yaml", TMP / "config" / "objectif.exemple.yaml")
sys.path.insert(0, str(RACINE_PROJET))

from agent_avocat import config, db, messagerie, orchestrateur, outils  # noqa: E402
from agent_avocat.agents import (concierge, envoyeur, garde, relance, trieur)  # noqa: E402
from agent_avocat.agents.concierge import Entrant  # noqa: E402


class CanalTest:
    nom = "test"

    def __init__(self):
        self.messages, self.fichiers = [], []

    def envoyer(self, t):
        self.messages.append(t)

    def envoyer_fichier(self, c, legende=""):
        self.fichiers.append(Path(c))


def _hors_ligne(url, timeout=20):
    raise ConnectionError("hors ligne (test)")


class Circuit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        outils.telecharger = _hors_ligne
        orchestrateur.envoyer_bientot = orchestrateur._envoyer        # synchrone pour le test
        orchestrateur.declencher = lambda: None
        cls.canal = CanalTest()
        messagerie.brancher(cls.canal)

    def dernier(self):
        return self.canal.messages[-1]

    def test_1_onboarding(self):
        cv = TMP / "mon_cv.pdf"
        cv.write_bytes(b"%PDF-1.4 faux")
        concierge.recevoir(Entrant(fichier=cv, nom_fichier="mon_cv.pdf"))
        self.assertTrue(config.chemin_cv().exists())
        # pas de pypdf/texte → l'agent demande une version lisible ; on écrit le profil comme le ferait le Profileur
        (config.PROFIL_DIR / "profil.md").write_text("# Profil\n- Nom : Alex Test\n- Master en droit ULB\n")
        concierge.recevoir(Entrant(texte="Je veux que du droit immobilier à Bruxelles"))
        self.assertEqual(config.domaine_actif()["matieres_uniquement"], ["droit immobilier"])
        concierge.recevoir(Entrant(texte="ok lance"))
        self.assertTrue(db.kv_get("onboarding_fini"))

    def test_2_recherche_et_tri(self):
        orchestrateur.pipeline()
        st = {r["entreprise"]: (r["statut"], r["raison"]) for r in db.q("SELECT * FROM offres")}
        self.assertEqual(st["Cabinet Themis"][0], "ecartee")              # pénal exclu
        self.assertIn("matière exclue", st["Cabinet Themis"][1])
        self.assertEqual(st["Nordlex"][0], "ecartee")                     # néerlandais exigé / hors matière
        self.assertEqual(st["Cabinet Lumen Avocats"][0], "a_valider")
        self.assertEqual(st["Delta & Associés"][0], "a_valider")
        self.assertIn("Nouvelles candidatures prêtes", "\n".join(self.canal.messages))
        orchestrateur.pipeline()                                           # 2e passage : aucun doublon
        self.assertEqual(db.q1("SELECT COUNT(*) AS n FROM offres")["n"], 4)

    def test_3_validation_et_envoi(self):
        concierge.recevoir(Entrant(texte="ok"))
        lumen = db.q1("SELECT * FROM offres WHERE entreprise='Cabinet Lumen Avocats'")
        delta = db.q1("SELECT * FROM offres WHERE entreprise='Delta & Associés'")
        self.assertEqual(lumen["statut"], "envoyee")
        self.assertTrue(lumen["message_id"])
        self.assertEqual(delta["statut"], "manuelle")
        emails = list((config.DONNEES / "sortie").glob("*.eml"))
        self.assertEqual(len(emails), 1)
        contenu = emails[0].read_bytes()
        self.assertIn(b"jobs@lumen-avocats.be", contenu)
        self.assertIn(b"CV", contenu)
        concierge.recevoir(Entrant(texte=f"fait {delta['id']}"))
        self.assertEqual(db.q1("SELECT statut FROM offres WHERE id=?", delta["id"])["statut"], "envoyee")

    def test_4_reponses_recruteurs(self):
        lumen = db.q1("SELECT * FROM offres WHERE entreprise='Cabinet Lumen Avocats'")
        boite = config.DONNEES / "boite_simulee"
        boite.mkdir(parents=True, exist_ok=True)
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "rh@lumen-avocats.be", "Votre candidature", "<rep1@lumen>"
        m["In-Reply-To"] = lumen["message_id"]
        m.set_content("Bonjour, nous aimerions vous rencontrer en entretien le 24 décembre à 16h30.")
        (boite / "1.eml").write_bytes(bytes(m))
        pub = EmailMessage()
        pub["From"], pub["Subject"], pub["Message-ID"] = "promo@boutique.be", "-50% ce week-end", "<pub@x>"
        pub.set_content("Soldes !")
        (boite / "2.eml").write_bytes(bytes(pub))

        avant = len(self.canal.messages)
        trieur.relever()
        nouveaux = self.canal.messages[avant:]
        self.assertEqual(len(nouveaux), 1)                    # la pub ne te dérange pas
        self.assertIn("entretien", nouveaux[0])
        self.assertIn("jeudi 24 décembre à 16h30", nouveaux[0])
        self.assertEqual(db.q1("SELECT statut FROM offres WHERE id=?", lumen["id"])["statut"], "entretien")

        concierge.recevoir(Entrant(texte="oui c'est parfait"))
        self.assertEqual(db.q1("SELECT statut FROM rdv")["statut"], "confirme")
        self.assertIn("Confirmé", self.dernier())
        self.assertTrue(any(f.suffix == ".ics" for f in self.canal.fichiers))
        self.assertEqual(len(list((config.DONNEES / "sortie").glob("*.eml"))), 2)   # réponse envoyée

    def test_5_refus_silencieux_et_relance(self):
        delta = db.q1("SELECT * FROM offres WHERE entreprise='Delta & Associés'")
        db.maj(delta["id"], envoye_le="2026-01-01 09:00:00", email_contact="rh@delta.be")
        self.assertEqual(relance.relancer(), 1)
        self.assertEqual(db.q1("SELECT statut FROM offres WHERE id=?", delta["id"])["statut"], "relancee")
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "rh@delta.be", "Votre candidature", "<ref@delta>"
        m.set_content("Nous avons le regret de vous informer que votre profil n'a pas été retenu.")
        (config.DONNEES / "boite_simulee" / "3.eml").write_bytes(bytes(m))
        avant = len(self.canal.messages)
        trieur.relever()
        self.assertEqual(len(self.canal.messages), avant)    # aucun message pour un refus
        self.assertEqual(db.q1("SELECT statut FROM offres WHERE id=?", delta["id"])["statut"], "refus")

    def test_6_raccourcis(self):
        concierge.recevoir(Entrant(texte="stats"))
        self.assertIn("Bilan", self.dernier())
        concierge.recevoir(Entrant(texte="pause"))
        self.assertTrue(db.kv_get("pause"))
        concierge.recevoir(Entrant(texte="reprendre"))
        self.assertFalse(db.kv_get("pause"))


class Garde(unittest.TestCase):
    def test_synonymes_et_langues(self):
        dom = {"matieres_exclues": ["droit pénal"], "langues": ["français"], "matieres_uniquement": []}
        regles = config.regles_envoi()
        v = lambda **o: garde.verdict({"id": 0, **o}, dom, regles)  # noqa: E731
        self.assertIsNotNone(v(titre="Juriste – contentieux correctionnel"))
        self.assertIsNotNone(v(titre="Juriste", langue="néerlandais courant"))
        self.assertIsNone(v(titre="Juriste immobilier", langue="français"))
        dom["matieres_uniquement"] = ["droit immobilier"]
        self.assertIsNotNone(v(titre="Juriste", matiere="droit fiscal"))
        self.assertIsNone(v(titre="Juriste", matiere="baux commerciaux et copropriété"))


class Outils(unittest.TestCase):
    def test_doublons(self):
        a = outils.cle_offre("https://www.jobat.be/x?utm_source=a", "Cabinet Lumen", "Juriste immobilier")
        b = outils.cle_offre("https://stepstone.be/y", "cabinet lumen", "Juriste Immobilier")
        self.assertEqual(a, b)

    def test_jsonld(self):
        page = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Juriste",'
                '"hiringOrganization":{"name":"X"},"jobLocation":{"address":{"addressLocality":"Liège"}},'
                '"description":"<p>Mission</p>"}</script>')
        jp = outils.jobposting_jsonld(page)
        self.assertEqual((jp["titre"], jp["entreprise"], jp["ville"]), ("Juriste", "X", "Liège"))

    def test_emails(self):
        self.assertEqual(outils.emails_dans("écrire à jobs@cab.be ou noreply@cab.be"), ["jobs@cab.be"])

    def test_heures(self):
        from datetime import datetime
        r = config.regles_envoi()
        self.assertTrue(envoyeur.heure_ouvrable(r, datetime(2026, 10, 19, 10)))   # lundi 10h
        self.assertFalse(envoyeur.heure_ouvrable(r, datetime(2026, 10, 18, 10)))  # dimanche
        self.assertFalse(envoyeur.heure_ouvrable(r, datetime(2026, 10, 19, 22)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
