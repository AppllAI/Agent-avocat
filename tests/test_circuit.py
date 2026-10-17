"""Test de bout en bout en SIMULATION : recherche → règles → lettres → répétition → envoi réel →
entretien → rendez-vous → relance → refus silencieux. Lancer : python -m unittest discover tests -v"""
import json
import os
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

RACINE_PROJET = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agent_avocat_test_"))
os.environ.update({"AGENT_AVOCAT_RACINE": str(TMP), "SIMULATION": "1", "ANTHROPIC_API_KEY": "",
                   "EMAIL_ADRESSE": "moi@exemple.be"})
sys.path.insert(0, str(RACINE_PROJET))

from agent_avocat import config, db, messagerie, orchestrateur, outils  # noqa: E402
from agent_avocat.agents import controle, envoyeur, essai, garde, relance, sources, trieur  # noqa: E402
from agent_avocat.agents import concierge  # noqa: E402
from agent_avocat.agents.concierge import Entrant  # noqa: E402


class CanalTest:
    nom = "test"

    def __init__(self):
        self.messages, self.boutons, self.fichiers = [], [], []

    def envoyer(self, t, boutons=None):
        self.messages.append(t)
        self.boutons.append(boutons)

    def envoyer_fichier(self, c, legende=""):
        self.fichiers.append(Path(c))


def _hors_ligne(*a, **k):
    raise ConnectionError("hors ligne (test)")


def emails_sortis():
    return sorted((config.DONNEES / "sortie").glob("*.eml"))


def offre(entreprise):
    return db.q1("SELECT * FROM offres WHERE entreprise=?", entreprise)


