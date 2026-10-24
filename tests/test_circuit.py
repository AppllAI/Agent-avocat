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
        sources._jobspy = lambda dom: []                        # ni Indeed ni Google
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
        (config.PROFIL_DIR / "profil.md").write_text("# Profil\n- Nom : Alex Test\n- Email : alex.test@exemple.be\n- Master en droit ULB\n",
                                                      encoding="utf-8")
        concierge.recevoir(Entrant(texte="Je veux que du droit immobilier à Bruxelles"))
        self.assertEqual(config.domaine_actif()["secteurs_uniquement"], ["droit immobilier"])
        concierge.recevoir(Entrant(texte="ok lance"))
        self.assertTrue(db.kv_get("onboarding_fini"))
        self.assertEqual(config.regles_envoi()["mode"], "repetition")     # mode test par défaut

    def test_2_recherche_et_tri(self):
        avant = len(self.canal.messages)
        orchestrateur.pipeline()
        st = {r["entreprise"]: (r["statut"], r["raison"]) for r in db.q("SELECT * FROM offres")}
        self.assertEqual(st["Cabinet Themis"][0], "ecartee")              # pénal exclu
        self.assertIn("matière exclue", st["Cabinet Themis"][1])
        self.assertEqual(st["Nordlex"][0], "ecartee")                     # hors matière / néerlandais
        # Mode test : tout est fait seul et part vers l'email du CV ; « via leur site » reste à faire plus tard
        for e, attendu in (("Cabinet Lumen Avocats", "repetee"), ("Cabinet Horizon Immo", "repetee"),
                           ("Delta & Associés", "manuelle")):
            self.assertEqual(st[e][0], attendu, e)
        self.assertNotIn("Sans Email & Co", st)                            # spontanée sans email vérifié : non
        self.assertEqual(offre("Cabinet Horizon Immo")["source"], "spontanee")
        self.assertEqual(offre("Cabinet Lumen Avocats")["note_lettre"], 9)
        self.assertIn("copropriété", offre("Cabinet Lumen Avocats")["pourquoi"])
        self.assertEqual(self.canal.messages[avant:], [])                 # mode test : RIEN sur la messagerie
        self.assertEqual(self.canal.fichiers, [])
        sortis = emails_sortis()
        self.assertEqual(len(sortis), 3)                                   # y compris l'offre « via leur site »
        import email
        import email.policy
        for f in sortis:
            m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
            self.assertEqual(m["To"], "alex.test@exemple.be")             # l'adresse du CV, jamais le cabinet
            self.assertIn("[TEST n°", m["Subject"])
            joints = [p for p in m.walk() if p.get_filename()]
            self.assertEqual(len(joints), 3)                              # CV + lettre + rapport de test
            self.assertTrue(all(p.get_content_type() == "application/pdf" for p in joints))
            self.assertTrue(all(p.get_content_disposition() == "attachment" for p in joints))
            corps = m.get_body(("plain",)).get_content()
            self.assertNotIn("Je vous prie d'agréer", corps)              # la lettre n'est PAS dans l'email
        orchestrateur.pipeline()                                           # 2e passage : aucun doublon
        self.assertEqual(db.q1("SELECT COUNT(*) AS n FROM offres")["n"], 5)

    def test_3_repetition_puis_vrai(self):
        lumen, delta = offre("Cabinet Lumen Avocats"), offre("Delta & Associés")
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
        concierge.recevoir(Entrant(texte="mode validation"))
        self.assertEqual(config.regles_envoi()["mode"], "validation")
        self.assertNotIn("🧪", self.dernier())

    def test_7_test_en_langage_naturel(self):
        concierge.recevoir(Entrant(texte="j'aimerais d'abord essayer pour voir si ça marche"))
        self.assertTrue(any("Test terminé" in m for m in self.canal.messages[-3:]))
        self.assertTrue(any(f.name == "banc_essai.pdf" for f in self.canal.fichiers))
        concierge.recevoir(Entrant(texte="aide"))
        self.assertIn("teste-toi", self.dernier())

    def test_7b_manager(self):
        """Le Manager AGIT : chercher maintenant, envoyer à une adresse, régler, envoyer ici, pause datée."""
        appels = []
        orchestrateur.declencher = lambda: appels.append("recherche")
        concierge.recevoir(Entrant(texte="lance une recherche maintenant stp"))
        self.assertEqual(appels, ["recherche"])
        self.assertIn("lancé", self.dernier())
        avant = len(emails_sortis())
        with db.tx() as c:                                       # une candidature testée récente
            c.execute("UPDATE offres SET statut='repetee', envoye_le=datetime('now') WHERE entreprise='Cabinet Horizon Immo'")
        concierge.recevoir(Entrant(texte="envoie-les sur mon autre mail alex.perso@exemple.com"))
        nouveaux = emails_sortis()[avant:]
        self.assertGreaterEqual(len(nouveaux), 1)
        self.assertIn(b"To: alex.perso@exemple.com", nouveaux[0].read_bytes())
        concierge.recevoir(Entrant(texte="mets le score minimum à 6"))
        self.assertEqual(config.regles_envoi()["score_minimum"], 6)
        n = len(self.canal.fichiers)
        concierge.recevoir(Entrant(texte="envoie ici la lettre"))
        self.assertGreater(len(self.canal.fichiers), n)
        concierge.recevoir(Entrant(texte="j'ai mes examens, pause"))
        self.assertEqual(db.kv_get("pause_jusqu"), "2099-06-20")
        db.kv_set("pause_jusqu", "2000-01-01")                   # date passée → reprise toute seule
        self.assertFalse(orchestrateur.en_pause())
        orchestrateur.declencher = lambda: None

    def test_8_banc_essai(self):
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


