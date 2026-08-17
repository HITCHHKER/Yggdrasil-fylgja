"""
Academic Risk Router V1 — classifieur heuristique binaire, sans dépendance
externe (pas d'Ollama en V1, cf. spec section 17).

Répond à UNE seule question : "Est-ce que je peux raisonnablement envoyer
cette requête en effort LOW sans risque pédagogique significatif ?"

Si oui -> low. Sinon (y compris en cas de doute) -> medium.
Aucune notion de 'high' en V1 (cf. spec section 11).
"""
import re

MATH_PATTERNS = [
    r'=',                     # signe egal seul, rare en francais casual
    r'\bf\(x\)',             # notation fonctionnelle
    r'\bx\s*=',
    r'\d+\s*[+\-*/^]\s*\d+', # expression numerique avec chiffres autour
]

CONFUSION_MARKERS = [
    "pourquoi", "comment", "comprends pas", "compris", "explique",
    "j'ai pas compris", "je bloque", "ça marche pas", "aide-moi",
    "je sais pas", "résoudre", "résous", "calcul", "exercice",
]

ACADEMIC_TERMS = [
    "dérivée", "dérivées", "fonction affine", "fonctions affines",
    "fraction", "fractions", "équation", "équations", "vitesse",
    "accélération", "pythagore", "hypoténuse", "angle", "angles",
    "triangle", "triangles", "physique", "maths", "mathématiques",
    "exercice", "exercices", "formule", "formules", "théorème",
    "théorèmes", "calcul", "calculs", "chapitre", "chapitres",
    "cours", "devoir", "devoirs", "note", "notes", "contrôle", "examen",
]

PURE_GREETING_PATTERN = re.compile(
    r'^\s*(salut|coucou|hey|hello|ça va|ca va|bonjour|bonsoir)[\s!.?]*$',
    re.IGNORECASE
)


def _contains_any(text, terms):
    text_lower = text.lower()
    return any(t in text_lower for t in terms)


def _contains_math_pattern(text):
    return any(re.search(p, text) for p in MATH_PATTERNS)


def is_safe_for_low(message, last_assistant_message_type=None):
    if message is None or not message.strip():
        return False

    text = message.strip()

    if last_assistant_message_type == "IS_PEDAGOGICAL_QUESTION" and len(text.split()) < 5:
        return False

    if PURE_GREETING_PATTERN.match(text):
        return True

    if _contains_math_pattern(text):
        return False
    if _contains_any(text, CONFUSION_MARKERS):
        return False
    if _contains_any(text, ACADEMIC_TERMS):
        return False

    if len(text.split()) < 3:
        return False

    return True


def classify(message, last_assistant_message_type=None):
    safe = is_safe_for_low(message, last_assistant_message_type)
    reason_codes = []
    text = (message or "").strip()

    if PURE_GREETING_PATTERN.match(text):
        reason_codes.append("PURE_GREETING")
    if _contains_math_pattern(text):
        reason_codes.append("MATH_SYMBOL")
    if _contains_any(text, CONFUSION_MARKERS):
        reason_codes.append("CONFUSION_MARKER")
    if _contains_any(text, ACADEMIC_TERMS):
        reason_codes.append("ACADEMIC_TERM")
    if not reason_codes and safe:
        reason_codes.append("NO_ACADEMIC_SIGNAL")
    if not reason_codes and not safe:
        reason_codes.append("TOO_SHORT_OR_EMPTY")

    return {
        "message": message,
        "safe_for_low": safe,
        "chosen_route": "LOW" if safe else "MEDIUM",
        "reason_codes": reason_codes,
    }