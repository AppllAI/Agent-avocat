"""Agent 6 — Évaluateur : note les offres /10 face à ton objectif.
Économie : 8 offres par appel (le profil et l'objectif ne sont envoyés qu'une fois) + modèle rapide."""
from __future__ import annotations

import json

from .. import config, db, llm

SCHEMA = {
    "type": "object",
    "properties": {"notes": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "regle_violee": {"type": "boolean"},
                       "score": {"type": "integer", "minimum": 1, "maximum": 10}, "raison": {"type": "string"}},
        "required": ["id", "regle_violee", "score", "raison"],
    }}},
    "required": ["notes"],
}
CHAMPS = ("id", "titre", "entreprise", "ville", "matiere", "contrat", "langue", "description")


def evaluer(taille_lot: int = 8):
    dom, regles = config.domaine_actif(), config.regles_envoi()
    offres = [dict(o) for o in db.q("SELECT * FROM offres WHERE statut='enrichie' ORDER BY id")]
    systeme = llm.prompt("evaluateur") + "\n\n## Objectif\n" + json.dumps(dom, ensure_ascii=False) + \
        "\n\n## Profil\n" + (config.profil_texte() or "(profil non rempli)")
    retenues = 0
    for i in range(0, len(offres), taille_lot):
        lot = offres[i:i + taille_lot]
        contenu = json.dumps([{k: (o[k][:1500] if k == "description" and o[k] else o[k]) for k in CHAMPS}
                              for o in lot], ensure_ascii=False)
        try:
            notes = llm.demander("evaluateur", "rapide", systeme, contenu, SCHEMA, max_tokens=1200)["notes"]
        except llm.BudgetDepasse:
            return retenues
        except Exception as e:
            db.journal("evaluateur", f"lot en échec, réessai au prochain cycle : {e}")
            continue
        ids = {o["id"] for o in lot}
        for n in notes:
            if n["id"] not in ids:
                continue
            ok = not n["regle_violee"] and n["score"] >= regles["score_minimum"]
            db.changer_statut(n["id"], "qualifiee" if ok else "ecartee", "evaluateur",
                              f"{n['score']}/10 · {n['raison']}", score=n["score"])
            retenues += ok
    return retenues
