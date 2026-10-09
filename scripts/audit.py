#!/usr/bin/env python3
"""
audit.py : audit du dépôt-modèle whatsapp-agentkit-fr.

Ce dépôt ne contient pas l'agent : il contient les INSTRUCTIONS (CLAUDE.md) avec
lesquelles Claude Code génère l'agent pour l'entreprise de l'utilisateur. Le code
à auditer vit donc dans des blocs markdown, et une erreur de syntaxe à cet endroit
n'est vue par personne tant qu'un vrai utilisateur n'en fait pas les frais.

Ce script lance 6 contrôles :

  1. Les blocs ```python de CLAUDE.md compilent
  2. Les blocs ```yaml de CLAUDE.md se lisent
  3. Il ne reste aucune trace des fournisseurs retirés (twilio, whapi)
  4. Toute variable d'environnement utilisée dans CLAUDE.md est dans .env.example
  5. Les liens du README répondent
  6. Les images citées dans le README existent et ont la taille annoncée

Utilisation :
    python3 scripts/audit.py
    python3 scripts/audit.py --skip-links
    python3 scripts/audit.py --repo /chemin/vers/le/depot

Dépendances : bibliothèque standard + pyyaml (déjà une dépendance du projet).
Code de sortie : 0 si tout passe, 1 si un contrôle a des erreurs.
"""

from __future__ import annotations

import argparse
import codecs
import os
import re
import struct
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERREUR : il manque pyyaml. Installe-le avec :  pip install pyyaml")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════

# Termes qui ne doivent apparaître dans AUCUN fichier du dépôt (contrôle 3).
# Classés du plus long au plus court pour signaler la correspondance la plus précise.
TERMES_INTERDITS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "twilio",
    "whapi",
]

# Dossiers qu'on ne parcourt jamais.
DOSSIERS_IGNORES = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", ".idea", ".vscode",
}

# Chemins relatifs au dépôt, exclus de la recherche du contrôle 3.
CHEMINS_IGNORES = {
    "docs/assets",   # binaires d'image
    ".env",          # secrets locaux de l'utilisateur, ne part pas sur GitHub
}

# Variables d'environnement du système, pas du projet (contrôle 4).
ENV_DU_SYSTEME = {"PATH", "HOME", "USER", "PWD", "LANG"}

# Plusieurs sites refusent le User-Agent par défaut de urllib (contrôle 5).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT_HTTP = 10

# Largeur minimale recommandée pour une image du README.
LARGEUR_MINIMALE_PNG = 600

# Nombre d'occurrences listées par fichier avant de résumer.
MAX_OCCURRENCES_PAR_FICHIER = 6


# ══════════════════════════════════════════════════════════════════════════
# Résultat d'un contrôle
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Resultat:
    """Ce que renvoie chaque contrôle : les erreurs font échouer (exit 1), pas les avertissements."""

    numero: int
    titre: str
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ignore: bool = False

    @property
    def reussi(self) -> bool:
        return not self.erreurs

    def erreur(self, message: str, que_faire: str = "") -> None:
        if que_faire:
            message = f"{message}\n           -> {que_faire}"
        self.erreurs.append(message)

    def avertir(self, message: str, que_faire: str = "") -> None:
        if que_faire:
            message = f"{message}\n           -> {que_faire}"
        self.avertissements.append(message)


# ══════════════════════════════════════════════════════════════════════════
# Utilitaires de fichiers
# ══════════════════════════════════════════════════════════════════════════

def lire_texte(chemin: Path) -> str:
    """Lit un fichier texte en UTF-8. Lève FileNotFoundError s'il n'existe pas."""
    return chemin.read_text(encoding="utf-8")


def est_binaire(chemin: Path) -> bool:
    """
    Heuristique : si le premier bloc contient un octet nul ou n'est pas de l'UTF-8, c'est un binaire.

    On utilise exprès un décodeur incrémental : lire 4096 octets peut couper un
    caractère multi-octets en deux (les traits ── de ce dépôt occupent 3 octets),
    et un decode() ordinaire le prendrait pour un binaire, en sautant le fichier
    au contrôle 3 sans rien dire.
    """
    try:
        with chemin.open("rb") as f:
            morceau = f.read(4096)
        if b"\x00" in morceau:
            return True
        codecs.getincrementaldecoder("utf-8")().decode(morceau, final=False)
        return False
    except (UnicodeDecodeError, OSError):
        return True


