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

# Contexte temporel EXPLICITE, factuel, injecte tel quel dans le contexte --
# distinct de l'usage interne de l'heure/du jour dans la baseline affective
# (_compute_emotional_baseline), qui reste indirect et non-factuel (juste un
# nudge sur fatigue). Ici Kurisu SAIT reellement quel jour/heure il est,
# comme information factuelle simple -- pas de lien avec la neurochimie pour
# l'instant, connexion volontairement repoussee (voir discussion du 21 aout).
_FRENCH_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FRENCH_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                   "août", "septembre", "octobre", "novembre", "décembre"]

def _current_temporal_context_text():
    """Heure LOCALE reelle de la machine (coherent avec le choix deja fait
    pour _compute_emotional_baseline) -- pas l'UTC utilise ailleurs dans ce
    fichier pour les horodatages techniques."""
    local_now = datetime.now()
    day_name = _FRENCH_WEEKDAYS[local_now.weekday()]
    month_name = _FRENCH_MONTHS[local_now.month - 1]
    return f"Nous sommes {day_name} {local_now.day} {month_name} {local_now.year}, il est {local_now.strftime('%Hh%M')}."
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
    _save("memory/memories.json",memories)
    changed += _decay_and_archive_relationship_events()
    return changed

# Equivalent Muninn (6.9, patch du 20 aout) : les evenements de
# important_events n'etaient jamais elagues -- extension de decay_memories()
# pour leur donner une salience qui decroit dans le temps, comme les
# memoires, mais qui ARCHIVE au lieu de supprimer une fois sous le seuil.
# La vitesse de decroissance depend de l'importance (echelle 1/3/5/7/9-10) :
# un evenement anecdotique (1) s'efface vite, un pivot relationnel majeur
# (9-10) reste actif tres longtemps -- coherent avec le traitement deja
# applique aux marques_integrite (jamais totalement effacees).
RELATIONSHIP_EVENT_ARCHIVE_THRESHOLD = 0.3

def _relationship_event_decay_rate(importance):
    if importance is None: importance = 3
    if importance >= 9: return 0.002
    if importance >= 7: return 0.005
    if importance >= 5: return 0.01
    if importance >= 3: return 0.02
    return 0.04

def _decay_and_archive_relationship_events():
    """Fait decroitre la salience de chaque important_events ; deplace vers
    rel['archive'] (recuperable, jamais supprime) ceux qui passent sous le
    seuil. Les marques_integrite et l'escalade_hostile ne sont PAS touchees
    ici -- elles ont deja leur propre logique de persistance/reparation."""
    rel = _load("relationship/relationship.json", {})
    events = rel.get("important_events", [])
    if not events:
        return 0
    kept, archived = [], []
    for e in events:
        salience = e.get("salience", 1.0)
        salience = max(0.0, salience - _relationship_event_decay_rate(e.get("importance")))
        e["salience"] = salience
        if salience < RELATIONSHIP_EVENT_ARCHIVE_THRESHOLD:
            e["archived_at"] = now()
            archived.append(e)
        else:
            kept.append(e)
    if not archived:
        rel["important_events"] = kept
        _save("relationship/relationship.json", rel)
        return 0
    rel["important_events"] = kept
    rel.setdefault("archive", []).extend(archived)
    _save("relationship/relationship.json", rel)
    return len(archived)

def recover_archived_event(index):
    """Recupere un evenement archive (par index dans rel['archive']) et le
    remet dans important_events avec une salience fraiche -- l'archive n'est
    donc jamais une suppression definitive, juste une mise en sommeil."""
    rel = _load("relationship/relationship.json", {})
    archive = rel.get("archive", [])
    if index < 0 or index >= len(archive):
        return None
    event = archive.pop(index)
    event["salience"] = 1.0
    event.pop("archived_at", None)
    rel.setdefault("important_events", []).append(event)
    _save("relationship/relationship.json", rel)
    return event
def start_session(session_id=None):
    state=_load("state/state.json",{}); state.update({"session_id":session_id or str(uuid.uuid4()),"current_focus":None,"recent_topic":None,"interaction_mode":"normal","user_state":None,"session_started":now()}); _save("state/state.json",state); return state

def update_state(**changes):
    state=_load("state/state.json",{}); state.update({k:v for k,v in changes.items() if v is not None}); _save("state/state.json",state); return state

# =====================================================================
# 6.8 — Couche affective (etat RAPIDE, volatile), DISTINCTE des axes
# internes (LENTS, stables). Version stabilisee du 21 aout (soir),
# remplace la premiere version (rebond discret + decay par tour) suite
# a la proposition de refonte : decay temporel CONTINU (exponentiel, base
# sur le temps reel ecoule, pas le nombre de tours), baseline sans alea
# cache et sans regles jour/heure rigides, modulation d'evenement continue
# (jamais de seuil dur type "if stress>0.7"). Regle stricte inchangee :
# cette couche n'ecrit JAMAIS directement dans axes_internes ni dans
# escalade_hostile -- signal de saillance informatif uniquement (voir
# _emotional_salience_hint). Branchement direct sur escalade_hostile /
# marques et lien avec 6.7 (longueur de reponse) toujours repousses a
# une session ulterieure.
# =====================================================================

EMOTIONAL_DIMENSIONS = ("stress", "reward", "social_affiliation", "mood", "fatigue")

# Unite temporelle UNIQUE et explicite pour tout ce bloc : la SECONDE.
# recovery_rate est exprime en 1/seconde -- ne jamais melanger avec des
# minutes/heures ailleurs dans ce module sans conversion explicite.
#
# recovery_rate = 1/tau, ou tau est le temps caracteristique (en secondes)
# pour revenir a ~63% du chemin vers la baseline. Ce sont des parametres de
# MODELE COMPORTEMENTAL, pas des constantes biologiques mesurees -- valeurs
# provisoires, a ajuster en usage reel comme tous les autres seuils de ce
# fichier. Les noms internes (dopamine, cortisol...) du 6.8 d'origine sont
# volontairement abandonnes comme noms de champs (gardes seulement en
# commentaire pour readabilite / continuite conceptuelle) au profit des
# noms comportementaux recommandes par la proposition du 21 aout.
RECOVERY_RATE_PER_SECOND = {
    "stress": 1 / 1800,               # ~30 min (cortisol-like)
    "reward": 1 / 1200,                # ~20 min (dopamine-like)
    "social_affiliation": 1 / 3600,    # ~60 min (ocytocine-like)
    "mood": 1 / 7200,                  # ~120 min, humeur de fond, lente (serotonine-like)
    "fatigue": 1 / 9000,               # ~150 min, ne recupere pas vite sans repos reel
}

