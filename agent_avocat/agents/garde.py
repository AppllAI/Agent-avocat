"""Agent 5 — Garde : applique tes règles NON NÉGOCIABLES, sans IA (gratuit, instantané, infaillible).
Tout ce qu'il peut trancher seul n'arrive jamais jusqu'à l'IA → économie de tokens."""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import config, db
from ..outils import sans_accents

# Synonymes : "droit pénal" exclu doit aussi attraper "criminel", "correctionnel"…
SYNONYMES = {
    "droit penal": ["penal", "criminel", "correctionnel", "infraction", "parquet", "cour d'assises", "droit penal"],
    "droit immobilier": ["immobilier", "bail", "copropriete", "urbanisme", "construction", "notarial"],
    "droit des societes": ["societes", "corporate", "m&a", "fusions", "gouvernance"],
    "droit social": ["droit social", "droit du travail", "employment", "securite sociale"],
    "droit fiscal": ["fiscal", "tax", "tva", "impots"],
    "droit familial": ["familial", "famille", "divorce", "filiation", "successions"],
    "droit administratif": ["administratif", "conseil d'etat", "marches publics", "public law"],
    "droit europeen": ["europeen", "eu law", "concurrence", "competition"],
    "droit commercial": ["commercial", "contrats", "distribution", "insolvabilite", "faillite"],
    "propriete intellectuelle": ["propriete intellectuelle", "ip ", "marques", "brevets", "droit d'auteur"],
    "droit des etrangers": ["etrangers", "asile", "immigration", "sejour"],
}


def _termes(matiere: str) -> list[str]:
    m = sans_accents(matiere).strip()
    for cle, syn in SYNONYMES.items():
        if m == cle or m in syn or cle.replace("droit ", "") == m.replace("droit ", ""):
            return syn
    return [m.replace("droit ", "") or m]


def verdict(o: dict, dom: dict, regles: dict) -> str | None:
    """Renvoie la raison de rejet, ou None si l'offre passe."""
    matiere = sans_accents(o.get("matiere") or "")
    titre = sans_accents(o.get("titre") or "")
    tout = f"{titre} {matiere} {sans_accents((o.get('description') or '')[:600])}"

    for m in dom.get("matieres_exclues") or []:
        # titre ou matière = signal fort ; on ne regarde la description que pour le début (le cœur du poste)
        if any(t in f"{titre} {matiere}" for t in _termes(m)):
            return f"matière exclue : {m}"

    seules = dom.get("matieres_uniquement") or []
    if seules and matiere and matiere != "generaliste":
        if not any(t in tout for m in seules for t in _termes(m)):
            return f"hors matières voulues ({', '.join(seules)})"

    for e in dom.get("exclure_entreprises") or []:
        if sans_accents(e) in sans_accents(o.get("entreprise") or ""):
            return f"employeur exclu : {e}"

    if o.get("entreprise"):
        limite = (datetime.now() - timedelta(days=regles["delai_meme_cabinet_jours"])).isoformat(" ")
        deja = db.q1("SELECT 1 FROM offres WHERE id<>? AND lower(entreprise)=lower(?) AND envoye_le>=?",
                     o["id"], o["entreprise"], limite)
        if deja:
            return "déjà postulé chez cet employeur récemment"

    langue = sans_accents(o.get("langue") or "")
    connues = [sans_accents(l) for l in dom.get("langues") or []]
    if langue and connues:
        exigees = [x for x in ("neerlandais", "anglais", "allemand", "francais") if x in langue]
        manquantes = [x for x in exigees if not any(x in c for c in connues)]
        if manquantes and ("bilingue" in langue or "+" in langue or " et " in langue or len(exigees) == 1):
            return f"langue exigée non maîtrisée : {', '.join(manquantes)}"
    return None


def filtrer():
    dom, regles = config.domaine_actif(), config.regles_envoi()
    n = 0
    for o in db.q("SELECT * FROM offres WHERE statut='enrichie'"):
        raison = verdict(dict(o), dom, regles)
        if raison:
            db.changer_statut(o["id"], "ecartee", "garde", raison, score=0)
            n += 1
    return n