def parcourir_fichiers_texte(racine: Path, exclure: set[Path]) -> list[Path]:
    """
    Renvoie tous les fichiers texte du dépôt, en sautant les dossiers ignorés,
    les binaires et les chemins de `exclure` (chemins ABSOLUS déjà résolus).
    """
    trouves: list[Path] = []
    for dossier, sous_dossiers, fichiers in os.walk(racine):
        sous_dossiers[:] = [d for d in sous_dossiers if d not in DOSSIERS_IGNORES]
        dossier_path = Path(dossier)
        for nom in fichiers:
            chemin = dossier_path / nom
            try:
                absolu = chemin.resolve()
            except OSError:
                continue
            # Comparaison par chemin absolu : jamais par un bout du nom, pour que
            # ce script ne se signale pas lui-même et n'en exclue pas d'autres.
            if absolu in exclure:
                continue
            if any(absolu == e or e in absolu.parents for e in exclure):
                continue
            if est_binaire(chemin):
                continue
            trouves.append(chemin)
    return sorted(trouves)


def relatif(chemin: Path, racine: Path) -> str:
    """Chemin lisible, relatif au dépôt (ou absolu s'il est en dehors)."""
    try:
        return str(chemin.resolve().relative_to(racine))
    except ValueError:
        return str(chemin)


# ══════════════════════════════════════════════════════════════════════════
# Extraction des blocs de code d'un markdown
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class BlocCode:
    langage: str
    code: str
    ligne_ouverture: int   # ligne (à partir de 1) où se trouve le ``` d'ouverture
    ligne_debut: int       # ligne (à partir de 1) de la première ligne de code


OUVRE_BLOC = re.compile(r"^(?P<indent>\s*)```(?P<lang>[A-Za-z0-9_+-]*)\s*$")
FERME_BLOC = re.compile(r"^\s*```\s*$")


def extraire_blocs(markdown: str, langage: str) -> list[BlocCode]:
    """
    Extrait les blocs ```<langage> d'un markdown, en gardant le numéro de
    ligne RÉEL dans le fichier (pas la ligne relative au bloc).

    Gère les blocs indentés (ceux qui sont dans une liste numérotée) et leur
    retire l'indentation commune pour que le contenu compile pareil.
    """
    blocs: list[BlocCode] = []
    lignes = markdown.splitlines()

    dedans = False
    lang_courant = ""
    indent_courant = 0
    ligne_ouverture = 0
    tampon: list[str] = []

    for i, ligne in enumerate(lignes, start=1):
        if not dedans:
            m = OUVRE_BLOC.match(ligne)
            if m:
                dedans = True
                lang_courant = m.group("lang").lower()
                indent_courant = len(m.group("indent"))
                ligne_ouverture = i
                tampon = []
            continue

        # On est dans un bloc : on cherche la fermeture.
        if FERME_BLOC.match(ligne):
            if lang_courant == langage.lower():
                # On retire l'indentation du bloc à chaque ligne du corps.
                corps = [
                    l[indent_courant:] if l[:indent_courant].strip() == "" else l
                    for l in tampon
                ]
                blocs.append(BlocCode(
                    langage=lang_courant,
                    code="\n".join(corps),
                    ligne_ouverture=ligne_ouverture,
                    ligne_debut=ligne_ouverture + 1,
                ))
            dedans = False
            lang_courant = ""
            tampon = []
            continue

        tampon.append(ligne)

    return blocs


def ressemble_a_un_extrait(code: str) -> bool:
    """
    True si le bloc est visiblement une illustration et pas du code complet :
    il a un '...' seul sur une ligne ou un commentaire du genre '# ...'.
    """
    for ligne in code.splitlines():
        nettoyee = ligne.strip()
        if nettoyee == "..." or nettoyee == "# ...":
            return True
        if nettoyee.startswith("# ...") or nettoyee.endswith("..."):
            if nettoyee.startswith("#") or nettoyee == "...":
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 1 : les blocs Python de CLAUDE.md compilent
# ══════════════════════════════════════════════════════════════════════════

