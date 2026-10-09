#!/bin/bash
# AgentKit : script de démarrage
# L'utilisateur lance : bash start.sh

set -e

echo ""
echo "==========================================================="
echo "   AgentKit : ton agent WhatsApp avec IA"
echo "==========================================================="
echo ""
echo "  Je prépare ton environnement pour construire ton agent..."
echo ""

# ── Vérifier Python ───────────────────────────────────────────
echo "  [1/4] Vérification de Python..."
if ! command -v python3 &> /dev/null; then
    echo ""
    echo "  ERREUR : Python 3 est introuvable."
    echo "  Télécharge-le ici : https://python.org/downloads"
    echo ""
    exit 1
fi

PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo ""
    echo "  ERREUR : il te faut Python 3.11 ou plus récent."
    echo "  Version actuelle : $(python3 --version)"
    echo "  Télécharge la dernière version ici : https://python.org/downloads"
    echo ""
    exit 1
fi
echo "  OK : $(python3 --version)"

# ── Chercher un assistant de code ────────────────────────────
echo "  [2/4] Recherche d'un assistant de code..."
ASSISTANT=""
if command -v claude &> /dev/null; then
    ASSISTANT="claude"
elif command -v codex &> /dev/null; then
    ASSISTANT="codex"
elif command -v copilot &> /dev/null; then
    ASSISTANT="copilot"
fi
if [ -n "$ASSISTANT" ]; then
    echo "  OK : $ASSISTANT est installé"
else
    echo "  Aucun assistant trouvé en ligne de commande (claude, codex, copilot)."
    echo "  Ce n'est pas bloquant si tu utilises un assistant dans ton éditeur."
    echo "  Sinon, pour installer Claude Code :"
    echo "    npm install -g @anthropic-ai/claude-code   (Node.js : https://nodejs.org)"
fi

# ── Créer les dossiers de base ───────────────────────────────
echo "  [3/4] Préparation des dossiers..."
mkdir -p knowledge
echo "  OK : structure prête"

# ── Préparer le .env ─────────────────────────────────────────
echo "  [4/4] Préparation des variables d'environnement..."
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "  OK : .env créé à partir de .env.example (encore vide, on le remplit pendant la configuration)"
else
    echo "  OK : le .env existe déjà, on n'y touche pas"
fi

echo ""
echo "==========================================================="
echo ""
echo "  Tout est prêt. Ouvre maintenant ton assistant de code dans ce dossier."
echo ""
echo "  Avec Claude Code :"
echo ""
echo "    claude"
echo "    /creer-agent"
echo ""
echo "  Avec un autre assistant (Codex, GitHub Copilot...), écris-lui :"
echo ""
echo "    crée mon agent"
echo ""
echo "  Il te guide pas à pas pour construire"
echo "  ton agent WhatsApp personnalisé avec IA."
echo ""
echo "  Il te faudra :"
echo "    - Une clé API Anthropic  (platform.anthropic.com)"
echo "    - Un compte Zernio       (zernio.com, offre gratuite, sans carte bancaire)"
echo "      ou des identifiants Meta Cloud API si tu préfères te connecter toi-même"
echo ""
echo "==========================================================="
echo ""
