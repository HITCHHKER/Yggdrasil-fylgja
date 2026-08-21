"""
Academic Router V2 — Cache-conscious.

NIVEAUX D'EXÉCUTION (logiques) :
- LOCAL   : bypass total (0 appel, 0 coût, 0 latence)
- LOW     : log seulement, l'effort réel envoyé à Claude est MEDIUM
- MEDIUM  : effort réel = MEDIUM (cache stable)
- HIGH    : effort réel = HIGH (cache cassé, mais rare)

Pourquoi LOW collapsé sur MEDIUM ?
Le cache Anthropic est indexé sur output_config.effort. Si on switch entre low/medium/high
à chaque tour, on perd l'effet du cache. On garde donc MEDIUM pour la grande majorité des
requêtes, et on réserve HIGH aux cas rares où une explication complexe justifie de casser
le cache.

Règle de sécurité : fallback = MEDIUM (jamais LOW ni LOCAL).
Exécution < 10ms.
"""
import re
import operator
import random

# ──────────────────────────────────────────────────────────────
# PATTERNS DE DÉTECTION (LOCAL)
# ──────────────────────────────────────────────────────────────

PURE_GREETINGS = re.compile(
    r'^\s*(?:salut|bonjour|bonsoir|coucou|hey|hello|yo|wesh|cc|bjr|bsr|ça va|ca va|comment tu vas|comment ça va)[\s!?.]*$',
    re.IGNORECASE
)

PURE_THANKS = re.compile(
    r'^\s*(?:merci|thanks|thx|merci beaucoup|je te remercie|c\'est gentil|cimer)[\s!?.]*$',
    re.IGNORECASE
)

PURE_AFFIRMATION = re.compile(
    r'^\s*(?:oui|ouais|ok|d\'accord|okay|yes|yep|ouep|bah oui|bien sûr|carrément|exact|exactement)[\s!?.]*$',
    re.IGNORECASE
)

PURE_NEGATION = re.compile(
    r'^\s*(?:non|nan|nope|pas du tout|pas vraiment|non merci)[\s!?.]*$',
    re.IGNORECASE
)

ARITHMETIC_PATTERN = re.compile(
    r'^\s*([\d.]+)\s*([+\-*/^])\s*([\d.]+)\s*$'
)

ARITHMETIC_FORBIDDEN = re.compile(r'[a-zA-Z()[\]]')

# ──────────────────────────────────────────────────────────────
# PATTERNS ACADÉMIQUES (pour HIGH)
# ──────────────────────────────────────────────────────────────

CONFUSION_MARKERS = re.compile(
    r'\b(?:comprends pas|compris|j\'y arrive pas|je bloque|'
    r'c\'est flou|je suis perdu|ça me dépasse|j\'ai du mal|'
    r'explique|résoudre|résous|aide-moi|je sais pas|'
    r'pourquoi|comment ça marche|j\'ai rien compris)\b',
    re.IGNORECASE
)

ADVANCED_ACADEMIC = re.compile(
    r'\b(?:dérivée|intégrale|équation différentielle|'
    r'matrice|vecteur propre|valeur propre|déterminant|'
    r'produit scalaire|produit vectoriel|transformée de Fourier|'
    r'série de Taylor|limite|continuité|théorème|'
    r'probabilité|statistique|écart-type|variance|'
    r'fonction exponentielle|logarithme|complexe|'
    r'relativité|mécanique quantique|électromagnétisme|'
    r'thermodynamique|fluide|géométrie non-euclidienne)\b',
    re.IGNORECASE
)

BASIC_ACADEMIC = re.compile(
    r'\b(?:fraction|équation|fonction affine|'
    r'angle|triangle|pythagore|théorème de Pythagore|'
    r'vitesse|accélération|force|masse|énergie|'
    r'maths|physique|cours|exercice|chapitre|'
    r'formule|calcul|devoir|examen|contrôle)\b',
    re.IGNORECASE
)

COMPLEX_QUESTION = re.compile(
    r'\b(?:comment|pourquoi|qu\'est-ce que|quel|quelle|'
    r'comment est-ce que|pourquoi est-ce que)\b.*\b(?:'
    r'fonctionne|calculer|trouver|démontrer|prouver|'
    r'résoudre|expliquer|comprendre|interpréter|analyser)\b',
    re.IGNORECASE | re.DOTALL
)

MULTI_STEP_REQUEST = re.compile(
    r'\b(?:explique-moi|peux-tu|pourrais-tu|tu peux|'
    r'j\'aimerais comprendre|je voudrais savoir|'
    r'comment on fait|comment résoudre)\b',
    re.IGNORECASE
)

# ──────────────────────────────────────────────────────────────
# RÉPONSES LOCALES
# ──────────────────────────────────────────────────────────────

def _local_greeting(continuing=False):
    if continuing:
        return random.choice([
            "Hn. Toujours là, à ce que je vois.",
            "On reprend où on en était.",
            "Hey. Prête à continuer ?",
            "Toujours dans le coin, hein.",
        ])
    return random.choice([
        "Salut ! Comment ça va aujourd'hui ?",
        "Bonjour ! Prêt pour une nouvelle session ?",
        "Coucou. On attaque quand tu veux.",
        "Hey ! Je suis là si t'as besoin.",
    ])