# Effets par categorie d'evenement (base, avant modulation continue par
# l'importance de l'evenement -- voir _apply_emotional_events). Mapping
# conceptuel conserve du 6.8 d'origine, transpose sur les 5 dimensions
# comportementales. A valider en usage reel comme le reste des mappings
# categorie->effet deja presents dans ce fichier.
CATEGORY_EMOTION_EFFECTS = {
    "vulnerabilite_partagee": {"social_affiliation": 0.15},
    "curiosite_intellectuelle": {"reward": 0.15},
    "admiration_intellectuelle": {"reward": 0.15},
    "transgression_competence": {"stress": 0.05, "reward": -0.05},
    "transgression_integrite": {"stress": 0.25, "social_affiliation": -0.1, "mood": -0.1, "fatigue": 0.05},
    "transgression_confiance": {"stress": 0.15, "social_affiliation": -0.05, "mood": -0.05, "fatigue": 0.03},
    "reparation": {"stress": -0.12, "social_affiliation": 0.05, "mood": 0.1, "fatigue": -0.03},
    "hostilite_isolee": {"stress": 0.2, "mood": -0.1, "social_affiliation": -0.05, "fatigue": 0.05},
    "hostilite_repetee": {"stress": 0.2, "mood": -0.1, "social_affiliation": -0.05, "fatigue": 0.05},
    "rejet_engagement": {"stress": 0.2, "mood": -0.1, "social_affiliation": -0.05, "fatigue": 0.05},
}

def _clamp01(v):
    """Garde-fou NUMERIQUE uniquement (borne technique [0,1] apres toute
    modification) -- ne constitue PAS un mecanisme emotionnel en soi,
    contrairement a l'ancien rebond discret qu'il remplace. La stabilite
    du systeme repose sur le decay exponentiel continu, pas sur ce clamp."""
    return max(0.0, min(1.0, v))

def _recent_reflection_texts(limit=3):
    reflections = _load("data/reflections.json", [])
    if not reflections:
        return []
    return [r for r in sorted(reflections, key=lambda r: r.get("date", ""))[-limit:]]

def _reflection_keyword_fraction(reflections, pattern):
    if not reflections:
        return 0.0
    matches = sum(1 for r in reflections if re.search(pattern, r.get("content", ""), re.I))
    return matches / len(reflections)

def _time_of_day_fatigue_bias(local_now):
    """Fonction CONTINUE de l'heure (pic vers 3h du matin, creux vers 15h) --
    jamais de branche dure type 'if hour < 8'. Amplitude modeste (+-0.15) :
    un indice contextuel parmi d'autres, pas une causalite rigide (section 5
    de la proposition du 21 aout)."""
    hour_frac = local_now.hour + local_now.minute / 60.0
    phase = 2 * math.pi * (hour_frac - 3) / 24.0
    return 0.15 * math.cos(phase)

def _rest_factor(elapsed_hours):
    """Plus le temps REEL ecoule depuis la derniere session est long, plus on
    presume un repos reel -- fonction saturante continue (jamais un reset
    binaire du type 'a dormi -> fatigue=0', section 6 de la proposition)."""
    if elapsed_hours <= 0:
        return 0.0
    return 1 - math.exp(-elapsed_hours / 12.0)

def _compute_emotional_baseline(session_id):
    """Etat de base NON NEUTRE calcule une seule fois au debut de chaque
    session distincte, a partir UNIQUEMENT de sources contextuelles reelles
    (evenements recents, reflexions, historique relationnel, temporalite) --
    AUCUN alea cache (pas de random), AUCUNE regle jour/heure rigide
    (section 4-5 de la proposition du 21 aout). L'historique relationnel
    (axes_internes) sert de source explicitement autorisee pour la baseline
    de social_affiliation -- une relation etablie de longue date part d'un
    terrain plus chaleureux, une relation jeune part plus neutre."""
    rel = _load("relationship/relationship.json", {})
    axes = rel.get("axes_internes", {})
    unresolved_marks = len([m for m in rel.get("marques_integrite", []) if m.get("status") != "resolue"])
    reflections = _recent_reflection_texts()
    conflict_frac = _reflection_keyword_fraction(reflections, r"conflit|tension|hostil|rejet")
    warmth_frac = _reflection_keyword_fraction(reflections, r"complicité|confiance|proximité|chaleur|admiration|curiosité")

    state_file = _load("state/state.json", {})
    elapsed_hours = 0.0
    prev_updated = (rel.get("etat_emotionnel") or {}).get("last_updated_at")
    if prev_updated:
        try:
            prev_dt = datetime.fromisoformat(prev_updated)
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=timezone.utc)
            elapsed_hours = (datetime.now(timezone.utc) - prev_dt).total_seconds() / 3600.0
        except ValueError:
            elapsed_hours = 0.0

    local_now = datetime.now()
    fatigue_time_bias = _time_of_day_fatigue_bias(local_now)
    rest = _rest_factor(elapsed_hours)

    stress = 0.2 + 0.2 * conflict_frac + 0.03 * unresolved_marks
    reward = 0.5 + 0.2 * warmth_frac - 0.1 * conflict_frac
    social_affiliation = 0.5 + 0.05 * axes.get("affection", 0) + 0.03 * axes.get("confiance", 0)
    mood = 0.5 + 0.15 * warmth_frac - 0.15 * conflict_frac
    fatigue = 0.35 + fatigue_time_bias - 0.2 * rest

    return {
        "stress": _clamp01(stress),
        "reward": _clamp01(reward),
        "social_affiliation": _clamp01(social_affiliation),
        "mood": _clamp01(mood),
        "fatigue": _clamp01(fatigue),
    }

