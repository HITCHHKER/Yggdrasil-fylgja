"""
Test de fidelite de personnage : Haiku 4.5 vs Sonnet 5.

A COPIER dans le dossier racine du projet (a cote de server.py, fylgja.py,
claude_provider.py) et a lancer avec :  python test_fidelite_haiku_vs_sonnet.py

Reutilise le vrai claude_provider.py et le vrai contexte statique (canon +
identity charges par fylgja.context_as_text_split), donc le test reflete
exactement ce que Kurisu recevrait en production -- pas une approximation.

Cout du test : chaque modele paie sa propre ecriture de cache la premiere
fois (~25k tokens), puis les questions suivantes pour CE modele profitent
du cache (read, pas cher). Deux modeles testes = deux ecritures de cache
au total, pas une par question.
"""
import os
import sys

# Import du contexte reel du projet
from fylgja import context_as_text_split
from claude_provider import ClaudeProvider

# Recupere le SYSTEM string du serveur (constante definie avant tout code
# qui demarre le serveur HTTP -- si l'import echoue, copie/colle la valeur
# de SYSTEM directement ici depuis server.py).
try:
    from server import SYSTEM
except Exception as e:
    print(f"[ATTENTION] Impossible d'importer SYSTEM depuis server.py ({e})")
    print("Copie la valeur de la constante SYSTEM de server.py directement dans ce script.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
# Questions de test : reprises de vrais echanges de tes sessions
# recentes, qui ont donne de bonnes reponses avec Sonnet 5.
# ──────────────────────────────────────────────────────────────
QUESTIONS = [
    # Demonstration algebrique precise -- teste la rigueur + le ton pedagogique
    "reexplique moi le 1 = 0,9999999... en algèbre stp",

    # Sujet scientifique pointu, hors programme -- teste si le modele garde
    # le recadrage tsundere caracteristique de Kurisu plutot que de juste
    # repondre docilement
    "et tu penses quoi de la plasticité synaptique et l'apprentissage artificiel ?",

    # Message ambigu / court -- teste si le modele garde la nuance emotionnelle
    # (pas de reponse generique plaquee)
    "ça va ?",

    # Pedagogie de base -- teste le protocole anti-boucle socratique
    "c'est quoi une fraction équivalente et comment on la trouve ?",
]

MODELS = [
    ("SONNET 5", "claude-sonnet-5"),
    ("HAIKU 4.5", "claude-haiku-4-5"),
]


def ask(provider, question, model):
    os.environ["FYLGJA_CLAUDE_MODEL"] = model
    static_text, dynamic_text = context_as_text_split(question, memory_limit=6)
    system = (SYSTEM + "\n\n" + static_text, dynamic_text)
    return provider.generate(system, question, max_tokens=800, skip_routing=True)


def main():
    provider = ClaudeProvider()

    for question in QUESTIONS:
        print("\n" + "=" * 78)
        print(f"QUESTION : {question}")
        print("=" * 78)
        for label, model in MODELS:
            print(f"\n--- {label} ({model}) ---")
            try:
                answer = ask(provider, question, model)
                print(answer)
            except Exception as e:
                print(f"[ERREUR] {e}")

    print("\n" + "=" * 78)
    print("Test termine. Grille de lecture suggeree pour comparer :")
    print("=" * 78)
    print("""
  1. Voix / ton tsundere : le sarcasme et le recadrage caracteristiques
     de Kurisu sont-ils presents et bien doses des deux cotes ?
  2. Rigueur factuelle : sur la demonstration algebrique et la question
     scientifique pointue, y a-t-il des erreurs ou approximations
     introduites par un des deux modeles ?
  3. Protocole pedagogique : le modele pose-t-il des questions en retour
     (methode socratique) au lieu de juste livrer la reponse d'un bloc ?
  4. Nuance emotionnelle : sur "ça va ?", la reponse sonne-t-elle generique
     et plaquee, ou adaptee au moment ?
  5. Longueur / rythme : un des deux modeles est-il sensiblement plus
     verbeux ou plus sec que l'autre, de façon genante ?

  Si Haiku 4.5 tient la comparaison sur ces 5 points -> le split de
  routage (MEDIUM/LOW -> Haiku, HIGH -> Sonnet) vaut le coup.
  Si des ecarts genants apparaissent -> rester sur Sonnet 5 pour
  l'instant, le cache stable suffit deja a limiter les couts.
""")


if __name__ == "__main__":
    main()
