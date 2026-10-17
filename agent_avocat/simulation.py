"""Réponses factices pour faire tourner TOUT le circuit sans clé API (SIMULATION=1).
Elles respectent les mêmes schémas que les vraies : si ça marche ici, la plomberie est bonne."""
from __future__ import annotations

import json
import re

OFFRES = [
    {"url": "https://www.jobat.be/fr/emplois/juriste-immobilier-123", "titre": "Juriste en droit immobilier",
     "entreprise": "Cabinet Lumen Avocats", "ville": "Bruxelles", "matiere": "droit immobilier", "contrat": "CDI",
     "langue": "français", "description": "Le cabinet recherche un juriste pour des dossiers de baux commerciaux, "
     "copropriété et ventes immobilières. Rédaction d'actes et de consultations.",
     "email_contact": "jobs@lumen-avocats.be", "mode_candidature": "email"},
    {"url": "https://www.legalworld.be/offre/stage-penal-77", "titre": "Stagiaire avocat – droit pénal",
     "entreprise": "Cabinet Themis", "ville": "Bruxelles", "matiere": "droit pénal", "contrat": "stage",
     "langue": "français", "description": "Défense pénale, audiences au tribunal correctionnel.",
     "email_contact": "stage@themis.be", "mode_candidature": "email"},
    {"url": "https://www.stepstone.be/offre/paralegal-corporate-9", "titre": "Paralegal corporate",
     "entreprise": "Nordlex", "ville": "Bruxelles", "matiere": "droit des sociétés", "contrat": "CDI",
     "langue": "français + néerlandais", "description": "Support aux opérations M&A, bilinguisme FR/NL exigé.",
     "email_contact": None, "mode_candidature": "formulaire"},
    {"url": "https://www.avocats-delta.be/carrieres/collaborateur", "titre": "Collaborateur en droit immobilier",
     "entreprise": "Delta & Associés", "ville": "Bruxelles", "matiere": "droit immobilier", "contrat": "CDI",
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
        return {"matiere": "généraliste", "mode_candidature": "inconnu"}
    if agent == "evaluateur":
        notes = []
        for o in d:
            imm = "immobilier" in (o.get("matiere") or "")
            notes.append({"id": o["id"], "regle_violee": False, "score": 9 if imm else 5,
                          "raison": "Matière et ville alignées" if imm else "Matière secondaire"})
        return {"notes": notes}
    if agent == "enqueteur":
        return {"faits": [f"{d.get('employeur')} est actif en baux commerciaux à Bruxelles."],
                "email_recrutement": None, "destinataire": None}
    if agent == "redacteur":
        o = d["offre"]
        return {"lettre": f"Bruxelles, le {d['date_du_jour']}\n\nMadame, Monsieur,\n\nVotre offre de {o['poste']} "
                          f"chez {o['employeur']} a retenu toute mon attention…\n\nJe vous prie d'agréer, Madame, "
                          "Monsieur, l'expression de mes salutations distinguées.",
                "objet": f"Candidature – {o['poste']}",
                "email": "Madame, Monsieur,\n\nVeuillez trouver ci-joint mon CV et ma lettre de motivation.\n\nBien à vous"}
    if agent == "verificateur":
        return {"ok": True, "corrections": []}
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
        return {"action": "discuter", "reponse": "Bien noté 👍"}
    if agent == "coach":
        m = d.get("message", "").lower()
        maj = {}
        if "immobilier" in m:
            maj["matieres_uniquement"] = ["droit immobilier"]
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
