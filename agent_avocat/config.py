"""Réglages : .env (secrets) + config/objectif.yaml (ce que tu cherches)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

RACINE = Path(os.getenv("AGENT_AVOCAT_RACINE", Path(__file__).resolve().parent.parent))
DONNEES = RACINE / "donnees"
PROFIL_DIR = RACINE / "profil"
OBJECTIF = RACINE / "config" / "objectif.yaml"
OBJECTIF_EXEMPLE = RACINE / "config" / "objectif.exemple.yaml"
PROMPTS = Path(__file__).resolve().parent / "prompts"


def _charger_env():
    f = RACINE / ".env"
    if not f.exists():
        return
    for ligne in f.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            k, v = ligne.split("=", 1)
            v = v.split(" #")[0].split("\t#")[0]   # commentaire en fin de ligne
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_charger_env()


def env(cle: str, defaut: str | None = None) -> str | None:
    v = os.getenv(cle)
    return v if v not in (None, "") else defaut


def env_int(cle: str, defaut: int) -> int:
    return int(env(cle, str(defaut)))


def simulation() -> bool:
    """Mode simulation : aucune IA payante, aucun email réel. Parfait pour tester."""
    return env("SIMULATION", "0") == "1" or not env("ANTHROPIC_API_KEY")


# ---------- Objectif ----------
def objectif() -> dict:
    src = OBJECTIF if OBJECTIF.exists() else OBJECTIF_EXEMPLE
    with open(src, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def domaine_actif() -> dict:
    o = objectif()
    return o.get("domaines", {}).get(o.get("domaine_actif"), {})


def sauver_objectif(o: dict) -> None:
    OBJECTIF.parent.mkdir(parents=True, exist_ok=True)
    with open(OBJECTIF, "w", encoding="utf-8") as f:
        yaml.safe_dump(o, f, allow_unicode=True, sort_keys=False)


def regles_envoi() -> dict:
    defaut = {"mode": "validation", "max_par_jour": 15, "score_minimum": 7,
              "heures_envoi": [8, 19], "jours_envoi": [0, 1, 2, 3, 4],
              "relance_apres_jours": 8, "delai_meme_cabinet_jours": 60}
    defaut.update(objectif().get("envoi") or {})
    return defaut


# ---------- Profil ----------
def profil_texte() -> str:
    f = PROFIL_DIR / "profil.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def chemin_cv() -> Path:
    return PROFIL_DIR / "cv.pdf"