def ensure_emotional_session(session_id):
    """Assure qu'un etat de base existe pour cette session_id (peu importe
    qu'elle soit 'qualifiante' au sens des axes -- l'etat affectif est plus
    reactif, pas gate par min_turns). Recalcule aussi si le schema stocke
    est celui de l'ancienne version (cle 'state'/'baseline' absente) --
    evite d'avoir a nettoyer relationship.json a la main apres cette refonte."""
    if not session_id:
        return None
    rel = _load("relationship/relationship.json", {})
    etat = rel.setdefault("etat_emotionnel", {})
    schema_ok = "state" in etat and "baseline" in etat
    if etat.get("session_id") == session_id and schema_ok:
        return etat
    baseline = _compute_emotional_baseline(session_id)
    etat.clear()
    etat.update({
        "session_id": session_id,
        "baseline": baseline,
        "state": dict(baseline),
        "last_updated_at": now(),
    })
    _save("relationship/relationship.json", rel)
    return etat

def _decay_state_to_now(etat):
    """Decay temporel CONTINU (exponentiel), base sur le temps REEL ecoule
    depuis last_updated_at -- pas sur le nombre de tours. Formule :
    state = baseline + (state - baseline) * exp(-recovery_rate * elapsed_s).
    Proprietes voulues : retour rapide juste apres un pic, qui ralentit en
    approchant la baseline ; 10 evenements en 2 minutes et 10 evenements en
    2 heures donnent des trajectoires differentes, comme demande (test E de
    la proposition)."""
    last_updated = etat.get("last_updated_at")
    if not last_updated:
        etat["last_updated_at"] = now()
        return etat
    try:
        last_dt = datetime.fromisoformat(last_updated)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        etat["last_updated_at"] = now()
        return etat
    elapsed_s = max(0.0, (datetime.now(timezone.utc) - last_dt).total_seconds())
    baseline = etat.get("baseline", {})
    state = etat.setdefault("state", dict(baseline))
    for dim in EMOTIONAL_DIMENSIONS:
        b = baseline.get(dim, 0.5)
        s = state.get(dim, b)
        rate = RECOVERY_RATE_PER_SECOND.get(dim, 1 / 3600)
        state[dim] = _clamp01(b + (s - b) * math.exp(-rate * elapsed_s))
    etat["state"] = state
    etat["last_updated_at"] = now()
    return etat

def decay_emotional_state():
    """A appeler UNE FOIS PAR TOUR (server.py, avant de construire le
    contexte) -- applique le decay continu jusqu'a maintenant. Idempotent
    a quelques secondes pres si appele plusieurs fois de suite (elapsed_s
    proche de 0 -> quasi aucun mouvement)."""
    rel = _load("relationship/relationship.json", {})
    etat = rel.get("etat_emotionnel")
    if not etat or "state" not in etat or "baseline" not in etat:
        return
    rel["etat_emotionnel"] = _decay_state_to_now(etat)
    _save("relationship/relationship.json", rel)

def _apply_emotional_events(session_id, batch_events):
    """Applique les effets des relationship_events fraichement extraits.
    Modulation CONTINUE par l'importance de l'evenement (echelle 1-9/10 deja
    existante) -- jamais de seuil dur type 'if importance>=7: impact*=2'.
    Decay-to-now applique d'abord (l'extraction tourne en arriere-plan,
    potentiellement un peu apres le tour qui l'a declenchee) pour garder
    last_updated_at comme unique source de verite temporelle."""
    if not session_id:
        return
    rel = _load("relationship/relationship.json", {})
    etat = rel.get("etat_emotionnel")
    if not etat or etat.get("session_id") != session_id or "state" not in etat:
        # Securite : etat non initialise pour cette session (devrait avoir
        # ete fait par ensure_emotional_session cote server.py) -- on ne
        # bouge rien plutot que d'ecrire dans un etat incoherent.
        return
    etat = _decay_state_to_now(etat)
    state = etat["state"]
    for ev in batch_events:
        effects = CATEGORY_EMOTION_EFFECTS.get(ev.get("category"))
        if not effects:
            continue
        importance = ev.get("importance", 3)
        try:
            weight = max(0.1, min(1.0, float(importance) / 10.0))
        except (TypeError, ValueError):
            weight = 0.3
        for dim, base_delta in effects.items():
            state[dim] = _clamp01(state.get(dim, 0.5) + base_delta * weight)
    etat["state"] = state
    rel["etat_emotionnel"] = etat
    _save("relationship/relationship.json", rel)

def _emotional_salience_hint():
    """SEUL point de contact autorise entre la couche affective et le reste
    du systeme -- texte informatif injecte au prompt d'extraction, jamais
    une ecriture mecanique. L'audit de cohérence (6.5) reste seul
    decisionnaire sur l'importance reelle d'un evenement (regle stricte
    inchangee depuis le 6.8 d'origine)."""
    rel = _load("relationship/relationship.json", {})
    state = rel.get("etat_emotionnel", {}).get("state")
    if not state:
        return ""
    spikes = []
    if state.get("stress", 0.2) >= 0.6:
        spikes.append("tension/stress élevé")
    r = state.get("reward", 0.5)
    if r >= 0.7 or r <= 0.25:
        spikes.append("énergie/intérêt hors norme (haut ou bas)")
    sa = state.get("social_affiliation", 0.5)
    if sa >= 0.7 or sa <= 0.25:
        spikes.append("proximité ou distance émotionnelle marquée")
    if not spikes:
        return ""
    return (
        "SIGNAL DE SAILLANCE (contexte informatif uniquement, n'impose rien) : "
        "l'état affectif du moment montre : " + ", ".join(spikes) + ". "
        "Cela PEUT justifier une importance candidate plus élevée pour un "
        "événement de ce batch si le contenu réel de l'échange le confirme -- "
        "ne jamais l'utiliser seul pour décider, juge toujours sur le contenu."
    )

