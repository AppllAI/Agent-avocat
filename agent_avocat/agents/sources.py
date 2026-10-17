"""Agents 1-3 — Éclaireurs : trouvent les offres, en parallèle.

  • Indeed Belgique via JobSpy (gratuit, sans IA, librairie open source MIT)
  • Pages à surveiller (flux RSS ou pages carrières de cabinets) — sans IA
  • Éclaireur web (IA + recherche web) pour tout le reste : barreaux, Legalworld, Jobat, StepStone,
    sites des cabinets… Il tourne sur UNE requête par cycle (rotation) pour limiter les coûts.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from .. import config, db, llm, outils

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
        },
        "required": ["url", "titre"],
    }}},
    "required": ["offres"],
}


def _jobspy(dom: dict) -> list[dict]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return []
    sortie = []
    for mot in dom.get("mots_cles_recherche", [])[:4]:
        for ville in (dom.get("villes") or ["Belgique"])[:3]:
            try:
                df = scrape_jobs(site_name=["indeed"], search_term=mot, location=ville,
                                 country_indeed="belgium", results_wanted=15, hours_old=24 * 14)
            except Exception as e:
                db.journal("eclaireur", f"Indeed indisponible : {e}")
                return sortie
            for _, r in df.iterrows():
                sortie.append({"url": r.get("job_url"), "titre": r.get("title"), "entreprise": r.get("company"),
                               "ville": r.get("location"), "description": (r.get("description") or "")[:4000],
                               "email_contact": (outils.emails_dans(str(r.get("emails") or "")) or [None])[0],
                               "source": "indeed"})
    return sortie


def _pages(dom: dict) -> list[dict]:
    sortie = []
    for url in dom.get("pages_a_surveiller") or []:
        try:
            page = outils.telecharger(url)
        except Exception as e:
            db.journal("eclaireur", f"page {url} : {e}")
            continue
        if "<rss" in page[:500] or "<feed" in page[:500]:
            racine = ET.fromstring(page.encode())
            for it in racine.iter():
                if it.tag.split("}")[-1] in ("item", "entry"):
                    lien = it.findtext("link") or (it.find("{http://www.w3.org/2005/Atom}link").get("href")
                                                   if it.find("{http://www.w3.org/2005/Atom}link") is not None else None)
                    titre = it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title")
                    if lien and titre:
                        sortie.append({"url": lien, "titre": titre, "source": "flux"})
        else:
            jp = outils.jobposting_jsonld(page)
            if jp:
                sortie.append({**jp, "url": url, "source": "page"})
    return sortie


def _web(dom: dict) -> list[dict]:
    requetes = dom.get("mots_cles_recherche") or []
    if not requetes:
        return []
    i = db.kv_get("rotation_requete", 0) % len(requetes)
    db.kv_set("rotation_requete", i + 1)
    connues = [r["url"] for r in db.q("SELECT url FROM offres ORDER BY id DESC LIMIT 80")]
    contenu = json.dumps({"requete": requetes[i], "villes": dom.get("villes"), "postes": dom.get("postes_vises"),
                          "matieres_uniquement": dom.get("matieres_uniquement"),
                          "matieres_exclues": dom.get("matieres_exclues"),
                          "deja_connues": connues, "nombre_max": 10}, ensure_ascii=False)
    r = llm.demander("eclaireur", "rapide", llm.prompt("eclaireur_web"), contenu, SCHEMA_OFFRES,
                     web=True, recherches_max=5, max_tokens=4000)
    return [{**o, "source": "web"} for o in r.get("offres", [])]


def chercher() -> int:
    dom = config.domaine_actif()
    with ThreadPoolExecutor(3) as ex:
        lots = list(ex.map(lambda f: _sur(f, dom), (_jobspy, _pages, _web)))
    nouvelles = 0
    with db.tx() as c:
        for o in (x for lot in lots for x in lot):
            if not o.get("url") or not o.get("titre"):
                continue
            cle = outils.cle_offre(o["url"], o.get("entreprise"), o.get("titre"))
            cur = c.execute(
                """INSERT OR IGNORE INTO offres (cle, url, source, titre, entreprise, ville, matiere, contrat, langue,
                   description, email_contact, mode_candidature) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cle, o["url"], o.get("source"), o["titre"], o.get("entreprise"), o.get("ville"), o.get("matiere"),
                 o.get("contrat"), o.get("langue"), o.get("description"), o.get("email_contact"),
                 o.get("mode_candidature")))
            nouvelles += cur.rowcount
    db.journal("eclaireur", f"{nouvelles} nouvelle(s) offre(s)")
    return nouvelles


def _sur(f, dom):
    try:
        return f(dom)
    except Exception as e:
        db.journal("eclaireur", f"{f.__name__} en échec : {e}")
        return []
