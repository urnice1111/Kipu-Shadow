"""Local probes for the hidden-test families, on the cached migrated corpus.

Runs the full engine in memory with a throwaway registry and prints counts plus a few
examples per family. Prints real data: run it locally only, never paste its output anywhere.

    .venv/bin/python scripts/probes.py [--examples 5]
"""

import argparse
import pickle
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import detect  # noqa: E402
from app.core.anonymize import anonymize_corpus, prepare_engine  # noqa: E402
from app.core.audit import record_text  # noqa: E402
from app.core.entities import build_entities  # noqa: E402
from app.core.lexicon import OCCUPATION_SECTOR  # noqa: E402
from app.core.registry import Registry  # noqa: E402
from app.core.text import digits, fold, judge_compact_digits, judge_contains, judge_norm, norm_name  # noqa: E402

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class Index:
    """Pre-normalized record texts so judge_contains stays cheap across thousands of lookups."""

    def __init__(self, records: dict[str, dict]):
        self.text = {rid: record_text(r) for rid, r in records.items()}
        self.norm = {rid: judge_norm(t) for rid, t in self.text.items()}
        self.compact = {rid: judge_compact_digits(t) for rid, t in self.text.items()}
        self.whole_norm = "\n".join(self.norm.values())
        self.whole_compact = "\n".join(self.compact.values())

    def has(self, rid: str, needle: str) -> bool:
        return rid in self.norm and judge_contains(self.norm[rid], self.compact[rid], needle)

    def where(self, needle: str) -> list[str]:
        if not judge_contains(self.whole_norm, self.whole_compact, needle):
            return []
        return [rid for rid in self.norm if judge_contains(self.norm[rid], self.compact[rid], needle)]


def snippet(text: str, needle: str, pad: int = 60) -> str:
    i = fold(text).find(fold(needle))
    if i < 0:
        return text[: 2 * pad].replace("\n", " ")
    return text[max(0, i - pad) : i + len(needle) + pad].replace("\n", " ")


