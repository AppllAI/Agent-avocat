"""Point d'accès unique vers la personne (le canal actif : WhatsApp, Telegram ou console)."""
from __future__ import annotations

from pathlib import Path

from . import db

_canal = None


def brancher(canal):
    global _canal
    _canal = canal


def dire(texte: str):
    db.dire("agent", texte)
    if _canal:
        _canal.envoyer(texte)
    else:
        print(f"\n💬 {texte}\n", flush=True)


def fichier(chemin: Path, legende: str = ""):
    if _canal:
        _canal.envoyer_fichier(Path(chemin), legende)
    else:
        print(f"📎 {chemin} {legende}", flush=True)
