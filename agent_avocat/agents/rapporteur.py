"""Agent 14 — Rapporteur (sans IA) : stats à la demande et petit bilan quotidien."""
from __future__ import annotations

from datetime import date

from .. import db, llm, messagerie


def stats() -> str:
    s = {r["statut"]: r["n"] for r in db.q("SELECT statut, COUNT(*) AS n FROM offres GROUP BY statut")}
    envoyees = sum(s.get(k, 0) for k in ("envoyee", "relancee", "refus", "entretien", "sans_reponse", "offre_recue"))
    rdv = db.q1("SELECT COUNT(*) AS n FROM rdv WHERE statut='confirme'")["n"]
    total = db.q1("SELECT COALESCE(SUM(eur),0) AS e FROM couts")["e"]
    return (f"📊 *Bilan*\n"
            f"Envoyées : {envoyees} · en attente de ton ok : {s.get('a_valider', 0)} · à faire via site : {s.get('manuelle', 0)}\n"
            f"Entretiens : {s.get('entretien', 0)} (rdv confirmés : {rdv}) · refus : {s.get('refus', 0)} · "
            f"sans réponse : {s.get('sans_reponse', 0)}\n"
            f"Offres écartées par tes règles : {s.get('ecartee', 0)}\n"
            f"Coût IA : {llm.depense_du_jour():.2f} € aujourd'hui · {total:.2f} € au total")


def bilan_du_jour():
    if db.kv_get("dernier_bilan") == date.today().isoformat():
        return
    db.kv_set("dernier_bilan", date.today().isoformat())
    n = db.q1("SELECT COUNT(*) AS n FROM offres WHERE date(envoye_le)=?", date.today().isoformat())["n"]
    if n:
        messagerie.dire(f"🌙 Aujourd'hui : {n} candidature(s) envoyée(s).\n" + stats())