def controle_1_python(racine: Path) -> Resultat:
    r = Resultat(1, "Les blocs Python de CLAUDE.md compilent")
    chemin = racine / "CLAUDE.md"

    try:
        contenu = lire_texte(chemin)
    except FileNotFoundError:
        r.erreur("le fichier CLAUDE.md est absent",
                 "CLAUDE.md est le cerveau du dépôt-modèle : sans lui, "
                 "'/creer-agent' n'a aucune instruction à suivre.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire CLAUDE.md : {e}")
        return r

    blocs = extraire_blocs(contenu, "python")
    if not blocs:
        r.avertir("aucun bloc ```python trouvé dans CLAUDE.md",
                  "Vérifie que les modèles de code sont bien marqués "
                  "```python et pas ``` tout court.")
        return r

    echoues = 0
    for b in blocs:
        nom = f"CLAUDE.md:bloc@{b.ligne_ouverture}"
        try:
            compile(b.code, nom, "exec")
        except SyntaxError as e:
            # e.lineno est relatif au bloc -> on le convertit en ligne réelle.
            ligne_reelle = b.ligne_debut + (e.lineno - 1 if e.lineno else 0)
            detail = f"{type(e).__name__}: {e.msg}"
            emplacement = (f"CLAUDE.md:{b.ligne_ouverture} (bloc ```python), "
                           f"erreur dans CLAUDE.md:{ligne_reelle}")
            if ressemble_a_un_extrait(b.code):
                r.avertir(
                    f"{emplacement} : {detail}",
                    "On dirait un extrait d'illustration (il contient '...'), pas "
                    "du code complet. Si c'est voulu, ignore-le.",
                )
            else:
                echoues += 1
                r.erreur(
                    f"{emplacement} : {detail}",
                    f"Ouvre CLAUDE.md à la ligne {ligne_reelle} et corrige la "
                    f"syntaxe. Claude Code recopie ce bloc tel quel.",
                )
        except ValueError as e:
            echoues += 1
            r.erreur(f"CLAUDE.md:{b.ligne_ouverture} : le bloc n'a pas pu être "
                     f"compilé : {e}",
                     "C'est souvent un caractère invalide dans le bloc.")

    r.notes.append(
        f"{len(blocs) - echoues}/{len(blocs)} blocs ```python compilent"
    )
    return r


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 2 : les blocs YAML de CLAUDE.md se lisent
# ══════════════════════════════════════════════════════════════════════════

def controle_2_yaml(racine: Path) -> Resultat:
    r = Resultat(2, "Les blocs YAML de CLAUDE.md se lisent")
    chemin = racine / "CLAUDE.md"

    try:
        contenu = lire_texte(chemin)
    except FileNotFoundError:
        r.erreur("le fichier CLAUDE.md est absent",
                 "Sans CLAUDE.md, il n'y a aucun modèle à auditer.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire CLAUDE.md : {e}")
        return r

    blocs = extraire_blocs(contenu, "yaml")
    if not blocs:
        r.avertir("aucun bloc ```yaml trouvé dans CLAUDE.md",
                  "business.yaml et prompts.yaml devraient être en ```yaml.")
        return r

    echoues = 0
    for b in blocs:
        try:
            # Les repères du type [NOM DE L'ENTREPRISE] sont du YAML valide
            # (une liste ou une chaîne). Ça n'échoue que si safe_load lève.
            yaml.safe_load(b.code)
        except yaml.YAMLError as e:
            echoues += 1
            ligne_reelle = b.ligne_ouverture
            marque = getattr(e, "problem_mark", None)
            if marque is not None:
                ligne_reelle = b.ligne_debut + marque.line
            probleme = getattr(e, "problem", None) or str(e).splitlines()[0]
            r.erreur(
                f"CLAUDE.md:{b.ligne_ouverture} (bloc ```yaml), erreur dans "
                f"CLAUDE.md:{ligne_reelle} : {probleme}",
                f"Corrige le YAML à la ligne {ligne_reelle}. Attention à "
                f"l'indentation et aux deux-points sans guillemets.",
            )

    r.notes.append(
        f"{len(blocs) - echoues}/{len(blocs)} blocs ```yaml se lisent"
    )
    return r


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 3 : aucune trace des fournisseurs retirés
# ══════════════════════════════════════════════════════════════════════════

