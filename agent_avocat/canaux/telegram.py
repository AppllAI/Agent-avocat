"""Canal Telegram — API OFFICIELLE et gratuite : aucun risque de blocage, vocaux et fichiers natifs.
Mise en place : parle à @BotFather → /newbot → colle le jeton dans TELEGRAM_JETON.
Sécurité : seul le 1er compte qui envoie le code d'appairage affiché au démarrage est écouté."""
from __future__ import annotations

import random
import time
from pathlib import Path

import requests

from .. import config, db


class Telegram:
    nom = "telegram"

    def __init__(self):
        self.jeton = config.env("TELEGRAM_JETON")
        if not self.jeton:
            raise SystemExit("TELEGRAM_JETON manquant dans .env")
        self.api = f"https://api.telegram.org/bot{self.jeton}"
        self.chat = db.kv_get("telegram_chat")

    def _post(self, methode, **kw):
        r = requests.post(f"{self.api}/{methode}", timeout=60, **kw)
        r.raise_for_status()
        return r.json()["result"]

    def envoyer(self, texte):
        if not self.chat:
            print(f"(pas encore appairé) {texte}")
            return
        for i in range(0, len(texte), 4000):
            try:
                self._post("sendMessage", data={"chat_id": self.chat, "text": texte[i:i + 4000], "parse_mode": "Markdown"})
            except requests.HTTPError:  # Markdown invalide → texte brut
                self._post("sendMessage", data={"chat_id": self.chat, "text": texte[i:i + 4000]})

    def envoyer_fichier(self, chemin: Path, legende=""):
        if self.chat and Path(chemin).exists():
            with open(chemin, "rb") as f:
                self._post("sendDocument", data={"chat_id": self.chat, "caption": legende}, files={"document": f})

    def _telecharger(self, file_id, nom):
        info = self._post("getFile", data={"file_id": file_id})
        dossier = config.DONNEES / "recus"
        dossier.mkdir(parents=True, exist_ok=True)
        dest = dossier / f"{int(time.time())}_{nom}"
        dest.write_bytes(requests.get(f"https://api.telegram.org/file/bot{self.jeton}/{info['file_path']}", timeout=120).content)
        return dest

    def ecouter(self, callback):
        from ..agents.concierge import Entrant

        code = db.kv_get("telegram_code") or str(random.randint(100000, 999999))
        db.kv_set("telegram_code", code)
        if not self.chat:
            print(f"\n👉 Ouvre ton bot Telegram et envoie-lui ce code : {code}\n", flush=True)
        decalage = None
        while True:
            try:
                maj = self._post("getUpdates", data={"timeout": 50, "offset": decalage})
            except Exception as e:
                print("Telegram :", e)
                time.sleep(10)
                continue
            for u in maj:
                decalage = u["update_id"] + 1
                m = u.get("message") or {}
                chat = m.get("chat", {}).get("id")
                if not self.chat:
                    if (m.get("text") or "").strip() == code:
                        self.chat = chat
                        db.kv_set("telegram_chat", chat)
                        db.kv_set("bienvenue_envoyee", False)
                        from ..agents import coach
                        coach.bienvenue()
                    continue
                if chat != self.chat:
                    continue
                if "voice" in m or "audio" in m:
                    a = m.get("voice") or m.get("audio")
                    callback(Entrant(audio=self._telecharger(a["file_id"], "vocal.ogg")))
                elif "document" in m:
                    d = m["document"]
                    callback(Entrant(fichier=self._telecharger(d["file_id"], d.get("file_name", "doc")),
                                     nom_fichier=d.get("file_name", ""), texte=m.get("caption", "")))
                elif m.get("text"):
                    callback(Entrant(texte=m["text"]))