class ChiffresInventes(unittest.TestCase):
    def test_duree_inventee_detectee(self):
        profil = "Stagiaire, étude Lambert, 2025 (3 mois). Mémoire (16/20). Job 2024 (2 mois). 0470 12 34 56"
        self.assertEqual(controle.chiffres_inventes("Pendant un an, j'ai étudié la copropriété.", profil), ["1 an"])
        self.assertEqual(controle.chiffres_inventes("Mon stage de trois mois, noté 16/20, en 2025.", profil), [])
        self.assertEqual(controle.chiffres_inventes("Une équipe de 40 avocats.", profil), ["40"])
        self.assertEqual(controle.chiffres_inventes("Néerlandais B2.", profil + " Néerlandais : B1"), ["niveau B2"])
        self.assertEqual(controle.chiffres_inventes("Néerlandais B1.", profil + " Néerlandais : B1"), [])

    def test_dates_et_telephone_ignores(self):
        profil = "Tél. 0470 12 34 56 · stage 2025 (3 mois)"
        self.assertEqual(controle.chiffres_inventes(
            "Bruxelles, le 24 novembre 2026. Joignable au 0470/12.34.56 ou +32 470 12 34 56.", profil), [])

    def test_preuves(self):
        profil = "- Stagiaire, étude notariale Lambert & Fils, Ixelles\n- Préparation de compromis de vente"
        self.assertTrue(controle.preuve_valide("Préparation de compromis de vente", profil))
        self.assertFalse(controle.preuve_valide("plaidé devant la justice de paix", profil))
        self.assertFalse(controle.preuve_valide(None, profil))


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


class AnnoncePrecise(unittest.TestCase):
    def test_pages_de_liste_rejetees(self):
        a = sources.annonce_precise
        self.assertFalse(a({"entreprise": "X", "url": "https://www.lexgo.be/en/functions/1-legal-jobs/jobs"}))
        self.assertFalse(a({"entreprise": None, "url": "https://www.jobat.be/fr/emplois/juriste-123"}))
        self.assertFalse(a({"entreprise": "Cab", "url": "https://www.stepstone.be/emplois/"}))
        self.assertTrue(a({"entreprise": "Cab", "url": "https://www.jobat.be/fr/emplois/juriste-immobilier-123"}))
        self.assertTrue(a({"entreprise": "Cab", "url": "https://www.lexgo.be/fr/emploi/12345-avocat-stagiaire"}))


