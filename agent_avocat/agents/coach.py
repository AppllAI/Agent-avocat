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


MENU = ("📋 *Ce que tu peux me dire* (ou en vocal 🎙️, avec tes mots) :\n"
        "• « ok » / « ok sauf 3 » / « montre 3 » → valider, retirer, voir une lettre\n"
        "• « oui » / « plutôt jeudi » / « non » → répondre à un entretien\n"
        "• « essai » + un lien d'offre → je te montre ce que je ferais, sans envoyer\n"
        "• « teste-toi » → 5 lettres d'exemple notées, pour juger ma qualité\n"
        "• « plus de droit fiscal », « ajoute Liège » → changer ta recherche\n"
        "• « trop long », « moins formel » → régler le style des lettres\n"
        "• « cherche » · « stats » · « pause » · « reprendre » · « mode »")


def bienvenue():
    messagerie.dire("⚖️ *Agent Avocat*\nJe cherche les offres en continu, j'écris une lettre sur mesure pour "
                    "chacune et je postule. Je ne te dérange que pour décider.\n\n"
                    "*Pour démarrer :*\n1️⃣ Envoie ton CV en PDF ici\n2️⃣ Dis-moi ce que tu cherches "
                    "(poste, matières, villes, ce que tu refuses)\n\n"
                    "🧪 Je démarre en *mode répétition* : les emails arrivent dans TA boîte, jamais chez les "
                    "cabinets, tant que tu ne me dis pas « mode validation ».\n\n" + MENU)


def parler(texte: str):
    o = config.objectif()
    actif = o.get("domaine_actif", "droit_belge")
    dom = o.setdefault("domaines", {}).setdefault(actif, {})
    contexte = {"objectif_actuel": dom, "cv_recu": config.chemin_cv().exists() and bool(config.profil_texte().strip()),
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
    except Exception as e:
        db.journal("profileur", f"lecture du CV en échec : {e}")
        return messagerie.dire("⚠️ Je n'ai pas réussi à analyser ton CV (erreur technique). Je réessaie tout seul "
                               "dans quelques minutes, pas besoin de le renvoyer.")
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
