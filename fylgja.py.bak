"""Fylgja V3 — persistent continuity layer for Kurisu.

Responsibilities:
- persistent identity/canon/state/relationship/academic data
- hybrid semantic + lexical memory retrieval
- automatic memory extraction through Claude
- background memory writes after a response
- salience decay and consolidation helpers
- one /turn orchestration endpoint can call this module directly
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, re, uuid, math
from embedding import embed, cosine
from config import cfg

ROOT = Path(__file__).resolve().parent

def _load(name, default=None):
    p = ROOT / name
    if not p.exists(): return {} if default is None else default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return {} if default is None else default

def _load_text(name, default=""):
    p = ROOT / name
    if not p.exists(): return default
    try: return p.read_text(encoding="utf-8").strip()
    except OSError: return default

def _save(name, data):
    p = ROOT / name; p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def tokenize(text): return set(re.findall(r"[A-Za-zÀ-ÿ0-9']+", (text or "").lower()))

def _importance_value(x): return {"critical":1.0,"high":0.75,"normal":0.45,"low":0.2}.get(x,0.45)

def add_memory(content, kind="episodic", importance="normal", tags=None, source="automatic", create_embedding=True, metadata=None):
    content=(content or "").strip()
    if not content: raise ValueError("memory content cannot be empty")
    memories=_load("memory/memories.json",[])
    item={"id":str(uuid.uuid4()),"created_at":now(),"last_retrieved":None,"kind":kind,
          "importance":importance,"salience":1.0,"content":content,"tags":tags or [],
          "retrieval_count":0,"source":source,"embedding":None,"metadata":metadata or {}}
    if create_embedding:
        try: item["embedding"]=embed(item["content"]+" "+" ".join(item["tags"]))
        except Exception: item["embedding"]=None
    memories.append(item); _save("memory/memories.json",memories); return item

def _lexical_score(query,m):
    q=tokenize(query); text=" ".join([m.get("content","")," ".join(m.get("tags",[])),m.get("kind","")]); words=tokenize(text)
    if not q: return 0.0
    overlap=len(q & words)/max(1,len(q)); phrase=1.0 if query.lower() in m.get("content","").lower() else 0.0
    return min(1.0, overlap*0.8+phrase*0.2)

def search_memories(query, limit=6, candidate_limit=None):
    memories=_load("memory/memories.json",[])
    candidate_limit = candidate_limit if candidate_limit is not None else cfg("memory","candidate_limit",default=30)
    sem_w = cfg("memory","semantic_weight",default=0.72)
    lex_w = cfg("memory","lexical_weight",default=0.18)
    imp_w = cfg("memory","importance_weight",default=0.10)
    min_score = cfg("memory","min_score",default=0.18)
    try: qvec=embed(query)
    except Exception: qvec=None
    scored=[]
    for m in memories:
        sem=cosine(qvec,m.get("embedding")) if qvec and m.get("embedding") else 0.0
        lex=_lexical_score(query,m)
        imp=_importance_value(m.get("importance"))
        # Retrieval relevance dominates. Importance breaks ties; salience is a gentle modifier.
        raw=sem_w*sem+lex_w*lex+imp_w*imp
        score=raw*(0.65+0.35*min(2.0,max(0.25,m.get("salience",1.0))))
        if score>=min_score: scored.append((score,m))
    scored.sort(key=lambda x:x[0],reverse=True)
    result=[m for _,m in scored[:min(limit,candidate_limit)]]
    ids={m["id"] for m in result}
    changed=False
    for m in memories:
        if m["id"] in ids:
            m["last_retrieved"]=now(); m["retrieval_count"]=m.get("retrieval_count",0)+1; m["salience"]=min(2.0,m.get("salience",1.0)+0.01); changed=True
    if changed: _save("memory/memories.json",memories)
    return result

def reindex_memories():
    memories=_load("memory/memories.json",[]); changed=0
    for m in memories:
        try:
            m["embedding"]=embed(m.get("content","")+" "+" ".join(m.get("tags",[]))); changed+=1
        except Exception: pass
    _save("memory/memories.json",memories); return changed

def decay_memories():
    memories=_load("memory/memories.json",[]); changed=0
    for m in memories:
        if m.get("importance")=="critical": continue
        # Frequently retrieved memories decay much more slowly.
        rc = m.get("retrieval_count",0)
        if rc==0: m["salience"]=max(0.25,m.get("salience",1.0)-0.01); changed+=1
        elif rc<3: m["salience"]=max(0.35,m.get("salience",1.0)-0.003); changed+=1
        else: m["salience"]=max(0.45,m.get("salience",1.0)-0.001); changed+=1
    _save("memory/memories.json",memories); return changed
def start_session(session_id=None):
    state=_load("state/state.json",{}); state.update({"session_id":session_id or str(uuid.uuid4()),"current_focus":None,"recent_topic":None,"interaction_mode":"normal","user_state":None,"session_started":now()}); _save("state/state.json",state); return state

def update_state(**changes):
    state=_load("state/state.json",{}); state.update({k:v for k,v in changes.items() if v is not None}); _save("state/state.json",state); return state

def update_relationship(**changes):
    rel=_load("relationship/relationship.json",{}); rel.update({k:v for k,v in changes.items() if v is not None}); _save("relationship/relationship.json",rel); return rel

def add_relationship_event(content, importance="normal"):
    rel=_load("relationship/relationship.json",{}); rel.setdefault("important_events",[]).append({"date":now(),"content":content,"importance":importance}); _save("relationship/relationship.json",rel); return rel

def propose_evolution(content, reason, category="personality"):
    proposals=_load("evolution/proposals.json",[]); item={"id":str(uuid.uuid4()),"created_at":now(),"status":"pending","category":category,"proposal":content,"reason":reason}; proposals.append(item); _save("evolution/proposals.json",proposals); return item

def resolve_evolution(proposal_id, approved):
    proposals=_load("evolution/proposals.json",[])
    for p in proposals:
        if p["id"]==proposal_id: p["status"]="approved" if approved else "rejected"; p["resolved_at"]=now(); break
    _save("evolution/proposals.json",proposals)

def update_academic(subject, **fields):
    academic=_load("data/academic.json",{}); academic.setdefault("subjects",{}).setdefault(subject,{}).update(fields); academic["subjects"][subject]["updated_at"]=now(); _save("data/academic.json",academic); return academic["subjects"][subject]

def add_observation(content, category="learning"):
    academic=_load("data/academic.json",{}); academic.setdefault("observations",[]).append({"date":now(),"category":category,"content":content}); _save("data/academic.json",academic)

def log_interaction(user_message, assistant_message, turn_id):
    log = _load("data/interactions.json", [])
    log.append({"turn_id": turn_id, "date": now(), "user": user_message, "assistant": assistant_message})
    # Keep the local raw log bounded for the first prototype.
    max_items = cfg("memory","raw_interaction_limit",default=200)
    _save("data/interactions.json", log[-max_items:])

def _load_markdown_dir(dirname):
    """Concatenate every .md file found in a Fylgja subfolder (e.g. identity/, canon/).
    This is how the full character card / lorebook content actually reaches the context —
    identity.json and canon.json alone are only short summaries."""
    d = ROOT / dirname
    if not d.exists(): return ""
    parts = []
    for p in sorted(d.glob("*.md")):
        try: parts.append(f"--- {p.name} ---\n" + p.read_text(encoding="utf-8").strip())
        except OSError: continue
    return "\n\n".join(parts)

def _resolve_user_name():
    """Le nom {{user}} vient des fichiers SillyTavern (character card / lorebook) et
    n'est jamais un vrai nom sans substitution — sans ça, Claude reçoit littéralement
    la chaîne '{{user}}'. Priorité : variable d'environnement > config.json > fallback neutre."""
    import os
    env_name = os.getenv("FYLGJA_USER_NAME", "").strip()
    if env_name:
        return env_name
    cfg_name = (cfg("user", "name", default="") or "").strip()
    return cfg_name or "l'utilisateur"