class Garde(unittest.TestCase):
    def test_synonymes_et_langues(self):
        dom = {"secteurs_exclus": ["droit pénal"], "langues": ["français"], "secteurs_uniquement": []}
        regles = config.regles_envoi()
        v = lambda **o: garde.verdict({"id": 0, **o}, dom, regles)  # noqa: E731
        self.assertIsNotNone(v(titre="Juriste – contentieux correctionnel"))
        self.assertIsNotNone(v(titre="Juriste", langue="néerlandais courant"))
        self.assertIsNone(v(titre="Juriste immobilier", langue="français"))
        self.assertIsNone(v(titre="Juriste", description="Cabinet actif en droit pénal, civil et immobilier"))
        self.assertIsNotNone(v(titre="Juriste", langue="français + néerlandais"))
        from datetime import date
        an = date.today().year
        self.assertIn("trop ancienne", v(titre="Juriste", publie_le=f"{an - 3}-05-02") or "")
        self.assertIn("date limite", v(titre="Juriste", date_limite=f"{an - 1}-01-01") or "")
        dom["secteurs_uniquement"] = ["droit immobilier"]
        self.assertIsNotNone(v(titre="Juriste", secteur="droit fiscal"))
        self.assertIsNone(v(titre="Juriste", secteur="baux commerciaux et copropriété"))


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


class SitesEtEmails(unittest.TestCase):
    """Les bonnes infos sur les bons sites, et aucune adresse email devinée."""

    def test_domaine_officiel(self):
        self.assertEqual(outils.domaine_officiel("https://www.jobat.be/fr/x", "jobs@lumen-avocats.be"), "lumen-avocats.be")
        self.assertEqual(outils.domaine_officiel("https://www.avocats-delta.be/carrieres", None), "avocats-delta.be")
        self.assertEqual(outils.domaine_officiel("https://www.lexgo.be/fr/emploi/1", "alex@gmail.com"), "")

    def test_email_verifie_par_le_code(self):
        pages = {"https://cab-x.be": "<p>Cabinet X</p> <a href='mailto:recrutement@cab-x.be'>",
                 "https://cab-x.be/contact": "info@cab-x.be"}
        ancien = outils.telecharger
        outils.telecharger = lambda u, timeout=20: pages.get(u.rstrip("/"), "") or _hors_ligne()
        try:
            # lue sur le site → gardée ; devinée → remplacée par celle que le site publie vraiment
            self.assertEqual(outils.verifier_email("recrutement@cab-x.be", "Cabinet X"), "recrutement@cab-x.be")
            self.assertEqual(outils.verifier_email("jobs@cab-x.be", "Cabinet X"), "recrutement@cab-x.be")
            self.assertIsNone(outils.verifier_email("jobs@gmail.com", "Cabinet X"))
            self.assertIsNone(outils.verifier_email("rh@inconnu-sans-site.be", "Cabinet X"))
        finally:
            outils.telecharger = ancien
        # site officiel connu mais illisible : le domaine officiel fait foi
        self.assertEqual(outils.verifier_email("stage@horizon.be", "Horizon", "horizon.be"), "stage@horizon.be")

    def test_recherche_web_ciblee(self):
        from agent_avocat import llm
        o = llm._recherche_web("claude-haiku-5-5", 2, None, ["lexgo.be"])
        self.assertEqual(o["type"], "web_search_20250305")
        self.assertIn("lexgo.be", o["blocked_domains"])
        o = llm._recherche_web("claude-sonnet-5-5", 2, ["cabinet.be"], ["lexgo.be"])
        self.assertEqual((o["type"], o["allowed_domains"]), ("web_search_20260209", ["cabinet.be"]))
        self.assertNotIn("blocked_domains", o)                      # jamais les deux à la fois
        self.assertFalse(llm._forcer("claude-sonnet-5-5"))
        self.assertTrue(llm._forcer("claude-haiku-5-5"))

    def test_lettre_toujours_en_pdf(self):
        from agent_avocat import pdf
        from agent_avocat.agents.redacteur import chemin_lettre
        with db.tx() as c:          # lettre d'une ancienne version : texte seulement, pas de PDF
            oid = c.execute("INSERT INTO offres (cle, url, titre, lettre, statut) VALUES "
                            "('ancienne', 'https://x.be/1', 'Poste', 'Madame, Monsieur,\n\nTexte.', 'a_valider')").lastrowid
        f = chemin_lettre(oid)
        self.assertEqual(f.suffix, ".pdf")
        self.assertTrue(f.read_bytes().startswith(b"%PDF"))
        l = {"expediteur": ["Alex Test"], "lieu_date": "Bruxelles, le 1er mars 2027", "objet_lettre": "Candidature",
             "appel": "Madame, Monsieur,", "paragraphes": ["Un.", "Deux."], "politesse": "Salutations.",
             "signature": "Alex Test"}
        self.assertIn("Objet : Candidature\n\nMadame, Monsieur,\n\nUn.\n\nDeux.", pdf.texte_lettre(l))
        self.assertNotIn("🎯", pdf.propre("Fiche 🎯 **gras**"))


