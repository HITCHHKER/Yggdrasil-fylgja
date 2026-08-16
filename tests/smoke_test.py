import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fylgja

# Offline test: monkeypatch embedding so the test never needs Ollama.
fylgja.embed=lambda text:[1.0,0.0] if "dériv" in text.lower() or "pente" in text.lower() else [0.0,1.0]
fylgja.cosine=lambda a,b: (sum(x*y for x,y in zip(a,b)) if a and b and len(a)==len(b) else 0.0)

with tempfile.TemporaryDirectory() as td:
    old=fylgja.ROOT; fylgja.ROOT=__import__('pathlib').Path(td)
    for d in ["memory","state","relationship","evolution","data","identity","canon"]: (fylgja.ROOT/d).mkdir(parents=True,exist_ok=True)
    (fylgja.ROOT/"memory/memories.json").write_text("[]")
    (fylgja.ROOT/"relationship/relationship.json").write_text("{}")
    (fylgja.ROOT/"state/state.json").write_text("{}")
    (fylgja.ROOT/"evolution/proposals.json").write_text("[]")
    (fylgja.ROOT/"data/academic.json").write_text("{}")
    (fylgja.ROOT/"identity/identity.json").write_text("{}")
    (fylgja.ROOT/"canon/canon.json").write_text("{}")
    fylgja.add_memory("La représentation géométrique de la pente aide pour les dérivées.",tags=["maths"])
    result=fylgja.search_memories("Je n'arrive pas à visualiser les dérivées")
    assert result and "dériv" in result[0]["content"]
    fylgja.start_session("test")
    assert fylgja._load("state/state.json")["session_id"]=="test"
    fylgja.ROOT=old
print("Fylgja V3 smoke test: OK")
