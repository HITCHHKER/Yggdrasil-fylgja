"""Test rapide de la couche affective (6.8) -- a lancer depuis la racine du
projet (la ou se trouve fylgja.py). Ne fait aucun appel API : simule un
evenement fort puis "avance le temps" en modifiant last_updated_at, pour
voir le decay exponentiel sans attendre des heures pour de vrai."""
import fylgja, json
from datetime import datetime, timedelta, timezone

def show(label):
    print(f"\n--- {label} ---")
    print(fylgja.synthesize_emotional_state_narrative())
    rel = fylgja._load("relationship/relationship.json", {})
    print(json.dumps(rel.get("etat_emotionnel", {}).get("state"), indent=2))

# 0. Etat actuel (baseline de la session en cours, ou cree une nouvelle
#    session si aucune n'existe -- ne devrait normalement pas arriver si tu
#    as deja discute avec Kurisu au moins une fois ce soir).
rel = fylgja._load("relationship/relationship.json", {})
etat = rel.get("etat_emotionnel", {})
session_id = etat.get("session_id")
if not session_id:
    session_id = "sess_test_manuel"
    fylgja.ensure_emotional_session(session_id)
show("ÉTAT ACTUEL (avant test)")

# 1. Simule un evenement hostile fort, sans passer par l'extraction Claude
#    (teste directement _apply_emotional_events, comme le ferait
#    apply_extraction() en conditions reelles).
fake_event = {"category": "hostilite_isolee", "importance": 7, "content": "test manuel"}
fylgja._apply_emotional_events(session_id, [fake_event])
show("APRÈS UN ÉVÉNEMENT HOSTILE SIMULÉ (importance 7)")

# 2. "Avance" le temps de 30 minutes sans rien faire d'autre, puis decay.
rel = fylgja._load("relationship/relationship.json", {})
rel["etat_emotionnel"]["last_updated_at"] = (
    datetime.now(timezone.utc) - timedelta(minutes=30)
).isoformat(timespec="seconds")
fylgja._save("relationship/relationship.json", rel)
fylgja.decay_emotional_state()
show("APRÈS 30 MIN SIMULÉES (retour partiel attendu)")

# 3. "Avance" encore de 3h -- le stress (tau ~30min) devrait etre quasi
#    revenu a la baseline, mood/fatigue (tau ~2-2.5h) beaucoup moins.
rel = fylgja._load("relationship/relationship.json", {})
rel["etat_emotionnel"]["last_updated_at"] = (
    datetime.now(timezone.utc) - timedelta(hours=3)
).isoformat(timespec="seconds")
fylgja._save("relationship/relationship.json", rel)
fylgja.decay_emotional_state()
show("APRÈS 3H SIMULÉES (stress quasi revenu, mood/fatigue encore décalés)")

print("\nTest terminé. Si tu veux revenir à l'état réel précédent, relance le serveur normalement (le prochain vrai tour recalculera/décroîtra depuis l'état sauvegardé ici).")
