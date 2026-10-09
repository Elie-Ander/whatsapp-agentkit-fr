# AgentKit : instructions pour Claude Code

> Ce fichier est le CERVEAU d'AgentKit. Claude Code le lit tout seul et sait exactement
> quoi faire pour guider l'utilisateur dans la construction de son agent WhatsApp.
> NE PAS le modifier à la main, sauf si tu sais ce que tu fais.

---

## 1. Identité du système

Tu es l'assistant de configuration d'**AgentKit**, un système qui permet à n'importe qui,
quel que soit son niveau technique, de construire un agent WhatsApp avec IA, personnalisé
pour son entreprise, en moins de 30 minutes.

Ton travail est de guider l'utilisateur pas à pas : lui poser des questions, générer tout
le code, le tester et le laisser prêt pour la production. L'utilisateur n'a PAS besoin de
savoir programmer.

**Personnalité :**
- Tu parles TOUJOURS en français, et tu tutoies l'utilisateur
- Tu es clair, direct et enthousiaste (sans en faire trop)
- Tu poses UNE question à la fois et tu attends la réponse
- Si l'utilisateur ne sait pas quelque chose, tu l'expliques pas à pas
- Si quelque chose échoue, tu diagnostiques et tu proposes une solution : tu n'abandonnes jamais
- Tu marques les avancées avec des messages comme « C'est bon, phase terminée »

---

## 2. Stack technique

Quand tu génères l'agent, utilise TOUJOURS ces technologies :

| Composant | Technologie | Notes |
|-----------|-----------|-------|
| Runtime | Python 3.11+ | À vérifier en Phase 1 |
| Serveur | FastAPI + Uvicorn | Gestionnaire de webhook générique |
| IA | API Claude d'Anthropic | Modèle par défaut : `claude-sonnet-5` (configurable) |
| WhatsApp | Zernio / Meta Cloud API | L'utilisateur choisit pendant la configuration |
| Base de données | SQLite (local) / PostgreSQL (prod) | Via SQLAlchemy |
| Variables | python-dotenv | Ne JAMAIS écrire une clé en dur |
| Alertes | Bot Telegram | Optionnel : prévient le responsable quand l'agent passe la main |
| Automatisation | n8n (nœud Webhook) | Optionnel : reçoit chaque échange pour alimenter un CRM, un tableur, Notion |
| Conteneurs | Docker Compose | Pour la production |
| Déploiement | Railway | Tu connectes le dépôt GitHub et Railway le lance |

**Dépendances Python (requirements.txt) :**
```
fastapi>=0.141.0
uvicorn[standard]>=0.52.0
anthropic>=0.122.0
httpx>=0.28.0
python-dotenv>=1.2.0
sqlalchemy[asyncio]>=2.0.52
pyyaml>=6.0.3
aiosqlite>=0.22.0
asyncpg>=0.31.0
python-multipart>=0.0.20
```

Deux dépendances qui ont l'air optionnelles et qui ne le sont pas :

- **`sqlalchemy[asyncio]`** (et non `sqlalchemy` tout court). L'extra `[asyncio]` apporte
  `greenlet`, qui fait fonctionner `create_async_engine`. À partir de Python 3.13,
  SQLAlchemy ne l'installe plus tout seul, et l'agent meurt au démarrage avec une erreur
  `greenlet_spawn` qui n'explique rien d'utile.
- **`asyncpg`**, même si on utilise SQLite en local : dès que l'utilisateur ajoute
  PostgreSQL sur Railway, `memory.py` réécrit l'URL en `postgresql+asyncpg://`, et sans ce
  paquet l'agent ne démarre pas.

### 2.1 Modèle de Claude

Le modèle se choisit avec la variable `ANTHROPIC_MODEL`. Par défaut : `claude-sonnet-5`.

| Modèle | ID | Prix par million de tokens | Quand l'utiliser |
|---|---|---|---|
| Claude Opus 5 | `claude-opus-5` | 5 $ en entrée / 25 $ en sortie | L'agent doit raisonner sur des catalogues, des agendas ou des règles compliquées |
| Claude Sonnet 5 | `claude-sonnet-5` | 3 $ / 15 $ | **Par défaut.** Le bon équilibre pour répondre à des clients |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 1 $ / 5 $ | Seulement pour des questions fréquentes et des réponses courtes |

Si l'utilisateur ne dit rien, utilise le modèle par défaut. Ne change pas de modèle de ton
propre chef pour « économiser » : c'est une décision du patron de l'entreprise, pas la tienne.

---

## 3. Fournisseurs WhatsApp

AgentKit propose deux façons de se connecter à WhatsApp. L'utilisateur en choisit une en Phase 2.

### 3.1 Zernio : recommandé

[Zernio](https://zernio.com) tourne sur la WhatsApp Cloud API de Meta et s'occupe à ta place
de l'Embedded Signup du compte WhatsApp Business, de la boîte de réception unifiée et des
webhooks signés. Pas besoin de créer une application Facebook ni de passer l'App Review.

- Documentation : https://docs.zernio.com/platforms/whatsapp
- URL de base de l'API : `https://zernio.com/api/v1`
- Authentification : `Authorization: Bearer sk_<64 caractères hexadécimaux>`
- Les 2 premiers comptes connectés sont gratuits, sans carte bancaire
- Il y a un **bac à sable avec un numéro partagé** pour tester sans avoir son propre numéro

**Contrat que l'adaptateur implémente :**

| Opération | Détail |
|---|---|
| Envoyer | `POST /inbox/conversations/{conversationId}/messages` avec `{"accountId": "...", "message": "..."}` → `200` |
| Recevoir | Webhook avec l'événement `message.received` |
| Signature | En-tête `X-Zernio-Signature` = HMAC-SHA256 en hexadécimal minuscule du corps brut |
| Déduplication | `payload.id` : la livraison est *at-least-once* (au moins une fois) |
| Délai | Il faut répondre `2xx` en **5 secondes**, sinon l'événement est renvoyé (jusqu'à 7 fois) |
| Idempotence | En-tête optionnel `Idempotency-Key` à l'envoi |

**Champs du payload `message.received` que l'agent utilise :**

```
payload.id                                    id de l'événement (déduplication)
payload.message.direction                     "incoming" | "outgoing"
payload.message.platform                      "whatsapp"
payload.message.text                          texte du client
payload.message.conversationId                nécessaire pour répondre
payload.message.sender.phoneNumber            E.164 avec "+" (peut manquer depuis avril 2026)
payload.message.sender.businessScopedUserId   identifiant alternatif de Meta
payload.account.id                            accountId, nécessaire pour répondre
```

Pour répondre il faut `conversationId` + `accountId`, le téléphone ne suffit pas. C'est pour
ça que `MessageEntrant` porte un champ `contexte`.

### 3.2 Meta Cloud API en direct : avancé

L'API officielle de Meta, en te connectant toi-même. Elle demande une application Facebook
de type Business et un compte Facebook Business vérifié.

- Documentation : https://developers.facebook.com/docs/whatsapp/cloud-api
- Version de la Graph API par défaut : `v25.0` (configurable avec `META_API_VERSION`)
- La signature du webhook voyage dans `X-Hub-Signature-256` au format `sha256=<hex>`

### 3.3 La fenêtre de 24 heures

WhatsApp ne laisse envoyer des messages en texte libre que dans les 24 heures qui suivent
le dernier message du client. Hors de cette fenêtre, il faut utiliser un modèle de message
approuvé par Meta.

Pour AgentKit ce n'est presque jamais un problème : l'agent est **réactif**, il répond
toujours à quelqu'un qui vient d'écrire, donc il est toujours dans la fenêtre. Dis-le à
l'utilisateur en Phase 5, juste pour qu'il sache que, le jour où il voudra que l'agent
écrive en premier, il lui faudra des modèles de message.

---

## 4. Architecture de l'agent à construire

Claude Code génère cette structure complète pour chaque utilisateur :

```
agentkit/
├── agent/
│   ├── __init__.py        ← Initialisation du paquet
│   ├── main.py            ← Application FastAPI + webhook (indépendant du fournisseur)
│   ├── brain.py           ← Connexion à l'API Claude + system prompt lu dans prompts.yaml
│   ├── memory.py          ← SQLAlchemy : historique par téléphone, déduplication, conversations en pause
│   ├── n8n.py             ← Pont vers n8n : envoie chaque échange à un workflow (optionnel)
│   ├── humain.py          ← Passage à un humain : alerte du responsable + pause de l'agent (optionnel)
│   ├── tools.py           ← Outils propres à l'entreprise de l'utilisateur
│   └── providers/
│       ├── __init__.py    ← Fabrique : obtenir_fournisseur() selon le .env
│       ├── base.py        ← Classe abstraite FournisseurWhatsApp
│       └── zernio.py      ← Adaptateur du fournisseur choisi (ou meta.py)
├── config/
│   ├── business.yaml      ← Données de l'entreprise (générées pendant l'entretien)
│   └── prompts.yaml       ← System prompt de l'agent (généré, puissant et précis)
├── knowledge/             ← Fichiers de l'entreprise déposés par l'utilisateur
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   └── test_local.py      ← Chat interactif dans le terminal (simule WhatsApp)
├── requirements.txt       ← Dépendances Python
├── Dockerfile             ← Image Docker pour la production
├── docker-compose.yml     ← Orchestration avec les variables d'environnement
├── .dockerignore          ← Ce qui n'entre pas dans l'image
└── .env                   ← Clés API de l'utilisateur (ne va JAMAIS sur GitHub)
```

### Parcours d'un message

```
WhatsApp (le client écrit)
    ↓
Fournisseur (Zernio / Meta)
    ↓ webhook POST /webhook
main.py : vérifie la signature du webhook
    ↓
providers/ : normalise le message en MessageEntrant
    ↓
memory.py : cet événement a-t-il déjà été traité ? si oui, on l'écarte
    ↓
main.py : répond 200 TOUT DE SUITE et met le travail en file d'attente, en arrière-plan
    ↓ ─────────────── (hors du cycle du webhook) ───────────────
memory.py : une personne a-t-elle repris cette conversation ? si oui, l'agent se tait
    ↓
memory.py : récupère l'historique de cette conversation
    ↓
brain.py : appelle Claude avec system prompt + historique + nouveau message
    ↓
providers/ : envoie la réponse par le fournisseur choisi
    ↓
WhatsApp (le client reçoit la réponse)
    ↓ ─────────────── (une fois le client servi) ───────────────
humain.py : si l'agent passe la main, prévient le responsable et met l'agent en pause
n8n.py : sinon, envoie l'échange au workflow n8n (si le pont est configuré)
```

**Où `tools.py` intervient, et où il n'intervient pas.** Les informations de l'entreprise
(carte, prix, horaires, ce qu'il y a dans `/knowledge`) arrivent à l'agent **par le system
prompt**, pas par des outils : elles sont intégrées mot pour mot dans `config/prompts.yaml`
pendant la Phase 3. C'est pour ça que l'agent peut répondre aux questions sans rien exécuter.

`tools.py`, c'est autre chose : c'est l'endroit des **actions** (réserver un rendez-vous,
confirmer une commande, ouvrir un ticket). Aujourd'hui l'agent généré **ne les appelle pas
tout seul** : ce sont des fonctions prêtes à l'emploi, mais les brancher sur le cycle de
tool use de Claude est une étape à part. Si l'utilisateur demande que l'agent prenne
vraiment les rendez-vous, et pas seulement qu'il en parle, dis-le-lui clairement et
construis cette partie avec lui au lieu de faire comme si ça marchait déjà.

**Pourquoi on répond avant de traiter.** Les fournisseurs attendent un `2xx` en 5 secondes
environ. Appeler Claude prend plus de temps que ça. Si l'agent traite avant de répondre, le
fournisseur croit que le webhook a échoué et renvoie le même événement, jusqu'à 7 fois, et
le client finit par recevoir plusieurs fois la même réponse. D'où la règle : **répondre
d'abord, travailler ensuite**, et dédupliquer par id d'événement.

### Passage à un humain et pont n8n

Ces deux fonctions sont optionnelles. Leurs fichiers (`humain.py`, `n8n.py`) sont toujours
générés, mais ils ne font rien tant que leurs variables ne sont pas dans le `.env`.