def header(title: str, n: int) -> None:
    print(f"\n=== {title}: {n}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples", type=int, default=5)
    args = parser.parse_args()
    k = args.examples

    corpus = pickle.load(open(ROOT / "data/state/corpus_dev.pkl", "rb"))
    with tempfile.TemporaryDirectory() as tmp:
        engine = prepare_engine(corpus, Registry(Path(tmp) / "pseudonyms.db"))
        outputs = anonymize_corpus(engine, corpus)
        entities = build_entities(engine)
    d = engine.d

    inp = {r["id"]: r for src in (corpus.chats, corpus.docs, corpus.tables) for r in src}
    out = {r["id"]: r for src in outputs.values() for r in src}
    I, O = Index(inp), Index(out)
    by_uid = {e["entity_id"]: e for e in entities if not e.get("kept")}
    uid_of = {pid: engine.uid(pid) for pid in engine.hits}
    totals = {}

    def pseudos_of(pid: str) -> list[str]:
        ent = by_uid.get(uid_of.get(pid, ""))
        return list((ent or {}).get("pseudonyms", {}).values())

    sharing = defaultdict(set)
    for pid, p in d.persons.items():
        for n in p.names:
            if len(n.split()) >= 2:
                sharing[norm_name(n)].add(pid)

    # 1. Consistency: full names of a person found in the input whose record lacks every pseudonym
    # of every person who carries that name.
    missing = []
    for name_norm, pids in sharing.items():
        name = name_norm
        pseudos = [v for pid in pids for v in pseudos_of(pid)]
        for rid in I.where(name):
            if O.has(rid, name):
                continue
            if not pseudos or not any(O.has(rid, v) for v in pseudos):
                missing.append((sorted(pids), name, rid))
    totals["consistencia_registros_sin_seudonimo"] = len(missing)
    header("Consistencia: registros con el nombre real de una persona y sin ninguno de sus seudónimos", len(missing))
    for pid, name, rid in missing[:k]:
        print(f"  {pid} {name!r} en {rid}: {snippet(O.text[rid], '')[:160]!r}")

    # Judge-style consistency test for every client and employee: lookup forms like tests_public
    # (email, cédula with and without dots, phone, full name, given + first surname), one owning
    # entity, and the pseudonym present in every input record that carries one of those forms.
    def dotted(c: str) -> str:
        return f"{int(c):,}".replace(",", ".") if c.isdigit() else c

    form_owners = defaultdict(set)
    for pid, p in d.persons.items():
        for n in p.names:
            form_owners[norm_name(n)].add(pid)
    judge_fail = defaultdict(list)
    for pid, p in d.persons.items():
        if p.kind not in ("client", "employee") or not p.surnames:
            continue
        forms = sorted(p.emails) + sorted(p.cedulas) + [dotted(c) for c in sorted(p.cedulas)] + sorted(p.phones)
        full2 = p.canonical
        full = " ".join(p.given + p.surnames[:1])
        for n in (full2, full):
            if len(form_owners.get(norm_name(n), ())) <= 1:
                forms.append(n)
        owners = [e for e in entities if not e.get("kept") and set(forms) & set(e.get("originals", []))]
        if len(owners) != 1:
            judge_fail["entidades"].append((pid, p.canonical, [e["entity_id"] for e in owners]))
            continue
        pseudos = list(owners[0]["pseudonyms"].values())
        recs = sorted({rid for f in forms for rid in I.where(f)})
        miss = [rid for rid in recs if not any(O.has(rid, v) for v in pseudos)]
        if miss:
            judge_fail["registros"].append((pid, p.canonical, owners[0]["pseudonyms"].get("name"), miss[:3], len(recs)))
    totals["consistencia_juez_varias_entidades"] = len(judge_fail["entidades"])
    totals["consistencia_juez_registros_sin_seudonimo"] = len(judge_fail["registros"])
    header("Consistencia (como el juez): personas con 0 o varias entidades", len(judge_fail["entidades"]))
    for row in judge_fail["entidades"][:k]:
        print(f"  {row}")
    header("Consistencia (como el juez): personas con registros sin su seudónimo", len(judge_fail["registros"]))
    for row in judge_fail["registros"][:k]:
        print(f"  {row}")
        rid = row[3][0]
        print(f"     IN : {snippet(I.text[rid], '', 90)[:180]!r}")
        print(f"     OUT: {snippet(O.text[rid], '', 90)[:180]!r}")

    # Given names left literal in chats where their owner is the author or is mentioned in the thread.
    literal = []
    threads = defaultdict(list)
    for rec in corpus.chats:
        threads[rec["thread_id"]].append(rec)
    for tid, msgs in threads.items():
        owners = set()
        for m in msgs:
            info = corpus.chat_meta.get(m["id"], {})
            pid = d.by_uid.get(info.get("uid", ""))
            if pid:
                owners.add(pid)
        for pid in owners:
            p = d.persons[pid]
            if not p.given:
                continue
            first = p.given[0]
            rx = re.compile(rf"(?<![a-z0-9]){re.escape(fold(first))}(?![a-z0-9])")
            for m in msgs:
                o = out[m["id"]]["text"]
                if rx.search(fold(o)) and rx.search(fold(m["text"])):
                    literal.append((pid, first, m["id"], o))
    totals["nombre_de_pila_literal_en_hilo"] = len(literal)
    header("Consistencia: nombre de pila del dueño del hilo que sigue literal", len(literal))
    for pid, first, rid, o in literal[:k]:
        print(f"  {pid} {first!r} en {rid}: {snippet(o, first)!r}")

    # Slack-only persons whose name matches a client or employee (possible missed link).
    names_tab = defaultdict(list)
    for pid, p in d.persons.items():
        if p.kind in ("client", "employee"):
            names_tab[norm_name(p.canonical)].append(pid)
    slack_unlinked = [
        (pid, p.canonical, names_tab[norm_name(p.canonical)])
        for pid, p in d.persons.items()
        if pid.startswith("slack:") and names_tab.get(norm_name(p.canonical))
    ]
    totals["slack_sin_ligar_con_homonimo_en_tabla"] = len(slack_unlinked)
    header("Consistencia: perfiles de Slack sin ligar que se llaman como una fila", len(slack_unlinked))
    for row in slack_unlinked[:k]:
        print(f"  {row}")

    # 2. Homonyms: persons sharing first given name + first surname, and records where the name
    # was resolved with no evidence.
    groups = defaultdict(list)
    for pid, p in d.persons.items():
        if p.given and p.surnames:
            groups[f"{fold(p.given[0])} {fold(p.surnames[0])}"].append(pid)
    homs = {n: pids for n, pids in groups.items() if len(pids) >= 2}
    same_pseudo = []
    for n, pids in homs.items():
        rendered = {engine.render_name(pid, "all", "all") for pid in pids}
        if len(rendered) < len(pids):
            same_pseudo.append((n, pids))
    totals["grupos_homonimos"] = len(homs)
    totals["homonimos_mismo_seudonimo"] = len(same_pseudo)
    header("Homónimos: grupos con el mismo nombre completo", len(homs))
    for n, pids in list(homs.items())[:k]:
        print(f"  {n!r}: {[(pid, d.persons[pid].kind, engine.render_name(pid, 'all', 'all')) for pid in pids]}")
    header("Homónimos: grupos que comparten seudónimo", len(same_pseudo))
    for row in same_pseudo[:k]:
        print(f"  {row}")

    # For each homonym name, records that mention it: which candidate won, and whether any of
    # that candidate's strong ids (or a strong id of the other one) appear in the record or its thread.
    thread_of = {r["id"]: r["thread_id"] for r in corpus.chats}
    thread_text = {tid: "\n".join(m["text"] for m in msgs) for tid, msgs in threads.items()}
    unresolved = []
    for n, pids in homs.items():
        for rid in I.where(n):
            winners = [pid for pid in pids if pid in engine.hits and rid in engine.hits[pid].records]
            context = I.text[rid] + "\n" + thread_text.get(thread_of.get(rid, ""), "")
            evidence = set(d.pids_in_text(context))
            info = corpus.chat_meta.get(rid, {})
            if info.get("uid"):
                evidence.add(d.by_uid.get(info["uid"]))
            supported = [pid for pid in pids if pid in evidence]
            if len(winners) != 1 or not supported or winners[0] not in supported:
                unresolved.append((n, rid, winners, supported))
    totals["menciones_homonimo_sin_evidencia"] = len(unresolved)
    header("Homónimos: menciones resueltas sin evidencia fuerte del ganador", len(unresolved))
    for row in unresolved[:k]:
        print(f"  {row}")

    # 3. Indirect: occupation + place + year still together in one output record.
    occ_cols = defaultdict(int)
    for rec in corpus.tables:
        if rec["table"] == "clientes" and rec["columns"].get("ocupacion"):
            occ_cols[rec["columns"]["ocupacion"].strip()] += 1
    lex = {fold(o) for o in OCCUPATION_SECTOR}
    not_in_lex = sorted(o for o in occ_cols if fold(o) not in lex)
    totals["ocupaciones_fuera_del_lexico"] = len(not_in_lex)
    header("Indirecta: ocupaciones de clientes que no están en OCCUPATION_SECTOR", len(not_in_lex))
    print(f"  {not_in_lex}")

    barrios = {rec["columns"]["barrio"].strip() for rec in corpus.tables if rec["table"] == "clientes" and rec["columns"].get("barrio")}
    occupations = sorted({o for o in occ_cols} | set(OCCUPATION_SECTOR), key=len, reverse=True)
    occ_rx = re.compile(r"(?<![a-z])(" + "|".join(re.escape(fold(o)) for o in occupations) + r")(?![a-z])")
    bar_rx = re.compile(r"(?<![a-z])(" + "|".join(re.escape(fold(b)) for b in sorted(barrios, key=len, reverse=True)) + r")(?![a-z])")
    together = []
    for rid, rec in out.items():
        t = fold(O.text[rid])
        occ = occ_rx.search(t)
        if not occ:
            continue
        bar = bar_rx.search(t)
        yr = detect.YEAR.search(O.text[rid])
        if bar or yr:
            together.append((rid, occ.group(0), bar.group(0) if bar else None, yr.group(0) if yr else None))
    totals["ocupacion_con_barrio_o_anio"] = len(together)
    header("Indirecta: registros de salida con una ocupación real junto a barrio o año", len(together))
    for rid, occ, bar, yr in together[:k]:
        print(f"  {rid} ocupación={occ!r} barrio={bar!r} año={yr!r}: {snippet(O.text[rid], occ)!r}")

    # Master-row join: chat/doc output that names a client's real occupation or barrio while
    # their clientes row keeps the city and the year.
    joined = []
    for pid, p in d.persons.items():
        if p.kind != "client":
            continue
        for row in p.rows:
            cols = inp[row]["columns"]
            occ, bar = cols.get("ocupacion", ""), cols.get("barrio", "")
            for rid in engine.hits.get(pid).records if pid in engine.hits else ():
                if rid == row or rid not in out:
                    continue
                t = fold(O.text[rid])
                hit_occ = occ and re.search(rf"(?<![a-z]){re.escape(fold(occ))}(?![a-z])", t)
                hit_bar = bar and re.search(rf"(?<![a-z]){re.escape(fold(bar))}(?![a-z])", t)
                if hit_occ or hit_bar:
                    joined.append((pid, row, rid, occ if hit_occ else None, bar if hit_bar else None))
    totals["ocupacion_o_barrio_real_en_registros_del_cliente"] = len(joined)
    header("Indirecta: ocupación o barrio real del cliente en otros registros suyos", len(joined))
    for row in joined[:k]:
        print(f"  {row}: {snippet(O.text[row[2]], row[3] or row[4])!r}")

    # 4. Direct and hidden: every strong id and full name of every known person, searched in the output.
    direct = []
    for pid, p in d.persons.items():
        forms = [n for n in p.names if len(n.split()) >= 2]
        forms += list(p.emails) + list(p.cedulas) + list(p.phones) + list(p.addresses)
        for f in forms:
            if len(f) < 4:
                continue
            for rid in O.where(f)[:3]:
                direct.append((pid, f, rid))
    totals["formas_conocidas_en_salida"] = len(direct)
    header("Directa: formas de personas del directorio que siguen en la salida", len(direct))
    for pid, f, rid in direct[:k]:
        print(f"  {pid} {f!r} en {rid}: {snippet(O.text[rid], f)!r}")

    prose = []
    for pid, p in d.persons.items():
        for b in p.births:
            m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", b)
            if not m:
                continue
            y, mo, dd = m.groups()
            month = MONTHS[int(mo) - 1]
            for form in (f"{int(dd)} de {month} de {y}", f"{month} {int(dd)} de {y}", f"{int(dd)} {month} {y}", f"{dd}/{mo}/{y}", f"{int(dd)}/{int(mo)}/{y}"):
                for rid in O.where(form)[:2]:
                    prose.append((pid, form, rid))
    totals["nacimiento_en_otro_formato"] = len(prose)
    header("Directa: fechas de nacimiento reales en prosa u otro formato", len(prose))
    for row in prose[:k]:
        print(f"  {row}: {snippet(O.text[row[2]], row[1])!r}")

    initials = []
    for pid, p in d.persons.items():
        if len(p.given) and p.surnames:
            ini = f"{p.given[0][0]}. {p.surnames[0]}"
            for rid in O.where(ini)[:2]:
                if I.has(rid, ini):
                    initials.append((pid, ini, rid))
    totals["inicial_mas_apellido"] = len(initials)
    header("Directa: inicial + apellido real que siguen en la salida", len(initials))
    for row in initials[:k]:
        print(f"  {row}: {snippet(O.text[row[2]], row[1])!r}")

    # Digit runs that did not change and look like ids (7 to 10 digits, not amounts, not dates).
    runs = []
    for rid in out:
        ot = O.text[rid]
        for m in detect.DIGIT_RUN.finditer(ot):
            s = m.group(0)
            dg = digits(s)
            if not (7 <= len(dg) <= 12) or detect.DATE_LIKE.fullmatch(s) or detect.AMOUNT.fullmatch(s):
                continue
            if "." in s and len(s.split(".")[-1]) == 6:
                continue
            if I.has(rid, s):
                runs.append((rid, s, snippet(ot, s, 40)))
    totals["numeros_largos_sin_cambiar"] = len(runs)
    header("Oculta: números largos que no cambiaron (posibles ids sin dueño)", len(runs))
    for row in runs[:k]:
        print(f"  {row}")

    # Unknown names: capitalised given name + surname in the output that were already in the input.
    unknown = []
    for rid in out:
        ot = O.text[rid]
        for s, e in detect.find_names(ot, False, engine.given_names, engine.surname_names):
            name = ot[s:e]
            kept = detect.KEPT and detect.KEPT.search(fold(name))
            if len(name.split()) >= 2 and not kept and I.has(rid, name):
                unknown.append((rid, name))
    totals["nombres_sin_reemplazar"] = len(unknown)
    header("Oculta: nombre + apellido que siguen igual en la salida", len(unknown))
    for rid, name in unknown[:k]:
        print(f"  {rid} {name!r}: {snippet(O.text[rid], name)!r}")

    handles = []
    for rid in out:
        for m in re.finditer(r"(?<![\w.])@([a-z][a-z0-9._]{2,})", O.text[rid]):
            if m.group(0) in I.text[rid]:
                handles.append((rid, m.group(0)))
    totals["handles_sin_reemplazar"] = len(handles)
    header("Oculta: @handles que siguen igual en la salida", len(handles))
    for row in handles[:k]:
        print(f"  {row}: {snippet(O.text[row[0]], row[1])!r}")

    print("\n=== Resumen")
    for key, v in totals.items():
        print(f"  {key}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
