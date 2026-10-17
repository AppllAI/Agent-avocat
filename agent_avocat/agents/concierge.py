"""Agent 18 — Concierge : le SEUL qui te parle. Il reçoit tes messages (texte, vocal, PDF),
comprend ce que tu veux et passe la main au bon agent (motif « routing » d'Anthropic).

Économie : les commandes évidentes (« stats », « ok », « ok sauf 3 », « montre 4 », « pause »)
sont reconnues sans IA. L'IA rapide n'intervient que pour les phrases libres."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .. import db, llm, messagerie
from . import coach, rapporteur, secretaire, transcripteur
from .redacteur import chemin_lettre

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": [
            "valider", "ecarter", "details", "confirmer_rdv", "autre_date", "decliner_rdv", "repondre_recruteur",
            "objectif", "profil", "fait", "stats", "pause", "reprendre", "aide", "discuter"]},
        "ids": {"type": "array", "items": {"type": "integer"}},
        "rdv_id": {"type": ["integer", "null"]}, "creneau": {"type": ["string", "null"]},
        "email_id": {"type": ["integer", "null"]}, "texte": {"type": ["string", "null"]},
        "reponse": {"type": "string"},
    },
    "required": ["action", "reponse"],
}
AIDE = ("Je m'occupe de tout, tu n'interviens que pour décider. Tu peux me dire par exemple :\n"
        "• « ok » / « ok sauf 3 » / « montre 3 » pour les candidatures en attente\n"
        "• « oui » / « plutôt jeudi 14h » / « non » pour un entretien\n"
        "• « je ne veux plus de droit fiscal », « ajoute Liège » pour changer ta recherche\n"
        "• « stats », « pause », « reprendre »\nLes vocaux marchent aussi 🎙️")


@dataclass
class Entrant:
    texte: str = ""
    audio: Path | None = None
    fichier: Path | None = None
    nom_fichier: str = ""


def recevoir(m: Entrant):
    if m.fichier:
        if (m.nom_fichier or str(m.fichier)).lower().endswith(".pdf"):
            coach.recevoir_cv(Path(m.fichier))
            if not coach.onboarding_fini():
                coach.parler(m.texte or "Voici mon CV.")
            return
        return messagerie.dire("Je ne sais lire que les PDF pour l'instant 📄")
    texte = (m.texte or "").strip()
    if m.audio:
        try:
            texte = (transcripteur.transcrire(Path(m.audio)) or "").strip()
        except Exception as e:
            db.journal("transcripteur", f"échec : {e}")
            texte = ""
        if not texte:
            return messagerie.dire("🎙️ Je n'ai pas pu écouter ton vocal, tu peux me l'écrire ?")
        db.journal("transcripteur", f"« {texte[:80]} »")
    if not texte:
        return
    db.dire("moi", texte)

    if not coach.onboarding_fini():
        return coach.parler(texte)
    if _raccourci(texte):
        return
    _ia(texte)


# ---------- Raccourcis sans IA ----------
def _ids(s):
    return [int(x) for x in re.findall(r"\d+", s)]


def _raccourci(t: str) -> bool:
    b = t.lower().strip(" !.?")
    attente = [r["id"] for r in db.q("SELECT id FROM offres WHERE statut='a_valider'")]
    rdv_ouverts = db.q("SELECT id FROM rdv WHERE statut='propose'")
    if b in ("stats", "bilan", "statistiques"):
        messagerie.dire(rapporteur.stats())
    elif b in ("aide", "help", "?"):
        messagerie.dire(AIDE)
    elif b in ("pause", "stop"):
        db.kv_set("pause", True)
        messagerie.dire("⏸️ En pause. Dis « reprendre » quand tu veux.")
    elif b in ("reprendre", "go", "relance", "reprends"):
        db.kv_set("pause", False)
        messagerie.dire("▶️ C'est reparti.")
    elif re.fullmatch(r"(montre|details?|détails?|voir)\s+\d+", b):
        details(_ids(b)[0])
    elif re.fullmatch(r"fait\s+[\d ,et]+", b):
        _fait(_ids(b))
    elif attente and not rdv_ouverts and re.fullmatch(r"(ok|oui|valide|go|envoie)( tout| tous| toutes)?", b):
        valider(attente)
    elif attente and re.fullmatch(r"(ok|valide|envoie)( tout)? sauf [\d ,et]+", b):
        sauf = set(_ids(b))
        ecarter(list(sauf))
        valider([i for i in attente if i not in sauf])
    else:
        return False
    return True


# ---------- IA pour le reste ----------
def _contexte():
    attente = [dict(r) for r in db.q("SELECT id, titre, entreprise, ville, score FROM offres WHERE statut='a_valider'")]
    rdv = [dict(r) for r in db.q("SELECT id, email_id, entreprise, debut, lieu FROM rdv WHERE statut='propose'")]
    questions = [{"email_id": r["id"], "de": r["expediteur"], "resume": json.loads(r["analyse"] or "{}").get("resume")}
                 for r in db.q("SELECT * FROM emails_recus WHERE categorie='question' AND traite=0")]
    manuelles = [dict(r) for r in db.q("SELECT id, entreprise, url FROM offres WHERE statut='manuelle'")]
    return {"en_attente_de_validation": attente, "rdv_proposes": rdv, "questions_recruteurs": questions,
            "a_postuler_via_site": manuelles, "en_pause": db.kv_get("pause", False)}


def _ia(texte: str):
    try:
        d = llm.demander("concierge", "rapide", llm.prompt("concierge"),
                         json.dumps({"contexte": _contexte(), "historique": db.historique(8), "message": texte},
                                    ensure_ascii=False), SCHEMA, max_tokens=700)
    except llm.BudgetDepasse as e:
        return messagerie.dire(f"⏸️ {e}. Les envois sans IA continuent ; on reprend demain.")
    a, ids = d["action"], d.get("ids") or []
    try:
        if a == "valider":
            return valider(ids or [r["id"] for r in db.q("SELECT id FROM offres WHERE statut='a_valider'")])
        if a == "ecarter":
            ecarter(ids)
        elif a == "details" and ids:
            return details(ids[0])
        elif a == "confirmer_rdv" and d.get("rdv_id"):
            return secretaire.confirmer(d["rdv_id"], d.get("creneau"))
        elif a == "autre_date" and d.get("rdv_id"):
            return secretaire.autre_date(d["rdv_id"], d.get("texte") or texte)
        elif a == "decliner_rdv" and d.get("rdv_id"):
            return secretaire.decliner(d["rdv_id"])
        elif a == "repondre_recruteur" and d.get("email_id"):
            return secretaire.repondre_question(d["email_id"], d.get("texte") or texte)
        elif a == "objectif":
            return coach.parler(texte)
        elif a == "profil":
            return coach.completer_profil(texte)
        elif a == "fait":
            return _fait(ids)
        elif a in ("stats", "aide", "pause", "reprendre"):
            return _raccourci(a)
    except Exception as e:
        db.journal("concierge", f"action {a} en échec : {e}")
        return messagerie.dire(f"⚠️ Je n'ai pas réussi : {e}")
    messagerie.dire(d["reponse"])


# ---------- Actions ----------
def valider(ids):
    n = 0
    for i in ids:
        o = db.q1("SELECT statut FROM offres WHERE id=?", i)
        if o and o["statut"] == "a_valider":
            db.changer_statut(i, "validee", "concierge")
            n += 1
    from .. import orchestrateur
    messagerie.dire(f"✅ {n} candidature(s) validée(s). Je les envoie une par une, en heures de bureau, "
                    "pour ne pas finir en spam.")
    orchestrateur.envoyer_bientot()


def ecarter(ids):
    for i in ids:
        o = db.q1("SELECT statut FROM offres WHERE id=?", i)
        if o and "ecartee" in db.TRANSITIONS.get(o["statut"], set()):
            db.changer_statut(i, "ecartee", "concierge", "écartée par moi")


def details(i):
    o = db.q1("SELECT * FROM offres WHERE id=?", i)
    if not o:
        return messagerie.dire(f"Pas d'offre n°{i}.")
    messagerie.dire(f"*{o['titre']}* — {o['entreprise'] or '?'} ({o['ville'] or '?'})\n"
                    f"{o['score'] or '?'}/10 · {o['raison'] or ''}\n{o['url']}\n\n"
                    f"✉️ Objet : {o['objet_mail'] or '—'}\n\n{(o['lettre'] or '(lettre pas encore écrite)')[:1500]}")
    if o["lettre"]:
        messagerie.fichier(chemin_lettre(i), "Lettre de motivation")


def _fait(ids):
    from datetime import datetime
    for i in ids:
        o = db.q1("SELECT statut FROM offres WHERE id=?", i)
        if o and o["statut"] == "manuelle":
            db.changer_statut(i, "envoyee", "concierge", "postulé via le site",
                              envoye_le=datetime.now().isoformat(" ", "seconds"))
    messagerie.dire("👍 Noté.")