def _local_thanks():
    return random.choice([
        "Mais je t'en prie. C'est mon rôle, après tout.",
        "De rien. T'as bossé, c'est mérité.",
        "Pas de quoi. On continue quand tu veux.",
        "Hn. T'as pas besoin de me remercier à chaque fois, hein. ...Mais c'est apprécié.",
    ])

def _local_affirmation():
    return random.choice([
        "Bon. Alors on y va ?",
        "Parfait. J'attendais que tu sois prêt.",
        "Bien. Je suis toute ouïe.",
        "Ok. On enchaîne.",
    ])

def _local_negation():
    return random.choice([
        "Non ? Alors qu'est-ce que tu veux faire ?",
        "D'accord. Tu veux qu'on change de sujet ?",
        "Ah bon ? Je t'écoute.",
        "Non ? Explique-moi ce que t'as en tête, alors.",
    ])

def _safe_arithmetic(expr):
    match = ARITHMETIC_PATTERN.match(expr)
    if not match:
        return None, False

    left_str, op, right_str = match.groups()
    try:
        left = float(left_str)
        right = float(right_str)
    except ValueError:
        return None, False

    if op == '/' and right == 0:
        return "Division par zéro impossible.", True

    ops = {
        '+': operator.add,
        '-': operator.sub,
        '*': operator.mul,
        '/': operator.truediv,
        '^': operator.pow,
    }
    if op not in ops:
        return None, False

    result = ops[op](left, right)
    if result == int(result):
        return str(int(result)), True
    return f"{result:.2f}", True

# ──────────────────────────────────────────────────────────────
# ROUTEUR
# ──────────────────────────────────────────────────────────────
def _is_academic_confusion(text):
    """CONFUSION_MARKERS seul est trop large : 'je sais pas', 'pourquoi' sont des
    tournures courantes hors contexte scolaire (ex: 'je sais pas, je voulais
    savoir si ca va' declenchait HIGH a tort). On exige la co-occurrence avec un
    signal academique pour eviter les faux positifs sur du relationnel pur."""
    return bool(CONFUSION_MARKERS.search(text)) and bool(
        BASIC_ACADEMIC.search(text) or ADVANCED_ACADEMIC.search(text)
    )

class AcademicRouter:
    def __init__(self):
        self._local_count = 0
        self._low_count = 0
        self._medium_count = 0
        self._high_count = 0

    def classify(self, message: str, continuing: bool = False) -> dict:
        if not message or not message.strip():
            return self._fallback("message_vide")

        text = message.strip()

        if PURE_GREETINGS.match(text):
            return self._local_result(_local_greeting(continuing), "PURE_GREETING")
        if PURE_THANKS.match(text):
            return self._local_result(_local_thanks(), "PURE_THANKS")
        if PURE_AFFIRMATION.match(text):
            return self._local_result(_local_affirmation(), "PURE_AFFIRMATION")
        if PURE_NEGATION.match(text):
            return self._local_result(_local_negation(), "PURE_NEGATION")
        if not ARITHMETIC_FORBIDDEN.search(text):
            result, ok = _safe_arithmetic(text)
            if ok:
                return self._local_result(result, "ARITHMETIC")

        if _is_academic_confusion(text):
            return self._high_result("CONFUSION_MARKER")
        if ADVANCED_ACADEMIC.search(text):
            return self._high_result("ADVANCED_ACADEMIC")
        if COMPLEX_QUESTION.search(text) and MULTI_STEP_REQUEST.search(text):
            return self._high_result("COMPLEX_MULTI_STEP")

        if not BASIC_ACADEMIC.search(text) and not ADVANCED_ACADEMIC.search(text):
            if len(text.split()) > 10:
                return self._medium_result("LONG_NON_ACADEMIC")
            return self._low_result("NO_ACADEMIC_SIGNAL")

        return self._medium_result("BASIC_ACADEMIC")

    def _local_result(self, response: str, reason: str) -> dict:
        self._local_count += 1
        return {"level": "LOCAL", "response": response, "reason": reason, "safe": True, "effort": None, "stats": self._get_stats()}

    def _low_result(self, reason: str) -> dict:
        self._low_count += 1
        return {"level": "LOW", "response": None, "reason": reason, "safe": True, "effort": "medium", "stats": self._get_stats()}

    def _medium_result(self, reason: str) -> dict:
        self._medium_count += 1
        return {"level": "MEDIUM", "response": None, "reason": reason, "safe": True, "effort": "medium", "stats": self._get_stats()}

    def _high_result(self, reason: str) -> dict:
        self._high_count += 1
        return {"level": "HIGH", "response": None, "reason": reason, "safe": True, "effort": "high", "stats": self._get_stats()}

    def _fallback(self, reason: str) -> dict:
        return self._medium_result(f"FALLBACK_{reason}")

    def _get_stats(self) -> dict:
        return {
            "local": self._local_count, "low": self._low_count,
            "medium": self._medium_count, "high": self._high_count,
            "total": self._local_count + self._low_count + self._medium_count + self._high_count,
        }

    def reset_stats(self):
        self._local_count = self._low_count = self._medium_count = self._high_count = 0


_router = None

def get_router() -> AcademicRouter:
    global _router
    if _router is None:
        _router = AcademicRouter()
    return _router