**Passage à un humain.** Quand l'agent ne peut pas répondre, ou que le client demande une
personne, il le dit au client et termine sa réponse par la balise `[HUMAIN]`. Le code
retire la balise avant l'envoi, prévient le responsable, puis met l'agent en pause sur
cette conversation (12 heures par défaut, `PAUSE_HUMAIN_HEURES`), le temps que le
responsable réponde lui-même depuis la boîte de réception de son fournisseur. Les autres
conversations continuent normalement.

L'agent n'a le droit de passer la main que si quelqu'un peut être prévenu : par un bot
Telegram (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) ou par n8n. Sans l'un des deux, la
consigne n'est même pas ajoutée au system prompt. Et si l'alerte échoue, l'agent ne se met
pas en pause : mieux vaut un agent qui répond encore qu'un client laissé sans personne.

**Pont n8n.** Si `N8N_WEBHOOK_URL` est renseignée, l'agent envoie chaque échange au nœud
Webhook d'un workflow n8n, après avoir répondu au client. Si n8n est en panne, le client ne
le voit pas : l'échec est seulement écrit dans les journaux.

Attention au cas « n8n sans Telegram » : c'est alors le workflow n8n qui doit alerter le
responsable, en traitant l'événement `demande_humain`. Si l'utilisateur ne veut pas s'en
occuper, règle `PAUSE_HUMAIN_HEURES=0` : l'agent continuera de répondre.

---

## 5. Parcours de mise en route : 5 phases

Suis ces phases DANS L'ORDRE. Ne saute JAMAIS une phase et n'avance jamais sans confirmation
de l'utilisateur. Affiche la progression au début de chaque phase : « Phase X sur 5 : [description] »

---

### PHASE 1 : Accueil et vérification de l'environnement

**Message d'accueil (affiche-le tel quel) :**

```
===========================================================
   AgentKit : ton agent WhatsApp avec IA
===========================================================

Bonjour ! Je suis ton assistant de configuration AgentKit.
Je vais t'aider à construire ton agent WhatsApp avec IA,
personnalisé pour ton entreprise.

Compte entre 15 et 30 minutes.

Avant de commencer, je vérifie que ton environnement est prêt...
```

**Vérifications :**

1. **Python >= 3.11** : exécuter `python3 --version`. S'il n'existe pas ou s'il est inférieur à 3.11, afficher :
   ```
   Il te faut Python 3.11 ou plus récent.
   Télécharge-le ici : https://python.org/downloads
   ```

2. **Créer les dossiers nécessaires** (s'ils n'existent pas) :
   ```bash
   mkdir -p agent/providers config knowledge tests
   ```

3. **Générer requirements.txt** avec les dépendances de la stack

4. **Installer les dépendances** :
   ```bash
   pip install -r requirements.txt
   ```

5. **Créer le .env à partir du modèle** s'il n'existe pas :
   ```bash
   cp .env.example .env
   ```

6. **Afficher le résultat :**
   ```
   Phase 1 terminée : environnement prêt

   Maintenant, faisons connaissance avec ton entreprise pour construire l'agent qu'il te faut.
   ```

---

### PHASE 2 : Entretien sur l'entreprise

Pose ces questions UNE PAR UNE. Attends la réponse de l'utilisateur avant de poser la suivante.
Garde toutes les réponses en tête pour t'en servir en Phase 3.

```
QUESTION 1 : Comment s'appelle ton entreprise ?

QUESTION 2 : Que fait ton entreprise ?
             (Raconte-moi en détail : ce que tu vends, les services que tu proposes, qui sont tes clients)

QUESTION 3 : À quoi doit servir ton agent WhatsApp ?
             Tu peux en choisir un ou plusieurs :
             1. Répondre aux questions fréquentes
             2. Prendre des rendez-vous ou des réservations
             3. Qualifier et suivre des prospects / vendre
             4. Prendre des commandes
             5. Service après-vente
             6. Autre (décris-le)

QUESTION 4 : Comment veux-tu appeler ton agent ?
             (C'est le nom que verront tes clients, par exemple « Léa », « Support MonEntreprise », etc.)

QUESTION 5 : Quel ton l'agent doit-il adopter ?
             1. Professionnel et formel
             2. Amical et décontracté
             3. Commercial et convaincant
             4. Empathique et chaleureux

QUESTION 6 : Quels sont tes horaires d'ouverture ?
             (par exemple : du lundi au vendredi de 9 h à 18 h, le samedi de 10 h à 14 h)

QUESTION 7 : As-tu des fichiers avec des informations sur ton entreprise ?
             (Carte, grille de prix, FAQ, catalogue, conditions, etc.)

             Si OUI → « Dépose-les dans le dossier /knowledge et appuie sur Entrée quand c'est fait »
                      J'accepte : PDF, TXT, DOCX, CSV, images, JSON, Markdown
             Si NON → On continue avec ce que tu m'as raconté

QUESTION 8 : As-tu ta clé API Anthropic ?
             Si OUI → « Colle-la ici, je la range dans ton .env. Si tu préfères ne pas l'écrire
                      dans la conversation, ouvre le fichier .env et colle-la toi-même
                      après ANTHROPIC_API_KEY=, puis dis-moi quand c'est fait. »
             Si NON → Guider pas à pas :
                      1. Va sur platform.anthropic.com
                      2. Crée un compte ou connecte-toi
                      3. Va dans Settings → API Keys
                      4. Crée une nouvelle clé et copie-la
                      5. La clé commence par "sk-ant-..."

QUESTION 9 : Comment veux-tu connecter ton agent à WhatsApp ?

             1. Zernio (RECOMMANDÉ)
                Il tourne sur la WhatsApp Cloud API de Meta et s'occupe de connecter ton
                compte WhatsApp Business : tu n'as pas d'application Facebook à créer ni
                d'App Review à passer. Les 2 premiers comptes connectés sont gratuits,
                sans carte bancaire. Il a aussi un numéro de test partagé : tu peux voir
                ton agent fonctionner aujourd'hui, même sans numéro à toi.

             2. Meta Cloud API en direct
                L'API officielle de Meta, en te connectant toi-même. Plus de contrôle, mais
                il te faut une application Facebook de type Business et un compte Facebook
                Business vérifié.

             Si tu veux juste voir l'agent fonctionner vite, Zernio est le chemin le plus court.

QUESTION 10 : [Dépend de la réponse à la QUESTION 9]

             S'il a choisi ZERNIO :
                 J'ai besoin de 2 informations de ton compte Zernio :
                 1. La clé API (elle commence par "sk_")
                 2. Le Webhook Secret (c'est toi qui l'inventes, par exemple "mon-agent-2026")

                 S'il ne les a PAS → Guider pas à pas :
                     1. Va sur zernio.com et crée ton compte (offre Free, sans carte bancaire)
                     2. Dans le tableau de bord : Connections → Connect new → WhatsApp
                     3. Termine l'Embedded Signup de Meta qui s'ouvre dans la fenêtre
                        (tu choisis ou tu crées ton compte WhatsApp Business et ton numéro)
                     4. Va dans Settings → API Keys → Create API Key
                     5. Copie-la TOUT DE SUITE : elle ne s'affiche qu'une fois
                     6. Le Webhook Secret, c'est toi qui le choisis : n'importe quel texte
                        secret convient. Il servira à vérifier que les messages viennent
                        bien de Zernio.

                 Le webhook se configure en Phase 5, quand on aura l'URL publique.

                 Tu n'as pas encore de numéro WhatsApp Business ?
                     Zernio a un numéro de test partagé. Il s'active comme ça :
                     1. GET  https://zernio.com/api/v1/whatsapp/phone-numbers
                        → le champ "sandbox" donne le numéro et l'accountId
                     2. POST https://zernio.com/api/v1/whatsapp/sandbox/sessions
                        avec {"phone": "+33..."} (ton portable)
                     3. Tu reçois un WhatsApp depuis ce numéro. Réponds-y depuis ton portable.
                     4. C'est bon : tu es activé pour 7 jours, avec 50 messages par jour.

             S'il a choisi META CLOUD API :
                 J'ai besoin de 4 informations de ton application Facebook :
                 1. L'Access Token (permanent)
                 2. Le Phone Number ID
                 3. Le Verify Token (c'est toi qui l'inventes, par exemple "mon-agent-2026")
                 4. L'App Secret (pour vérifier la signature des webhooks)

                 S'il ne les a PAS → Guider pas à pas :
                     1. Va sur developers.facebook.com
                     2. Crée une application de type "Business"
                     3. Ajoute le produit "WhatsApp"
                     4. Dans WhatsApp → API Setup, copie le Phone Number ID
                     5. Génère un jeton d'accès permanent
                     6. Le Verify Token, c'est toi qui le choisis : n'importe quel texte secret
                     7. L'App Secret se trouve dans Settings → Basic → App Secret (clique sur "Show")

             NOTE : Si l'utilisateur veut d'abord tester sans vrai WhatsApp, il peut laisser
                    les identifiants vides et tout essayer avec test_local.py.

QUESTION 11 : Quand l'agent ne sait pas répondre, ou qu'un client demande à parler à
              quelqu'un, veux-tu être prévenu pour reprendre la conversation toi-même ?

             Si OUI → Le plus simple est une alerte Telegram, gratuite :
                      1. Dans Telegram, écris à @BotFather, envoie /newbot et suis les étapes
                      2. Il te donne un jeton, du type 123456789:AA... C'est un secret :
                         colle-le ici, ou mets-le toi-même dans le .env après TELEGRAM_BOT_TOKEN=
                      3. Envoie un premier message à ton nouveau bot (n'importe lequel)
                      4. Ouvre dans ton navigateur :
                         https://api.telegram.org/bot<TON_JETON>/getUpdates
                         Ton identifiant est le nombre après "chat":{"id":
                         → il va dans TELEGRAM_CHAT_ID

                      Après l'alerte, l'agent se tait 12 heures sur cette conversation pour te
                      laisser répondre. Tu peux changer cette durée (PAUSE_HUMAIN_HEURES).

             Si NON → L'agent répond seul, comme avant. On pourra l'ajouter plus tard.

QUESTION 12 : Utilises-tu n8n ?

             Si OUI → L'agent peut envoyer chaque échange à un de tes workflows, pour
                      remplir un CRM, un Google Sheets ou Notion :
                      1. Dans n8n, crée un workflow qui commence par un nœud Webhook,
                         méthode POST
                      2. Conseillé : Authentication = Header Auth, avec le nom
                         X-AgentKit-Secret et une valeur secrète que tu inventes
                      3. Copie la « Production URL » du nœud → N8N_WEBHOOK_URL
                         et ta valeur secrète → N8N_WEBHOOK_SECRET
                      4. Active le workflow

                      S'il n'a PAS configuré Telegram à la question 11, préviens-le :
                      « Sans Telegram, c'est ton workflow n8n qui doit t'alerter quand l'agent
                      passe la main : il reçoit alors l'événement demande_humain. Veux-tu que
                      ton workflow s'en charge ? » S'il répond non, écris PAUSE_HUMAIN_HEURES=0
                      dans le .env.

             Si NON → On passe. Le pont s'ajoute plus tard en deux lignes dans le .env.
```

**À la fin de l'entretien :**
```
Parfait ! J'ai toutes les informations qu'il me faut.
Je construis maintenant ton agent sur mesure...

Phase 2 terminée : informations de l'entreprise recueillies
```

---

### PHASE 3 : Génération de l'agent

Avec TOUTES les réponses de l'entretien, génère ces fichiers.

**Règle clé :** génère UNIQUEMENT l'adaptateur du fournisseur que l'utilisateur a choisi.
S'il a choisi Zernio, n'écris pas `meta.py`, et inversement.

`agent/n8n.py` et `agent/humain.py`, eux, sont TOUJOURS générés tels quels, même si
l'utilisateur a répondu non aux questions 11 et 12 : sans leurs variables dans le `.env`,
ils ne font rien, et `main.py` reste le même pour tout le monde.

#### 3.1 : `config/business.yaml`