def synthesize_emotional_state_narrative():
    """Traduit l'etat affectif courant en texte qualitatif, jamais de valeur
    brute exposee a Claude -- meme principe que
    synthesize_relationship_narrative() pour les axes. Seuils de lecture
    provisoires, a ajuster en usage reel."""
    rel = _load("relationship/relationship.json", {})
    state = rel.get("etat_emotionnel", {}).get("state")
    if not state:
        return "État du moment : pas encore de session établie."
    parts = []
    stress = state.get("stress", 0.2)
    if stress >= 0.6: parts.append("tension nette perceptible, sur la défensive")
    elif stress >= 0.35: parts.append("légère tension en arrière-plan")
    reward = state.get("reward", 0.5)
    if reward >= 0.65: parts.append("énergie et intérêt visibles")
    elif reward <= 0.3: parts.append("motivation en berne, plus terne que d'habitude")
    mood = state.get("mood", 0.5)
    if mood <= 0.3: parts.append("humeur maussade sous-jacente")
    elif mood >= 0.65: parts.append("humeur posée, plutôt satisfaite")
    social_affiliation = state.get("social_affiliation", 0.5)
    if social_affiliation >= 0.65: parts.append("plus ouverte/chaleureuse que d'habitude en surface")
    elif social_affiliation <= 0.3: parts.append("plus distante, moins encline à se livrer")
    fatigue = state.get("fatigue", 0.35)
    if fatigue >= 0.55: parts.append("fatiguée, moins alerte")
    elif fatigue <= 0.2: parts.append("vigilance accrue, en forme")
    if not parts:
        return "État du moment : stable, rien de notable actuellement."
    return "État du moment (modulé par le tier, ne remplace jamais les axes de fond) : " + "; ".join(parts) + "."


def _apply_axis_movements(session_id, new_relational_session, batch_events):
    """Fait bouger les 3 axes internes (jamais exposes bruts a Claude, voir
    synthesize_relationship_narrative) a partir des relationship_events qu'on
    vient d'ajouter. Deux garde-fous du patch du 20 aout, appliques ensemble :

    - Audit de cohérence (6.5) : un evenement ne "vote" pour un mouvement
      d'axe que si son importance >= 5 -- une remarque anecdotique ne fait
      jamais bouger un axe, meme repetee.
    - Plafond par session (6.3) : chaque axe ne bouge que d'UN palier MAX par
      session distincte, quel que soit le nombre ou l'intensite des
      evenements qualifiants cette session-la -- y compris a travers
      plusieurs appels d'extraction successifs de la MEME session (traque via
      axes_internes.last_moved_session, pas juste au sein d'un seul appel).
    - Rien ne bouge si session_id est None (session non qualifiante, cf.
      _is_new_relational_session cote server.py) -- c'est deja l'audit le
      plus simple possible : pas de session distincte, pas de mouvement.

    Une transgression_integrite pose en plus une marque persistante
    (section 3 du doc d'origine : jamais effacee totalement, seulement
    attenuee par une reparation ulterieure vers "expliquee, acceptee
    provisoirement")."""
    if not session_id:
        return
    rel = _load("relationship/relationship.json", {})
    axes = rel.setdefault("axes_internes", {})
    for a in AXES:
        axes.setdefault(a, 0)
    last_moved = axes.setdefault("last_moved_session", {a: None for a in AXES})
    marks = rel.setdefault("marques_integrite", [])

    if new_relational_session and axes.get("last_counted_session_id") != session_id:
        axes["sessions_qualifiantes_comptees"] = axes.get("sessions_qualifiantes_comptees", 0) + 1
        axes["last_counted_session_id"] = session_id
        axes.setdefault("premiere_session_date", now())  # jamais ecrase une fois pose

    votes = {a: 0 for a in AXES}
    for ev in batch_events:
        if ev.get("importance", 0) < 5:
            continue
        effects = CATEGORY_AXIS_EFFECTS.get(ev.get("category"), {})
        for axis, sign in effects.items():
            votes[axis] += sign
        if ev.get("category") == "transgression_integrite":
            marks.append({"date": ev.get("date"), "content": ev.get("content", "")[:200], "status": "non_resolue"})
        if ev.get("category") == "reparation":
            target_date = ev.get("incident_date")
            matched = None
            if target_date:
                # matching precis : l'incident explicitement identifie par l'extraction
                matched = next((m for m in marks if m.get("status") == "non_resolue" and m.get("date") == target_date), None)
            if matched is None:
                # fallback : plus recente non resolue (limite connue si incident_date absent/errone)
                matched = next((m for m in reversed(marks) if m["status"] == "non_resolue"), None)
            if matched:
                matched["status"] = "expliquee_acceptee_provisoirement"

    for axis, vote in votes.items():
        if vote == 0 or last_moved.get(axis) == session_id:
            continue
        axes[axis] = axes.get(axis, 0) + (1 if vote > 0 else -1)
        last_moved[axis] = session_id

    _save("relationship/relationship.json", rel)

def _apply_hostility_escalation(session_id, new_relational_session, batch_events):
    """Section 5 + 6.3 du doc d'origine, systeme SEPARE des 3 axes. Un seul
    niveau scalaire 0-4 :
    1 = agacement/froideur, 2 = retrait partiel, 3 = refus d'engagement,
    4 = limite durable. Escalade plafonnee a +1 palier/session (meme logique
    que 6.3 pour les axes). Desescalade volontairement lente : exige
    plusieurs sessions qualifiantes CONSECUTIVES sans aucun evenement
    d'hostilite avant de redescendre d'un palier -- jamais un simple
    compteur inverse (une seule bonne session ne suffit pas, cf. section 4)."""
    if not session_id:
        return
    rel = _load("relationship/relationship.json", {})
    esc = rel.setdefault("escalade_hostile", {
        "niveau": 0, "last_moved_session": None,
        "sessions_positives_consecutives": 0, "last_counted_session_id": None,
    })

    hostility_events = [e for e in batch_events if e.get("importance", 0) >= 5 and e.get("category") in HOSTILITY_CATEGORIES]
    positive_events = [e for e in batch_events if e.get("importance", 0) >= 5 and e.get("category") not in HOSTILITY_CATEGORIES]
    already_moved_this_session = esc.get("last_moved_session") == session_id

    if hostility_events and not already_moved_this_session:
        cats_present = {e["category"] for e in hostility_events}
        implied = esc["niveau"]
        if "hostilite_isolee" in cats_present: implied = max(implied, 1)
        if "hostilite_repetee" in cats_present: implied = max(implied, 2)
        if "rejet_engagement" in cats_present: implied = max(implied, 3)
        if esc["niveau"] >= 3: implied = max(implied, 4)  # persistance malgre le niveau deja atteint
        new_niveau = min(implied, esc["niveau"] + 1, 4)  # jamais plus d'1 palier/session, meme si implied saute plus loin
        if new_niveau > esc["niveau"]:
            esc["niveau"] = new_niveau
            esc["last_moved_session"] = session_id
        esc["sessions_positives_consecutives"] = 0  # une hostilite casse le streak de desescalade
    elif not hostility_events and positive_events and esc["niveau"] > 0:
        if new_relational_session and esc.get("last_counted_session_id") != session_id:
            esc["sessions_positives_consecutives"] = esc.get("sessions_positives_consecutives", 0) + 1
            esc["last_counted_session_id"] = session_id
            threshold = cfg("relationship", "positive_sessions_to_deescalate", default=2)
            if esc["sessions_positives_consecutives"] >= threshold and not already_moved_this_session:
                esc["niveau"] = max(0, esc["niveau"] - 1)
                esc["sessions_positives_consecutives"] = 0
                esc["last_moved_session"] = session_id

    _save("relationship/relationship.json", rel)

