import sys,tempfile,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import fylgja
from logger import ok
fylgja.embed=lambda text:[1.0,0.0] if any(k in text.lower() for k in ["dériv","pente","géométr","visualiser","mathématique"]) else [0.0,1.0]
fylgja.cosine=lambda a,b: sum(x*y for x,y in zip(a,b)) if a and b and len(a)==len(b) else 0.0
with tempfile.TemporaryDirectory() as td:
 old=fylgja.ROOT; fylgja.ROOT=pathlib.Path(td)
 for d in ["memory","state","relationship","evolution","data","identity","canon"]: (fylgja.ROOT/d).mkdir(parents=True,exist_ok=True)
 (fylgja.ROOT/"memory/memories.json").write_text("[]"); (fylgja.ROOT/"relationship/relationship.json").write_text("{}"); (fylgja.ROOT/"state/state.json").write_text("{}"); (fylgja.ROOT/"evolution/proposals.json").write_text("[]"); (fylgja.ROOT/"data/academic.json").write_text("{}"); (fylgja.ROOT/"identity/identity.json").write_text("{}"); (fylgja.ROOT/"canon/canon.json").write_text("{}")
 ok("Fylgja chargee")
 m=fylgja.add_memory("La représentation géométrique de la pente aide pour comprendre les dérivées.",tags=["maths"])
 ok("Mémoire créée",id=m["id"][:8])
 r=fylgja.search_memories("Je n'arrive pas à visualiser cette notion mathématique")
 assert r and "dériv" in r[0]["content"]
 ok("Recherche sémantique testée",found=r[0]["id"][:8])
 s=fylgja.start_session("test-00001"); assert s["session_id"]=="test-00001"; ok("Session testée")
 ctx=fylgja.context_as_text("Je n'arrive pas à visualiser cette notion"); assert "SOUVENIRS PERTINENTS" in ctx; ok("Contexte construit")
 fylgja.ROOT=old
print("SYSTEM TEST: OK")