def controle_3_fournisseurs(racine: Path, ce_script: Path) -> Resultat:
    r = Resultat(3, "Aucune trace des fournisseurs retirés (twilio, whapi)")

    motif = re.compile("|".join(re.escape(t) for t in TERMES_INTERDITS),
                       re.IGNORECASE)

    # Ce script cite lui-même les termes qu'il cherche : on l'exclut en comparant
    # des chemins absolus résolus, jamais par un bout du nom de fichier.
    exclure = {ce_script.resolve()}
    for rel in CHEMINS_IGNORES:
        exclure.add((racine / rel).resolve())

    try:
        fichiers = parcourir_fichiers_texte(racine, exclure)
    except OSError as e:
        r.erreur(f"impossible de parcourir le dépôt : {e}")
        return r

    total_occurrences = 0
    fichiers_touches = 0

    for chemin in fichiers:
        try:
            contenu = lire_texte(chemin)
        except (OSError, UnicodeDecodeError):
            continue

        occurrences: list[tuple[int, str, str]] = []
        for numero, ligne in enumerate(contenu.splitlines(), start=1):
            m = motif.search(ligne)
            if m:
                texte = ligne.strip()
                if len(texte) > 110:
                    texte = texte[:107] + "..."
                occurrences.append((numero, m.group(0), texte))

        if not occurrences:
            continue

        fichiers_touches += 1
        total_occurrences += len(occurrences)
        nom = relatif(chemin, racine)

        for numero, terme, texte in occurrences[:MAX_OCCURRENCES_PAR_FICHIER]:
            r.erreur(f"{nom}:{numero} : contient '{terme}'  |  {texte}")

        restantes = len(occurrences) - MAX_OCCURRENCES_PAR_FICHIER
        if restantes > 0:
            r.erreur(f"{nom} : et {restantes} occurrence(s) de plus dans le "
                     f"même fichier")

    if total_occurrences:
        r.erreurs.append(
            f"TOTAL : {total_occurrences} occurrence(s) dans {fichiers_touches} "
            f"fichier(s).\n           -> Réécris ces fichiers en ne gardant que "
            f"les fournisseurs en vigueur : zernio (recommandé) et meta "
            f"(Cloud API en direct)."
        )
    else:
        r.notes.append(
            f"{len(fichiers)} fichiers texte vérifiés, aucune trace de "
            f"fournisseur retiré"
        )

    return r


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 4 : variables d'environnement complètes
# ══════════════════════════════════════════════════════════════════════════

# os.getenv("X")  /  os.environ.get("X")  /  os.environ["X"]
USAGE_ENV = re.compile(
    r"""os\.getenv\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
    r"""|os\.environ\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*\]"""
)

# X=  ou  # X=   dans .env.example
DECLARE_ENV = re.compile(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def controle_4_env(racine: Path) -> Resultat:
    r = Resultat(4, "Variables d'environnement complètes dans .env.example")
    chemin_md = racine / "CLAUDE.md"
    chemin_env = racine / ".env.example"

    try:
        contenu_md = lire_texte(chemin_md)
    except FileNotFoundError:
        r.erreur("le fichier CLAUDE.md est absent",
                 "Sans CLAUDE.md, impossible de savoir quelles variables l'agent utilise.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire CLAUDE.md : {e}")
        return r

    try:
        contenu_env = lire_texte(chemin_env)
    except FileNotFoundError:
        r.erreur("le fichier .env.example est absent",
                 "Crée-le à la racine du dépôt : c'est le modèle que l'utilisateur "
                 "copie en .env pendant la configuration.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire .env.example : {e}")
        return r

    # Variables utilisées dans CLAUDE.md, avec la ligne de la première apparition.
    utilisees: dict[str, int] = {}
    for numero, ligne in enumerate(contenu_md.splitlines(), start=1):
        for m in USAGE_ENV.finditer(ligne):
            nom = m.group(1) or m.group(2) or m.group(3)
            if nom in ENV_DU_SYSTEME:
                continue
            utilisees.setdefault(nom, numero)

    # Variables déclarées dans .env.example (en commentaire ou non).
    declarees: dict[str, int] = {}
    for numero, ligne in enumerate(contenu_env.splitlines(), start=1):
        m = DECLARE_ENV.match(ligne)
        if m:
            declarees.setdefault(m.group(1), numero)

    if not utilisees:
        r.avertir("aucune variable d'environnement détectée dans CLAUDE.md",
                  "Vérifie que les modèles utilisent os.getenv(\"...\").")

    manquantes = [v for v in utilisees if v not in declarees]
    for nom in sorted(manquantes):
        r.erreur(
            f"{nom} : utilisée dans CLAUDE.md:{utilisees[nom]} mais absente de "
            f".env.example",
            f"Ajoute une ligne '{nom}=' (ou '# {nom}=' si elle est optionnelle) "
            f"dans .env.example.",
        )

    inutilisees = [v for v in declarees if v not in utilisees]
    for nom in sorted(inutilisees):
        r.avertir(
            f"{nom} : déclarée dans .env.example:{declarees[nom]} mais "
            f"personne ne l'utilise dans CLAUDE.md",
            "C'est peut-être un reste d'une ancienne version. Si elle ne sert plus, "
            "retire-la de .env.example.",
        )

    r.notes.append(
        f"{len(utilisees)} variable(s) utilisée(s) dans CLAUDE.md, "
        f"{len(declarees)} déclarée(s) dans .env.example, "
        f"{len(manquantes)} non déclarée(s)"
    )
    return r


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 5 : les liens du README répondent
# ══════════════════════════════════════════════════════════════════════════

COMMENTAIRE_HTML = re.compile(r"<!--.*?-->", re.DOTALL)
LIEN_MARKDOWN = re.compile(r"\[[^\]]*\]\(\s*(<?https?://[^)\s]+>?)")
URL_NUE = re.compile(r"https?://[^\s)>\]\"'`]+")


def nettoyer_url(url: str) -> str:
    """Retire les chevrons du markdown et la ponctuation collée à la fin."""
    url = url.strip().strip("<>")
    while url and url[-1] in ".,;:!?)]}\"'":
        url = url[:-1]
    return url


def extraire_urls(markdown: str) -> list[str]:
    """URL http(s) du README, sans les commentaires HTML, dédupliquées dans l'ordre."""
    sans_commentaires = COMMENTAIRE_HTML.sub("", markdown)
    vues: dict[str, None] = {}
    for m in LIEN_MARKDOWN.finditer(sans_commentaires):
        vues.setdefault(nettoyer_url(m.group(1)), None)
    for m in URL_NUE.finditer(sans_commentaires):
        vues.setdefault(nettoyer_url(m.group(0)), None)
    return [u for u in vues if u]


