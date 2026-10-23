"""Réponses factices pour faire tourner TOUT le circuit sans clé API (SIMULATION=1).
Elles respectent les mêmes schémas que les vraies : si ça marche ici, la plomberie est bonne."""
from __future__ import annotations

import json
import re

OFFRES = [
    {"url": "https://www.jobat.be/fr/emplois/juriste-immobilier-123", "titre": "Juriste en droit immobilier",
     "entreprise": "Cabinet Lumen Avocats", "ville": "Bruxelles", "secteur": "droit immobilier", "contrat": "CDI",
     "langue": "français", "description": "Le cabinet recherche un juriste pour des dossiers de baux commerciaux, "
     "copropriété et ventes immobilières. Rédaction d'actes et de consultations.",
     "email_contact": "jobs@lumen-avocats.be", "mode_candidature": "email"},
    {"url": "https://www.legalworld.be/offre/stage-penal-77", "titre": "Stagiaire avocat – droit pénal",
     "entreprise": "Cabinet Themis", "ville": "Bruxelles", "secteur": "droit pénal", "contrat": "stage",
     "langue": "français", "description": "Défense pénale, audiences au tribunal correctionnel.",
     "email_contact": "stage@themis.be", "mode_candidature": "email"},
    {"url": "https://www.stepstone.be/offre/paralegal-corporate-9", "titre": "Paralegal corporate",
     "entreprise": "Nordlex", "ville": "Bruxelles", "secteur": "droit des sociétés", "contrat": "CDI",
     "langue": "français + néerlandais", "description": "Support aux opérations M&A, bilinguisme FR/NL exigé.",
     "email_contact": None, "mode_candidature": "formulaire"},
    {"url": "https://www.avocats-delta.be/carrieres/collaborateur", "titre": "Collaborateur en droit immobilier",
     "entreprise": "Delta & Associés", "ville": "Bruxelles", "secteur": "droit immobilier", "contrat": "CDI",
     "langue": "français", "description": "Urbanisme, permis, contentieux de la construction.",
     "email_contact": None, "mode_candidature": "formulaire"},
]