class Circuit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        outils.telecharger = _hors_ligne
        sources._get_json = _hors_ligne                         # pas de vrai LexGO pendant les tests
        orchestrateur.en_fond = lambda f, *a: f(*a)             # tout en synchrone
        orchestrateur.envoyer_bientot = orchestrateur._envoyer
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
        (config.PROFIL_DIR / "profil.md").write_text("# Profil\n- Nom : Alex Test\n- Master en droit ULB\n")
        concierge.recevoir(Entrant(texte="Je veux que du droit immobilier à Bruxelles"))
        self.assertEqual(config.domaine_actif()["matieres_uniquement"], ["droit immobilier"])
        concierge.recevoir(Entrant(texte="ok lance"))
        self.assertTrue(db.kv_get("onboarding_fini"))
        self.assertIn("🧪", self.dernier())                    # mode répétition par défaut, rappelé partout

    def test_2_recherche_et_tri(self):
        orchestrateur.pipeline()
        st = {r["entreprise"]: (r["statut"], r["raison"]) for r in db.q("SELECT * FROM offres")}
        self.assertEqual(st["Cabinet Themis"][0], "ecartee")              # pénal exclu
        self.assertIn("matière exclue", st["Cabinet Themis"][1])
        self.assertEqual(st["Nordlex"][0], "ecartee")                     # hors matière / néerlandais
        for e in ("Cabinet Lumen Avocats", "Delta & Associés", "Cabinet Horizon Immo"):
            self.assertEqual(st[e][0], "a_valider", e)
        self.assertNotIn("Sans Email & Co", st)                            # spontanée sans email vérifié : non
        self.assertEqual(offre("Cabinet Horizon Immo")["source"], "spontanee")
        self.assertEqual(offre("Cabinet Lumen Avocats")["note_lettre"], 9)
        self.assertIn("copropriété", offre("Cabinet Lumen Avocats")["pourquoi"])
        cartes = [b for b in self.canal.boutons if b and b[0][0][1].startswith("ok ")]
        self.assertGreaterEqual(len(cartes), 3)                            # une carte + boutons par candidature
        orchestrateur.pipeline()                                           # 2e passage : aucun doublon
        self.assertEqual(db.q1("SELECT COUNT(*) AS n FROM offres")["n"], 5)

    def test_3_repetition_puis_vrai(self):
        concierge.recevoir(Entrant(texte="ok"))
        lumen, delta, horizon = offre("Cabinet Lumen Avocats"), offre("Delta & Associés"), offre("Cabinet Horizon Immo")
        self.assertEqual(lumen["statut"], "repetee")
        self.assertEqual(horizon["statut"], "repetee")
        self.assertEqual(delta["statut"], "manuelle")                     # formulaire : lien + lettre
        sortis = emails_sortis()
        self.assertEqual(len(sortis), 2)
        for f in sortis:
            import email
            m = email.message_from_bytes(f.read_bytes())
            self.assertEqual(m["To"], "moi@exemple.be")                    # vers MOI, pas le cabinet
            self.assertIn("RÉPÉTITION", str(email.header.make_header(email.header.decode_header(m["Subject"]))))
        concierge.recevoir(Entrant(texte=f"vrai {lumen['id']}"))          # « L'envoyer pour de vrai »
        self.assertEqual(offre("Cabinet Lumen Avocats")["statut"], "envoyee")
        self.assertTrue(offre("Cabinet Lumen Avocats")["message_id"])
        self.assertIn(b"To: jobs@lumen-avocats.be", emails_sortis()[-1].read_bytes())
        concierge.recevoir(Entrant(texte=f"fait {delta['id']}"))
        self.assertEqual(offre("Delta & Associés")["statut"], "envoyee")

    def test_4_reponses_recruteurs(self):
        lumen = offre("Cabinet Lumen Avocats")
        boite = config.DONNEES / "boite_simulee"
        boite.mkdir(parents=True, exist_ok=True)
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "rh@lumen-avocats.be", "Votre candidature", "<rep1@lumen>"
        m["In-Reply-To"] = lumen["message_id"]
        m.set_content("Bonjour, nous aimerions vous rencontrer en entretien le 24 décembre à 16h30.")
        (boite / "1.eml").write_bytes(bytes(m))
        for i, (de, sujet) in enumerate((("promo@boutique.be", "-50% ce week-end"),
                                          ("moi@exemple.be", "[RÉPÉTITION → x] Candidature"))):
            p = EmailMessage()
            p["From"], p["Subject"], p["Message-ID"] = de, sujet, f"<bruit{i}@x>"
            p.set_content("…")
            (boite / f"2{i}.eml").write_bytes(bytes(p))

        avant = len(self.canal.messages)
        trieur.relever()
        nouveaux = self.canal.messages[avant:]
        self.assertEqual(len(nouveaux), 1)                                 # ni la pub ni nos copies
        self.assertIn("entretien", nouveaux[0])
        self.assertIn("jeudi 24 décembre à 16h30", nouveaux[0])
        rid = db.q1("SELECT id FROM rdv")["id"]
        self.assertIn(("✅ Jeudi 16h30", f"rdv {rid} oui"), self.canal.boutons[-1][0])
        self.assertEqual(offre("Cabinet Lumen Avocats")["statut"], "entretien")

        concierge.recevoir(Entrant(texte=f"rdv {rid} oui"))               # bouton touché
        self.assertEqual(db.q1("SELECT statut FROM rdv")["statut"], "confirme")
        self.assertIn("Confirmé", self.dernier())
        self.assertTrue(any(f.suffix == ".ics" for f in self.canal.fichiers))

    def test_5_refus_silencieux_et_relance(self):
        delta = offre("Delta & Associés")
        db.maj(delta["id"], envoye_le="2026-01-01 09:00:00", email_contact="rh@delta.be")
        self.assertEqual(relance.relancer(), 1)
        self.assertEqual(offre("Delta & Associés")["statut"], "relancee")
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "rh@delta.be", "Votre candidature", "<ref@delta>"
        m.set_content("Nous avons le regret de vous informer que votre profil n'a pas été retenu.")
        (config.DONNEES / "boite_simulee" / "3.eml").write_bytes(bytes(m))
        avant = len(self.canal.messages)
        trieur.relever()
        self.assertEqual(len(self.canal.messages), avant)                  # aucun message pour un refus
        self.assertEqual(offre("Delta & Associés")["statut"], "refus")

    def test_6_commandes(self):
        concierge.recevoir(Entrant(texte="/stats"))
        self.assertIn("Bilan", self.dernier())
        concierge.recevoir(Entrant(texte="pause"))
        self.assertTrue(db.kv_get("pause"))
        concierge.recevoir(Entrant(texte="reprendre"))
        self.assertFalse(db.kv_get("pause"))
        concierge.recevoir(Entrant(texte="mes lettres sont trop longues"))
        self.assertIn("250 mots", config.style_texte())
        concierge.recevoir(Entrant(texte="mode validation"))
        self.assertEqual(config.regles_envoi()["mode"], "validation")
        self.assertNotIn("🧪", self.dernier())

    def test_7_banc_essai(self):
        rapport = essai.banc_essai()
        texte = rapport.read_text(encoding="utf-8")
        self.assertIn("Note moyenne du Juge", texte)
        self.assertEqual(texte.count("\n## "), 5)