def demander(url: str, methode: str) -> int:
    """Fait la requête et renvoie le code HTTP. Laisse remonter les erreurs réseau."""
    req = urllib.request.Request(url, method=methode)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "*/*")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_HTTP) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def controle_5_liens(racine: Path, sauter: bool) -> Resultat:
    r = Resultat(5, "Les liens du README répondent")

    if sauter:
        r.ignore = True
        r.notes.append("ignoré avec --skip-links (aucun accès au réseau)")
        return r

    chemin = racine / "README.md"
    try:
        contenu = lire_texte(chemin)
    except FileNotFoundError:
        r.erreur("le fichier README.md est absent",
                 "C'est la vitrine du dépôt sur GitHub : crée-le à la racine.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire README.md : {e}")
        return r

    urls = extraire_urls(contenu)
    if not urls:
        r.notes.append("le README n'a aucun lien http(s)")
        return r

    ok = 0
    for url in urls:
        try:
            code = demander(url, "HEAD")
            # Plusieurs serveurs n'implémentent pas HEAD : on réessaie avec GET.
            if code in (403, 405, 501):
                code = demander(url, "GET")
        except (urllib.error.URLError, OSError, ValueError) as e:
            # Délai dépassé, DNS, TLS : ça peut venir du réseau de celui qui lance le script.
            raison = getattr(e, "reason", e)
            r.avertir(f"{url} : vérification impossible ({raison})",
                      "C'est peut-être ta connexion. Ouvre-le à la main pour confirmer.")
            continue

        if code in (404, 410):
            r.erreur(
                f"{url} : HTTP {code} (lien cassé)",
                "Mets à jour ou retire ce lien dans README.md. Attention : certaines "
                "pages derrière une connexion renvoient 404 à un visiteur "
                "anonyme, confirme-le en l'ouvrant dans une fenêtre privée.",
            )
        elif 200 <= code < 400 or code == 429:
            ok += 1
            if code == 429:
                r.notes.append(f"{url} : HTTP 429 (limite de débit, compté OK)")
        else:
            r.avertir(f"{url} : HTTP {code} (réponse inattendue)",
                      "Vérifie-le à la main : c'est peut-être un blocage temporaire.")

    r.notes.append(f"{ok}/{len(urls)} liens ont répondu OK")
    return r


