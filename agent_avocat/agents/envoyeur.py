"""Agent 10 — Envoyeur (sans IA) : envoie CV + lettre par email, comme un humain le ferait.

Garde-fous : heures de bureau uniquement, plafond journalier, espacement entre envois,
jamais deux fois le même employeur. Offres « formulaire » → lien + lettre prête envoyés sur ta messagerie.
En mode SIMULATION, les emails sont écrits dans donnees/sortie/ au lieu d'être envoyés."""
from __future__ import annotations

import random
import smtplib
import time
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

from .. import config, db, messagerie
from .redacteur import chemin_lettre

BXL = ZoneInfo("Europe/Brussels")


def heure_ouvrable(regles, maintenant=None) -> bool:
    m = maintenant or datetime.now(BXL)
    debut, fin = regles["heures_envoi"]
    return m.weekday() in regles["jours_envoi"] and debut <= m.hour < fin


def envoyes_aujourdhui() -> int:
    return db.q1("SELECT COUNT(*) AS n FROM offres WHERE date(envoye_le)=?", date.today().isoformat())["n"]


def construire(o) -> EmailMessage:
    m = EmailMessage()
    m["From"] = config.env("EMAIL_ADRESSE", "moi@exemple.be")
    m["To"] = o["email_contact"]
    m["Subject"] = o["objet_mail"]
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=(config.env("EMAIL_ADRESSE", "x@agent-avocat.local").split("@")[1]))
    m.set_content(o["corps_mail"])
    cv = config.chemin_cv()
    if cv.exists():
        m.add_attachment(cv.read_bytes(), maintype="application", subtype="pdf", filename=_nom("CV", "pdf"))
    lettre = chemin_lettre(o["id"])
    if lettre.exists():
        sub = "pdf" if lettre.suffix == ".pdf" else "plain"
        m.add_attachment(lettre.read_bytes(), maintype="application" if sub == "pdf" else "text", subtype=sub,
                         filename=_nom("Lettre_de_motivation", lettre.suffix[1:]))
    return m


def _nom(base, ext):
    nom = (config.env("NOM_CANDIDAT") or "").strip().replace(" ", "_")
    return f"{base}_{nom}.{ext}" if nom else f"{base}.{ext}"


def expedier(m: EmailMessage):
    if config.simulation():
        sortie = config.DONNEES / "sortie"
        sortie.mkdir(parents=True, exist_ok=True)
        (sortie / f"{datetime.now():%Y%m%d_%H%M%S_%f}.eml").write_bytes(bytes(m))
        return
    with connexion_smtp() as s:
        s.send_message(m)


def connexion_smtp():
    """SMTP chiffré : port 465 (SSL direct) ou 587 (STARTTLS), selon le fournisseur."""
    hote, port = config.env("SMTP_HOTE", "smtp.gmail.com"), config.env_int("SMTP_PORT", 465)
    if port == 465:
        s = smtplib.SMTP_SSL(hote, port, timeout=30)
    else:
        s = smtplib.SMTP(hote, port, timeout=30)
        s.starttls()
    s.login(config.env("EMAIL_ADRESSE"), config.env("EMAIL_MOT_DE_PASSE"))
    return s


def envoyer(max_par_cycle: int = 5, pause_secondes: tuple = (90, 300)):
    regles = config.regles_envoi()
    envoyees = 0
    for o in db.q("SELECT * FROM offres WHERE statut='validee' ORDER BY score DESC"):
        if not o["email_contact"]:
            db.changer_statut(o["id"], "manuelle", "envoyeur", "candidature par formulaire")
            messagerie.dire(f"✋ *{o['entreprise'] or o['titre']}* se postule via leur site. "
                            f"Ta lettre est prête, il te reste à la coller ici :\n{o['url']}\n"
                            f"Dis-moi « fait {o['id']} » quand c'est envoyé.")
            messagerie.fichier(chemin_lettre(o["id"]), f"Lettre – {o['entreprise'] or ''}")
            continue
        if not config.simulation():
            if not heure_ouvrable(regles):
                break
            if envoyes_aujourdhui() >= regles["max_par_jour"] or envoyees >= max_par_cycle:
                break
            if not config.chemin_cv().exists():
                db.journal("envoyeur", "CV manquant : envoi suspendu")
                break
        try:
            m = construire(o)
            expedier(m)
        except Exception as e:
            db.changer_statut(o["id"], "erreur", "envoyeur", f"envoi impossible : {e}")
            continue
        db.changer_statut(o["id"], "envoyee", "envoyeur", message_id=m["Message-ID"],
                          envoye_le=datetime.now().isoformat(" ", "seconds"))
        envoyees += 1
        if not config.simulation():
            time.sleep(random.randint(*pause_secondes))  # rythme humain, évite les filtres anti-spam
    return envoyees