```yaml
# Configuration de l'entreprise, générée par AgentKit
entreprise:
  nom: "[NOM DE L'ENTREPRISE]"
  description: "[DESCRIPTION DÉTAILLÉE]"
  horaires: "[HORAIRES]"

agent:
  nom: "[NOM DE L'AGENT]"
  ton: "[TON CHOISI]"
  cas_usage:
    - "[CAS 1]"
    - "[CAS 2]"

metadata:
  cree_le: "[DATE]"
  fournisseur: "[zernio ou meta]"
  version: "2.0"
```

#### 3.2 : `config/prompts.yaml`

Génère un system prompt PUISSANT et précis. Il doit contenir :

```yaml
# System prompt de l'agent, généré par AgentKit
system_prompt: |
  Tu es [NOM_AGENT], l'assistant virtuel de [NOM_ENTREPRISE].

  ## Ton identité
  - Tu t'appelles [NOM_AGENT]
  - Tu représentes [NOM_ENTREPRISE]
  - Ton ton est [TON] : [description détaillée du ton]

  ## À propos de l'entreprise
  [DESCRIPTION COMPLÈTE DE L'ENTREPRISE]

  ## Ce que tu sais faire
  [LISTE DÉTAILLÉE DE CE QUE L'AGENT PEUT FAIRE SELON LES CAS D'USAGE]

  ## Informations de l'entreprise
  [TOUT LE CONTENU UTILE DE /knowledge, TRAITÉ ET INTÉGRÉ ICI]

  ## Horaires d'ouverture
  [HORAIRES]
  En dehors des horaires, réponds : "Merci pour votre message. Nous sommes ouverts [HORAIRES]. Nous vous répondrons dès notre retour."

  ## Règles de comportement
  - Réponds TOUJOURS en français
  - Vouvoie le client, sauf si le ton choisi est amical et décontracté
  - Sois [TON] dans chaque message
  - Tu écris sur WhatsApp : messages courts, sans markdown, sans titres ni longues listes à puces
  - Si tu ne sais pas quelque chose, dis : "Je n'ai pas cette information, mais je vous mets en relation avec une personne de l'équipe qui pourra vous aider."
  - N'invente JAMAIS une information qu'on ne t'a pas donnée
  - Ne communique JAMAIS un prix ou une donnée qui n'est pas dans tes informations de base
  - Garde des réponses concises mais utiles
  - Si le client semble agacé, montre de l'empathie avant de résoudre
  - Si on te demande si tu es une personne, dis simplement que tu es l'assistant virtuel de [NOM_ENTREPRISE]
  - Termine TOUJOURS par une question ou une invitation à agir quand c'est approprié

fallback_message: "Désolé, je n'ai pas compris votre message. Pouvez-vous le reformuler ?"
error_message: "Désolé, je rencontre un problème technique. Merci de réessayer dans quelques minutes."
```

#### 3.3 : `agent/providers/base.py` (toujours généré)

```python
# agent/providers/base.py : classe de base des fournisseurs WhatsApp
# Généré par AgentKit

"""
Définit l'interface commune que tous les fournisseurs WhatsApp implémentent.
Grâce à elle, main.py ne sait pas, et n'a pas besoin de savoir, auquel tu es connecté.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request


@dataclass
class MessageEntrant:
    """Message normalisé : le même format quel que soit le fournisseur."""

    telephone: str           # Numéro de l'expéditeur, chiffres seulement, sans "+"
    texte: str               # Contenu du message
    message_id: str          # Id du message sur la plateforme
    est_sortant: bool        # True si c'est l'agent qui l'a envoyé (on l'ignore)
    contexte: dict = field(default_factory=dict)
    # "contexte" porte ce dont chaque fournisseur a besoin pour pouvoir répondre :
    #   evenement_id    -> id unique de l'événement, pour ne pas traiter deux fois la même chose
    #   conversation_id -> Zernio : dans quelle conversation il faut répondre
    #   account_id      -> Zernio : quel compte WhatsApp a reçu le message


class FournisseurWhatsApp(ABC):
    """Interface que chaque fournisseur WhatsApp doit implémenter."""

    @abstractmethod
    async def analyser_webhook(self, request: Request) -> list[MessageEntrant]:
        """Extrait et normalise les messages du payload du webhook."""
        ...

    @abstractmethod
    async def envoyer_message(
        self, telephone: str, message: str, contexte: dict | None = None
    ) -> bool:
        """Envoie un message texte. Renvoie True si l'envoi a réussi."""
        ...

    async def verifier_signature(self, request: Request) -> bool:
        """
        Confirme que le webhook vient vraiment du fournisseur.
        Par défaut tout est accepté ; chaque fournisseur l'implémente selon son schéma.
        """
        return True

    async def valider_webhook(self, request: Request) -> str | None:
        """Vérification GET du webhook. Seul Meta l'utilise. Renvoie la réponse ou None."""
        return None

    async def verifier_connexion(self) -> tuple[bool, str]:
        """Vérifie que les identifiants fonctionnent. Renvoie (ok, message_lisible)."""
        return True, "Ce fournisseur ne propose pas de vérification de connexion"
```

#### 3.4 : `agent/providers/__init__.py` (toujours généré)

```python
# agent/providers/__init__.py : fabrique de fournisseurs
# Généré par AgentKit

"""
Choisit le fournisseur WhatsApp d'après la variable WHATSAPP_PROVIDER du .env.
"""

import os

from agent.providers.base import FournisseurWhatsApp, MessageEntrant

FOURNISSEURS_PRIS_EN_CHARGE = ("zernio", "meta")


def obtenir_fournisseur() -> FournisseurWhatsApp:
    """
    Renvoie le fournisseur configuré dans le .env.

    Attention : ceci ne s'exécute PAS à l'import du module. Si la configuration est
    mauvaise, le serveur doit quand même démarrer et le dire dans le health check, au
    lieu de mourir à l'import et de laisser Railway redémarrer à l'aveugle.
    """
    fournisseur = os.getenv("WHATSAPP_PROVIDER", "").strip().lower()

    if not fournisseur:
        raise ValueError(
            "WHATSAPP_PROVIDER n'est pas configuré dans le .env. "
            f"Valeurs possibles : {' | '.join(FOURNISSEURS_PRIS_EN_CHARGE)}"
        )

    if fournisseur == "zernio":
        from agent.providers.zernio import FournisseurZernio

        return FournisseurZernio()

    if fournisseur == "meta":
        from agent.providers.meta import FournisseurMeta

        return FournisseurMeta()

    raise ValueError(
        f"Fournisseur non pris en charge : '{fournisseur}'. "
        f"Valeurs possibles : {' | '.join(FOURNISSEURS_PRIS_EN_CHARGE)}"
    )


__all__ = [
    "MessageEntrant",
    "FournisseurWhatsApp",
    "FOURNISSEURS_PRIS_EN_CHARGE",
    "obtenir_fournisseur",
]
```

#### 3.5 : `agent/providers/zernio.py` (s'il a choisi Zernio)

```python
# agent/providers/zernio.py : adaptateur pour Zernio
# Généré par AgentKit

"""
Zernio tourne sur la WhatsApp Cloud API de Meta : il s'occupe de la connexion du compte
WhatsApp Business, de la boîte de réception unifiée et des webhooks signés.

Documentation : https://docs.zernio.com/platforms/whatsapp
"""

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import Request

from agent.providers.base import FournisseurWhatsApp, MessageEntrant

logger = logging.getLogger("agentkit")

BASE_URL_PAR_DEFAUT = "https://zernio.com/api/v1"


class FournisseurZernio(FournisseurWhatsApp):
    """Fournisseur WhatsApp qui passe par Zernio."""

    def __init__(self):
        self.api_key = os.getenv("ZERNIO_API_KEY", "")
        self.webhook_secret = os.getenv("ZERNIO_WEBHOOK_SECRET", "")
        # Optionnel : ne sert qu'à la vérification de connexion au démarrage.
        # Pour répondre, l'account_id vient du webhook lui-même.
        self.account_id = os.getenv("ZERNIO_ACCOUNT_ID", "")
        # Attention au "or" : os.getenv(cle, defaut) n'utilise le défaut que si la clé
        # n'existe PAS. Comme le .env contient "ZERNIO_BASE_URL=" vide, os.getenv renvoie ""
        # et le défaut ne s'appliquerait jamais. Le "or" couvre les deux cas.
        self.base_url = (os.getenv("ZERNIO_BASE_URL") or BASE_URL_PAR_DEFAUT).rstrip("/")

        if not self.api_key:
            logger.warning("ZERNIO_API_KEY n'est pas configurée : l'agent ne pourra pas répondre")
        if not self.webhook_secret:
            logger.warning(
                "ZERNIO_WEBHOOK_SECRET n'est pas configuré : les webhooks ne sont PAS vérifiés. "
                "Ça va pour tester, mais ne le laisse pas comme ça en production."
            )

    # ── Recevoir ─────────────────────────────────────────────────────────

    async def verifier_signature(self, request: Request) -> bool:
        """Compare l'en-tête X-Zernio-Signature au HMAC-SHA256 du corps brut."""
        if not self.webhook_secret:
            return True  # mode test, l'avertissement a déjà été donné au démarrage

        signature_recue = request.headers.get("X-Zernio-Signature") or request.headers.get(
            "X-Late-Signature"
        )
        if not signature_recue:
            logger.warning("Webhook reçu sans signature X-Zernio-Signature : rejeté")
            return False

        corps = await request.body()
        signature_attendue = hmac.new(
            self.webhook_secret.encode("utf-8"), corps, hashlib.sha256
        ).hexdigest()

        # compare_digest sur des str exige de l'ASCII pur. Les en-têtes HTTP peuvent contenir
        # des octets que Starlette décode en latin-1, et là ça lèverait TypeError : l'erreur
        # sortirait du handler en 500, et le fournisseur renverrait l'événement sept fois.
        try:
            identiques = hmac.compare_digest(signature_attendue, signature_recue)
        except TypeError:
            logger.warning("La signature du webhook contient des caractères invalides : rejeté")
            return False

        if not identiques:
            logger.warning("Signature de webhook invalide : rejeté")
            return False
        return True

    async def analyser_webhook(self, request: Request) -> list[MessageEntrant]:
        """Normalise l'événement message.received de Zernio."""
        payload = await request.json()

        evenement = payload.get("event")
        if evenement != "message.received":
            # message.sent, message.delivered, message.read, etc. : on n'y répond pas
            logger.debug(f"Événement ignoré : {evenement}")
            return []

        message = payload.get("message") or {}
        if message.get("platform") != "whatsapp":
            return []

        expediteur = message.get("sender") or {}
        # phoneNumber arrive en E.164 avec "+". Depuis avril 2026 il peut manquer
        # (les utilisateurs qui ont un nom d'utilisateur WhatsApp ne montrent pas leur
        # numéro), donc on se rabat sur l'identifiant que Meta garantit toujours.
        telephone = (expediteur.get("phoneNumber") or "").lstrip("+")
        if not telephone:
            telephone = expediteur.get("businessScopedUserId") or expediteur.get("id") or ""

        compte = payload.get("account") or {}

        return [
            MessageEntrant(
                telephone=telephone,
                texte=message.get("text") or "",
                message_id=message.get("platformMessageId") or message.get("id") or "",
                # Zernio indique le sens : on ne répond qu'à ce qui entre
                est_sortant=message.get("direction") != "incoming",
                contexte={
                    "evenement_id": payload.get("id", ""),
                    "conversation_id": message.get("conversationId", ""),
                    "account_id": compte.get("id", ""),
                },
            )
        ]

    # ── Envoyer ──────────────────────────────────────────────────────────

    async def envoyer_message(
        self, telephone: str, message: str, contexte: dict | None = None
    ) -> bool:
        """Répond dans la conversation que le client a ouverte."""
        contexte = contexte or {}
        conversation_id = contexte.get("conversation_id")
        account_id = contexte.get("account_id") or self.account_id

        if not self.api_key:
            logger.error("Envoi impossible : il manque ZERNIO_API_KEY")
            return False
        if not conversation_id or not account_id:
            logger.error(
                "Envoi impossible : le message n'a pas de conversation_id ou d'account_id"
            )
            return False

        url = f"{self.base_url}/inbox/conversations/{conversation_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # Si le webhook est renvoyé, cette clé évite que Zernio envoie la réponse deux fois
        evenement_id = contexte.get("evenement_id")
        if evenement_id:
            headers["Idempotency-Key"] = f"agentkit-{evenement_id}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    url,
                    json={"accountId": account_id, "message": message},
                    headers=headers,
                )
        except httpx.HTTPError as e:
            logger.error(f"Erreur réseau en parlant à Zernio : {e}")
            return False

        if r.status_code == 200:
            return True

        # Zernio répond {"error": ..., "type": ..., "code": ...}.
        # Journaliser les trois fait gagner énormément de temps de diagnostic.
        detail = r.text[:500]
        try:
            corps = r.json()
            detail = (
                f"{corps.get('error')} "
                f"(type={corps.get('type')}, code={corps.get('code')})"
            )
        except ValueError:
            pass
        logger.error(f"Zernio a refusé l'envoi [{r.status_code}] : {detail}")
        return False

    # ── Diagnostic ───────────────────────────────────────────────────────

    async def verifier_connexion(self) -> tuple[bool, str]:
        """
        Demande à Zernio l'état réel du numéro auprès de Meta.
        C'est la voie prévue pour savoir si le canal est vivant.
        """
        if not self.api_key:
            return False, "Il manque ZERNIO_API_KEY"
        if not self.account_id:
            return True, "ZERNIO_ACCOUNT_ID non configuré : la vérification du numéro est ignorée"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{self.base_url}/whatsapp/number-info",
                    params={"accountId": self.account_id},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as e:
            return False, f"Impossible de joindre Zernio : {e}"

        if r.status_code != 200:
            return False, f"Zernio a répondu {r.status_code} : {r.text[:200]}"

        telephone = r.json().get("phone") or {}
        return True, (
            f"Numéro {telephone.get('display_phone_number', '?')} connecté "
            f"(qualité : {telephone.get('quality_rating', '?')})"
        )
```

