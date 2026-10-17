"""Agents Rédacteur & Juge (boucle « écrire → noter → corriger », motif evaluator-optimizer d'Anthropic).

  Rédacteur (modèle qualité) : écrit la lettre + l'email, nourri par
     – le profil (seule source de vérité),
     – les liens « pourquoi toi » trouvés par l'Évaluateur, les faits trouvés par l'Enquêteur,
     – tes notes de style (« plus court », « moins formel »…) et 2 lettres que tu as validées (il apprend ton goût).
  Juge (modèle rapide, regard neuf) : note /10 selon une grille d'associé exigeant, bloque toute invention.
  Jusqu'à 3 versions ; on garde la meilleure. Sous la note minimale → elle t'est montrée avec un ⚠️."""
from __future__ import annotations

import json
from datetime import date

from .. import config, db, llm, messagerie

SCHEMA_LETTRE = {
    "type": "object",
    "properties": {"lettre": {"type": "string"}, "objet": {"type": "string"}, "email": {"type": "string"}},
    "required": ["lettre", "objet", "email"],
}
SCHEMA_JUGE = {
    "type": "object",
    "properties": {"note": {"type": "integer", "minimum": 1, "maximum": 10}, "invention": {"type": "boolean"},
                   "corrections": {"type": "array", "items": {"type": "string"}}},
    "required": ["note", "invention", "corrections"],
}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def _offre(o) -> dict:
    infos = json.loads(o["infos_cabinet"] or "{}")
    return {"source": o["source"], "poste": o["titre"], "employeur": o["entreprise"], "ville": o["ville"],
            "matiere": o["matiere"], "contrat": o["contrat"], "langue": o["langue"],
            "description": (o["description"] or "")[:3000], "pourquoi": json.loads(o["pourquoi"] or "[]"),
            "faits_employeur": infos.get("faits", []), "destinataire": infos.get("destinataire")}


def lettres_aimees(n: int = 2) -> list[str]:
    """Les dernières lettres que tu as validées toi-même : le Rédacteur s'aligne sur ton goût."""
    return [r["lettre"][:1400] for r in db.q(
        "SELECT lettre FROM offres WHERE lettre IS NOT NULL AND id IN "
        "(SELECT offre_id FROM evenements WHERE agent='concierge' AND quoi='→ validee') ORDER BY id DESC LIMIT ?", n)]


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
    for f in ("C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
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


def ecrire_une(o) -> dict:
    """Écrit, fait juger, corrige. Renvoie la meilleure version {lettre, objet, email, note, corrections}."""
    regles = config.regles_envoi()
    profil = config.profil_texte()
    systeme_r = llm.prompt("redacteur") + "\n\n## Profil (seule source de vérité)\n" + profil
    systeme_j = llm.prompt("verificateur") + "\n\n## Profil\n" + profil
    aujourdhui = f"{date.today().day} {MOIS[date.today().month - 1]} {date.today().year}"
    demande = {"offre": _offre(o), "date_du_jour": aujourdhui, "notes_style": config.style_texte() or None,
               "lettres_aimees": lettres_aimees()}
    meilleure = None
    for _ in range(3):
        r = llm.demander("redacteur", "qualite", systeme_r, json.dumps(demande, ensure_ascii=False),
                         SCHEMA_LETTRE, max_tokens=2200)
        j = llm.demander("juge", "rapide", systeme_j,
                         json.dumps({"offre": demande["offre"], "candidature": r}, ensure_ascii=False),
                         SCHEMA_JUGE, max_tokens=700)
        note = 1 if j["invention"] else j["note"]
        if meilleure is None or note > meilleure["note"]:
            meilleure = {**r, "note": note, "corrections": j["corrections"]}
        if note >= regles["note_lettre_minimum"]:
            break
        demande["corrections_a_appliquer"] = j["corrections"]
        demande["version_precedente"] = r
    return meilleure


def rediger(limite: int = 8):
    if not config.profil_texte().strip():
        db.journal("redacteur", "profil vide : en attente du CV")
        return
    regles = config.regles_envoi()
    dossier = config.DONNEES / "lettres"
    dossier.mkdir(parents=True, exist_ok=True)
    # les offres les plus fraîches d'abord : postuler dans les 4 premiers jours multiplie les chances
    offres = db.q("SELECT * FROM offres WHERE statut='qualifiee' AND infos_cabinet IS NOT NULL "
                  "ORDER BY COALESCE(publie_le, date(cree_le)) DESC, score DESC LIMIT ?", limite)
    for o in offres:
        try:
            v = ecrire_une(o)
        except llm.BudgetDepasse:
            return
        except Exception as e:
            db.journal("redacteur", f"échec : {e}", o["id"])
            continue
        ecrire_pdf(v["lettre"], dossier / f"lettre_{o['id']}.pdf")
        bonne = v["note"] >= regles["note_lettre_minimum"]
        db.changer_statut(o["id"], "redigee", "redacteur",
                          None if bonne else "à relire : " + "; ".join(v["corrections"])[:300],
                          lettre=v["lettre"], objet_mail=v["objet"], corps_mail=v["email"], note_lettre=v["note"])
        auto = regles["mode"] == "auto" and bonne
        db.changer_statut(o["id"], "validee" if auto else "a_valider", "redacteur")


def chemin_lettre(offre_id: int):
    base = config.DONNEES / "lettres" / f"lettre_{offre_id}"
    return base.with_suffix(".pdf") if base.with_suffix(".pdf").exists() else base.with_suffix(".txt")


def carte(o) -> tuple[str, list]:
    """Une candidature prête, présentée en 5 lignes avec ses boutons."""
    pourquoi = json.loads(o["pourquoi"] or "[]")
    alerte = "\n⚠️ À relire : " + o["raison"][10:160] if (o["raison"] or "").startswith("à relire") else ""
    via = "📧 par email" if o["email_contact"] else "🌐 via leur site (je te prépare tout)"
    spont = "✨ Spontanée · " if o["source"] == "spontanee" else ""
    frais = f" · publiée le {o['publie_le']}" if o["publie_le"] else ""
    texte = (f"*{o['id']}. {o['titre']}*\n{spont}{o['entreprise'] or '?'} — {o['ville'] or '?'}{frais}\n"
             f"Adéquation {o['score']}/10 · lettre {o['note_lettre'] or '?'}/10 · {via}\n"
             + "".join(f"• {p}\n" for p in pourquoi[:2]) + alerte)
    boutons = [[("✅ Envoyer", f"ok {o['id']}"), ("👁 Lettre", f"montre {o['id']}"), ("❌ Non", f"ecarte {o['id']}")]]
    return texte.strip(), boutons


def proposer_lot():
    """Chaque nouvelle candidature prête t'arrive en carte, avec ses boutons (une seule fois chacune)."""
    lot = db.q("SELECT * FROM offres WHERE statut='a_valider' AND notifie=0 ORDER BY score DESC, note_lettre DESC")
    if not lot:
        return
    messagerie.dire(f"🔎 {len(lot)} candidature(s) prête(s) :")
    for o in lot:
        messagerie.dire(*carte(o))
    if len(lot) > 1:
        messagerie.dire("Ou d'un coup :", [[("✅ Tout envoyer", "ok tout")]])
    with db.tx() as c:
        c.executemany("UPDATE offres SET notifie=1 WHERE id=?", [(o["id"],) for o in lot])
