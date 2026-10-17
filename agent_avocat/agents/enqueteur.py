"""Agent 7 — Enquêteur : 2-3 faits vérifiés sur l'employeur + email de recrutement manquant.
Il ne travaille que pour les meilleures offres (score ≥ 8) : c'est là que la personnalisation paie."""
from __future__ import annotations

import json

from .. import db, llm, outils

SCHEMA = {
    "type": "object",
    "properties": {
        "faits": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "email_recrutement": {"type": ["string", "null"]},
        "destinataire": {"type": ["string", "null"], "description": "Nom de la personne à qui adresser la lettre"},
    },
    "required": ["faits"],
}


def enqueter(score_min: int = 8):
    for o in db.q("SELECT * FROM offres WHERE statut='qualifiee' AND infos_cabinet IS NULL"):
        infos = {"faits": [], "destinataire": None}
        if (o["score"] or 0) >= score_min and o["entreprise"]:
            try:
                r = llm.demander("enqueteur", "rapide", llm.prompt("enqueteur"),
                                 json.dumps({"employeur": o["entreprise"], "ville": o["ville"],
                                             "poste": o["titre"], "url_offre": o["url"],
                                             "email_connu": o["email_contact"]}, ensure_ascii=False),
                                 SCHEMA, web=True, recherches_max=2, max_tokens=1200)
                infos = {"faits": r.get("faits", []), "destinataire": r.get("destinataire")}
                email = outils.emails_dans(r.get("email_recrutement") or "")
                if email and not o["email_contact"]:
                    db.maj(o["id"], email_contact=email[0], mode_candidature="email")
            except llm.BudgetDepasse:
                return
            except Exception as e:
                db.journal("enqueteur", f"échec : {e}", o["id"])
        db.maj(o["id"], infos_cabinet=json.dumps(infos, ensure_ascii=False))