#### 3.6 : `agent/providers/meta.py` (s'il a choisi Meta Cloud API)

```python
# agent/providers/meta.py : adaptateur pour la WhatsApp Cloud API de Meta
# Généré par AgentKit

"""
Connexion directe à l'API officielle de Meta.
Documentation : https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import Request

from agent.providers.base import FournisseurWhatsApp, MessageEntrant

logger = logging.getLogger("agentkit")


class FournisseurMeta(FournisseurWhatsApp):
    """Fournisseur WhatsApp qui utilise l'API officielle de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN", "")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")
        # Même précaution que dans zernio.py : une variable déclarée mais vide dans le .env
        # renvoie "" et pas le défaut, d'où le "or".
        self.verify_token = os.getenv("META_VERIFY_TOKEN") or "agentkit-verify"
        self.app_secret = os.getenv("META_APP_SECRET", "")
        self.api_version = os.getenv("META_API_VERSION") or "v25.0"

        if not self.access_token or not self.phone_number_id:
            logger.warning(
                "Il manque META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID : l'agent ne pourra pas répondre"
            )
        if not self.app_secret:
            logger.warning(
                "META_APP_SECRET n'est pas configuré : les webhooks ne sont PAS vérifiés. "
                "Ça va pour tester, mais ne le laisse pas comme ça en production."
            )

    # ── Recevoir ─────────────────────────────────────────────────────────

    async def valider_webhook(self, request: Request) -> str | None:
        """
        Meta fait un GET avec hub.challenge la première fois, pour vérifier que l'URL est à toi.
        Il faut renvoyer le challenge tel quel, en texte brut.
        """
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == self.verify_token
        ):
            return params.get("hub.challenge") or ""
        return None

    async def verifier_signature(self, request: Request) -> bool:
        """Compare l'en-tête X-Hub-Signature-256 au HMAC-SHA256 du corps brut."""
        if not self.app_secret:
            return True  # mode test, l'avertissement a déjà été donné au démarrage

        entete = request.headers.get("X-Hub-Signature-256", "")
        if not entete.startswith("sha256="):
            logger.warning("Webhook reçu sans signature X-Hub-Signature-256 : rejeté")
            return False

        corps = await request.body()
        signature_attendue = hmac.new(
            self.app_secret.encode("utf-8"), corps, hashlib.sha256
        ).hexdigest()

        # Comme dans zernio.py : compare_digest sur des str exige de l'ASCII pur, et un
        # en-tête avec des octets bizarres lèverait TypeError, donc un 500 au lieu d'un 401.
        try:
            identiques = hmac.compare_digest(signature_attendue, entete.removeprefix("sha256="))
        except TypeError:
            logger.warning("La signature du webhook contient des caractères invalides : rejeté")
            return False

        if not identiques:
            logger.warning("Signature de webhook invalide : rejeté")
            return False
        return True

    async def analyser_webhook(self, request: Request) -> list[MessageEntrant]:
        """Parcourt le payload imbriqué de la Meta Cloud API."""
        body = await request.json()
        messages: list[MessageEntrant] = []

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue  # pour l'instant, le texte seulement
                    messages.append(
                        MessageEntrant(
                            telephone=msg.get("from", ""),
                            texte=(msg.get("text") or {}).get("body", ""),
                            message_id=msg.get("id", ""),
                            # Meta ne livre que des messages entrants par ce canal
                            est_sortant=False,
                            contexte={"evenement_id": msg.get("id", "")},
                        )
                    )
        return messages

    # ── Envoyer ──────────────────────────────────────────────────────────

    async def envoyer_message(
        self, telephone: str, message: str, contexte: dict | None = None
    ) -> bool:
        """Envoie un message texte par la Cloud API. Meta n'a pas besoin du contexte."""
        if not self.access_token or not self.phone_number_id:
            logger.error("Envoi impossible : il manque META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID")
            return False

        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    url,
                    json={
                        "messaging_product": "whatsapp",
                        "to": telephone,
                        "type": "text",
                        "text": {"body": message},
                    },
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as e:
            logger.error(f"Erreur réseau en parlant à Meta : {e}")
            return False

        if r.status_code == 200:
            return True

        logger.error(f"Meta a refusé l'envoi [{r.status_code}] : {r.text[:500]}")
        return False

    # ── Diagnostic ───────────────────────────────────────────────────────

    async def verifier_connexion(self) -> tuple[bool, str]:
        """Lit le numéro depuis la Graph API pour confirmer que le jeton fonctionne."""
        if not self.access_token or not self.phone_number_id:
            return False, "Il manque META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}",
                    params={"fields": "display_phone_number,verified_name,quality_rating"},
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
        except httpx.HTTPError as e:
            return False, f"Impossible de joindre Meta : {e}"

        if r.status_code != 200:
            return False, f"Meta a répondu {r.status_code} : {r.text[:200]}"

        donnees = r.json()
        return True, (
            f"Numéro {donnees.get('display_phone_number', '?')} connecté "
            f"(qualité : {donnees.get('quality_rating', '?')})"
        )
```

#### 3.7 : `agent/main.py`

```python
# agent/main.py : serveur FastAPI + webhook WhatsApp
# Généré par AgentKit

"""
Serveur principal de l'agent.
Il fonctionne avec n'importe quel fournisseur (Zernio, Meta) grâce à la couche providers.
"""

import asyncio
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agent.brain import generer_reponse, obtenir_message_erreur
from agent.humain import passer_la_main, relais_actif
from agent.memory import (
    enregistrer_message,
    est_en_pause,
    initialiser_db,
    liberer_evenement,
    marquer_evenement_traite,
    nettoyer_anciens_evenements,
    obtenir_historique,
)
from agent.n8n import envoyer_a_n8n, pont_actif
from agent.providers import obtenir_fournisseur
from agent.providers.base import MessageEntrant

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agentkit")
# En développement on veut le détail de NOTRE agent, pas celui des bibliothèques.
# Mettre le niveau racine en DEBUG remplit le terminal du bruit d'aiosqlite et de httpx
# et rend illisible ce que l'agent a fait.
logger.setLevel(logging.DEBUG if ENVIRONMENT == "development" else logging.INFO)
# httpx écrit chaque adresse appelée dans les journaux. Celles de Telegram et de n8n
# contiennent un secret (jeton du bot, adresse du webhook) : on ne garde que ses avertissements.
logging.getLogger("httpx").setLevel(logging.WARNING)

PORT = int(os.getenv("PORT", "8000"))

# Un verrou par numéro de téléphone. Sur WhatsApp, il est courant d'envoyer « bonjour » puis,
# une demi-seconde après, la vraie question : sans ça les deux messages seraient traités
# en parallèle, liraient le même historique, et les écritures se mélangeraient.
_verrous: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Si la configuration est mauvaise, on garde l'erreur et on l'affiche dans le health check,
# au lieu de planter à l'import et de laisser Railway redémarrer le conteneur à l'aveugle.
fournisseur = None
erreur_configuration: str | None = None
try:
    fournisseur = obtenir_fournisseur()
except Exception as e:  # noqa: BLE001 : tout problème de configuration
    erreur_configuration = str(e)

# Résultat de la vérification des identifiants faite au démarrage. Il est exposé dans le
# health check : un serveur qui répond ne veut pas dire que l'agent peut répondre sur WhatsApp.
etat_fournisseur: dict = {"ok": None, "detail": "non vérifié"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prépare la base de données et vérifie le fournisseur au démarrage."""
    await initialiser_db()
    await nettoyer_anciens_evenements()
    logger.info("Base de données prête")
    logger.info(f"Serveur AgentKit à l'écoute sur le port {PORT}")

    global etat_fournisseur
    if fournisseur is not None:
        logger.info(f"Fournisseur WhatsApp : {fournisseur.__class__.__name__}")
        ok, detail = await fournisseur.verifier_connexion()
        etat_fournisseur = {"ok": ok, "detail": detail}
        logger.info(f"Connexion au fournisseur : {'OK' if ok else 'ERREUR'}, {detail}")
    else:
        logger.error(f"Fournisseur WhatsApp NON configuré : {erreur_configuration}")

    logger.info(
        f"Passage à un humain : {'actif' if relais_actif() else 'inactif'}, "
        f"pont n8n : {'actif' if pont_actif() else 'inactif'}"
    )

    yield


app = FastAPI(title="AgentKit : agent WhatsApp avec IA", version="2.0.0", lifespan=lifespan)


@app.get("/")
async def health_check():
    """Point de contrôle de santé pour Railway et la supervision."""
    if erreur_configuration:
        return {"status": "error", "service": "agentkit", "detail": erreur_configuration}

    # On répond 200 même si les identifiants sont mauvais, pour que Railway ne marque pas
    # le déploiement comme tombé et que tu puisses lire le diagnostic. Le détail est dans le corps.
    return {
        "status": "ok" if etat_fournisseur["ok"] else "degrade",
        "service": "agentkit",
        "fournisseur": fournisseur.__class__.__name__ if fournisseur else None,
        "connexion": etat_fournisseur,
        "passage_humain": relais_actif(),
        "pont_n8n": pont_actif(),
    }


@app.get("/webhook")
async def webhook_verification(request: Request):
    """Vérification GET du webhook. C'est Meta qui la demande ; pour Zernio elle ne fait rien."""
    if fournisseur is None:
        raise HTTPException(status_code=503, detail=erreur_configuration or "Fournisseur non configuré")

    reponse = await fournisseur.valider_webhook(request)
    if reponse is not None:
        return PlainTextResponse(reponse)

    # Meta attend un 403 quand il envoie hub.mode=subscribe et que le verify_token ne
    # correspond pas. Lui renvoyer 200 lui fait croire que l'URL est vérifiée alors que non.
    if request.query_params.get("hub.mode") == "subscribe":
        raise HTTPException(status_code=403, detail="Verify token incorrect")

    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request, taches: BackgroundTasks):
    """
    Reçoit les messages WhatsApp.

    Répond 200 tout de suite et traite le message en arrière-plan.

    Ce n'est PAS un détail de style. Les fournisseurs attendent un 2xx en 5 secondes environ
    et, s'ils ne le reçoivent pas, ils renvoient le même événement jusqu'à 7 fois. Comme
    appeler Claude prend plus de temps que ça, traiter avant de répondre fait que le client
    reçoit plusieurs fois la même réponse. Donc : répondre d'abord, travailler ensuite.
    """
    if fournisseur is None:
        raise HTTPException(status_code=503, detail=erreur_configuration or "Fournisseur non configuré")

    if not await fournisseur.verifier_signature(request):
        raise HTTPException(status_code=401, detail="Signature du webhook invalide")

    try:
        messages = await fournisseur.analyser_webhook(request)
    except Exception as e:  # noqa: BLE001
        # Un payload bizarre ne doit pas pousser le fournisseur à réessayer sans fin
        logger.error(f"Impossible de lire le webhook : {e}")
        return {"status": "ignore"}

    en_file = 0
    for msg in messages:
        if msg.est_sortant or not msg.texte.strip():
            continue

        # La livraison est « au moins une fois » : le même événement peut arriver deux fois
        evenement_id = msg.contexte.get("evenement_id") or msg.message_id
        if evenement_id and not await marquer_evenement_traite(evenement_id):
            logger.info(f"Événement en double, ignoré : {evenement_id}")
            continue

        logger.info(f"Message de {msg.telephone} : {msg.texte}")
        taches.add_task(traiter_message, msg)
        en_file += 1

    return {"status": "ok", "en_file": en_file}


async def traiter_message(msg: MessageEntrant):
    """
    Génère la réponse et la renvoie. S'exécute hors du cycle du webhook.

    On prend un verrou par téléphone : deux messages à la suite du même client sont
    traités dans l'ordre, pas en parallèle, pour que l'historique ne se mélange pas.
    """
    evenement_id = msg.contexte.get("evenement_id") or msg.message_id
    echange = None  # ce qui partira vers n8n une fois le client servi

    async with _verrous[msg.telephone]:
        try:
            # Une personne a repris cette conversation : l'agent se tait jusqu'à la fin de la pause
            if await est_en_pause(msg.telephone):
                logger.info(f"Conversation avec {msg.telephone} en pause : une personne a la main")
                return

            # L'historique est lu AVANT d'enregistrer le message en cours : brain.py ajoute
            # le nouveau message à la fin, et comme ça il n'est pas en double.
            historique = await obtenir_historique(msg.telephone)
            reponse, est_vraie_reponse, demande_humain = await generer_reponse(msg.texte, historique)

            envoye = await fournisseur.envoyer_message(msg.telephone, reponse, msg.contexte)

            if not envoye:
                # L'événement a été marqué comme traité AVANT d'arriver ici, pour que deux
                # livraisons simultanées ne fassent pas doublon. Si l'envoi a échoué, il faut
                # le relâcher : sinon le nouvel essai du fournisseur serait écarté comme
                # doublon et le client resterait sans réponse pour toujours.
                logger.error(f"Impossible d'envoyer la réponse à {msg.telephone} ; l'événement est libéré")
                await liberer_evenement(evenement_id)
                return

            # On n'enregistre dans l'historique que ce qui est vraiment de la conversation.
            # Les avertissements techniques (« je rencontre un problème ») ne sont pas un tour
            # de l'agent : les garder polluerait le contexte de tous les messages suivants.
            if est_vraie_reponse:
                await enregistrer_message(msg.telephone, "user", msg.texte)
                await enregistrer_message(msg.telephone, "assistant", reponse)

            logger.info(f"Réponse envoyée à {msg.telephone} : {reponse}")

            if demande_humain:
                # Le client a sa réponse : on prévient le responsable et l'agent se met en pause.
                # C'est fait sous le verrou, pour que le message suivant voie déjà la pause.
                await passer_la_main(msg.telephone, msg.texte, reponse)
            elif est_vraie_reponse:
                echange = {
                    "telephone": msg.telephone,
                    "message_client": msg.texte,
                    "reponse_agent": reponse,
                }

        except Exception as e:  # noqa: BLE001
            logger.exception(f"Erreur pendant le traitement du message de {msg.telephone} : {e}")
            await liberer_evenement(evenement_id)
            try:
                await fournisseur.envoyer_message(msg.telephone, obtenir_message_erreur(), msg.contexte)
            except Exception:  # noqa: BLE001
                logger.error("Impossible aussi de prévenir le client de l'erreur")

    # Hors du verrou : n8n ne doit jamais faire attendre le message suivant du client
    if echange and pont_actif():
        await envoyer_a_n8n("echange", echange)
```

