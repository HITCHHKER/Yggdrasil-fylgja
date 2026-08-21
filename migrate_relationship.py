"""Migration relationship.json — patch de confiance, 20 aout 2026.

Usage :
    python migrate_relationship.py relationship/relationship.json

Fait trois choses (section 3, 4, 5 du patch) :
1. Supprime les entrees a content vide (bruit d'extraction)
2. Convertit `importance` en entier partout. Les valeurs deja numeriques sont
   gardees telles quelles. Les valeurs non numeriques (ex: "normal") recoivent
   une valeur provisoire de 3 ET un flag `_needs_review: true` -- reclassifier
   automatiquement le poids relationnel d'un evenement sans relire son contenu
   serait justement l'erreur identifiee en section 2.2 du patch (un aveu de
   vulnerabilite majeur et une remarque anodine etaient tous deux "normal").
   Ce script ne devine pas ; il isole ce qui doit etre relu.
3. Reconstruit session_id / new_relational_session a partir des seuls
   timestamps existants, via la meme regle que _is_new_relational_session()
   (ecart >= distinct_session_gap_hours). Note : cette reconstruction ne
   verifie PAS min_turns (ca necessite data/interactions.json, absent ici) --
   elle pose seulement les bornes de session par ecart de temps.

Fait une sauvegarde .bak avant d'ecrire.
"""
from __future__ import annotations
import json, sys, shutil
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_GAP_HOURS = 4


def migrate(path: Path, gap_hours: float = DEFAULT_GAP_HOURS) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("important_events", [])

    cleaned = []
    dropped_empty = 0
    flagged_for_review = 0
    last_dt = None
    session_start = None
    session_count = 0

    for e in events:
        content = (e.get("content") or "").strip()
        if not content:
            dropped_empty += 1
            continue

        try:
            dt = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            dt = None

        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if last_dt is None or (dt - last_dt).total_seconds() >= gap_hours * 3600:
                session_start = dt
                session_count += 1
                new_session = True
            else:
                new_session = False
            last_dt = dt
            session_id = f"sess_{session_start.strftime('%Y-%m-%dT%H')}"
        else:
            # Pas de date exploitable : ne pas inventer de session.
            session_id, new_session = None, False

        importance = e.get("importance")
        needs_review = False
        if not isinstance(importance, int):
            importance = 3
            needs_review = True
            flagged_for_review += 1

        item = {
            "date": e.get("date"),
            "content": content,
            "importance": importance,
            "category": e.get("category"),  # a completer, voir section 4
            "session_id": session_id,
            "new_relational_session": new_session,
        }
        if needs_review:
            item["_needs_review"] = True
        cleaned.append(item)

    data["important_events"] = cleaned
    data.setdefault("axes_internes", {})
    data["axes_internes"]["sessions_qualifiantes_comptees"] = session_count

    print(f"Entrees vides supprimees : {dropped_empty}")
    print(f"Entrees marquees _needs_review (importance a reclasser) : {flagged_for_review}")
    print(f"Sessions distinctes reconstruites (seuil {gap_hours}h) : {session_count}")
    print("Rappel : min_turns non verifie ici (necessite interactions.json).")

    return data


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python migrate_relationship.py <chemin/vers/relationship.json>")
        sys.exit(1)

    target = Path(sys.argv[1])
    backup = target.with_suffix(target.suffix + ".bak")
    shutil.copy2(target, backup)
    print(f"Sauvegarde -> {backup}")

    migrated = migrate(target)
    target.write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ecrit -> {target}")