def repondre(agent: str, contenu: str, schema: dict) -> dict:
    try:
        d = json.loads(contenu)
    except Exception:
        d = {"texte": contenu}

    if agent == "eclaireur":
        return {"offres": [o for o in OFFRES if o["url"] not in (d.get("deja_connues") or [])]}
    if agent == "extracteur":
        return {"secteur": "généraliste", "mode_candidature": "inconnu"}
    if agent == "evaluateur":
        notes = []
        for o in d:
            imm = "immobilier" in (o.get("secteur") or "")
            notes.append({"id": o["id"], "regle": None, "regle_violee": False, "score": 9 if imm else 5,
                          "raison": "Matière et ville alignées" if imm else "Matière secondaire",
                          "pourquoi": ["Mémoire en droit de la copropriété ↔ dossiers de copropriété"] if imm else []})
        return {"notes": notes}
    if agent == "enqueteur":
        return {"faits": [f"{d.get('employeur')} est actif en baux commerciaux à Bruxelles."],
                "email_recrutement": None, "destinataire": None}
    if agent == "redacteur":
        o = d["offre"]
        corps = ("Mon parcours m'a permis de travailler des dossiers concrets, de rédiger des notes de synthèse "
                 "et de suivre des audiences, ce qui correspond aux missions décrites dans votre annonce. ") * 6
        return {"lettre": f"Bruxelles, le {d['date_du_jour']}\n\nMadame, Monsieur,\n\nVotre offre de {o['poste']} "
                          f"chez {o['employeur']} a retenu toute mon attention.\n\n{corps}\n\nJe vous prie d'agréer, "
                          "Madame, Monsieur, l'expression de mes salutations distinguées.\n\nAlex Test",
                "objet": f"Candidature – {o['poste']}",
                "email": "Madame, Monsieur,\n\nVeuillez trouver ci-joint mon CV et ma lettre de motivation.\n\nBien à vous"}
    if agent == "juge":
        return {"note": 9, "invention": False, "corrections": []}
    if agent == "prospecteur":
        return {"employeurs": [
            {"nom": "Cabinet Horizon Immo", "site": "https://horizon-immo.example", "ville": "Bruxelles",
             "secteurs": ["droit immobilier"], "email_recrutement": "stage@horizon-immo.example",
             "destinataire": None, "faits": ["Actif en baux commerciaux."]},
            {"nom": "Sans Email & Co", "site": "https://sansemail.example", "ville": "Bruxelles",
             "secteurs": ["droit immobilier"], "email_recrutement": None, "faits": []}]}
    if agent == "preparateur":
        return {"fiche": "1. L'employeur…\n2. Pourquoi toi…"}
    if agent == "trieur":
        t = f"{d.get('sujet', '')} {d.get('corps', '')}".lower()
        if "entretien" in t or "rencontrer" in t:
            return {"categorie": "entretien", "resume": "Invitation à un entretien.",
                    "employeur": (d.get("offre_liee") or {}).get("entreprise"),
                    "creneaux": ["2026-12-24T16:30"], "lieu": "Avenue Louise 54, Bruxelles"}
        if "pas retenu" in t or "regret" in t:
            return {"categorie": "refus", "resume": "Candidature non retenue.", "creneaux": []}
        return {"categorie": "autre", "resume": "Sans lien.", "creneaux": []}
    if agent == "secretaire":
        return {"email": "Madame, Monsieur,\n\nJe vous remercie et vous confirme ma présence.\n\nBien à vous"}
    if agent == "concierge":
        m = d.get("message", "").lower()
        rdv = (d.get("contexte") or {}).get("rdv_proposes") or []
        if rdv and re.search(r"\b(oui|ok|parfait|confirme)", m):
            return {"action": "confirmer_rdv", "rdv_id": rdv[0]["id"], "reponse": "Je confirme !"}
        if "blocus" in m or "examens" in m:
            return {"action": "pause", "jusqu_au": "2099-06-20", "reponse": "Bon courage pour les examens."}
        if "essayer" in m or "voir si ça marche" in m:
            return {"action": "banc", "reponse": "Je me teste"}
        if "longue" in m or "formel" in m:
            return {"action": "style", "texte": "Lettres plus courtes (250 mots max).", "reponse": "Noté"}
        return {"action": "discuter", "reponse": "Bien noté 👍"}
    if agent == "coach":
        m = d.get("message", "").lower()
        maj = {}
        if "immobilier" in m:
            maj["secteurs_uniquement"] = ["droit immobilier"]
        if "lance" in m or "go" in m:
            return {"reponse": "C'est parti 🚀", "objectif_maj": maj, "termine": True}
        return {"reponse": "Super. Quelles villes ? Et tu veux un CDI ou un stage ?", "objectif_maj": maj,
                "termine": False}
    if agent == "profileur":
        if "lignes" in schema.get("properties", {}):
            return {"lignes": [f"- {d.get('texte', contenu)}"]}
        return {"fiche_markdown": "# Profil\n- Nom : Alex Test\n- Master en droit (simulation)\n",
                "nom": "Alex Test", "telephone": "0470 00 00 00", "manquants": ["disponibilité"]}
    raise KeyError(f"Pas de réponse simulée pour {agent}")


def manager(texte: str) -> tuple[list, str]:
    """Le Manager en simulation : quelques intentions reconnues par mots-clés → mêmes OUTILS que la vraie IA."""
    import re as _re
    from . import db as _db
    m = texte.lower()
    rdv = _db.q("SELECT id FROM rdv WHERE statut='propose'")
    if rdv and _re.search(r"\b(oui|ok|parfait|confirme)", m):
        return [("rendez_vous", {"rdv_id": rdv[0]["id"], "decision": "confirmer"})], "Je confirme le rendez-vous."
    if "blocus" in m or "examens" in m:
        return [("pause", {"jusqu_au": "2099-06-20"})], ""
    if "essayer" in m or "voir si ça marche" in m:
        return [("teste_toi", {})], "Je me teste, rapport dans 3 minutes."
    if "longue" in m or "formel" in m:
        return [("regle_de_style", {"consigne": "Lettres plus courtes (250 mots max)."})], "Noté."
    if adresse := _re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", texte):
        return [("envoyer_par_email", {"adresse": adresse.group(0)})], ""
    if "ici" in m and "envoie" in m:
        return [("envoyer_dans_le_chat", {"ids": []})], ""
    if "maintenant" in m or "tout de suite" in m:
        return [("chercher_maintenant", {})], "C'est lancé."
    if "score" in m or "note minimum" in m:
        return [("regler", {"cle": "score_minimum", "valeur": int(_re.findall(r"\d+", m)[0])})], ""
    return [], "Bien noté."