def _substitute_placeholders(text):
    return text.replace("{{user}}", _resolve_user_name()).replace("{{User}}", _resolve_user_name())

def build_context(user_message, memory_limit=6):
    return {"identity":_load("identity/identity.json",{}),"canon":_load("canon/canon.json",{}),
            "identity_full":_load_markdown_dir("identity"),"canon_full":_load_markdown_dir("canon"),
            "relationship":_load("relationship/relationship.json",{}),"state":_load("state/state.json",{}),
            "academic":_load("data/academic.json",{}),"relevant_memories":search_memories(user_message,memory_limit),
            "approved_evolution":[p for p in _load("evolution/proposals.json",[]) if p.get("status")=="approved"]}

def context_as_text(user_message, memory_limit=6):
    c=build_context(user_message,memory_limit)
    text = "\n".join([
        "=== FYLGJA CONTEXT — KURISU ===",
        "IDENTITÉ (résumé) : "+json.dumps(c["identity"],ensure_ascii=False),
        "IDENTITÉ (fiche complète) :\n"+c["identity_full"],
        "CANON (résumé) : "+json.dumps(c["canon"],ensure_ascii=False),
        "CANON (lorebook complet) :\n"+c["canon_full"],
        "RELATION : "+json.dumps(c["relationship"],ensure_ascii=False),
        "ÉTAT : "+json.dumps(c["state"],ensure_ascii=False),
        "ACADÉMIQUE : "+json.dumps(c["academic"],ensure_ascii=False),
        "SOUVENIRS PERTINENTS :\n"+"\n".join("- "+m["content"] for m in c["relevant_memories"]),
        "ÉVOLUTION APPROUVÉE : "+json.dumps(c["approved_evolution"],ensure_ascii=False)
    ])
    return _substitute_placeholders(text)