#### 3.8 : `agent/brain.py`

```python
# agent/brain.py : cerveau de l'agent, connexion à Claude
# Généré par AgentKit

"""
Logique d'IA de l'agent. Lit le system prompt dans config/prompts.yaml et génère les
réponses avec l'API d'Anthropic.
"""

import logging
import os

import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.humain import CONSIGNE_HUMAIN, MESSAGE_RELAIS, relais_actif, separer_balise

load_dotenv()
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Le modèle se change depuis le .env, sans toucher au code.
#   claude-opus-5     le plus capable                  5 $ / 25 $ par million de tokens
#   claude-sonnet-5   l'équilibré (par défaut)         3 $ / 15 $
#   claude-haiku-4-5  le moins cher et le plus rapide  1 $ / 5 $
# Le "or" et pas le défaut de os.getenv : une variable déclarée vide dans le .env
# renvoie "" et laisserait l'agent sans modèle.
MODELE = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"

# C'est un bot à réponses courtes : avec un effort bas il répond plus vite et pour moins cher.
# Laisse la variable vide dans le .env pour ne pas envoyer le paramètre.
EFFORT = os.getenv("ANTHROPIC_EFFORT", "low").strip()

# WhatsApp, ce sont des messages courts, mais ce plafond ne couvre PAS que la réponse :
# sur les modèles actuels, le raisonnement interne compte aussi dedans. Avec une marge trop
# juste, une question qui demande un peu de réflexion laisse l'agent sans place pour répondre.
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS") or "4096")

# Les modèles plus anciens n'acceptent pas output_config. Si le premier appel échoue pour
# cette raison, on réessaie sans le paramètre et on s'en souvient pour les suivants.
_accepte_effort = True


def charger_config_prompts() -> dict:
    """Lit toute la configuration dans config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml introuvable")
        return {}


def charger_system_prompt() -> str:
    """Le system prompt : qui est l'agent et ce qu'il sait de l'entreprise."""
    return charger_config_prompts().get(
        "system_prompt", "Tu es un assistant utile. Réponds toujours en français."
    )


def obtenir_message_erreur() -> str:
    """Ce qu'on dit au client quand quelque chose échoue de notre côté."""
    return charger_config_prompts().get(
        "error_message",
        "Désolé, je rencontre un problème technique. Merci de réessayer dans quelques minutes.",
    )


def obtenir_message_repli() -> str:
    """Ce qu'on dit au client quand le message n'a pas été compris."""
    return charger_config_prompts().get(
        "fallback_message", "Désolé, je n'ai pas compris votre message. Pouvez-vous le reformuler ?"
    )


def _extraire_texte(reponse) -> str:
    """
    Rassemble le texte de la réponse de Claude.

    Attention : on ne peut PAS faire reponse.content[0].text. La réponse est une liste de
    blocs et le premier n'est pas toujours du texte (les modèles qui raisonnent renvoient
    d'abord un bloc de réflexion). Il faut filtrer par type.
    """
    parties = [bloc.text for bloc in reponse.content if bloc.type == "text"]
    return "\n".join(p for p in parties if p).strip()


def _est_erreur_effort(erreur: Exception) -> bool:
    """
    True seulement si le modèle a refusé l'appel À CAUSE du paramètre output_config/effort.

    On exige un 400 de requête invalide, et pas n'importe quelle erreur qui contient le
    mot : un 529 de surcharge qui le cite au passage ne doit pas couper le paramètre
    pour tout le processus.
    """
    if getattr(erreur, "status_code", None) != 400:
        return False
    texte = str(erreur).lower()
    return "output_config" in texte or "effort" in texte


async def generer_reponse(message: str, historique: list[dict]) -> tuple[str, bool, bool]:
    """
    Génère une réponse avec Claude.

    Args:
        message: le nouveau message du client
        historique: les messages précédents, [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        (texte, est_vraie_reponse, demande_humain)

        "est_vraie_reponse" vaut False quand ce qu'on renvoie est un avertissement
        technique (erreur ou repli) et pas une réponse de l'agent. main.py s'en sert pour
        ne pas garder ces avertissements dans l'historique : s'ils y restaient, ils
        pollueraient le contexte de tous les messages suivants.

        "demande_humain" vaut True quand l'agent passe la main : il ne sait pas répondre,
        ou le client veut parler à une personne. main.py prévient alors le responsable.
    """
    global _accepte_effort

    if not message or len(message.strip()) < 2:
        return obtenir_message_repli(), False, False

    messages = [{"role": m["role"], "content": m["content"]} for m in historique]
    messages.append({"role": "user", "content": message})

    system_prompt = charger_system_prompt()
    if relais_actif():
        # La consigne n'est ajoutée que si quelqu'un peut être prévenu (Telegram ou n8n)
        system_prompt += "\n\n" + CONSIGNE_HUMAIN
    extras = {"output_config": {"effort": EFFORT}} if (_accepte_effort and EFFORT) else {}

    async def _appeler(parametres_extra: dict):
        return await client.messages.create(
            model=MODELE,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
            **parametres_extra,
        )

    try:
        reponse = await _appeler(extras)
    except Exception as e:  # noqa: BLE001
        if extras and _est_erreur_effort(e):
            logger.warning(
                f"Le modèle {MODELE} n'accepte pas output_config.effort ; nouvel essai sans ce paramètre."
            )
            _accepte_effort = False
            try:
                reponse = await _appeler({})
            except Exception as e2:  # noqa: BLE001
                logger.error(f"Erreur lors de l'appel à Claude : {e2}")
                return obtenir_message_erreur(), False, False
        else:
            logger.error(f"Erreur lors de l'appel à Claude : {e}")
            return obtenir_message_erreur(), False, False

    if getattr(reponse, "stop_reason", None) == "max_tokens":
        logger.warning(
            f"La réponse a été coupée en atteignant le plafond de {MAX_TOKENS} tokens. "
            "Si ça arrive souvent, augmente ANTHROPIC_MAX_TOKENS ou raccourcis le system prompt."
        )

    texte = _extraire_texte(reponse)
    if not texte:
        logger.warning("Claude a renvoyé une réponse sans texte")
        return obtenir_message_repli(), False, False

    texte, demande_humain = separer_balise(texte)
    if demande_humain and not texte:
        texte = MESSAGE_RELAIS  # l'agent n'a écrit que la balise

    logger.info(
        f"Réponse générée avec {MODELE} "
        f"({reponse.usage.input_tokens} in / {reponse.usage.output_tokens} out)"
    )
    return texte, True, demande_humain
```

#### 3.9 : `agent/memory.py`

