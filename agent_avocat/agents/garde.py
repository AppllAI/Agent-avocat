"""Agent 5 — Garde : applique tes règles NON NÉGOCIABLES, sans IA (gratuit, instantané, infaillible).
Tout ce qu'il peut trancher seul n'arrive jamais jusqu'à l'IA → économie de tokens."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .. import config, db
from ..outils import sans_accents

# Synonymes : "droit pénal" exclu doit aussi attraper "criminel", "correctionnel"…
SYNONYMES = {   # FR / NL / EN : les offres belges arrivent dans les trois langues
    "droit penal": ["penal", "criminel", "correctionnel", "infraction", "parquet", "cour d'assises",
                    "criminal", "strafrecht", "white collar"],
    "droit immobilier": ["immobilier", "bail", "baux", "copropriete", "urbanisme", "construction", "notarial",
                         "real estate", "vastgoed", "huur", "bouwrecht", "stedenbouw"],
    "droit des societes": ["societes", "corporate", "m&a", "fusions", "gouvernance", "vennootschap"],
    "droit social": ["droit social", "droit du travail", "employment", "labour", "labor", "arbeidsrecht",
                     "sociaal recht", "securite sociale"],
    "droit fiscal": ["fiscal", "tax", "tva", "impots", "fiscaal", "belasting"],
    "droit familial": ["familial", "famille", "divorce", "filiation", "successions", "family", "familierecht"],
    "droit administratif": ["administratif", "conseil d'etat", "marches publics", "public law", "bestuursrecht",
                            "overheidsopdrachten"],
    "droit europeen": ["europeen", "eu law", "european", "concurrence", "competition", "mededinging"],
    "droit commercial": ["commercial", "contrats", "distribution", "insolvabilite", "faillite", "handelsrecht",
                         "insolvency"],
    "propriete intellectuelle": ["propriete intellectuelle", "intellectual property", "marques", "brevets",
                                 "droit d'auteur", "trademark", "intellectuele eigendom"],
    "droit des etrangers": ["etrangers", "asile", "immigration", "sejour", "vreemdelingenrecht"],
}


def _termes(matiere: str) -> list[str]:
    m = sans_accents(matiere).strip()
    for cle, syn in SYNONYMES.items():
        if m == cle or m in syn or cle.replace("droit ", "") == m.replace("droit ", ""):
            return syn
    return [m.replace("droit ", "") or m]


def _contient(texte: str, terme: str) -> bool:
    """Mot entier (« bar » ne doit pas attraper « embarquement »)."""
    return re.search(rf"(?<![a-z]){re.escape(terme)}(?![a-z])", texte) is not None


# Pas un job étudiant (quand tu ne cherches QUE ça) : CDI, stage, temps plein, indépendant…
_PAS_ETUDIANT = re.compile(r"(?<![a-z])(cdi|stagiaire|internship|stagiair|vast contract|"
                           r"freelance|independant|zelfstandige|commission uniquement)(?![a-z])")
_ETUDIANT = re.compile(r"(?<![a-z])(etudiant|etudiante|etudiants|student|studenten|studentenjob|jobiste|flexi)")
# Arnaques et « petits boulots » qui n'en sont pas
_ARNAQUE = re.compile(r"sondages?|enquetes? (?:en ligne|de chez vous|remunerees?)|repondez a des|gagnez de l.argent|"
                      r"jeux en ligne|jouant a des jeux|teletravail.{0,20}sondage|"
                      r"gagner de l.argent|argent facile|paid surveys?|mystery shopper|"
                      r"vendeur a domicile|marketing de reseau|frais d.inscription|mlm")
# Une langue n'est éliminatoire que si l'annonce l'EXIGE (sinon c'est un atout : l'Évaluateur pèse)
_EXIGE = re.compile(r"exig|obligatoire|indispensable|requis|imperati|courant|couramment|bilingue|parfait|native|"
                    r"fluent|required|vereist|vlot|must")


def _date(v):
    try:
        return datetime.fromisoformat(str(v)[:10]).date() if v else None
    except ValueError:
        return None


def verdict(o: dict, dom: dict, regles: dict) -> str | None:
    """Renvoie la raison de rejet, ou None si l'offre passe."""
    secteur = sans_accents(o.get("secteur") or "")
    titre = sans_accents(o.get("titre") or "")
    tout = f"{titre} {secteur} {sans_accents((o.get('description') or '')[:600])}"

    for m in dom.get("secteurs_exclus") or []:
        # titre ou matière = signal fort (la description cite souvent toutes les matières d'un cabinet généraliste)
        if any(_contient(f"{titre} {secteur}", t) for t in _termes(m)):
            return f"matière exclue : {m}"

    seules = dom.get("secteurs_uniquement") or []
    if seules and secteur and secteur not in ("generaliste", "divers"):
        if not any(_contient(tout, t) for m in seules for t in _termes(m)):
            return f"hors matières voulues ({', '.join(seules)})"

    # Trop ancienne : publiée il y a plus de 2 ans (ex. 2023 alors qu'on est en 2026). Un peu vieille (2024) :
    # on tente quand même, ils n'ont peut-être trouvé personne. Date limite dépassée : inutile.
    aujourdhui = datetime.now().date()
    publie = _date(o.get("publie_le"))
    if publie and publie.year < aujourdhui.year - 2:
        return f"offre trop ancienne (publiée en {publie.year})"
    limite_cand = _date(o.get("date_limite"))
    if limite_cand and limite_cand < aujourdhui:
        return f"date limite dépassée ({limite_cand:%d/%m/%Y})"

    if _ARNAQUE.search(tout):
        return "ressemble à une arnaque ou à des sondages rémunérés"
    contrats = " ".join(sans_accents(c) for c in dom.get("contrats") or [])
    if contrats and _ETUDIANT.search(contrats) and not any(m in contrats for m in ("cdi", "stage", "cdd", "temps plein")):
        signal = f"{titre} {sans_accents(o.get('contrat') or '')}"
        if _PAS_ETUDIANT.search(signal) and not _ETUDIANT.search(signal):
            return "pas un job étudiant (CDI, stage ou temps plein)"

    for e in dom.get("exclure_entreprises") or []:
        if sans_accents(e) in sans_accents(o.get("entreprise") or ""):
            return f"employeur exclu : {e}"

    if o.get("entreprise"):
        limite = (datetime.now() - timedelta(days=regles["delai_meme_cabinet_jours"])).isoformat(" ")
        deja = db.q1("SELECT 1 FROM offres WHERE id<>? AND lower(entreprise)=lower(?) AND envoye_le>=?",
                     o["id"], o["entreprise"], limite)
        if deja:
            return "déjà postulé chez cet employeur récemment"

    # Salaire horaire minimum (quand l'offre l'indique)
    mini = float(dom.get("salaire_min_horaire") or 0)
    if mini and o.get("salaire_horaire") and float(o["salaire_horaire"]) < mini:
        return f"salaire trop bas ({o['salaire_horaire']} €/h < {mini} €/h)"

    langue = sans_accents(o.get("langue") or "")
    connues = [sans_accents(l) for l in dom.get("langues") or []]
    if langue and connues:
        exigees = [x for x in ("neerlandais", "anglais", "allemand", "francais") if x in langue]
        manquantes = [x for x in exigees if not any(x in c for c in connues)]
        # champ « langue » = langues EXIGÉES selon l'Extracteur ; « + », « et », « bilingue » = exigence cumulée
        if manquantes and (_EXIGE.search(langue) or "+" in langue or " et " in langue):
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