class Controleur(unittest.TestCase):
    def test_attrape_les_erreurs(self):
        base = {"id": 999, "entreprise": "Cabinet Lumen Avocats", "email_contact": "a@b.be", "objet_mail": "Candidature",
                "corps_mail": "Bonjour", "lettre": "Cabinet Lumen Avocats " + "mot " * 250}
        self.assertNotIn("le nom", " ".join(controle.problemes(base)))
        p = controle.problemes({**base, "lettre": "Cabinet Delta " + "mot " * 250})
        self.assertTrue(any("n'apparaît pas" in x for x in p))
        p = controle.problemes({**base, "lettre": base["lettre"] + " [Nom du cabinet]"})
        self.assertTrue(any("trous" in x for x in p))
        p = controle.problemes({**base, "lettre": "Cabinet Lumen Avocats court"})
        self.assertTrue(any("longueur" in x for x in p))


class LexGO(unittest.TestCase):
    def test_lecture_api(self):
        def faux(url, params=None, etag_cle=None):
            if url.endswith("/functions"):
                return {"functions": [{"id": 4, "fr_name": "Stagiaire", "nl_name": "Stagiair", "en_name": "Trainee"}]}
            if url.endswith("/jobs"):
                return {"jobs": [{"id": 77, "click_url": "https://www.lexgo.be/fr/emploi/77?ref=x"}], "next_cursor": None}
            return {"id": 77, "click_url": "https://www.lexgo.be/fr/emploi/77?ref=x",
                    "titles": {"fr": "Avocat stagiaire"}, "company": {"name": "Cabinet X"},
                    "location": {"city": "Bruxelles"}, "disciplines": [{"fr_name": "Droit immobilier"}],
                    "contract": {"permanent": True}, "descriptions": {"fr": "Missions…"},
                    "published_at": "2026-10-15T08:00:00Z", "languages": ["fr"]}
        ancien = sources._get_json
        sources._get_json = faux
        db.kv_set("lexgo_fonctions", None)
        try:
            o = sources._lexgo({"postes_vises": ["stagiaire avocat"]})
        finally:
            sources._get_json = ancien
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["titre"], o[0]["ville"], o[0]["publie_le"], o[0]["contrat"]),
                         ("Avocat stagiaire", "Bruxelles", "2026-10-15", "permanent"))


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
        self.assertTrue(envoyeur.heure_ouvrable(r, datetime(2026, 10, 19, 9)))    # lundi 9h
        self.assertFalse(envoyeur.heure_ouvrable(r, datetime(2026, 10, 18, 9)))   # dimanche
        self.assertFalse(envoyeur.heure_ouvrable(r, datetime(2026, 10, 19, 18)))  # après 17h

    def test_banc_valide(self):
        self.assertEqual(len(json.loads(essai.BANC.read_text(encoding="utf-8"))), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