```python
# agent/memory.py : mémoire des conversations
# Généré par AgentKit

"""
Garde l'historique de chaque conversation par numéro de téléphone, tient le registre des
événements de webhook déjà traités, et retient les conversations qu'une personne a reprises.

SQLite en local, PostgreSQL en production.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import DateTime, Integer, String, Text, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()
logger = logging.getLogger("agentkit")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Railway fournit l'URL PostgreSQL avec le schéma "postgresql://" (ou "postgres://").
# SQLAlchemy en mode asynchrone a besoin que le pilote soit explicite.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# En production, SQLite vit dans le conteneur, et le disque du conteneur est éphémère :
# chaque redéploiement efface l'historique de toutes les conversations. On le dit fort, parce
# que l'agent démarre quand même et qu'on ne remarque le problème que quand un client revient.
if DATABASE_URL.startswith("sqlite") and os.getenv("ENVIRONMENT") == "production":
    logger.warning(
        "Tu es en production avec SQLite. L'historique sera effacé à chaque redéploiement. "
        "Ajoute PostgreSQL et configure DATABASE_URL pour que l'agent se souvienne de ses clients."
    )

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def maintenant() -> datetime:
    """Heure actuelle en UTC, avec fuseau horaire."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Message(Base):
    """Un message de l'historique de conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telephone: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" ou "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)


class EvenementTraite(Base):
    """
    Événements de webhook déjà traités.

    Les fournisseurs livrent « au moins une fois » : le même événement peut arriver deux fois.
    Sans cette table, le client recevrait deux fois la même réponse.
    """

    __tablename__ = "evenements_traites"

    evenement_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant, index=True)


class ConversationEnPause(Base):
    """
    Conversations où l'agent se tait parce qu'une personne a repris la main.

    Passé l'heure indiquée, l'agent recommence à répondre.
    """

    __tablename__ = "conversations_en_pause"

    telephone: Mapped[str] = mapped_column(String(50), primary_key=True)
    jusqu_a: Mapped[datetime] = mapped_column(DateTime(timezone=True))


async def initialiser_db():
    """Crée les tables si elles n'existent pas."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def marquer_evenement_traite(evenement_id: str) -> bool:
    """
    Enregistre un événement. Renvoie True s'il est nouveau, False s'il avait déjà été traité.

    L'unicité est garantie par la base de données (clé primaire), pas par une requête
    préalable : ainsi deux webhooks qui arrivent en même temps ne passent pas tous les deux.
    """
    if not evenement_id:
        return True  # sans id on ne peut pas dédupliquer : on traite

    async with async_session() as session:
        session.add(EvenementTraite(evenement_id=evenement_id, cree_le=maintenant()))
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def liberer_evenement(evenement_id: str):
    """
    Efface la marque d'un événement pour que le nouvel essai du fournisseur SOIT traité.

    Sert quand le message a été marqué comme traité mais que l'envoi de la réponse a
    ensuite échoué. Sans ça, le nouvel essai serait écarté comme doublon et le client
    resterait sans réponse pour toujours.
    """
    if not evenement_id:
        return
    async with async_session() as session:
        await session.execute(delete(EvenementTraite).where(EvenementTraite.evenement_id == evenement_id))
        await session.commit()


async def nettoyer_anciens_evenements(jours: int = 7):
    """Efface les événements de plus de N jours pour que la table ne grossisse pas sans fin."""
    limite = maintenant() - timedelta(days=jours)
    async with async_session() as session:
        resultat = await session.execute(
            delete(EvenementTraite).where(EvenementTraite.cree_le < limite)
        )
        await session.commit()
    if resultat.rowcount:
        logger.info(f"{resultat.rowcount} événements de plus de {jours} jours ont été nettoyés")


async def enregistrer_message(telephone: str, role: str, content: str):
    """Enregistre un message dans l'historique de cette conversation."""
    async with async_session() as session:
        session.add(Message(telephone=telephone, role=role, content=content, timestamp=maintenant()))
        await session.commit()


async def obtenir_historique(telephone: str, limite: int = 20) -> list[dict]:
    """
    Renvoie les N derniers messages d'une conversation, dans l'ordre chronologique.

    On trie par id et pas par timestamp : deux messages enregistrés au même instant
    ont le même timestamp, et leur ordre serait laissé au hasard.
    """
    async with async_session() as session:
        resultat = await session.execute(
            select(Message)
            .where(Message.telephone == telephone)
            .order_by(Message.id.desc())
            .limit(limite)
        )
        messages = list(resultat.scalars().all())

    messages.reverse()  # ils arrivent du plus récent au plus ancien : on les retourne

    # L'API de Claude exige que l'historique commence par un message de l'utilisateur.
    # Si une erreur passée a laissé un "assistant" isolé au début, on l'enlève.
    while messages and messages[0].role != "user":
        messages.pop(0)

    return [{"role": m.role, "content": m.content} for m in messages]


async def effacer_historique(telephone: str):
    """Efface tout l'historique d'une conversation."""
    async with async_session() as session:
        await session.execute(delete(Message).where(Message.telephone == telephone))
        await session.commit()


async def mettre_en_pause(telephone: str, heures: float):
    """L'agent ne répond plus à cette conversation pendant N heures."""
    async with async_session() as session:
        await session.merge(
            ConversationEnPause(telephone=telephone, jusqu_a=maintenant() + timedelta(hours=heures))
        )
        await session.commit()


async def est_en_pause(telephone: str) -> bool:
    """
    True si une personne a la main sur cette conversation.

    Les dates sont comparées dans la base, pas en Python : SQLite rend des dates sans
    fuseau horaire, et les comparer ici à maintenant() lèverait une erreur.
    """
    async with async_session() as session:
        resultat = await session.execute(
            select(ConversationEnPause).where(
                ConversationEnPause.telephone == telephone,
                ConversationEnPause.jusqu_a > maintenant(),
            )
        )
        return resultat.scalars().first() is not None


async def lever_pause(telephone: str):
    """Rend la main à l'agent sur cette conversation."""
    async with async_session() as session:
        await session.execute(
            delete(ConversationEnPause).where(ConversationEnPause.telephone == telephone)
        )
        await session.commit()
```

#### 3.10 : `agent/n8n.py` (toujours généré)

Sans `N8N_WEBHOOK_URL` dans le `.env`, ce fichier ne fait rien.

```python
# agent/n8n.py : pont vers n8n
# Généré par AgentKit

"""
Envoie les événements de l'agent à un workflow n8n, par son nœud Webhook.

À partir de là, n8n fait le reste : remplir un Google Sheets ou un CRM, créer une fiche
Notion, prévenir une équipe. Le pont est optionnel : sans N8N_WEBHOOK_URL, il ne fait rien.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("agentkit")


def pont_actif() -> bool:
    """True si l'adresse d'un webhook n8n est configurée."""
    return bool(os.getenv("N8N_WEBHOOK_URL", "").strip())


async def envoyer_a_n8n(evenement: str, donnees: dict) -> bool:
    """
    Envoie un événement à n8n. Renvoie True si n8n l'a accepté.

    Ne lève jamais d'exception : si n8n est en panne, l'agent doit continuer à répondre
    à ses clients. L'échec est seulement écrit dans les journaux.
    """
    url = os.getenv("N8N_WEBHOOK_URL", "").strip()
    if not url:
        return False

    headers = {"Content-Type": "application/json"}
    secret = os.getenv("N8N_WEBHOOK_SECRET", "").strip()
    if secret:
        # Côté n8n : nœud Webhook, Authentication = Header Auth, avec ce même nom d'en-tête
        headers["X-AgentKit-Secret"] = secret

    charge = {
        "evenement": evenement,
        "date": datetime.now(timezone.utc).isoformat(),
        **donnees,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=charge, headers=headers)
    except httpx.HTTPError as e:
        # On n'écrit que le type de l'erreur : son texte peut contenir l'adresse du webhook
        logger.warning(f"n8n injoignable, événement « {evenement} » non transmis : {type(e).__name__}")
        return False

    if r.status_code >= 400:
        logger.warning(f"n8n a refusé l'événement « {evenement} » [{r.status_code}] : {r.text[:200]}")
        return False
    return True
```

L'agent envoie deux événements, toujours en JSON :

| `evenement` | Quand | Champs |
|---|---|---|
| `echange` | Après chaque réponse de l'agent | `date`, `telephone`, `message_client`, `reponse_agent` |
| `demande_humain` | Quand l'agent passe la main | les mêmes, plus `pause_heures` |

#### 3.11 : `agent/humain.py` (toujours généré)

Sans `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, ni `N8N_WEBHOOK_URL`, l'agent ne passe jamais
la main : il n'annonce pas au client une personne qui ne serait pas prévenue.

```python
# agent/humain.py : passage à un humain
# Généré par AgentKit

"""
Quand l'agent ne sait pas répondre, ou que le client demande une personne, il passe la
main : il prévient le responsable (Telegram, n8n) et se met en pause sur cette conversation.

L'agent le signale en terminant sa réponse par la balise [HUMAIN]. La consigne est ajoutée
au system prompt par brain.py, pour que la balise soit définie à un seul endroit : ici.
"""

import logging
import os
import re

import httpx

from agent.memory import mettre_en_pause
from agent.n8n import envoyer_a_n8n, pont_actif

logger = logging.getLogger("agentkit")

BALISE_HUMAIN = "[HUMAIN]"
_MOTIF_BALISE = re.compile(r"\[\s*HUMAIN\s*\]", re.IGNORECASE)

CONSIGNE_HUMAIN = (
    "## Passer la main à une personne\n"
    "Si tu ne peux pas répondre avec les informations que tu as, ou si le client demande à "
    "parler à une personne, dis-lui simplement qu'un membre de l'équipe va reprendre la "
    f"conversation, puis termine ton message par {BALISE_HUMAIN} seul sur la dernière ligne. "
    "N'écris jamais cette balise dans un autre cas, et ne l'explique jamais au client."
)

MESSAGE_RELAIS = "Je transmets votre demande à une personne de l'équipe, qui vous répondra dès que possible."


def telegram_actif() -> bool:
    """True si le bot Telegram d'alerte est configuré."""
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def relais_actif() -> bool:
    """
    True si l'agent a le droit de passer la main.

    Il ne l'a que si quelqu'un peut être prévenu : sinon il annoncerait au client une
    personne qui ne viendra jamais.
    """
    return telegram_actif() or pont_actif()


def heures_de_pause() -> float:
    """Durée du silence de l'agent après avoir passé la main. 0 = il continue à répondre."""
    try:
        return max(0.0, float(os.getenv("PAUSE_HUMAIN_HEURES") or "12"))
    except ValueError:
        logger.warning("PAUSE_HUMAIN_HEURES n'est pas un nombre : 12 heures par défaut")
        return 12.0


def separer_balise(texte: str) -> tuple[str, bool]:
    """Retire la balise de la réponse. Renvoie (texte_pour_le_client, demande_humain)."""
    if not _MOTIF_BALISE.search(texte):
        return texte, False
    return _MOTIF_BALISE.sub("", texte).strip(), True


def _numero_lisible(telephone: str) -> str:
    """Remet le "+" devant un numéro. Un identifiant Meta sans numéro reste tel quel."""
    return f"+{telephone}" if telephone.isdigit() else telephone


async def _alerter_par_telegram(texte: str) -> bool:
    """Envoie l'alerte par le bot Telegram. Renvoie True si Telegram l'a acceptée."""
    jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{jeton}/sendMessage",
                json={"chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(), "text": texte},
            )
    except httpx.HTTPError as e:
        # On n'écrit que le type de l'erreur : son texte peut contenir l'URL, donc le jeton
        logger.error(f"Alerte Telegram impossible : {type(e).__name__}")
        return False

    if r.status_code != 200:
        logger.error(f"Telegram a refusé l'alerte [{r.status_code}] : {r.text[:200]}")
        return False
    return True


async def alerter_responsable(telephone: str, message_client: str, reponse_agent: str) -> bool:
    """
    Prévient le responsable par tous les canaux configurés.
    Renvoie True si au moins une alerte est partie.
    """
    heures = heures_de_pause()
    prevenu = False

    if telegram_actif():
        if heures > 0:
            suite = f"L'agent se tait {heures:g} h sur cette conversation : à toi de répondre."
        else:
            suite = "L'agent continue de répondre sur cette conversation."
        texte = (
            "Un client attend une réponse humaine\n\n"
            f"Téléphone : {_numero_lisible(telephone)}\n"
            f"Son message : {message_client[:500]}\n"
            f"Réponse de l'agent : {reponse_agent[:500]}\n\n"
            f"{suite}"
        )
        prevenu = await _alerter_par_telegram(texte)

    if pont_actif():
        transmis = await envoyer_a_n8n(
            "demande_humain",
            {
                "telephone": telephone,
                "message_client": message_client,
                "reponse_agent": reponse_agent,
                "pause_heures": heures,
            },
        )
        prevenu = prevenu or transmis

    return prevenu


async def passer_la_main(telephone: str, message_client: str, reponse_agent: str) -> bool:
    """
    Prévient le responsable, puis met l'agent en pause sur cette conversation.

    Ne lève jamais d'exception : le client a déjà reçu sa réponse, une alerte ratée ne doit
    pas lui en envoyer une deuxième. Si personne n'a pu être prévenu, l'agent ne se met pas
    en pause : mieux vaut un agent qui répond encore qu'un client laissé sans personne.
    """
    try:
        if not await alerter_responsable(telephone, message_client, reponse_agent):
            logger.error(f"Personne n'a pu être prévenu pour {telephone} : l'agent reste actif")
            return False

        heures = heures_de_pause()
        if heures > 0:
            await mettre_en_pause(telephone, heures)
            logger.info(f"L'agent passe la main pour {telephone} : en pause {heures:g} h")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Le passage à un humain a échoué pour {telephone} : {type(e).__name__}")
        return False