class ZRobustesse(unittest.TestCase):
    """Ce qui fait qu'un agent « ne fait rien » doit être dit clairement, une seule fois."""

    def setUp(self):
        self.canal = CanalTest()
        messagerie.brancher(self.canal)

    def test_ia_indisponible_bloque_sans_insister(self):
        from agent_avocat import llm
        db.kv_set("ia_bloquee_jusqu", None)
        with self.assertRaises(llm.IAIndisponible):
            llm._bloquer("crédit Anthropic épuisé")
        with self.assertRaises(llm.BudgetDepasse):          # les agents l'attrapent comme un budget atteint
            llm._verifier_disponible()
        db.kv_set("ia_bloquee_jusqu", 0)
        llm._verifier_disponible()                          # délai passé : on réessaie

    def test_alerte_une_seule_fois(self):
        from agent_avocat import llm
        llm._alerte("essai_unique", "Ton crédit Claude est épuisé")
        llm._alerte("essai_unique", "Ton crédit Claude est épuisé")
        self.assertEqual(sum("crédit" in m for m in self.canal.messages), 1)

    def test_budget_reglable(self):
        concierge.recevoir(Entrant(texte="budget 5"))
        self.assertEqual(config.env("BUDGET_JOUR_EUR"), "5")
        self.assertIn("5 €", self.canal.messages[-1])

    def test_diagnostic(self):
        from agent_avocat.agents import diagnostic
        texte = diagnostic.rapport(envoyer=False)
        self.assertIn("SIMULATION", texte)
        db.kv_set("pause", True)
        self.assertIn("PAUSE", diagnostic.rapport(envoyer=False))
        db.kv_set("pause", False)

    def test_rappel_via_site_une_fois_par_jour(self):
        from agent_avocat.agents import rapporteur
        o = config.objectif()
        o.setdefault("envoi", {})["mode"] = "validation"
        config.sauver_objectif(o)
        with db.tx() as c:
            c.execute("INSERT OR IGNORE INTO offres (cle, url, titre, entreprise, statut) VALUES "
                      "('rappel1', 'https://exemple.be/offre/1', 'Poste', 'Employeur Rappel', 'manuelle')")
        db.kv_set("dernier_rappel_site", None)
        rapporteur.rappel_via_site(heure=10)
        rapporteur.rappel_via_site(heure=10)                     # 2e fois le même jour : rien
        self.assertEqual(sum("Employeur Rappel" in m for m in self.canal.messages), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
