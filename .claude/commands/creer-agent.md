Lis le fichier CLAUDE.md en entier. Il contient toutes les instructions détaillées.

Déroule la mise en route d'AgentKit en suivant les 5 phases DANS L'ORDRE :

PHASE 1 : Accueil et vérification de l'environnement
- Affiche le message d'accueil
- Vérifie Python >= 3.11
- Crée les dossiers nécessaires (agent/, agent/providers/, config/, knowledge/, tests/)
- Génère requirements.txt et installe les dépendances
- Crée le .env de base

PHASE 2 : Entretien sur l'entreprise
- Pose les 12 questions UNE PAR UNE
- Attends la réponse avant de passer à la suivante
- QUESTION 9 : l'utilisateur choisit son fournisseur WhatsApp (Zernio ou Meta Cloud API en direct)
- QUESTION 10 : demande les identifiants propres au fournisseur choisi
  - Zernio : ZERNIO_API_KEY + ZERNIO_WEBHOOK_SECRET
  - Meta :   META_ACCESS_TOKEN + META_PHONE_NUMBER_ID + META_VERIFY_TOKEN + META_APP_SECRET
- S'il n'a pas encore de numéro WhatsApp, propose-lui le bac à sable de Zernio
- QUESTION 11 : veut-il être prévenu quand l'agent passe la main ? (bot Telegram : TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
- QUESTION 12 : utilise-t-il n8n ? (N8N_WEBHOOK_URL + N8N_WEBHOOK_SECRET)
- Garde toutes les réponses pour la Phase 3

PHASE 3 : Génération de l'agent
- Génère config/business.yaml avec les données de l'entreprise
- Génère config/prompts.yaml avec un system prompt puissant et précis
- S'il y a des fichiers dans /knowledge, lis-les et intègre-les au prompt
- Génère agent/providers/ avec le fournisseur choisi (base.py + __init__.py + adaptateur)
- Génère agent/main.py (FastAPI + webhook, signature vérifiée, BackgroundTasks, déduplication)
- Génère agent/brain.py (API Claude)
- Génère agent/memory.py (historique + événements traités + conversations en pause)
- Génère agent/n8n.py (pont vers n8n) et agent/humain.py (passage à un humain), toujours, tels quels
- Génère agent/tools.py (outils selon le cas d'usage)
- Génère tests/test_local.py (simulateur de chat)
- Génère Dockerfile, docker-compose.yml et .dockerignore
- Configure le .env avec WHATSAPP_PROVIDER et les clés API de l'utilisateur

PHASE 4 : Test en local
- Lance python tests/test_local.py
- L'utilisateur discute avec son agent dans le terminal
- Vérifie que le serveur démarre et que GET / répond status ok
- Si le passage à un humain ou le pont n8n sont configurés, envoie une alerte de test
- S'il y a des ajustements, modifie prompts.yaml et recommence
- On n'avance pas sans l'accord de l'utilisateur

PHASE 5 : Mise en production sur Railway
- Seulement si l'utilisateur le veut
- Construction Docker + instructions Railway
- Configuration du webhook propre au fournisseur choisi
- Lui expliquer la fenêtre de 24 heures de WhatsApp
- Lui parler des données personnelles de ses clients (RGPD)

RÈGLES :
- Parle toujours en français, en tutoyant
- Une question à la fois
- N'écris jamais une clé API en dur
- N'avance pas de phase sans confirmation
- L'agent doit fonctionner avant de parler de mise en production
- Génère UNIQUEMENT l'adaptateur du fournisseur choisi, pas les deux
- Ne recopie jamais un secret dans un message ou un journal (jeton Telegram, adresse du webhook n8n, clés)
- Ne change pas le modèle de Claude de ton propre chef pour économiser : c'est la décision de l'utilisateur
