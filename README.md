# Agent Avocat ⚖️🤖

Une équipe d'agents IA qui **cherche les offres juridiques en Belgique, écrit une lettre sur mesure pour chacune,
postule, relance, trie les réponses** — et ne te dérange sur WhatsApp que quand il faut décider :
« Le cabinet X te propose un entretien jeudi 24 décembre à 16h30, tu confirmes ? »

Tu parles à l'agent comme à quelqu'un, **à l'écrit ou en vocal**. Les refus ? Tu n'en entends même pas parler.

## Comment ça se passe pour toi

1. Tu lances l'agent (double-clic sur `demarrer.bat`).
2. Sur WhatsApp, il te demande ton CV (PDF) et ce que tu cherches. Plus tu es précis, plus il est strict :
   « que du droit immobilier, Bruxelles ou Namur, jamais de pénal, CDI ou stage ».
3. Il cherche toutes les 3 heures, écrit les lettres, et te propose les meilleures :
   *« 3 candidatures prêtes… réponds ok »*. Tu réponds **ok**, **ok sauf 2** ou **montre 2**.
4. Il envoie (heures de bureau, rythme humain), relance après 8 jours, lit les réponses.
5. Entretien proposé → il te demande → tu dis **oui** → il répond au cabinet et t'envoie le rdv pour ton agenda.

Commandes utiles : `stats` · `pause` · `reprendre` · `aide` — ou n'importe quelle phrase normale.

## Installation (Windows)

1. Installe [Python 3.11+](https://www.python.org/downloads/) (coche *Add to PATH*) et [Node.js 20+](https://nodejs.org).
2. Télécharge ce dossier, double-clique **`demarrer.bat`**. Au 1er lancement il installe tout et ouvre `.env` :
   - `ANTHROPIC_API_KEY` : ta clé sur [console.anthropic.com](https://console.anthropic.com)
   - `EMAIL_ADRESSE` / `EMAIL_MOT_DE_PASSE` : une adresse **dédiée** aux candidatures
     (Gmail : active la validation en 2 étapes puis crée un *mot de passe d'application*)
3. Relance `demarrer.bat`, scanne le QR code avec WhatsApp (*Appareils connectés*). C'est tout.

Sans clé API, tout tourne en **simulation** : rien n'est envoyé, parfait pour tester.
Tester dans le terminal sans WhatsApp : `python -m agent_avocat --canal console`.

## WhatsApp ou Telegram ?

| | WhatsApp (Baileys) | Telegram |
|---|---|---|
| Habitude | ✅ tout le monde l'a | moins courant |
| Officiel / sans risque | ⚠️ non officiel : usage perso modéré OK, risque de blocage existe | ✅ API officielle et gratuite |
| Vocaux, PDF | ✅ | ✅ |
| Pour le distribuer à d'autres | il faudra l'API WhatsApp Business (payante, numéro dédié) | ✅ un bot suffit |

Conseil : un **2e numéro** (carte prépayée) pour le pont WhatsApp, ton numéro perso dans `WHATSAPP_MON_NUMERO` :
l'agent t'écrit comme un vrai contact et ton compte principal n'est jamais exposé.

## Ce qu'il ne fait pas (exprès)

- **Pas de remplissage automatique de LinkedIn / Jobat / StepStone** : interdit par leurs conditions, comptes bannis.
  Pour ces offres il te donne le lien + la lettre prête, tu colles, tu réponds « fait 12 ».
- **Il n'invente rien** : toute lettre est relue par un 2e agent qui bloque ce qui n'est pas dans ton profil.
- **Pas de spam** : max 15 envois/jour, jamais deux fois le même cabinet en 60 jours, réglable dans `config/objectif.yaml`.

## Pour aller plus loin

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — les 18 agents, les sources d'inspiration, les choix d'économie de tokens
- `python -m unittest discover tests -v` — test complet du circuit en simulation