HOSTILITY_LEVEL_TEXT = {
    1: "Niveau d'escalade hostile actuel : agacement / froideur accrue, suite à une hostilité isolée récente.",
    2: "Niveau d'escalade hostile actuel : retrait partiel — réponses plus courtes, moins d'élaboration, fermeture sur le sujet.",
    3: "Niveau d'escalade hostile actuel : refus d'engagement — pattern d'hostilité confirmé sur plusieurs sessions distinctes.",
    4: "Niveau d'escalade hostile actuel : limite durable — froideur/distance qui ne se répare plus facilement.",
}

def synthesize_relationship_narrative():
    """Traduit axes_internes en paragraphe narratif, format valide au point
    9.3 du doc d'origine ('Incident d'integrite... Explication consideree
    comme credible... Relation actuellement stable mais prudence accrue').
    C'est la SEULE fonction autorisee a lire axes_internes pour construire du
    texte envoye a Claude -- aucun nombre ne doit fuiter au-dela d'ici.
    Deterministe et local (pas d'appel API supplementaire) pour le v1 ;
    remplacable par une synthese via LLM plus tard si besoin de nuance."""
    rel = _load("relationship/relationship.json", {})
    axes = rel.get("axes_internes", {})

    # Pacing d'abord (voir plus bas pour le detail) : necessaire pour plafonner
    # l'affichage qualitatif des axes juste en dessous, evite d'envoyer
    # "confiance solide" et "relation encore recente" dans la meme synthese --
    # incoherence reperee concretement le 20 aout (confiance/affection/
    # securite deja hautes alors que le pacing temps+sessions ne l'etait pas).
    premiere = axes.get("premiere_session_date")
    elapsed_days = None
    if premiere:
        try:
            elapsed_days = (datetime.now(timezone.utc) - datetime.fromisoformat(premiere)).days
        except (TypeError, ValueError):
            elapsed_days = None
    sessions_count = axes.get("sessions_qualifiantes_comptees", 0)
    securite_raw = axes.get("securite", 0)
    pacing_established = (elapsed_days is not None and elapsed_days >= 60 and sessions_count >= 20 and securite_raw >= 5)

    def _level(v):
        if v <= -2: label = "fortement endommagée"
        elif v == -1: label = "légèrement entamée"
        elif v == 0: label = "neutre, pas encore établie"
        elif v <= 2: label = "en construction"
        elif v <= 4: label = "solide"
        else: label = "très solide"
        # Plafond : tant que le pacing temps+sessions n'est pas etabli, jamais
        # "solide"/"tres solide" -- la progression peut etre rapide en interne,
        # mais ne doit jamais se presenter comme acquise/meritee narrativement.
        if not pacing_established and label in ("solide", "très solide"):
            return "en progression rapide, mais encore récente (pas encore éprouvée dans la durée)"
        return label

    parts = [
        f"Confiance : {_level(axes.get('confiance', 0))}.",
        f"Affection : {_level(axes.get('affection', 0))}.",
        f"Sécurité relationnelle : {_level(axes.get('securite', 0))}.",
    ]

    # Garde-fou de pacing : COMBINE temps calendaire reel ecoule ET nombre de
    # sessions distinctes, jamais l'un sans l'autre -- c'est la resolution deja
    # actee section 4 du doc d'origine ("le temps comme espace pour que la
    # fiabilite se prouve elle-meme", pas un compteur passif seul, mais pas
    # non plus des actions seules sans temps reel : sinon un usage tres
    # frequent (plusieurs sessions/jour) atteindrait "plusieurs mois" de
    # progression en quelques jours calendaires, ce qui a ete repere
    # concretement le 20 aout). Seuils provisoires (60 jours, 20 sessions,
    # securite>=5), a ajuster avec l'usage reel -- aucun des deux n'a ete
    # valide sur des donnees longues.
    if not pacing_established:
        parts.append(
            "Pacing romance : relation encore récente (pas plusieurs mois de temps réel + "
            "conversations cumulées). Toute déclaration ou avance romantique reçoit un "
            "DÉMONTAGE SEC de Kurisu -- catégorique, sans ambiguïté, sans porte entrouverte "
            "(\"avec le temps peut-être\" est INTERDIT), recentrage immédiat sur le travail. "
            "Trouble physique bref possible (léger rougissement, phrase interrompue -- "
            "niveau 2-3 de son échelle habituelle), jamais un emballement complet "
            "(rougissement jusqu'aux oreilles, tremblements, bégaiement -- niveau 4, réservé "
            "à une confiance vraiment établie). Tsundere = déstabilisée en surface, "
            "inflexible sur le fond -- pas l'inverse."
        )

    unresolved = [m for m in rel.get("marques_integrite", []) if m.get("status") != "resolue"]
    status_text = {
        "non_resolue": "incident d'intégrité non abordé",
        "expliquee_acceptee_provisoirement": "incident d'intégrité expliqué, accepté provisoirement — prudence accrue sur ce sujet",
    }
    for m in unresolved:
        parts.append(f"{status_text.get(m.get('status'), m.get('status'))} ({m.get('date', 'date inconnue')}).")

    niveau_hostile = rel.get("escalade_hostile", {}).get("niveau", 0)
    if niveau_hostile > 0:
        parts.append(HOSTILITY_LEVEL_TEXT.get(niveau_hostile, ""))

    return " ".join(parts)

