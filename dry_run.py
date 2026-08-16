import sys
import fylgja
from logger import ok
message=" ".join(sys.argv[1:]).strip()
if not message: raise SystemExit('Usage: python dry_run.py "ton message"')
print("\n=== YGGDRASIL DRY-RUN ===")
print("MESSAGE:",message)
memories=fylgja.search_memories(message,6); ok("Souvenirs retenus",count=len(memories))
for i,m in enumerate(memories,1): print(f"{i}. [{m.get('importance')}] {m.get('content')}")
print("\n=== CONTEXTE ==="); print(fylgja.context_as_text(message,6)); print("\nAucun appel LLM n'a été effectué.")
