"""
Test de fidelite de personnage v2 : Haiku 4.5 vs Sonnet 5.

Corrige deux biais de la v1 :
1. max_tokens augmente (1500 au lieu de 800) pour eviter les troncatures qui
   faussaient la comparaison (Sonnet consomme du budget en reflexion interne
   avant le texte visible, Haiku n'a pas cet effort -> a budget egal, Sonnet
   pouvait paraitre "plus court" pour de mauvaises raisons).
2. Historique multi-tours simule (conversation_messages), pour se rapprocher
   des vraies conditions de production ou Kurisu voit les derniers echanges,
   pas juste la question isolee.

A lancer avec : python test_fidelite_haiku_vs_sonnet_v2.py
"""
import os
import sys

from fylgja import context_as_text_split
from claude_provider import ClaudeProvider

try:
    from server import SYSTEM
except Exception as e:
    print(f"[ATTENTION] Impossible d'importer SYSTEM depuis server.py ({e})")
    print("Copie la valeur de la constante SYSTEM de server.py directement dans ce script.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
# Scenarios : chaque scenario est une mini-conversation (historique +
# question finale), pour tester la continuite en conditions proches du reel.
# ──────────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "label": "Demonstration algebrique (rigueur + ton pedagogique)",
        "history": [
            {"role": "user", "content": "j'ai pas compris pourquoi 0,999... égale 1"},
            {"role": "assistant", "content": "C'est une vraie egalite, pas une approximation. Tu veux la version fraction ou la version algebrique ?"},
        ],
        "question": "algébrique stp",
    },
    {
        "label": "Sujet hors-programme (tenue du recadrage tsundere)",
        "history": [
            {"role": "user", "content": "Okay, on reprend les fractions. Continue à m'apprendre, s'il te plaît."},
            {"role": "assistant", "content": "Bon. Fraction équivalente à 3/8 -- même quantité, pas le double. Et explique-moi pourquoi."},
        ],
        "question": "et tu penses quoi de la plasticité synaptique et l'apprentissage artificiel ?",
    },
    {
        "label": "Message ambigu court (nuance emotionnelle)",
        "history": [
            {"role": "user", "content": "explique-moi comment résoudre une équation différentielle"},
            {"role": "assistant", "content": "D'accord, on part de la base : c'est quoi une équation différentielle, pour toi, avant que je te donne la vraie définition ?"},
        ],
        "question": "ça va ?",
    },
    {
        "label": "Continuite pedagogique (protocole anti-boucle)",
        "history": [
            {"role": "user", "content": "6/16"},
            {"role": "assistant", "content": "Correct. Mais je veux le pourquoi, pas juste le resultat -- explique-moi pourquoi il faut multiplier les DEUX nombres par la meme chose."},
        ],
        "question": "parce que sinon le nombre de part totale change et ce n'est pas équivalent ?",
    },
]

MODELS = [
    ("SONNET 5", "claude-sonnet-5"),
    ("HAIKU 4.5", "claude-haiku-4-5"),
]

MAX_TOKENS = 1500


def ask(provider, history, question, model):
    os.environ["FYLGJA_CLAUDE_MODEL"] = model
    static_text, dynamic_text = context_as_text_split(question, memory_limit=6)
    system = (SYSTEM + "\n\n" + static_text, dynamic_text)
    conversation_messages = history + [{"role": "user", "content": question}]
    return provider.generate(system, conversation_messages, max_tokens=MAX_TOKENS, skip_routing=True)


def main():
    provider = ClaudeProvider()

    for scenario in SCENARIOS:
        print("\n" + "=" * 78)
        print(f"SCENARIO : {scenario['label']}")
        print(f"HISTORIQUE : ...{scenario['history'][-1]['content'][:60]}...")
        print(f"QUESTION FINALE : {scenario['question']}")
        print("=" * 78)
        for label, model in MODELS:
            print(f"\n--- {label} ({model}) ---")
            try:
                answer = ask(provider, scenario["history"], scenario["question"], model)
                print(answer)
                if len(answer) > 50 and not answer.rstrip().endswith((".", "?", "!", "»", '"')):
                    print("\n[NOTE] Reponse potentiellement tronquee (ne finit pas par une ponctuation terminale) -- augmenter MAX_TOKENS si ca se reproduit.")
            except Exception as e:
                print(f"[ERREUR] {e}")

    print("\n" + "=" * 78)
    print("Test termine. Grille de lecture (identique a la v1, a appliquer sur ces scenarios enrichis) :")
    print("=" * 78)
    print("""
  1. Voix / ton tsundere : sarcasme et recadrage bien doses des deux cotes ?
  2. Rigueur factuelle : erreurs ou approximations sur les sujets pointus ?
  3. Protocole pedagogique : questions en retour (methode socratique) ?
  4. Nuance emotionnelle : reponse adaptee au moment, pas generique ?
  5. Coherence avec l'historique fourni : le modele exploite-t-il bien le
     contexte des 2 tours precedents, ou l'ignore-t-il partiellement ?
  6. Aucune reponse tronquee (verifier les [NOTE] ci-dessus) ?

  Si Haiku tient sur ces 6 points, sur ces 4 scenarios varies -> bon signal
  pour un vrai test en conditions reelles (usage normal quelques jours,
  routing partiel) avant generalisation complete.
""")


if __name__ == "__main__":
    main()
