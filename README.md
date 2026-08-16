# Yggdrasil + Fylgja V4.1 — premier test

V4.1 garde la vision long terme mais simplifie le chemin critique du premier test.

## Ce qui change
- **Un seul appel Claude par `/turn`**. L'extraction mémoire n'est plus lancée silencieusement en arrière-plan.
- Chaque tour est conservé dans `data/interactions.json`.
- L'extraction sémantique peut être déclenchée explicitement via `/memory/extract`.
- `config.json` est maintenant réellement utilisé pour le port, le modèle Claude, la clé et les limites mémoire.
- Le provider Claude est la même abstraction utilisée pour la réponse et l'extraction.
- Le serveur reste lié à `127.0.0.1` par défaut.

## Test minimal
1. `python tests/test_system.py`
2. `python dry_run.py "Je n'arrive pas à visualiser cette notion mathématique"`
3. Définir `ANTHROPIC_API_KEY`.
4. `python server.py`
5. Tester `/health` puis `/turn`.
6. Si tu veux ensuite consolider les souvenirs, appeler `/memory/extract`.

## Embeddings
Le provider par défaut est Ollama + `nomic-embed-text`. La recherche sémantique réelle nécessite qu'un provider d'embeddings soit disponible. Sans cela, Fylgja conserve un score lexical de secours.
Les réglages (`provider`, `url`, `model`) viennent de `config.json` (section `embedding`), avec possibilité de les surcharger via les variables d'environnement `FYLGJA_EMBEDDING_*`.

## Canon complet
`identity/*.md` et `canon/*.md` (character card, lorebook) sont chargés intégralement et injectés dans chaque contexte envoyé au LLM, en plus des résumés JSON (`identity.json`, `canon.json`). C'est ce qui donne à Kurisu sa personnalité réelle — les fichiers JSON seuls ne suffisent pas.

## Intégration SillyTavern
Le serveur expose `/v1/chat/completions` (+ `/v1/models`) au format compatible OpenAI. Dans SillyTavern, choisir "Chat Completion" → source "Custom (OpenAI-compatible)" → URL `http://127.0.0.1:8765/v1`.
Le character card configuré côté SillyTavern est **volontairement ignoré** : Fylgja reste la seule source de vérité sur l'identité de Kurisu, pour ne pas la dupliquer entre l'interface et le backend. Seul le dernier message utilisateur est utilisé ; le reste de l'historique de conversation ST n'est pas renvoyé à Claude (c'est `data/interactions.json` + la mémoire Fylgja qui portent la continuité).

## Architecture
SillyTavern → Yggdrasil (`server.py`) → Fylgja → LLM Provider.
Fylgja conserve identité, mémoire, état, relation, académique et évolution indépendamment du LLM.
