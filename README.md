# Agent Avocat ⚖️🤖

Une équipe d'agents IA qui **cherche les offres juridiques en Belgique, écrit une lettre sur mesure pour chacune,
postule, relance, trie les réponses** — et ne te dérange sur Telegram que quand il faut décider :
« Le cabinet X te propose un entretien jeudi 24 décembre à 16h30, tu confirmes ? »

Tu parles à l'agent comme à quelqu'un, **à l'écrit ou en vocal**. Les refus ? Tu n'en entends même pas parler.

## Comment ça se passe pour toi

1. Tu ouvres l'application, tu remplis : email, mot de passe d'application, clé API, jeton Telegram.
2. Sur Telegram, l'agent te demande ton CV (PDF) et ce que tu cherches (écrit ou vocal) :
   « que du droit immobilier, Bruxelles ou Namur, jamais de pénal, CDI ou stage ».
3. Il cherche en continu (LexGO, Indeed, Google Jobs, web, cabinets à contacter spontanément), écrit et fait noter chaque lettre,
   puis t'envoie des cartes : **[✅ Envoyer] [👁 Lettre] [❌ Non]**.
4. Il envoie, relance après 8 jours, lit les réponses. Les refus ? Tu n'en entends pas parler.
5. Entretien proposé → **[✅ Jeudi 16h30] [📆 Autre date]** → il répond au cabinet, t'envoie le rdv
   pour ton agenda, et la veille une fiche pour préparer l'entretien.

On démarre en **mode test** 🧪 : l'agent fait tout seul et envoie chaque candidature (lettre + CV en pièces
jointes) à **l'adresse email écrite dans ton CV**, jamais aux cabinets. Rien sur Telegram. Quand tout te plaît :
« mode validation », puis « vrai tout » pour envoyer pour de vrai celles que tu as reçues en test.

Sur Telegram, tu parles au **Manager** comme à quelqu'un : « cherche maintenant », « envoie ici la lettre 12 »,
« envoie-les sur mon autre mail », « note minimum 6 », « pause jusqu'au 15 janvier »… Il le fait, ou te dit
clairement pourquoi ce n'est pas possible.
Détails : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Si quelque chose ne marche pas, écris « **diagnostic** » : en 10 secondes, il vérifie la clé IA et le crédit, la boîte
mail (envoi et lecture), le CV, la pause et le budget, et te dit précisément ce qui bloque. « budget 5 » change le
plafond de dépense IA par jour. Crédit Claude épuisé ? Il te prévient une fois et reprend tout seul après la recharge.

## L'application (le plus simple)

Télécharge la dernière version dans l'onglet **Releases** de ce dépôt :
- **Windows** : `AgentAvocat-Windows.exe` → double-clic. Rien à extraire.
  Si Windows dit « a protégé votre ordinateur » : *Informations complémentaires* → *Exécuter quand même*.
- **Mac** : `AgentAvocat-Mac.dmg` → glisse *Agent Avocat* dans *Applications*. 1er lancement : clic droit → *Ouvrir*.

Au premier lancement, trois cases : **adresse email**, **mot de passe d'application**, **clé API Claude**,
puis le jeton de ton bot Telegram (2 min avec @BotFather). Un QR code s'affiche : tu le scannes, c'est relié.
Tu peux aussi discuter avec l'agent directement dans la fenêtre et y déposer ton CV.

**Publier une nouvelle version** : GitHub fabrique l'app tout seul (Windows + Mac). Crée un tag
`v0.3.0` (onglet *Releases* → *Draft a new release* → *Choose a tag*), attends ~10 min, les fichiers apparaissent.

## Installation développeur (Windows)

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
- **Rien dans le corps des emails** : CV et lettre partent toujours en **PDF joints** ; l'email reste court.
- **Pas de mémoire (pour l'instant)** : il n'apprend pas tes préférences de style d'une lettre à l'autre.
- **Pas de spam** : max 15 envois/jour, jamais deux fois le même cabinet en 60 jours, réglable dans `config/objectif.yaml`.

## Pour aller plus loin

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — les agents, les sources d'inspiration, les choix d'économie de tokens
- `python -m unittest discover tests -v` — test complet du circuit en simulation
