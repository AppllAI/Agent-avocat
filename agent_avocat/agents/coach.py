"""Agents 15 + 16 — Coach & Profileur : la mise en route, 100 % sur ta messagerie.

  • Profileur : tu envoies ton CV en PDF → il en tire une fiche profil factuelle (la seule source
    de vérité des lettres) et te dit ce qui manque.
  • Coach : il te pose les bonnes questions (à l'écrit ou en vocal) et transforme tes réponses
    en règles strictes dans config/objectif.yaml."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .. import config, db, llm, messagerie

LISTE = {"type": "array", "items": {"type": "string"}}
SCHEMA_COACH = {
    "type": "object",
    "properties": {
        "reponse": {"type": "string"},
        "objectif_maj": {"type": "object", "properties": {
            "description": {"type": "string"}, "postes_vises": LISTE, "matieres_uniquement": LISTE,
            "matieres_exclues": LISTE, "villes": LISTE, "teletravail_ok": {"type": "boolean"}, "langues": LISTE,
            "contrats": LISTE, "exclure_entreprises": LISTE, "mots_cles_recherche": LISTE,
            "disponibilite": {"type": "string"}}},
        "termine": {"type": "boolean"},
    },
    "required": ["reponse", "objectif_maj", "termine"],
}
SCHEMA_PROFIL = {
    "type": "object",
    "properties": {"fiche_markdown": {"type": "string"}, "nom": {"type": ["string", "null"]},
                   "telephone": {"type": ["string", "null"]}, "manquants": LISTE},
    "required": ["fiche_markdown", "manquants"],
}
SCHEMA_AJOUT = {"type": "object", "properties": {"lignes": LISTE}, "required": ["lignes"]}


def onboarding_fini() -> bool:
    return bool(db.kv_get("onboarding_fini", False))


def bienvenue():
    messagerie.dire("👋 Salut ! Je suis ton agent de candidature. Je cherche les offres en continu, j'écris une "
                    "lettre sur mesure pour chacune, je postule et je ne te dérange que pour décider "
                    "(une candidature à valider, un entretien).\n\n"
                    "Pour commencer :\n1️⃣ envoie-moi ton *CV en PDF* ici\n"
                    "2️⃣ dis-moi (écrit ou vocal 🎙️) ce que tu cherches : poste, matières de droit, villes, "
                    "ce que tu ne veux surtout pas.\n\n"
                    "On démarre en *mode répétition* 🧪 : tout est réel, mais les emails arrivent dans TA boîte, "
                    "pas chez les cabinets. Tu passes en vrai quand tu es convaincu.")


def parler(texte: str):
    o = config.objectif()
    actif = o.get("domaine_actif", "droit_belge")
    dom = o.setdefault("domaines", {}).setdefault(actif, {})
    contexte = {"objectif_actuel": dom, "cv_recu": config.chemin_cv().exists(),
                "profil": config.profil_texte()[:1500], "historique": db.historique(10), "message": texte}
    try:
        r = llm.demander("coach", "rapide", llm.prompt("coach"), json.dumps(contexte, ensure_ascii=False),
                         SCHEMA_COACH, max_tokens=900)
    except llm.BudgetDepasse as e:
        return messagerie.dire(f"⏸️ {e}. On reprend demain !")
    maj = {k: v for k, v in (r.get("objectif_maj") or {}).items() if v not in (None, "", [])}
    if maj:
        dom.update(maj)
        config.sauver_objectif(o)
        db.journal("coach", f"objectif mis à jour : {', '.join(maj)}")
    messagerie.dire(r["reponse"])
    if r.get("termine") and config.chemin_cv().exists():
        db.kv_set("onboarding_fini", True)
        from .. import orchestrateur
        orchestrateur.declencher()


def recevoir_cv(chemin: Path):
    config.PROFIL_DIR.mkdir(parents=True, exist_ok=True)
    if Path(chemin).resolve() != config.chemin_cv().resolve():
        shutil.copy(chemin, config.chemin_cv())
    texte = _texte_pdf(config.chemin_cv())
    if not texte.strip():
        return messagerie.dire("📄 CV bien reçu ! Je n'arrive pas à lire son texte (PDF scanné ?). "
                               "Tu peux me renvoyer une version exportée depuis Word/Google Docs ?")
    try:
        r = llm.demander("profileur", "qualite", llm.prompt("profileur"), texte[:12000], SCHEMA_PROFIL,
                         max_tokens=2500)
    except llm.BudgetDepasse as e:
        return messagerie.dire(f"⏸️ {e}.")
    (config.PROFIL_DIR / "profil.md").write_text(r["fiche_markdown"], encoding="utf-8")
    identite = {"NOM_CANDIDAT": r.get("nom"), "TELEPHONE": r.get("telephone")}
    db.kv_set("identite", identite)
    appliquer_identite()
    msg = "📄 CV lu et enregistré ✅"
    if r["manquants"]:
        msg += "\nIl me manque : " + ", ".join(r["manquants"]) + ". Tu peux me le dire quand tu veux."
    messagerie.dire(msg)


def completer_profil(texte: str):
    """« J'ai un niveau B2 en néerlandais » → ajouté à la fiche, mot pour mot ou presque."""
    r = llm.demander("profileur", "rapide",
                     "Transforme ce que la personne dit sur elle en lignes factuelles de fiche profil "
                     "(« - Langues : néerlandais B2 »). Uniquement ce qu'elle affirme.",
                     texte, SCHEMA_AJOUT, max_tokens=300)
    f = config.PROFIL_DIR / "profil.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(r["lignes"]) + "\n")
    messagerie.dire("📝 Ajouté à ton profil.")


def appliquer_identite():
    for k, v in (db.kv_get("identite") or {}).items():
        if v:
            os.environ[k] = v


def _texte_pdf(chemin: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(chemin)).pages)
    except Exception:
        return ""
