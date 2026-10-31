"""The judge's dictionary: what was found, what replaced it, and where."""

from app.core.engine import Engine
from app.core.lexicon import KEPT_REASON


def _best(counter) -> str | None:
    if not counter:
        return None
    return sorted(counter.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def _best_name(counter) -> str | None:
    multi = {k: v for k, v in counter.items() if len(k.split()) >= 2}
    return _best(multi) or _best(counter)


def build_entities(engine: Engine, records: set[str] | None = None) -> list[dict]:
    """records restricts the dictionary to a subset of record ids (used by /anonymize)."""
    by_uid: dict[str, dict] = {}
    for pid, hit in engine.hits.items():
        recs = hit.records if records is None else hit.records & records
        if not recs:
            continue
        uid = engine.uid(pid)
        entry = by_uid.setdefault(uid, {"originals": set(), "records": set(), "used": {}})
        entry["originals"] |= hit.originals
        entry["records"] |= recs
        for kind, counter in hit.used.items():
            entry["used"].setdefault(kind, type(counter)()).update(counter)

    short_by_uid = {}
    for pid in engine.hits:
        if engine.d.persons[pid].surnames:
            short_by_uid.setdefault(engine.uid(pid), engine.render_name(pid, "all", "first"))

    entities = []
    for uid in sorted(by_uid):
        entry = by_uid[uid]
        pseudonyms = {}
        used = entry["used"]
        if used.get("name"):
            short = short_by_uid.get(uid)
            if short and any(n == short or n.startswith(short + " ") for n in used["name"]):
                pseudonyms["name"] = short
            else:
                pseudonyms["name"] = _best_name(used["name"])
        for kind in ("email", "phone", "cedula", "address", "birth_iso", "handle", "plate", "account", "passport"):
            if used.get(kind):
                pseudonyms[kind] = _best(used[kind])
        if not pseudonyms:
            continue
        entities.append(
            {
                "entity_id": uid,
                "type": "person",
                "originals": sorted(o for o in entry["originals"] if o),
                "pseudonyms": pseudonyms,
                "records": sorted(entry["records"]),
            }
        )

    kept_terms = sorted(engine.kept_hits)
    for i, term in enumerate(kept_terms, 1):
        recs = engine.kept_hits[term] if records is None else engine.kept_hits[term] & records
        if not recs:
            continue
        entities.append(
            {
                "entity_id": f"kept_{i:03d}",
                "type": "organization_or_place",
                "originals": sorted(engine.kept_surface[term]),
                "pseudonyms": {},
                "records": sorted(recs),
                "kept": True,
                "reason": KEPT_REASON,
            }
        )
    return entities