# ══════════════════════════════════════════════════════════════════════════
# CONTRÔLE 6 : les images du README existent et ont la taille annoncée
# ══════════════════════════════════════════════════════════════════════════

IMAGE_MARKDOWN = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)")
IMAGE_HTML = re.compile(r"""<img[^>]*\ssrc\s*=\s*["']([^"']+)["']""",
                        re.IGNORECASE)

SIGNATURE_PNG = b"\x89PNG\r\n\x1a\n"


def lire_dimensions_png(chemin: Path) -> tuple[int, int]:
    """
    Lit la largeur et la hauteur directement dans l'en-tête IHDR du PNG, sans Pillow.

    Structure : 8 octets de signature, 4 de longueur du bloc, 4 de type ("IHDR"),
    puis la largeur et la hauteur en uint32 gros-boutiste -> octets 16..24.
    """
    with chemin.open("rb") as f:
        entete = f.read(24)
    if len(entete) < 24 or not entete.startswith(SIGNATURE_PNG):
        raise ValueError("pas de signature PNG valide")
    if entete[12:16] != b"IHDR":
        raise ValueError("le premier bloc n'est pas IHDR")
    largeur, hauteur = struct.unpack(">II", entete[16:24])
    return largeur, hauteur


def controle_6_images(racine: Path) -> Resultat:
    r = Resultat(6, "Les images du README existent et ont la taille annoncée")
    chemin = racine / "README.md"

    try:
        contenu = lire_texte(chemin)
    except FileNotFoundError:
        r.erreur("le fichier README.md est absent",
                 "C'est la vitrine du dépôt sur GitHub : crée-le à la racine.")
        return r
    except OSError as e:
        r.erreur(f"impossible de lire README.md : {e}")
        return r

    # Les images mises en commentaire avec <!-- --> ne s'affichent pas : on ne les compte pas.
    sans_commentaires = COMMENTAIRE_HTML.sub("", contenu)

    references: list[str] = []
    for regex in (IMAGE_MARKDOWN, IMAGE_HTML):
        for m in regex.finditer(sans_commentaires):
            src = m.group(1).strip().strip("<>")
            if src not in references:
                references.append(src)

    locales = [s for s in references
               if not s.startswith(("http://", "https://", "data:", "//"))]

    if not locales:
        r.notes.append("le README ne cite aucune image locale")
        if references:
            r.notes.append(f"{len(references)} image(s) distante(s), non "
                           f"vérifiée(s) ici")
        return r

    for src in locales:
        # On retire le fragment/la requête et on normalise le chemin relatif au dépôt.
        propre = src.split("#")[0].split("?")[0].lstrip("./")
        fichier = (racine / propre)

        if not fichier.is_file():
            r.erreur(f"README.md cite '{src}' mais le fichier n'existe pas",
                     f"Crée le fichier dans {propre} ou corrige le chemin dans le "
                     f"README.")
            continue

        poids_ko = fichier.stat().st_size / 1024

        if fichier.suffix.lower() != ".png":
            r.notes.append(f"{propre} : présent ({poids_ko:.0f} Ko, "
                           f"{fichier.suffix or 'sans extension'} ; les "
                           f"dimensions ne sont lues que pour les PNG)")
            continue

        try:
            largeur, hauteur = lire_dimensions_png(fichier)
        except (OSError, ValueError, struct.error) as e:
            r.erreur(f"{propre} : impossible de lire l'en-tête PNG : {e}",
                     "Le fichier est abîmé ou ce n'est pas un vrai PNG. "
                     "Régénère-le.")
            continue

        r.notes.append(f"{propre} : {largeur}x{hauteur} px ({poids_ko:.0f} Ko)")

        if largeur < LARGEUR_MINIMALE_PNG:
            r.avertir(
                f"{propre} : fait {largeur}px de large, moins de "
                f"{LARGEUR_MINIMALE_PNG}px",
                "Elle sera floue dans le README sur GitHub. Exporte-la plus "
                "grande (1200px de large, c'est bien).",
            )

    return r


# ══════════════════════════════════════════════════════════════════════════
# Affichage
# ══════════════════════════════════════════════════════════════════════════

LARGEUR = 66


def titre(texte: str) -> None:
    print("=" * LARGEUR)
    print(f"  {texte}")
    print("=" * LARGEUR)


