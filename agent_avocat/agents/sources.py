"""Agents Éclaireurs : trouvent les offres, en parallèle, aussi souvent que possible.

  Gratuits (sans IA) → tournent toutes les 15 min :
    • LexGO : LE site belge d'emplois juridiques, via son API publique officielle (faite pour les agents)
    • Indeed Belgique via JobSpy (librairie open source MIT, optionnelle)
    • Pages à surveiller (flux RSS ou pages carrières de cabinets)
  Payant (IA + recherche web) → toutes les heures en journée, 2 requêtes en parallèle (rotation) :
    • Éclaireur web : barreaux, Jobat, StepStone, Legalworld, sites des cabinets…
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from .. import config, db, llm, outils

LEXGO = "https://www.lexgo.be/api/v1"

SCHEMA_OFFRES = {
    "type": "object",
    "properties": {"offres": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "url": {"type": "string"}, "titre": {"type": "string"}, "entreprise": {"type": ["string", "null"]},
            "ville": {"type": ["string", "null"]}, "matiere": {"type": ["string", "null"]},
            "contrat": {"type": ["string", "null"]}, "langue": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]}, "email_contact": {"type": ["string", "null"]},
            "mode_candidature": {"type": "string", "enum": ["email", "formulaire", "inconnu"]},
            "publie_le": {"type": ["string", "null"], "description": "AAAA-MM-JJ si visible"},
        },
        "required": ["url", "titre"],
    }}},
    "required": ["offres"],
}


# ---------- LexGO (API publique, gratuite) ----------
def _get_json(url, params=None, etag_cle=None):
    import requests

    entetes = {"Accept": "application/json", "User-Agent": "agent-avocat (usage personnel de recherche d'emploi)"}
    if etag_cle and db.kv_get(etag_cle):
        entetes["If-None-Match"] = db.kv_get(etag_cle)
    r = requests.get(url, params=params, headers=entetes, timeout=20)
    if r.status_code == 304:
        return None
    r.raise_for_status()
    if etag_cle and r.headers.get("ETag"):
        db.kv_set(etag_cle, r.headers["ETag"])
    return r.json()


def _fonctions_lexgo(dom) -> list[int]:
    """Associe tes postes visés (stagiaire, juriste…) aux catégories LexGO."""
    cache = db.kv_get("lexgo_fonctions")
    if cache is None:
        cache = (_get_json(f"{LEXGO}/functions") or {}).get("functions", [])
        db.kv_set("lexgo_fonctions", cache)
    voulus = [outils.sans_accents(p) for p in dom.get("postes_vises") or []]
    ids = []
    for f in cache:
        noms = " ".join(outils.sans_accents(f.get(k) or "") for k in ("fr_name", "nl_name", "en_name"))
        if any(mot in noms for v in voulus for mot in v.split() if len(mot) > 3):
            ids.append(f["id"])
    return ids or [None]


def _lexgo(dom: dict) -> list[dict]:
    connus = {r["url"] for r in db.q("SELECT url FROM offres WHERE source='lexgo'")}
    sortie, details = [], 0
    for fid in _fonctions_lexgo(dom):
        params = {"domain": "be", "limit": 50}
        if fid:
            params["function_id"] = fid
        page = _get_json(f"{LEXGO}/jobs", params, etag_cle=f"lexgo_etag_{fid}")
        for j in (page or {}).get("jobs", []):
            url = j.get("click_url") or j.get("url")
            if not url or url in connus or details >= 40:
                continue
            try:
                time.sleep(1.1)          # LexGO autorise 60 requêtes / minute
                d = _get_json(f"{LEXGO}/jobs/{j['id']}")
                details += 1
            except Exception:
                d = j
            t, desc = d.get("titles") or {}, d.get("descriptions") or d.get("summaries") or {}
            c = d.get("contract") or {}
            sortie.append({
                "url": url, "source": "lexgo",
                "titre": t.get("fr") or t.get("en") or t.get("nl"),
                "entreprise": (d.get("company") or {}).get("name"),
                "ville": (d.get("location") or {}).get("city"),
                "matiere": ", ".join(x.get("fr_name") or x.get("en_name") or "" for x in d.get("disciplines") or []) or None,
                "contrat": ", ".join(k for k in ("permanent", "temporary", "self_employed") if c.get(k)) or None,
                "langue": None,   # LexGO donne la langue de l'ANNONCE, pas la langue exigée
                "description": ((f"[Annonce rédigée en : {', '.join(d.get('languages') or [])}] "
                                 if d.get("languages") else "")
                                + (desc.get("fr") or desc.get("en") or desc.get("nl") or ""))[:5000],
                "publie_le": (d.get("published_at") or "")[:10] or None,
                "mode_candidature": "formulaire",
            })
    return sortie


# ---------- Indeed via JobSpy (optionnel) ----------
def _jobspy(dom: dict) -> list[dict]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return []
    sortie = []
    for mot in dom.get("mots_cles_recherche", [])[:4]:
        for ville in (dom.get("villes") or ["Belgique"])[:3]:
            df = scrape_jobs(site_name=["indeed"], search_term=mot, location=ville,
                             country_indeed="belgium", results_wanted=20, hours_old=24 * 7)
            for _, r in df.iterrows():
                sortie.append({"url": r.get("job_url"), "titre": r.get("title"), "entreprise": r.get("company"),
                               "ville": r.get("location"), "description": (r.get("description") or "")[:4000],
                               "email_contact": (outils.emails_dans(str(r.get("emails") or "")) or [None])[0],
                               "publie_le": str(r.get("date_posted") or "")[:10] or None, "source": "indeed"})
    return sortie


# ---------- Pages surveillées ----------
def _pages(dom: dict) -> list[dict]:
    sortie = []
    for url in dom.get("pages_a_surveiller") or []:
        try:
            page = outils.telecharger(url)
        except Exception as e:
            db.journal("eclaireur", f"page {url} : {e}")
            continue
        if "<rss" in page[:500] or "<feed" in page[:500]:
            atom = "{http://www.w3.org/2005/Atom}"
            for it in ET.fromstring(page.encode()).iter():
                if it.tag.split("}")[-1] not in ("item", "entry"):
                    continue
                lien = it.findtext("link") or (it.find(f"{atom}link").get("href") if it.find(f"{atom}link") is not None else None)
                titre = it.findtext("title") or it.findtext(f"{atom}title")
                if lien and titre:
                    sortie.append({"url": lien, "titre": titre, "source": "flux"})
        else:
            jp = outils.jobposting_jsonld(page)
            if jp:
                sortie.append({**jp, "url": url, "source": "page", "publie_le": (jp.get("date") or "")[:10] or None})
    return sortie


# ---------- Éclaireur web (IA) ----------
def _une_requete(requete: str, dom: dict, connues: list) -> list[dict]:
    contenu = json.dumps({"requete": requete, "villes": dom.get("villes"), "postes": dom.get("postes_vises"),
                          "matieres_uniquement": dom.get("matieres_uniquement"),
                          "matieres_exclues": dom.get("matieres_exclues"), "langues": dom.get("langues"),
                          "deja_connues": connues, "nombre_max": 10}, ensure_ascii=False)
    r = llm.demander("eclaireur", "rapide", llm.prompt("eclaireur_web"), contenu, SCHEMA_OFFRES,
                     web=True, recherches_max=3, max_tokens=4000, priorite="fond")
    offres = [{**o, "source": "web"} for o in r.get("offres", [])]
    bonnes = [o for o in offres if annonce_precise(o)]
    if len(bonnes) < len(offres):
        db.journal("eclaireur", f"web : {len(offres) - len(bonnes)} résultat(s) ignoré(s) (pas une annonce précise)")
    return bonnes


_FIN_DE_LISTE = {"jobs", "job", "emploi", "emplois", "vacatures", "offres", "offres-d-emploi", "carrieres",
                 "careers", "recrutement", ""}
_MORCEAUX_DE_LISTE = ("/search", "/recherche", "/functions/", "?q=", "&q=", "?keywords=", "?query=")


def annonce_precise(o: dict) -> bool:
    """Une vraie annonce : un employeur nommé et un lien vers L'annonce, pas vers une page de résultats."""
    from urllib.parse import urlparse
    url = (o.get("url") or "").strip().lower()
    if not o.get("entreprise") or not url.startswith("http") or any(m in url for m in _MORCEAUX_DE_LISTE):
        return False
    dernier = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return dernier not in _FIN_DE_LISTE