def context_as_text_split(user_message, memory_limit=6):
    """Comme context_as_text, mais sépare la partie STATIQUE (identité + canon —
    identique d'un tour à l'autre dans une session) de la partie DYNAMIQUE (relation,
    état, académique, souvenirs — change à chaque tour). Cette séparation permet au
    provider Claude de marquer la partie statique en cache_control côté API : elle
    n'est facturée plein tarif qu'une fois, les tours suivants paient une fraction du
    prix sur ce bloc tant qu'il ne change pas (cf. Anthropic prompt caching)."""
    c = build_context(user_message, memory_limit)
    static_text = _substitute_placeholders("\n".join([
        "=== FYLGJA CONTEXT — KURISU (IDENTITÉ & CANON — STABLE) ===",
        "IDENTITÉ (résumé) : "+json.dumps(c["identity"],ensure_ascii=False),
        "IDENTITÉ (fiche complète) :\n"+c["identity_full"],
        "CANON (résumé) : "+json.dumps(c["canon"],ensure_ascii=False),
        "CANON (lorebook complet) :\n"+c["canon_full"],
    ]))
    dynamic_text = _substitute_placeholders("\n".join([
        "=== FYLGJA CONTEXT — KURISU (ÉTAT DU MOMENT — VARIABLE) ===",
        "RELATION : "+json.dumps(c["relationship"],ensure_ascii=False),
        "ÉTAT : "+json.dumps(c["state"],ensure_ascii=False),
        "ACADÉMIQUE : "+json.dumps(c["academic"],ensure_ascii=False),
        "SOUVENIRS PERTINENTS :\n"+"\n".join("- "+m["content"] for m in c["relevant_memories"]),
        "ÉVOLUTION APPROUVÉE : "+json.dumps(c["approved_evolution"],ensure_ascii=False)
    ]))
    return static_text, dynamic_text

def extract_memories_with_provider(provider_name="claude", turn_limit=10):
    from providers import get_provider
    interactions = _load("data/interactions.json", [])[-max(1, int(turn_limit)):]
    if not interactions:
        return {"memories": [], "relationship_events": [], "academic_observations": [], "evolution_proposals": []}
    system = """You are Fylgja's memory extractor. Analyze recent conversations between a user and Kurisu. Return ONLY valid JSON with keys memories, relationship_events, academic_observations, evolution_proposals. Do not invent facts. Only store useful durable information.

CRITICAL — PRESERVE EXACT DETAILS: When a specific number, name, date, or concrete detail was stated, keep it verbatim in the memory content. Do not compress "the user got 18/20 on the fractions exercise" into "the user did an exercise" or "the user mentioned struggling with a formula they'd seen before" into "the user has recurring difficulties." Vague summaries destroy the value of the memory. If the exact number/name/date is present in the conversation, it must be present in the stored memory. Prefer a slightly longer precise memory over a short vague one."""
    user = "\n\n".join(f"TURN {x['turn_id']}\nUSER: {x['user']}\nKURISU: {x['assistant']}" for x in interactions)
    raw = get_provider(provider_name).generate(system, user, max_tokens=2500, skip_routing=True)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    return json.loads(raw)


def apply_extraction(data):
    out={"memories":0,"relationship_events":0,"academic_observations":0,"evolution_proposals":0}
    for x in data.get("memories",[]):
        add_memory(x.get("content",""),x.get("kind","episodic"),x.get("importance","normal"),x.get("tags",[]),"claude_extractor"); out["memories"]+=1
    for x in data.get("relationship_events",[]):
        add_relationship_event(x.get("content",""),x.get("importance","normal")); out["relationship_events"]+=1
    for x in data.get("academic_observations",[]):
        add_observation(x.get("content",""),x.get("category","learning")); out["academic_observations"]+=1
    for x in data.get("evolution_proposals",[]):
        propose_evolution(x.get("proposal",""),x.get("reason",""),x.get("category","personality")); out["evolution_proposals"]+=1
    return out