def _relationship_context_text(limit_events=8):
    """Construit le bloc RELATION injecte a Claude : synthese narrative des
    axes (jamais de nombre, voir synthesize_relationship_narrative) + les
    evenements recents en clair. Remplace l'ancien json.dumps(relationship.json)
    brut qui aurait expose axes_internes tel quel des que les axes existeraient."""
    rel = _load("relationship/relationship.json", {})
    events = sorted(rel.get("important_events", []), key=lambda e: e.get("date", ""))[-limit_events:]
    events_text = "\n".join(f"- {e['content']}" for e in events if e.get("content"))
    narrative = synthesize_relationship_narrative()
    return f"{narrative}\nÉVÉNEMENTS RÉCENTS :\n{events_text}" if events_text else narrative

def update_relationship(**changes):
    rel=_load("relationship/relationship.json",{}); rel.update({k:v for k,v in changes.items() if v is not None}); _save("relationship/relationship.json",rel); return rel

# Echelle de ponderation des evenements relationnels (section 4 du patch,
# 20 aout 2026). 1=anecdotique, 3=notable, 5=significatif, 7=fort,
# 9-10=pivot relationnel majeur. Remplace l'ancien champ importance mixte
# (string "normal" / int 4-7) qui ne permettait aucun tri programmatique.
RELATIONSHIP_IMPORTANCE_SCALE = {
    1: "Anecdotique, contexte de fond",
    3: "Notable, contribue a la continuite",
    5: "Significatif, moment pedagogique ou relationnel reel",
    7: "Fort, marque potentiellement durable",
    9: "Pivot relationnel majeur (aveu, transgression grave)",
}

# Categories connues (section 5 du patch). transgression_confiance reste un
# fallback generique pour les cas ambigus ; transgression_competence et
# transgression_integrite sont les sous-types prefères, requis par la
# distinction de Kim et al. 2004 (point 7.1 du doc d'origine) -- une excuse
# repare mieux une violation de competence, un deni repare mieux une
# violation d'integrite, et l'integrite laisse une marque plus difficile a
# effacer (voir _apply_axis_movements / marques_integrite ci-dessous).
RELATIONSHIP_CATEGORIES = {
    "vulnerabilite_partagee", "limite_posee", "intrusion_tiers",
    "transgression_confiance", "transgression_competence", "transgression_integrite",
    "reparation", "curiosite_intellectuelle", "admiration_intellectuelle",
    "hostilite_isolee", "hostilite_repetee", "rejet_engagement",
}

# Section 5 du doc d'origine : hostilite gratuite (insultes, rejet actif),
# categorie DISTINCTE des transgressions de confiance -- limite_posee reste
# reservee au cas ou c'est KURISU qui pose une limite saine (ex: refuser
# d'enable l'evitement), ces trois-la decrivent une hostilite reelle venant
# de l'utilisateur.
HOSTILITY_CATEGORIES = {"hostilite_isolee", "hostilite_repetee", "rejet_engagement"}

# Mapping categorie -> axe(s) touches, section 9.2 du doc d'origine (confiance
# / affection / securite). Choix de conception explicite, a valider/ajuster :
# - vulnerabilite_partagee touche securite en priorite (Bowlby/Edmondson :
#   pouvoir etre vulnerable sans craindre le rejet) et affection en second
# - limite_posee touche confiance (previsibilite/structure saine, pas une
#   sanction)
# - intrusion_tiers ne bouge aucun axe directement : c'est Kurisu qui agit,
#   pas une action de l'utilisateur envers elle (voir section 1 du doc)
# - transgression_* baisse confiance ; integrite pose EN PLUS une marque
#   persistante qu'une reparation attenue mais n'efface jamais totalement
#   (section 3 du doc d'origine)
CATEGORY_AXIS_EFFECTS = {
    "vulnerabilite_partagee": {"securite": 1, "affection": 1},
    "limite_posee": {"confiance": 1},
    "curiosite_intellectuelle": {"affection": 1},
    "admiration_intellectuelle": {"affection": 1, "confiance": 1},
    "reparation": {"confiance": 1},
    "transgression_confiance": {"confiance": -1},
    "transgression_competence": {"confiance": -1},
    "transgression_integrite": {"confiance": -1},
    "intrusion_tiers": {},
}

AXES = ("confiance", "affection", "securite")

def add_relationship_event(content, importance=3, category=None, session_id=None, new_relational_session=False):
    """importance : entier 1/3/5/7/9-10, voir RELATIONSHIP_IMPORTANCE_SCALE.
    session_id / new_relational_session : fournis par l'appelant (server.py,
    via _is_new_relational_session()) -- Claude ne connait pas les bornes de
    session, ce n'est pas a l'extraction de les inventer.
    Retourne None si content est vide (bruit d'extraction) -- jamais stocke,
    jamais compte pour le vote de mouvement d'axes."""
    content = (content or "").strip()
    if not content:
        return None
    if not isinstance(importance, int):
        importance = 3  # valeur provisoire prudente, jamais une supposition d'exactitude
    rel = _load("relationship/relationship.json", {})
    event = {
        "date": now(),
        "content": content,
        "importance": importance,
        "category": category if category in RELATIONSHIP_CATEGORIES else None,
        "session_id": session_id,
        "new_relational_session": bool(new_relational_session),
        "salience": 1.0,
    }
    rel.setdefault("important_events", []).append(event)
    _save("relationship/relationship.json", rel)
    return rel

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
        "CONTEXTE TEMPOREL : "+_current_temporal_context_text(),
        "IDENTITÉ (résumé) : "+json.dumps(c["identity"],ensure_ascii=False),
        "IDENTITÉ (fiche complète) :\n"+c["identity_full"],
        "CANON (résumé) : "+json.dumps(c["canon"],ensure_ascii=False),
        "CANON (lorebook complet) :\n"+c["canon_full"],
        "RELATION : "+_relationship_context_text(),
        "ÉTAT ÉMOTIONNEL DU MOMENT : "+synthesize_emotional_state_narrative(),
        "RÉFLEXIONS RÉCENTES (recul de Kurisu sur sa propre évolution) :\n"+(_recent_reflections_text() or "aucune"),
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
        "CONTEXTE TEMPOREL : "+_current_temporal_context_text(),
        "RELATION : "+_relationship_context_text(),
        "ÉTAT ÉMOTIONNEL DU MOMENT : "+synthesize_emotional_state_narrative(),
        "RÉFLEXIONS RÉCENTES (recul de Kurisu sur sa propre évolution) :\n"+(_recent_reflections_text() or "aucune"),
        "ÉTAT : "+json.dumps(c["state"],ensure_ascii=False),
        "ACADÉMIQUE : "+json.dumps(c["academic"],ensure_ascii=False),
        "SOUVENIRS PERTINENTS :\n"+"\n".join("- "+m["content"] for m in c["relevant_memories"]),
        "ÉVOLUTION APPROUVÉE : "+json.dumps(c["approved_evolution"],ensure_ascii=False)
    ]))
    return static_text, dynamic_text