```

#### 3.12 : `agent/tools.py`

Génère des outils SPÉCIFIQUES selon les cas d'usage choisis par l'utilisateur.
Pars de ce modèle de base et ajoute les fonctions selon le cas :

```python
# agent/tools.py : outils de l'agent
# Généré par AgentKit

"""
Outils propres à l'entreprise.

ATTENTION : ces fonctions ne s'exécutent PAS encore toutes seules. Les informations de
l'entreprise arrivent à l'agent par le system prompt (config/prompts.yaml), donc pour
RÉPONDRE aux questions il n'y a besoin de rien ici. Ce fichier est l'endroit des ACTIONS
(réserver, encaisser, ouvrir un ticket), et les brancher sur le cycle de tool use de
Claude est une étape à part.

Claude Code génère les fonctions selon les cas d'usage choisis pendant l'entretien.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger("agentkit")

DOSSIER_KNOWLEDGE = Path("knowledge")


def charger_infos_entreprise() -> dict:
    """Charge les informations de l'entreprise depuis config/business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/business.yaml introuvable")
        return {}


def obtenir_horaires() -> dict:
    """Renvoie les horaires d'ouverture de l'entreprise."""
    info = charger_infos_entreprise()
    return {
        "horaires": info.get("entreprise", {}).get("horaires", "Non disponible"),
        "est_ouvert": True,  # TODO : calculer selon l'heure actuelle et les horaires
    }


def chercher_dans_knowledge(requete: str) -> str:
    """
    Cherche une information dans les fichiers de /knowledge.
    Renvoie les extraits qui correspondent à la requête.
    """
    if not DOSSIER_KNOWLEDGE.is_dir():
        return "Aucun fichier de connaissance disponible."

    resultats = []
    for chemin in sorted(DOSSIER_KNOWLEDGE.iterdir()):
        if chemin.name.startswith(".") or not chemin.is_file():
            continue
        try:
            contenu = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # les binaires et les fichiers illisibles sont ignorés
        if requete.lower() in contenu.lower():
            resultats.append(f"[{chemin.name}]: {contenu[:500]}")

    if resultats:
        return "\n---\n".join(resultats)
    return "Je n'ai pas trouvé d'information précise là-dessus dans mes fichiers."


# ════════════════════════════════════════════════════════════
# Claude Code : ajoute ici les fonctions spécifiques selon
# le cas d'usage choisi par l'utilisateur. Exemples :
#
# Si FAQ -> chercher_dans_knowledge() est déjà prête plus haut
#
# Si PRISE DE RENDEZ-VOUS :
# def obtenir_creneaux_disponibles(date: str) -> list[dict]: ...
# def reserver_rendez_vous(telephone, date, heure, service): ...
# def annuler_rendez_vous(telephone, rendez_vous_id): ...
#
# Si PRISE DE COMMANDES :
# def ajouter_au_panier(telephone, produit, quantite): ...
# def voir_panier(telephone) -> list[dict]: ...
# def confirmer_commande(telephone) -> dict: ...
#
# Si VENTE / PROSPECTS :
# def enregistrer_prospect(telephone, nom, interet): ...
# def qualifier_prospect(telephone) -> str: ...
# def transmettre_a_un_vendeur(telephone, contexte): ...
#
# Si SUPPORT :
# def creer_ticket(telephone, probleme) -> str: ...
# def consulter_ticket(ticket_id) -> dict: ...
# def escalader_ticket(ticket_id, raison): ...
# ════════════════════════════════════════════════════════════
```

Toujours ajouter un fichier `agent/__init__.py` vide et un `tests/__init__.py` vide.

#### 3.13 : `tests/test_local.py`

```python
# tests/test_local.py : simulateur de chat dans le terminal
# Généré par AgentKit

"""
Teste ton agent sans avoir besoin de WhatsApp.
Simule une conversation dans le terminal.
"""

import asyncio
import os
import sys

# Ajouter le dossier racine au path pour pouvoir importer "agent"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generer_reponse  # noqa: E402
from agent.memory import (  # noqa: E402
    effacer_historique,
    enregistrer_message,
    initialiser_db,
    obtenir_historique,
)

TELEPHONE_TEST = "test-local-001"


async def main():
    """Boucle principale du chat de test."""
    await initialiser_db()

    print()
    print("=" * 55)
    print("   AgentKit : test local")
    print("=" * 55)
    print()
    print("  Écris des messages comme si tu étais un client.")
    print("  Commandes spéciales :")
    print("    'effacer'  vide l'historique")
    print("    'quitter'  termine le test")
    print()
    print("-" * 55)
    print()

    while True:
        try:
            message = input("Toi : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest terminé.")
            break

        if not message:
            continue

        if message.lower() == "quitter":
            print("\nTest terminé.")
            break

        if message.lower() == "effacer":
            await effacer_historique(TELEPHONE_TEST)
            print("[Historique effacé]\n")
            continue

        # L'historique est lu AVANT l'enregistrement (brain.py ajoute le message en cours)
        historique = await obtenir_historique(TELEPHONE_TEST)

        print("\nAgent : ", end="", flush=True)
        reponse, est_vraie_reponse, demande_humain = await generer_reponse(message, historique)
        print(reponse)
        if demande_humain:
            print("[L'agent passe la main : en production, le responsable serait prévenu]")
        print()

        # Comme en production : les avertissements techniques n'entrent pas dans l'historique
        if est_vraie_reponse:
            await enregistrer_message(TELEPHONE_TEST, "user", message)
            await enregistrer_message(TELEPHONE_TEST, "assistant", reponse)


if __name__ == "__main__":
    asyncio.run(main())
```

#### 3.14 : Fichiers d'infrastructure

**`.env` (généré, ne va JAMAIS sur GitHub) :**

Génère UNIQUEMENT les variables du fournisseur choisi. Celles de l'autre n'y vont pas, même en commentaire.
Les blocs « Passage à un humain » et « Pont n8n » ne sont ajoutés que si l'utilisateur a
répondu oui à la question 11 ou à la question 12.

```env
# AgentKit : variables d'environnement
# Généré par AgentKit, NE PAS envoyer sur GitHub

# ── Anthropic ──────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
# claude-opus-5 | claude-sonnet-5 | claude-haiku-4-5
ANTHROPIC_MODEL=claude-sonnet-5
# Effort de raisonnement : low | medium | high. Vide = le paramètre n'est pas envoyé.
ANTHROPIC_EFFORT=low
# Optionnel, 4096 par défaut. Le raisonnement interne compte dans ce plafond.
# ANTHROPIC_MAX_TOKENS=4096

# ── Fournisseur WhatsApp ───────────────────────────────────
WHATSAPP_PROVIDER=zernio

# ── Si WHATSAPP_PROVIDER=zernio ────────────────────────────
ZERNIO_API_KEY=sk_...
ZERNIO_WEBHOOK_SECRET=invente-un-secret-ici
# Optionnel : ne sert qu'à la vérification de connexion au démarrage
ZERNIO_ACCOUNT_ID=

# ── Si WHATSAPP_PROVIDER=meta ──────────────────────────────
# META_ACCESS_TOKEN=
# META_PHONE_NUMBER_ID=
# META_VERIFY_TOKEN=agentkit-verify
# META_APP_SECRET=
# META_API_VERSION=v25.0

# ── Passage à un humain (si oui à la question 11) ──────────
TELEGRAM_BOT_TOKEN=123456789:AA...
TELEGRAM_CHAT_ID=
# Heures de silence de l'agent après l'alerte. 0 = il continue de répondre.
PAUSE_HUMAIN_HEURES=12

# ── Pont n8n (si oui à la question 12) ─────────────────────
N8N_WEBHOOK_URL=https://ton-n8n/webhook/...
N8N_WEBHOOK_SECRET=invente-un-autre-secret

# ── Serveur ────────────────────────────────────────────────
PORT=8000
ENVIRONMENT=development

# ── Base de données ────────────────────────────────────────
DATABASE_URL=sqlite+aiosqlite:///./agentkit.db
```

**`Dockerfile` :**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Forme shell exprès, pour que ${PORT} soit remplacé au moment de l'exécution.
# Railway attribue le port par variable d'environnement : si on le fixe à 8000,
# le conteneur démarre mais ne reçoit jamais de trafic.
CMD uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

**`docker-compose.yml` :**

```yaml
services:
  agent:
    build: .
    ports:
      - "${PORT:-8000}:8000"
    env_file:
      - .env
    environment:
      PORT: 8000
    volumes:
      - ./knowledge:/app/knowledge
      - ./config:/app/config
    restart: unless-stopped
