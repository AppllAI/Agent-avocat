# Architecture — pourquoi c'est construit comme ça

## Ce qu'on a retenu des meilleurs projets publics

| Source | Ce qu'on reprend | Ce qu'on évite |
|---|---|---|
| **Anthropic — *Building effective agents* / *Multi-agent research system* / *When to use multi-agent*** | Préférer des **workflows** simples (code) aux agents autonomes ; motifs *routing*, *prompt chaining*, *evaluator-optimizer* ; découper **par contexte**, pas par métier ; un vérificateur au regard neuf ; consignes claires par agent (objectif, format de sortie, limites). | Le multi-agent coûte 3 à 15× plus de tokens : on ne lance pas 15 IA qui discutent entre elles. |
| **AIHawk** (~30 k ⭐, AGPL) — l'agent de candidature le plus populaire | Profil candidat comme seule source de vérité ; filtres explicites ; lettre par offre. | Le remplissage automatique de LinkedIn (interdit par leurs CGU, comptes bannis). Aucun code AGPL copié. |
| **ApplyPilot** (AGPL) | Pipeline en étapes avec statut en base ; **enrichissement en cascade** (JSON-LD → regex → IA) ; score par bandes ; modèle rapide pour noter / modèle qualité pour écrire ; anti-fabrication avec relecture ; jamais deux fois le même employeur ; tri Gmail refus/entretien. | Idées seulement, pas de code (licence AGPL). |
| **JobSpy** (~4,5 k ⭐, MIT) | Utilisé tel quel comme dépendance optionnelle pour Indeed Belgique, sans IA. | — |
| **NanoClaw** | Agent personnel piloté par WhatsApp, vocaux transcrits par Whisper et passés à l'agent sous forme de texte. | — |
| **Baileys** | Librairie WhatsApp open source la plus utilisée, sans navigateur (plus légère que whatsapp-web.js). | — |

## Le schéma

```
                    ┌──────────── Concierge (routeur) ◄── toi : texte · vocal (Transcripteur) · PDF (Profileur)
                    │                  │
                    │       Coach ◄────┘ (définit l'objectif = règles strictes)
                    ▼
 Éclaireurs ─► Extracteur ─► Garde ─► Évaluateur ─► Enquêteur ─► Rédacteur ⇄ Vérificateur ─► [ton ok] ─► Envoyeur
 (Indeed, web, (JSON-LD,     (règles  (note /10,    (faits sur    (lettre +     (anti-invention,              (heures de
  pages suivies) regex, IA)  sans IA) par lots)     l'employeur)   email)        2 corrections max)            bureau, plafond)
                                                                                                                  │
 Relanceur (J+8, sans IA) ◄─────────────────────────────────────────────────────────────────────────────────────┘
 Trieur (boîte mail) ─► refus : silence · question : toi · entretien ─► Secrétaire ─► toi ─► email + .ics
 Rapporteur : stats, bilan du soir, coût IA
```

Les agents **ne discutent pas entre eux** : ils se passent le relais via le **statut** de chaque offre
(`db.py`, transitions vérifiées). Chaque agent reçoit uniquement ce dont il a besoin → contexte court,
coût bas, et un agent qui plante ne bloque pas les autres (il reprend au cycle suivant).

## Les 18 agents et leur coût

| # | Agent | IA | Rôle |
|---|---|---|---|
| 1-3 | Éclaireurs (Indeed, pages suivies, web) | web = rapide, le reste gratuit | trouvent les offres, en parallèle, dédoublonnées |
| 4 | Extracteur | gratuit sauf champs manquants | complète l'offre |
| 5 | Garde | **gratuit** | tes règles strictes (synonymes : « correctionnel » = pénal) |
| 6 | Évaluateur | rapide, 8 offres / appel | note /10 |
| 7 | Enquêteur | rapide + 2 recherches, offres ≥ 8 seulement | personnalisation |
| 8 | Rédacteur | **qualité** | lettre + email |
| 9 | Vérificateur | rapide | relit, bloque les inventions |
| 10 | Envoyeur | **gratuit** | SMTP, rythme humain |
| 11 | Trieur | rapide, seulement si email lié à une candidature | classe les réponses |
| 12 | Secrétaire | rapide | rendez-vous, réponses, .ics |
| 13 | Relanceur | **gratuit** | une relance polie |
| 14 | Rapporteur | **gratuit** | stats, coûts |
| 15 | Coach | rapide | interview de départ, modifications d'objectif |
| 16 | Profileur | qualité, une fois | CV → fiche profil |
| 17 | Transcripteur | Whisper local gratuit ou API | vocaux |
| 18 | Concierge | gratuit pour les commandes simples, sinon rapide | comprend tes messages |

**Leviers d'économie** : modèle rapide partout sauf l'écriture · sortie forcée par outil (pas de JSON cassé,
pas de bavardage) · prompt système en cache · évaluation par lots · filtres sans IA en premier ·
recherche web en rotation (1 requête / cycle) · budget journalier en € (`BUDGET_JOUR_EUR`).
Ordre de grandeur : quelques centimes par candidature envoyée.

## Ajouter un domaine (ex. finance au Luxembourg)

Un nouveau bloc dans `config/objectif.yaml` → `domaine_actif`. Les prompts sont dans `agent_avocat/prompts/` :
le seul qui parle de droit belge est `eclaireur_web.md` (sites à cibler) et `redacteur.md` (conventions de lettre).

## Tester

`python -m unittest discover tests -v` fait tourner tout le circuit en simulation : recherche → tri → lettres →
validation → envoi → réponse « entretien » → confirmation du rendez-vous → relance → refus silencieux.
