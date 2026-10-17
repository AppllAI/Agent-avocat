"""Agents 8 + 9 — Rédacteur & Vérificateur (boucle « écrire → relire → corriger »).

Le Rédacteur (modèle qualité) écrit ; le Vérificateur (modèle rapide, regard neuf, sans l'historique)
contrôle l'exactitude face au profil. 2 corrections max, sinon l'offre passe en validation manuelle
pour que tu tranches. C'est le motif « evaluator-optimizer » recommandé par Anthropic."""
from __future__ import annotations

import json
from datetime import date

from .. import config, db, llm, messagerie

SCHEMA_LETTRE = {
    "type": "object",
    "properties": {"lettre": {"type": "string"}, "objet": {"type": "string"}, "email": {"type": "string"}},
    "required": ["lettre", "objet", "email"],
}
SCHEMA_VERIF = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "corrections": {"type": "array", "items": {"type": "string"}}},
    "required": ["ok", "corrections"],
}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def _offre(o) -> dict:
    infos = json.loads(o["infos_cabinet"] or "{}")
    return {"poste": o["titre"], "employeur": o["entreprise"], "ville": o["ville"], "matiere": o["matiere"],
            "contrat": o["contrat"], "description": o["description"], "faits_employeur": infos.get("faits", []),
            "destinataire": infos.get("destinataire")}


def ecrire_pdf(texte: str, chemin):
    try:
        from fpdf import FPDF
    except ImportError:  # sans fpdf2 on garde un .txt lisible
        chemin.with_suffix(".txt").write_text(texte, encoding="utf-8")
        return chemin.with_suffix(".txt")
    pdf = FPDF()
    pdf.set_margins(22, 20, 22)
    pdf.add_page()
    police = "Helvetica"
    for f in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            pdf.add_font("Texte", "", f)
            police = "Texte"
            break
        except Exception:
            continue
    pdf.set_font(police, size=11)
    if police == "Helvetica":
        texte = texte.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 6, texte)
    pdf.output(str(chemin))
    return chemin


def rediger(limite: int = 6):
    profil = config.profil_texte()
    if not profil.strip():
        db.journal("redacteur", "profil vide : en attente du CV")
        return
    regles = config.regles_envoi()
    dossier = config.DONNEES / "lettres"
    dossier.mkdir(parents=True, exist_ok=True)
    aujourdhui = f"{date.today().day} {MOIS[date.today().month - 1]} {date.today().year}"
    systeme_r = llm.prompt("redacteur") + "\n\n## Profil (seule source de vérité)\n" + profil
    systeme_v = llm.prompt("verificateur") + "\n\n## Profil\n" + profil

    offres = db.q("SELECT * FROM offres WHERE statut='qualifiee' AND infos_cabinet IS NOT NULL "
                  "ORDER BY score DESC LIMIT ?", limite)
    for o in offres:
        demande = {"offre": _offre(o), "date_du_jour": aujourdhui}
        verdict = {"ok": False, "corrections": []}
        try:
            for essai in range(3):
                r = llm.demander("redacteur", "qualite", systeme_r, json.dumps(demande, ensure_ascii=False),
                                 SCHEMA_LETTRE, max_tokens=2200)
                verdict = llm.demander("verificateur", "rapide", systeme_v,
                                       json.dumps({"offre": demande["offre"], "candidature": r}, ensure_ascii=False),
                                       SCHEMA_VERIF, max_tokens=600)
                if verdict["ok"]:
                    break
                demande["corrections_a_appliquer"] = verdict["corrections"]
                demande["version_precedente"] = r
        except llm.BudgetDepasse:
            return
        except Exception as e:
            db.journal("redacteur", f"échec : {e}", o["id"])
            continue

        ecrire_pdf(r["lettre"], dossier / f"lettre_{o['id']}.pdf")
        db.changer_statut(o["id"], "redigee", "redacteur", None if verdict["ok"] else
                          "à relire : " + "; ".join(verdict["corrections"])[:300],
                          lettre=r["lettre"], objet_mail=r["objet"], corps_mail=r["email"])
        auto = regles["mode"] == "auto" and verdict["ok"]
        db.changer_statut(o["id"], "validee" if auto else "a_valider", "redacteur")


def chemin_lettre(offre_id: int):
    base = config.DONNEES / "lettres" / f"lettre_{offre_id}"
    return base.with_suffix(".pdf") if base.with_suffix(".pdf").exists() else base.with_suffix(".txt")


def proposer_lot():
    """Envoie sur la messagerie les nouvelles candidatures à valider (une seule fois chacune)."""
    lot = db.q("SELECT * FROM offres WHERE statut='a_valider' AND notifie=0 ORDER BY score DESC")
    if not lot:
        return
    lignes = []
    for o in lot:
        alerte = " ⚠️ à relire" if (o["raison"] or "").startswith("à relire") else ""
        canal = "" if o["email_contact"] else " (formulaire)"
        lignes.append(f"*{o['id']}.* {o['titre']} — {o['entreprise'] or '?'}, {o['ville'] or '?'} · {o['score']}/10{canal}{alerte}")
    messagerie.dire("🔎 Nouvelles candidatures prêtes :\n" + "\n".join(lignes) +
                    "\n\nRéponds « ok » pour tout envoyer, « ok sauf 4 », ou « montre 4 ».")
    with db.tx() as c:
        c.executemany("UPDATE offres SET notifie=1 WHERE id=?", [(o["id"],) for o in lot])
