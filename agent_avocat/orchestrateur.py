"""Le chef d'orchestre : du code simple, pas une IA (c'est gratuit et ça ne se trompe pas de chemin).

  Toutes les 3 h  : Éclaireurs → Extracteur → Garde → Évaluateur → Enquêteur → Rédacteur+Vérificateur
                    → proposition du lot sur ta messagerie → Envoyeur
  Toutes les 10 min : Trieur (boîte mail) → Secrétaire si entretien
  Chaque jour       : Relanceur, bilan du soir
  En permanence     : Concierge, qui écoute tes messages (traités dans l'ordre, un à la fois)
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime

from . import config, db, messagerie
from .agents import (coach, concierge, enqueteur, envoyeur, evaluateur, extracteur, garde, rapporteur,
                     redacteur, relance, sources, trieur)

_pipeline = threading.Lock()
_envoi = threading.Lock()
_boite = threading.Lock()


def _proteger(nom, f, *a):
    try:
        return f(*a)
    except Exception as e:  # un agent qui plante ne fait jamais tomber les autres
        db.journal("orchestre", f"{nom} a échoué : {type(e).__name__}: {e}")


def pret() -> bool:
    return coach.onboarding_fini() or (config.OBJECTIF.exists() and bool(config.profil_texte().strip()))


def pipeline():
    if db.kv_get("pause", False) or not pret():
        return
    if not _pipeline.acquire(blocking=False):
        return
    try:
        for nom, etape in (("éclaireurs", sources.chercher), ("extracteur", extracteur.enrichir),
                           ("garde", garde.filtrer), ("évaluateur", evaluateur.evaluer),
                           ("enquêteur", enqueteur.enqueter), ("rédacteur", redacteur.rediger),
                           ("proposition", redacteur.proposer_lot)):
            _proteger(nom, etape)
        _envoyer()
    finally:
        _pipeline.release()


def _envoyer():
    if db.kv_get("pause", False):
        return
    with _envoi:
        _proteger("envoyeur", envoyeur.envoyer)


def boite():
    if not _boite.acquire(blocking=False):
        return
    try:
        _proteger("trieur", trieur.relever)
    finally:
        _boite.release()


def quotidien():
    if db.kv_get("pause", False):
        return
    _proteger("relance", relance.relancer)
    if datetime.now().hour >= 19:
        _proteger("bilan", rapporteur.bilan_du_jour)


def declencher():
    threading.Thread(target=pipeline, daemon=True).start()


def envoyer_bientot():
    threading.Thread(target=_envoyer, daemon=True).start()


def _boucle(f, minutes):
    while True:
        f()
        time.sleep(minutes * 60)


def un_cycle():
    """Pour tester : un passage complet, sans attendre."""
    pipeline()
    boite()
    quotidien()


def demarrer(canal):
    db.connexion()
    coach.appliquer_identite()
    messagerie.brancher(canal)
    file: queue.Queue = queue.Queue()

    def ouvrier():
        while True:
            m = file.get()
            _proteger("concierge", concierge.recevoir, m)
            file.task_done()

    threading.Thread(target=ouvrier, daemon=True).start()
    for f, minutes in ((pipeline, config.env_int("INTERVALLE_RECHERCHE_MIN", 180)),
                       (boite, config.env_int("INTERVALLE_BOITE_MIN", 10)),
                       (quotidien, 60)):
        threading.Thread(target=_boucle, args=(f, minutes), daemon=True).start()

    if not db.kv_get("bienvenue_envoyee"):
        db.kv_set("bienvenue_envoyee", True)
        coach.bienvenue()
    db.journal("orchestre", f"démarré · canal {canal.nom} · {'SIMULATION' if config.simulation() else 'réel'}")
    canal.ecouter(file.put)   # bloquant
    file.join()               # fin de session : on finit de traiter les messages reçus