def add_reflection(content, session_id=None):
    """Equivalent Huginn (6.9, patch du 20 aout) : synthese de premier rang,
    stockee a part de important_events -- pas le meme cycle de vie (jamais
    revue a la baisse comme les axes, jamais reparee comme une marque
    d'integrite), et fichier dedie plutot que relationship.json pour ne pas
    transformer ce dernier en fourre-tout, dans une optique de memoire sur
    plusieurs annees."""
    content = (content or "").strip()
    if not content:
        return None
    reflections = _load("data/reflections.json", [])
    item = {
        "id": str(uuid.uuid4()),
        "date": now(),
        "session_id": session_id,
        "content": content,
    }
    reflections.append(item)
    _save("data/reflections.json", reflections)
    return item

def _recent_reflections_text(limit=2):
    """N'injecte que les toutes dernieres reflexions dans le contexte -- ce
    sont des syntheses deja condensees sur plusieurs evenements, pas la peine
    d'en remonter beaucoup a chaque tour (cout token)."""
    reflections = _load("data/reflections.json", [])
    if not reflections:
        return ""
    recent = sorted(reflections, key=lambda r: r.get("date", ""))[-limit:]
    return "\n".join(f"- {r['content']}" for r in recent if r.get("content"))

def _recent_events_for_reflection(limit=10):
    """Evenements deja logues dans important_events, fournis en LECTURE SEULE
    a l'etape de reflexion -- corrige le bug ou la reflexion ne voyait que
    les turn_limit derniers tours bruts (= extraction_interval, 2 chez Gwen),
    beaucoup trop etroit pour reperer un theme recurrent. Utiliser des
    evenements deja extraits plutot qu'elargir la fenetre de tours bruts
    evite aussi tout risque de re-extraction/doublon sur des tours deja
    traites par un cycle d'extraction periodique precedent."""
    rel = _load("relationship/relationship.json", {})
    events = sorted(rel.get("important_events", []), key=lambda e: e.get("date", ""))[-limit:]
    lines = [
        f"- [{e.get('date','?')}] (catégorie: {e.get('category') or 'aucune'}, importance {e.get('importance','?')}) {e.get('content','')}"
        for e in events if e.get("content")
    ]
    return "\n".join(lines)

def _unresolved_incidents_context():
    """Construit la liste des incidents d'integrite non resolus actuellement,
    pour que l'extraction puisse RECONNAITRE quand un nouvel echange en cloture
    un -- sans ca, chaque batch d'extraction ne voit que sa fenetre de tours
    bruts et n'a aucune idee qu'une transgression a deja ete loguee, donc ne
    peut jamais tagger correctement une reparation qui y fait suite."""
    rel = _load("relationship/relationship.json", {})
    marks = [m for m in rel.get("marques_integrite", []) if m.get("status") == "non_resolue"]
    if not marks:
        return ""
    lines = ["INCIDENTS D'INTÉGRITÉ NON RÉSOLUS ACTUELLEMENT (contexte de référence -- ne pas les re-décrire comme de nouveaux événements ; si un des tours ci-dessous y fait référence ou le clôture, vois les instructions plus bas) :"]
    for m in marks:
        lines.append(f"- [date: {m.get('date','?')}] {m.get('content','')}")
    return "\n".join(lines)