def recherche_web(n_requetes: int = 1) -> int:
    dom = config.domaine_actif()
    requetes = dom.get("mots_cles_recherche") or []
    if not requetes:
        return 0
    i = db.kv_get("rotation_requete", 0)
    choix = [requetes[(i + k) % len(requetes)] for k in range(min(n_requetes, len(requetes)))]
    db.kv_set("rotation_requete", i + len(choix))
    connues = [r["url"] for r in db.q("SELECT url FROM offres ORDER BY id DESC LIMIT 120")]
    with ThreadPoolExecutor(len(choix)) as ex:
        lots = list(ex.map(lambda q: _sur(lambda d: _une_requete(q, d, connues), dom, f"web « {q} »"), choix))
    return enregistrer([o for lot in lots for o in lot])


def veille_gratuite() -> int:
    dom = config.domaine_actif()
    with ThreadPoolExecutor(3) as ex:
        lots = list(ex.map(lambda f: _sur(f, dom, f.__name__.strip("_")), (_lexgo, _jobspy, _pages)))
    return enregistrer([o for lot in lots for o in lot])


def chercher() -> int:
    """Passage complet (utilisé par les tests et « cherche » sur Telegram)."""
    return veille_gratuite() + recherche_web()


def enregistrer(offres: list[dict]) -> int:
    nouvelles = 0
    with db.tx() as c:
        for o in offres:
            if not o.get("url") or not o.get("titre"):
                continue
            o["email_contact"] = (outils.emails_dans(o.get("email_contact") or "") or [None])[0]
            cle = outils.cle_offre(o["url"], o.get("entreprise"), o.get("titre"))
            cur = c.execute(
                """INSERT OR IGNORE INTO offres (cle, url, source, titre, entreprise, ville, matiere, contrat, langue,
                   description, email_contact, mode_candidature, publie_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cle, o["url"], o.get("source"), o["titre"], o.get("entreprise"), o.get("ville"), o.get("matiere"),
                 o.get("contrat"), o.get("langue"), o.get("description"), o.get("email_contact"),
                 o.get("mode_candidature"), o.get("publie_le")))
            nouvelles += cur.rowcount
    if nouvelles:
        db.journal("eclaireur", f"{nouvelles} nouvelle(s) offre(s)")
    return nouvelles


def _sur(f, dom, nom):
    try:
        return f(dom)
    except Exception as e:
        db.journal("eclaireur", f"{nom} indisponible : {type(e).__name__}: {e}")
        return []
