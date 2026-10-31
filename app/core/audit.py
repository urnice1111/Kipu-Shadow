"""Leak audit with the same matching rules the judge uses (validar.mjs).

Every original form declared in entities.json is searched across the whole output, after
accent folding, confusable mapping and removal of digit separators.
"""

import re
from dataclasses import dataclass, field

from app.core.text import fold, is_loose_name, judge_compact_digits, judge_contains, judge_norm


def flatten(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool):
        return ["True" if value else "False"]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [x for v in value for x in flatten(v)]
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in [k, *flatten(v)]]
    return [str(value)]


def record_text(rec: dict) -> str:
    return " | ".join(flatten({k: v for k, v in rec.items() if k != "id"}))


@dataclass
class AuditReport:
    leaks: list[dict] = field(default_factory=list)
    unused_pseudonyms: list[dict] = field(default_factory=list)
    checked_forms: int = 0

    @property
    def ok(self) -> bool:
        return not self.leaks and not self.unused_pseudonyms


def audit(outputs: dict[str, list[dict]], entities: list[dict]) -> AuditReport:
    records = {r["id"]: r for recs in outputs.values() for r in recs}
    texts = {rid: record_text(r) for rid, r in records.items()}
    norm = {rid: judge_norm(t) for rid, t in texts.items()}
    compact = {rid: judge_compact_digits(t) for rid, t in texts.items()}
    whole_norm = "\n".join(norm.values())
    whole_compact = "\n".join(compact.values())
    kept = [o for e in entities if e.get("kept") for o in e.get("originals", []) if len(o) >= 4]
    kept_norm = [(judge_norm(k), judge_compact_digits(k)) for k in kept]

    report = AuditReport()
    for e in entities:
        if e.get("kept"):
            continue
        for kind, value in (e.get("pseudonyms") or {}).items():
            recs = [r for r in e.get("records", []) if r in records]
            if recs and not any(judge_contains(norm[r], compact[r], value) for r in recs):
                report.unused_pseudonyms.append({"entity": e["entity_id"], "kind": kind, "value": value})
        for orig in e.get("originals", []):
            if len(orig) < 3 or is_loose_name(orig):
                continue
            if any(judge_contains(kn, kc, orig) for kn, kc in kept_norm):
                continue
            report.checked_forms += 1
            if not judge_contains(whole_norm, whole_compact, orig):
                continue
            hits = [rid for rid in records if judge_contains(norm[rid], compact[rid], orig)]
            if hits:
                report.leaks.append({"entity": e["entity_id"], "original": orig, "records": hits[:5]})
    return report


def scrub(outputs: dict[str, list[dict]], report: AuditReport, entities: list[dict]) -> int:
    """Last-resort fix for leaked name forms: replace them with the entity's name pseudonym."""
    by_id = {e["entity_id"]: e for e in entities}
    fixes = 0
    for leak in report.leaks:
        orig = leak["original"]
        name = (by_id[leak["entity"]].get("pseudonyms") or {}).get("name")
        if not name or re.search(r"\d|@", orig):
            continue
        words = fold(orig).split()
        rx = re.compile(r"(?<![a-z0-9])" + r"[\s_.\-]*".join(map(re.escape, words)) + r"(?![a-z0-9])")
        targets = set(leak["records"])
        for recs in outputs.values():
            for rec in recs:
                if rec["id"] in targets:
                    fixes += _scrub_record(rec, rx, name)
    return fixes


def _scrub_record(rec: dict, rx: re.Pattern, name: str) -> int:
    count = 0

    def fix(s: str) -> str:
        nonlocal count
        folded = fold(s)
        spans = [(m.start(), m.end()) for m in rx.finditer(folded)]
        for a, b in reversed(spans):
            s = s[:a] + name + s[b:]
            count += 1
        return s

    for key, value in list(rec.items()):
        if key == "id":
            continue
        if isinstance(value, str):
            rec[key] = fix(value)
        elif isinstance(value, dict):
            rec[key] = {k: fix(v) if isinstance(v, str) else v for k, v in value.items()}
        elif isinstance(value, list):
            rec[key] = [{k: fix(v) if isinstance(v, str) else v for k, v in a.items()} if isinstance(a, dict) else a for a in value]
    return count