def extract_memories_with_provider(provider_name="claude", turn_limit=10, reflect=False):
    from providers import get_provider
    interactions = _load("data/interactions.json", [])[-max(1, int(turn_limit)):]
    if not interactions:
        return {"memories": [], "relationship_events": [], "academic_observations": [], "evolution_proposals": []}
    system = """You are Fylgja's memory extractor. Analyze recent conversations between a user and Kurisu. Return ONLY valid JSON with keys memories, relationship_events, academic_observations, evolution_proposals. Do not invent facts. Only store useful durable information.

CRITICAL — PRESERVE EXACT DETAILS: When a specific number, name, date, or concrete detail was stated, keep it verbatim in the memory content. Do not compress "the user got 18/20 on the fractions exercise" into "the user did an exercise" or "the user mentioned struggling with a formula they'd seen before" into "the user has recurring difficulties." Vague summaries destroy the value of the memory. If the exact number/name/date is present in the conversation, it must be present in the stored memory. Prefer a slightly longer precise memory over a short vague one."""

    incidents_context = _unresolved_incidents_context()
    if incidents_context:
        system += "\n\n" + incidents_context + "\n\nIf one of the turns below explains, addresses, or resolves one of these incidents, tag that event category=\"reparation\" AND set \"incident_date\" to the exact [date: ...] value of the incident it resolves (copy it verbatim from the list above). If several turns could plausibly apply, pick the incident actually being discussed, not just the most recent one in the list. Omit incident_date entirely if no listed incident applies."

    salience_hint = _emotional_salience_hint()
    if salience_hint:
        system += "\n\n" + salience_hint

    system += """

RELATIONSHIP_EVENTS — importance scale (integer, do not use words like "normal"):
- 1 = anecdotal, background context only
- 3 = notable, contributes to continuity but not pivotal
- 5 = significant, a real pedagogical or relational moment
- 7 = strong, likely to leave a lasting mark
- 9 or 10 = major relational pivot (direct admission of feelings, serious breach of trust)
Judge each event on its own terms. A passing remark and a direct confession of feelings must NOT receive the same score.

RELATIONSHIP_EVENTS — category (pick the single best fit, or omit the field if none fit — never invent a new category):
vulnerabilite_partagee, limite_posee, intrusion_tiers, reparation, curiosite_intellectuelle, admiration_intellectuelle

GENERAL PRINCIPLE, apply this before anything below: when an event describes both what the user did/said AND how Kurisu reacted, categorize by the UNDERLYING TRIGGER (the user's action, or the state of an ongoing incident) — never by the surface tone of Kurisu's reaction alone. Several very different situations can produce a similarly firm, boundary-sounding response from her (a new boundary, an incident being resolved, hostility being met with firmness, a genuine transgression) — read what actually happened, not just how she said it.

- limite_posee vs hostilite_* : limite_posee is for when KURISU asserts a healthy boundary (e.g. refusing to enable avoidance of the actual lesson) — a POSITIVE, trust-building moment. hostilite_isolee / hostilite_repetee / rejet_engagement are for genuine hostility or rejection coming FROM the user — never tag these limite_posee even if Kurisu's reaction looks like her setting a limit:
  - hostilite_isolee : a single insult, contempt, or dismissive/hostile remark directed AT KURISU SPECIFICALLY — not a sarcastic or evasive remark about the user's own situation (that's deflection, not hostility; consider vulnerabilite_partagee or no tag at all if nothing else fits)
  - hostilite_repetee : hostility (as defined above, directed at Kurisu) repeated within the same conversation or across recent turns
  - rejet_engagement : the user actively refuses to continue or explicitly rejects the help/relationship (e.g. "I don't care, forget this") — tag the user's rejection itself, not Kurisu's reaction to it

- limite_posee vs reparation : if the event describes Kurisu CLOSING OUT or RESOLVING a previously-established incident (a trust violation, a hostile moment) — even if her tone sounds firm, refuses empty apologies, or insists on behavior change going forward — tag it reparation, not limite_posee. limite_posee is reserved for a NEW boundary about ongoing behavior, not for resolving something that already happened. Ask: is this line being drawn for the first time (limite_posee), or is Kurisu wrapping up something already flagged earlier (reparation)?

- vulnerabilite_partagee vs reparation : vulnerabilite_partagee is for emotional openness or self-disclosure in general (fears, insecurities, personal admissions) — it does NOT require a prior incident to exist. reparation specifically closes out a previously flagged trust or hostility incident. An admission that explains WHY a past transgression happened (e.g. "I panicked, I felt worthless") can reasonably be tagged either depending on whether it reads as resolving that incident or as a separate emotional disclosure — when genuinely unsure, prefer reparation if a prior transgression/hostility event exists in recent turns, since that keeps the incident's repair state accurate.

For trust violations, prefer the specific subtype over the generic one whenever you can tell which applies (Kim et al. 2004 — competence and integrity violations repair differently and integrity leaves a longer-lasting mark):
- transgression_competence : a failure, mistake, or misunderstanding (she got something wrong, missed something)
- transgression_integrite : a deliberate lie, manipulation, or broken promise
- transgression_confiance : only if genuinely unclear which of the two applies

Do NOT invent session_id or new_relational_session for relationship_events — those are added by the caller after extraction, not by you."""

    if reflect:
        system += """

REFLECTION_SYNTHESIS — this batch marks the start of a new distinct relational session (a real return after a gap, not just a lull inside the same session). In addition to the usual keys, add a top-level "reflection_synthesis" key: a short (2-4 sentences) step-back synthesis, not a restatement of any single event. Base this on the ALREADY-LOGGED EVENTS listed below, together with the raw turns provided.

Even just TWO events sharing a common undertone already counts as a pattern worth naming — do not hold out for a long track record. Phrase tentative observations with appropriate hedging ("a pattern may be starting to form...", "twice now...") rather than stating them as settled fact. Example: two logged events about forgetting course material and mixing up chapters both point to a possible organizational/follow-through issue — that is enough to write a short tentative synthesis, not a reason to stay silent.

Do NOT re-emit any of the already-logged events below as new relationship_events; they exist only as context for this synthesis. Do not invent a trend that isn't there at all — omit the "reflection_synthesis" key only if the events are genuinely unrelated to each other with nothing in common, not merely because there are few of them."""
        events_context = _recent_events_for_reflection()
        if events_context:
            system += "\n\nÉVÉNEMENTS DÉJÀ LOGUÉS (contexte pour la réflexion uniquement) :\n" + events_context

    user = "\n\n".join(f"TURN {x['turn_id']}\nUSER: {x['user']}\nKURISU: {x['assistant']}" for x in interactions)
    raw = get_provider(provider_name).generate(system, user, max_tokens=2500, skip_routing=True)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    return json.loads(raw)


def apply_extraction(data, session_id=None, new_relational_session=False):
    """session_id / new_relational_session : etat de session calcule par
    l'appelant (server.py, via _is_new_relational_session()) et applique a
    TOUS les relationship_events de ce batch d'extraction -- un seul appel
    d'extraction correspond a un seul point de decision de session, jamais
    invente par Claude lui-meme (voir prompt ci-dessus)."""
    out={"memories":0,"relationship_events":0,"academic_observations":0,"evolution_proposals":0,"reflection":False}
    reflection_content = (data.get("reflection_synthesis") or "").strip()
    if reflection_content:
        add_reflection(reflection_content, session_id)
        out["reflection"] = True
    for x in data.get("memories",[]):
        add_memory(x.get("content",""),x.get("kind","episodic"),x.get("importance","normal"),x.get("tags",[]),"claude_extractor"); out["memories"]+=1
    new_relationship_events=[]
    for x in data.get("relationship_events",[]):
        raw_importance = x.get("importance", 3)
        try: importance = int(raw_importance)
        except (TypeError, ValueError): importance = 3
        category = x.get("category")
        result = add_relationship_event(x.get("content",""), importance, category, session_id, new_relational_session)
        if result is None:
            continue  # contenu vide -- rejete par add_relationship_event, jamais compte
        new_relationship_events.append({"content": x.get("content",""), "importance": importance, "category": category, "date": now(), "incident_date": x.get("incident_date")})
        out["relationship_events"]+=1
    if new_relationship_events:
        _apply_axis_movements(session_id, new_relational_session, new_relationship_events)
        _apply_hostility_escalation(session_id, new_relational_session, new_relationship_events)
        _apply_emotional_events(session_id, new_relationship_events)
    for x in data.get("academic_observations",[]):
        add_observation(x.get("content",""),x.get("category","learning")); out["academic_observations"]+=1
    for x in data.get("evolution_proposals",[]):
        propose_evolution(x.get("proposal",""),x.get("reason",""),x.get("category","personality")); out["evolution_proposals"]+=1
    return out
