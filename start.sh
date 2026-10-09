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

# ── Vérifier Claude Code ─────────────────────────────────────
echo "  [2/4] Vérification de Claude Code..."
if ! command -v claude &> /dev/null; then
    echo ""
    echo "  Claude Code n'est pas installé."
    echo ""
    echo "  Pour l'installer :"
    echo "    npm install -g @anthropic-ai/claude-code"
    echo ""
    echo "  Si tu n'as pas npm/Node.js :"
    echo "    https://nodejs.org (télécharge la version LTS)"
    echo ""
    echo "  Après l'installation, lance 'claude' une fois pour te connecter,"
    echo "  puis relance : bash start.sh"
    echo ""
    exit 1
fi
echo "  OK : Claude Code est installé"

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
echo "  Tout est prêt. Ouvre maintenant Claude Code :"
echo ""
echo "    claude"
echo ""
echo "  Et écris :"
echo ""
echo "    /creer-agent"
echo ""
echo "  Claude Code te guide pas à pas pour construire"
echo "  ton agent WhatsApp personnalisé avec IA."
echo ""
echo "  Il te faudra :"
echo "    - Une clé API Anthropic  (platform.anthropic.com)"
echo "    - Un compte Zernio       (zernio.com, offre gratuite, sans carte bancaire)"
echo "      ou des identifiants Meta Cloud API si tu préfères te connecter toi-même"
echo ""
echo "==========================================================="
echo ""