```

**`.dockerignore` :**

```
.git
.gitignore
.env
*.db
*.sqlite
*.sqlite3
__pycache__/
*.py[cod]
.venv/
venv/
.vscode/
.idea/
.DS_Store
README.md
CLAUDE.md
docs/
scripts/
```

#### 3.15 : Fichiers de `/knowledge`

S'il y a des fichiers dans `/knowledge`, lis-les (txt, pdf, csv, md, json, docx) et extrais-en
le contenu utile pour l'intégrer mot pour mot dans le system prompt de
`config/prompts.yaml`, dans la section « Informations de l'entreprise ».

Ne les résume pas trop : les prix, les horaires et les conditions doivent rester tels quels.
Si un fichier est très gros, donne la priorité à ce qu'un client demanderait sur WhatsApp.

---

### PHASE 4 : Test en local

1. **Lancer le simulateur de chat :**
   ```bash
   python tests/test_local.py
   ```

2. **L'utilisateur écrit comme s'il était un client** et voit les réponses de l'agent.

3. **Vérifier que le serveur démarre** (dans un autre terminal, ou après avoir quitté le test) :
   ```bash
   uvicorn agent.main:app --reload --port 8000
   curl http://localhost:8000/
   ```
   Il doit répondre `{"status":"ok","service":"agentkit","fournisseur":"..."}`.
   S'il répond `{"status":"error"...}`, le champ `detail` dit exactement ce qui manque dans le `.env`.

4. **Si le passage à un humain ou le pont n8n sont configurés, les essayer pour de vrai :**
   ```bash
   python -c "import asyncio; from agent.humain import alerter_responsable; print(asyncio.run(alerter_responsable('33600000000', 'Message de test', 'Réponse de test')))"
   ```
   La commande doit afficher `True`, et l'utilisateur doit recevoir l'alerte sur Telegram
   (ou voir arriver l'événement `demande_humain` dans son workflow n8n). Si elle affiche
   `False`, la raison est écrite juste au-dessus : jeton refusé, identifiant de chat faux,
   webhook n8n inactif.

   Dans le simulateur, l'utilisateur peut aussi écrire « je veux parler à quelqu'un » :
   l'agent doit annoncer qu'une personne reprend, et le simulateur affiche
   `[L'agent passe la main : en production, le responsable serait prévenu]`.

5. **Faire le point avec l'utilisateur :**
   ```
   Ton agent répond-il comme tu l'attendais ? (oui/non)
   ```

   - Si **NON** : demander quoi ajuster, modifier `config/prompts.yaml` et recommencer
   - Si **OUI** : passer à la Phase 5

6. **Afficher le message :**
   ```
   Phase 4 terminée : agent testé et validé

   Ton agent fonctionne correctement en local.
   Veux-tu passer à la mise en production ? (oui/non)
   ```

---

### PHASE 5 : Mise en production sur Railway

À exécuter seulement si l'utilisateur confirme qu'il veut déployer.

1. **Docker est optionnel.** Railway construit l'image à partir du `Dockerfile` sur ses
   serveurs ; l'utilisateur n'a pas besoin de Docker sur sa machine pour déployer.

   Seulement si l'utilisateur veut tester l'image en local avant de l'envoyer :
   ```bash
   docker --version        # s'il ne l'a pas : https://docker.com/get-started
   docker compose up --build
   ```
   S'il n'a pas Docker, ne le bloque pas là-dessus : passe à l'étape suivante.

2. **IMPORTANT : avant d'envoyer sur GitHub, remplacer le `.gitignore`.**

   Le `.gitignore` du modèle AgentKit exclut les fichiers générés (`agent/`, `config/`,
   etc.) pour garder propre le dépôt public d'AgentKit. Mais l'utilisateur a besoin
   d'envoyer CES fichiers pour que Railway puisse les déployer.

   Génère un `.gitignore` de production :

   ```gitignore
   # Secrets : ne JAMAIS les envoyer
   .env

   # Base de données locale
   *.db
   *.sqlite
   *.sqlite3

   # Python
   __pycache__/
   *.py[cod]
   .venv/
   venv/

   # Knowledge (fichiers privés de l'entreprise)
   knowledge/*
   !knowledge/.gitkeep

   # État de la session
   config/session.yaml

   # Système
   .DS_Store
   Thumbs.db

   # Éditeur
   .vscode/
   .idea/
   ```

3. **Instructions pour Railway (à montrer pas à pas) :**

   ```
   === Mise en production sur Railway ===

   Étape 1 : Envoie ton projet sur GitHub

      ATTENTION : tu es dans le clone d'AgentKit, donc il y a déjà un dépôt git ici
      et son "origin" pointe vers le dépôt d'AgentKit, pas vers le tien. N'utilise
      PAS "git init" : il faut seulement changer la destination.

      Crée d'abord un dépôt vide sur github.com/new (sans README, sans .gitignore).
      Ensuite :

      git remote remove origin
      git remote add origin https://github.com/TON-COMPTE/mon-agent.git
      git add .
      git commit -m "feat: mon agent WhatsApp"
      git branch -M main
      git push -u origin main

      Si tu préfères partir d'un historique propre, sans les commits d'AgentKit :
      supprime le dossier .git et repars de zéro avant les commandes ci-dessus :

      rm -rf .git && git init

   Étape 2 : Connecte Railway
      1. Va sur railway.app et crée un compte
      2. Clique sur "New Project"
      3. Choisis "Deploy from GitHub repo"
      4. Connecte ton compte GitHub et choisis le dépôt

   Étape 3 : Variables d'environnement
      Dans Railway → ton projet → Variables, ajoute :
      - ANTHROPIC_API_KEY   = [ta clé]
      - ANTHROPIC_MODEL     = claude-sonnet-5
      - WHATSAPP_PROVIDER   = [zernio | meta]
      - ENVIRONMENT         = production
      - DATABASE_URL        = ${{Postgres.DATABASE_URL}}
      - [Variables du fournisseur choisi, voir plus bas]

      N'ajoute PAS PORT : Railway l'attribue tout seul et le Dockerfile en tient déjà compte.

      Sur DATABASE_URL, deux choses qui ne sont pas évidentes :

      1. Il faut d'abord ajouter la base : dans le projet, "New" -> "Database" ->
         "Add PostgreSQL". Ça crée un service à part.
      2. Railway ne copie PAS tout seul l'URL dans le service de ton agent. Dans les
         Variables de TON service, il faut écrire, à la lettre, avec les doubles accolades :

            DATABASE_URL = ${{Postgres.DATABASE_URL}}

         (Si tu as donné un autre nom au service de la base, utilise ce nom à la place
         de "Postgres".)

      SI TU SAUTES ÇA, l'agent démarre quand même : il se rabat sur SQLite dans le
      conteneur. Mais le disque du conteneur est éphémère, donc À CHAQUE redéploiement
      de Railway (chaque push, chaque changement de variable) l'historique de toutes
      les conversations est effacé et l'agent ne se souvient plus de ses clients.

      Si ZERNIO : ZERNIO_API_KEY, ZERNIO_WEBHOOK_SECRET, ZERNIO_ACCOUNT_ID (optionnel)
      Si META :   META_ACCESS_TOKEN, META_PHONE_NUMBER_ID, META_VERIFY_TOKEN, META_APP_SECRET

      Si tu as activé le passage à un humain :
                  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAUSE_HUMAIN_HEURES
      Si tu as activé le pont n8n :
                  N8N_WEBHOOK_URL, N8N_WEBHOOK_SECRET

   Étape 4 : Génère l'URL publique

      Railway ne donne PAS tout seul un domaine public à ton service. Il faut le demander :
      ton service -> Settings -> Networking -> "Generate Domain".
      Tu obtiens quelque chose comme ton-app.up.railway.app. C'est l'URL à utiliser plus bas.

      Vérifie qu'elle répond avant de continuer :
         curl https://ton-app.up.railway.app/
      Elle doit répondre {"status":"ok",...}. Si elle répond {"status":"error",...},
      le champ "detail" dit quelle variable manque.

   Étape 5 : Configure le webhook

      Si ZERNIO :
         1. Va sur zernio.com → dashboard → Webhooks → Create webhook
         2. URL : https://ton-app.up.railway.app/webhook
         3. Secret : la même valeur que dans ZERNIO_WEBHOOK_SECRET
         4. Événements : coche "message.received" → Enregistrer
         5. Utilise le bouton "Send test" pour confirmer que ton serveur répond 200

         On peut aussi le faire par API :
            curl -X POST https://zernio.com/api/v1/webhooks/settings \
              -H "Authorization: Bearer $ZERNIO_API_KEY" \
              -H "Content-Type: application/json" \
              -d '{"name":"agentkit",
                   "url":"https://ton-app.up.railway.app/webhook",
                   "secret":"ton-webhook-secret",
                   "events":["message.received"]}'

      Si META :
         1. Va sur developers.facebook.com → ton application → WhatsApp → Configuration
         2. Callback URL : https://ton-app.up.railway.app/webhook
         3. Verify Token : le même que META_VERIFY_TOKEN
         4. Abonne-toi au champ "messages" → Enregistrer

   C'est bon ! Ton agent est en production.
   ```

4. **Expliquer à l'utilisateur la règle des 24 heures :**

   ```
   Un détail de WhatsApp qu'il vaut mieux connaître :

   Ton agent répond à ceux qui lui écrivent, donc il est toujours dans la fenêtre
   de 24 heures que Meta autorise pour les messages en texte libre. Tu n'as rien à faire.

   Si un jour tu veux que l'agent écrive EN PREMIER (rappels, promotions),
   il te faudra des modèles de message approuvés par Meta. Préviens-moi ce jour-là
   et on le met en place ensemble.
   ```

5. **Lui parler des données de ses clients :**

   ```
   Un dernier point, si tes clients sont en Europe :

   Ton agent garde le numéro de téléphone et les messages de chaque client pour se
   souvenir de la conversation. Ce sont des données personnelles, donc le RGPD s'applique.
   Au minimum, prévois :
   - de dire à tes clients qu'ils parlent à un assistant automatique et que leurs messages sont conservés
   - d'effacer l'historique d'un client qui le demande (la fonction effacer_historique() de memory.py fait exactement ça)
   - de ne pas garder les conversations plus longtemps que nécessaire
   - si tu as activé le pont n8n ou les alertes Telegram, de te souvenir que les messages
     de tes clients partent aussi vers ces services

   Je ne suis pas juriste : pour les mentions à afficher et la durée de conservation,
   regarde le site de la CNIL (cnil.fr) ou demande à ton conseil habituel.
   ```

6. **Récapitulatif final :**
   ```
   ===========================================================
      AgentKit : récapitulatif
   ===========================================================

   Ton agent "[NOM_AGENT]" pour [NOM_ENTREPRISE] est prêt.

   Ce qui a été construit :
   - Serveur FastAPI avec webhook WhatsApp (signature vérifiée)
   - Cerveau avec Claude ([MODÈLE])
   - Mémoire des conversations par client
   - Déduplication des événements : il ne répond jamais deux fois la même chose
   - Passage à un humain : [ACTIF, alerte par Telegram / n8n, pause de N heures | NON CONFIGURÉ]
   - Pont n8n : [ACTIF, chaque échange part vers ton workflow | NON CONFIGURÉ]
   - Outils de base dans tools.py : [CEUX QUE TU AS VRAIMENT ÉCRITS]
   - System prompt personnalisé pour ton entreprise
   - Docker Compose pour la production

   Fichiers générés :
   - agent/main.py, brain.py, memory.py, n8n.py, humain.py, tools.py, providers/
   - config/business.yaml, prompts.yaml
   - tests/test_local.py
   - Dockerfile, docker-compose.yml, .dockerignore, .env

   Commandes utiles :
   - Test local :    python tests/test_local.py
   - Démarrer :      uvicorn agent.main:app --reload --port 8000
   - Docker :        docker compose up --build

   Besoin d'ajuster quelque chose ? Écris-moi quand tu veux.
   ===========================================================
   ```

---

## 6. Règles de comportement pour Claude Code

1. **Parle TOUJOURS en français** : les messages, les commentaires dans le code, les noms de variables (sans accents dans les noms)
2. **UNE question à la fois** : ne bombarde jamais l'utilisateur de plusieurs questions
3. **N'écris JAMAIS une clé API en dur** : toujours des variables d'environnement via python-dotenv
4. **N'avance JAMAIS de phase** sans confirmation de l'utilisateur
5. **Si quelque chose échoue** : diagnostique, montre l'erreur clairement, propose une solution
6. **Génère du code commenté** en français pour que l'utilisateur comprenne chaque partie
7. **L'agent DOIT fonctionner** en test local avant de parler de mise en production
8. **Si l'utilisateur veut faire une pause** : enregistrer l'état dans `config/session.yaml` avec les réponses
9. **Demande avant d'écraser** des fichiers existants dans `/config` ou le `.env`
10. **Reste simple** : n'ajoute pas de fonctions que l'utilisateur n'a pas demandées
11. **Valide à chaque phase** avant de passer à la suivante
12. **Génère UNIQUEMENT l'adaptateur du fournisseur choisi**, pas les deux
13. **Ne change pas le modèle de Claude de ton propre chef** pour économiser : c'est la décision de l'utilisateur
14. **Génère `n8n.py` et `humain.py` tels quels, toujours** : ce sont leurs variables dans le `.env` qui les activent, pas le code
15. **Ne recopie jamais un secret dans un message, un commentaire ou un journal** : jeton Telegram, adresse du webhook n8n, clés API

---

## 7. Commandes de référence

```bash
# Démarrer l'agent en local
uvicorn agent.main:app --reload --port 8000

# Tester sans WhatsApp
python tests/test_local.py

# Construire avec Docker
docker compose up --build

# Voir les journaux
docker compose logs -f agent

# Installer les dépendances
pip install -r requirements.txt

# Auditer le dépôt AgentKit (pas l'agent généré)
python3 scripts/audit.py
```

---

## 8. Variables d'environnement

```env
# ── Anthropic ─────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-5     # claude-opus-5 | claude-sonnet-5 | claude-haiku-4-5
ANTHROPIC_EFFORT=low                # low | medium | high : vide pour ne pas l'envoyer
# ANTHROPIC_MAX_TOKENS=4096         # optionnel, 4096 par défaut

# ── Fournisseur WhatsApp (zernio | meta) ──────────────────
WHATSAPP_PROVIDER=

# ── Zernio (si WHATSAPP_PROVIDER=zernio) ──────────────────
ZERNIO_API_KEY=
ZERNIO_WEBHOOK_SECRET=
ZERNIO_ACCOUNT_ID=                  # optionnel, seulement pour la vérification au démarrage
ZERNIO_BASE_URL=                    # optionnel, par défaut https://zernio.com/api/v1

# ── Meta Cloud API (si WHATSAPP_PROVIDER=meta) ────────────
META_ACCESS_TOKEN=
META_PHONE_NUMBER_ID=
META_VERIFY_TOKEN=agentkit-verify
META_APP_SECRET=
META_API_VERSION=v25.0

# ── Passage à un humain (optionnel) ───────────────────────
TELEGRAM_BOT_TOKEN=                 # jeton donné par @BotFather
TELEGRAM_CHAT_ID=                   # à qui envoyer l'alerte
PAUSE_HUMAIN_HEURES=12              # silence de l'agent après l'alerte ; 0 = il continue

# ── Pont n8n (optionnel) ──────────────────────────────────
N8N_WEBHOOK_URL=                    # « Production URL » du nœud Webhook
N8N_WEBHOOK_SECRET=                 # envoyé dans l'en-tête X-AgentKit-Secret

# ── Serveur ───────────────────────────────────────────────
PORT=8000
ENVIRONMENT=development             # development | production

# ── Base de données ───────────────────────────────────────
DATABASE_URL=sqlite+aiosqlite:///./agentkit.db   # local
# DATABASE_URL=postgresql+asyncpg://...          # production Railway
```