def afficher_resultat(r: Resultat) -> None:
    print()
    print(f"[{r.numero}/6] {r.titre}")

    for note in r.notes:
        print(f"  ...    {note}")

    for e in r.erreurs:
        print(f"  ERREUR {e}")

    for a in r.avertissements:
        print(f"  ALERTE {a}")

    if r.ignore:
        print("  SAUTÉ  contrôle non lancé")
    elif r.reussi and not r.avertissements:
        print("  OK     aucun problème")
    elif r.reussi:
        print("  OK     passe, avec des avertissements")
    else:
        print(f"  ÉCHEC  {len(r.erreurs)} erreur(s)")


def afficher_resume(resultats: list[Resultat]) -> int:
    print()
    print("-" * LARGEUR)
    print("  RÉSUMÉ")
    print("-" * LARGEUR)

    for r in resultats:
        if r.ignore:
            etat = "SAUTÉ"
        elif r.reussi:
            etat = "OK   "
        else:
            etat = "ÉCHEC"
        print(f"  [{etat}]  {r.numero}. {r.titre}")

    total = len(resultats)
    reussis = sum(1 for r in resultats if r.reussi)
    ignores = sum(1 for r in resultats if r.ignore)
    erreurs = sum(len(r.erreurs) for r in resultats)
    alertes = sum(len(r.avertissements) for r in resultats)

    print()
    ligne = f"  {reussis}/{total} contrôles OK"
    extras = []
    if erreurs:
        extras.append(f"{erreurs} erreur(s)")
    if alertes:
        extras.append(f"{alertes} avertissement(s)")
    if ignores:
        extras.append(f"{ignores} sauté(s)")
    if extras:
        ligne += " : " + ", ".join(extras)
    print(ligne)

    if erreurs:
        print("  L'audit ÉCHOUE. Corrige les ERREUR ci-dessus et "
              "relance-le.")
        return 1

    print("  Audit propre. Le dépôt-modèle est cohérent.")
    return 0


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    ce_script = Path(__file__).resolve()
    depot_par_defaut = ce_script.parent.parent

    parser = argparse.ArgumentParser(
        prog="audit.py",
        description="Audit du dépôt-modèle whatsapp-agentkit-fr.",
    )
    parser.add_argument(
        "--repo", default=str(depot_par_defaut),
        help="Chemin vers la racine du dépôt (par défaut : le dossier parent de scripts/)",
    )
    parser.add_argument(
        "--skip-links", action="store_true",
        help="Saute le contrôle des liens (aucun accès au réseau)",
    )
    args = parser.parse_args(argv)

    racine = Path(args.repo).expanduser().resolve()
    if not racine.is_dir():
        print(f"ERREUR : le chemin du dépôt n'existe pas : {racine}")
        return 1

    titre("AgentKit : audit du dépôt-modèle")
    print(f"  Dépôt : {racine}")
    print(f"  Liens : {'sautés (--skip-links)' if args.skip_links else 'vérifiés par le réseau'}")

    # Chaque contrôle est enveloppé : un bug dans l'un ne doit pas faire tomber l'audit.
    definitions = [
        (1, "Les blocs Python de CLAUDE.md compilent",
         lambda: controle_1_python(racine)),
        (2, "Les blocs YAML de CLAUDE.md se lisent",
         lambda: controle_2_yaml(racine)),
        (3, "Aucune trace des fournisseurs retirés (twilio, whapi)",
         lambda: controle_3_fournisseurs(racine, ce_script)),
        (4, "Variables d'environnement complètes dans .env.example",
         lambda: controle_4_env(racine)),
        (5, "Les liens du README répondent",
         lambda: controle_5_liens(racine, args.skip_links)),
        (6, "Les images du README existent et ont la taille annoncée",
         lambda: controle_6_images(racine)),
    ]

    resultats: list[Resultat] = []
    for numero, nom, fonction in definitions:
        try:
            r = fonction()
        except Exception as e:  # filet de sécurité : jamais de traceback brut
            r = Resultat(numero, nom)
            r.erreur(f"le contrôle a planté : {type(e).__name__}: {e}",
                     "C'est un bug de scripts/audit.py, pas du dépôt. Signale-le.")
        resultats.append(r)
        afficher_resultat(r)

    return afficher_resume(resultats)


if __name__ == "__main__":
    sys.exit(main())
