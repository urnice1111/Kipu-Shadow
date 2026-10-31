"""Apply the engine to whole records: chats with their thread context, docs, and table rows."""

import re
from collections import Counter, defaultdict

from app.core import detect
from app.core.engine import Ctx, Engine
from app.core.identities import Directory, build_directory
from app.core.lexicon import OCCUPATION_SECTOR
from app.core.registry import Registry
from app.core.text import digits, fold, norm_name, pour_digits

SECTOR_BY_FOLD = {fold(k): v for k, v in OCCUPATION_SECTOR.items()}


def barrios_by_city(table_records: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for rec in table_records:
        cols = rec["columns"]
        if rec["table"] == "clientes" and cols.get("ciudad") and cols.get("barrio"):
            out[cols["ciudad"]].add(cols["barrio"])
    return dict(out)


def text_fields(source: str, rec: dict) -> list[tuple[str, bool]]:
    """(text, is_filename) pairs worth scanning for unknown names."""
    if source == "chats":
        return [(rec.get("text", ""), False)] + [(a.get("filename", ""), True) for a in rec.get("attachments", [])]
    if source == "docs":
        return [(rec.get("title", ""), False), (rec.get("body", ""), False), (rec.get("filename", ""), True)] + [
            (v, False) for v in rec.get("metadata", {}).values()
        ]
    cols = rec.get("columns", {})
    keys = ("notas", "descripcion", "respuesta") if rec.get("table") in ("clientes", "pqrs", "transacciones") else cols
    return [(cols.get(k, ""), False) for k in keys if k in cols]


def discover_people(engine: Engine, batches: list[tuple[str, list[dict]]], key_suffix=None) -> int:
    """Add people named in free text who are in no table or profile. Returns how many were added."""
    names: Counter = Counter()
    authors: set[str] = set()
    for source, records in batches:
        for rec in records:
            for text, is_file in text_fields(source, rec):
                for name in engine.discover(text, lowercase_ok=is_file):
                    names[name] += 1
            author = " ".join(rec.get("author", "").split()) if source == "chats" else ""
            if author and not _known_name(engine, author):
                names[author] += 1
                authors.add(author)
    added = 0
    by_prefix: dict[tuple, str] = {}
    for name in sorted(names, key=lambda n: (-len(n.split()), n)):
        tokens = norm_name(name).split()
        prefix = tuple(tokens[:2])
        if prefix in by_prefix:
            engine.d.persons[by_prefix[prefix]].add_name(name)
            continue
        if len(tokens) < 2 and name not in authors:
            continue
        key = " ".join(tokens) + (key_suffix(name) if key_suffix else "")
        person = engine.d.add_ext(_title(name), key)
        by_prefix[prefix] = person.pid
        added += 1
    if added or names:
        engine.rebuild()
    return added


def _known_name(engine: Engine, author: str) -> bool:
    """Bots, kept names and people already in the directory are not new people."""
    folded = fold(author)
    if detect.KEPT and detect.KEPT.fullmatch(folded):
        return True
    if author in ("deactivateduser", "Usuario desconocido"):
        return True
    return bool(engine.name_rx and engine.name_rx.fullmatch(folded))


def _title(name: str) -> str:
    return " ".join(t if not t.islower() else t.capitalize() for t in name.split())


# --- chats -----------------------------------------------------------------------------------


def anonymize_chats(engine: Engine, chats: list[dict], meta: dict[str, dict] | None = None) -> list[dict]:
    meta = meta or {}
    d = engine.d
    threads: dict[str, list[dict]] = defaultdict(list)
    for rec in chats:
        threads[rec["thread_id"]].append(rec)
    thread_ctx: dict[str, list[str]] = {}
    for tid, msgs in threads.items():
        pids: list[str] = []
        for m in msgs:
            pid = author_pid(engine, m, meta)
            if pid and pid not in pids:
                pids.append(pid)
        thread_text = "\n".join(m.get("text", "") for m in msgs)
        for pid in d.pids_in_text(thread_text) + engine.named_pids(thread_text):
            if pid not in pids:
                pids.append(pid)
        thread_ctx[tid] = pids

    out = []
    for rec in chats:
        apid = author_pid(engine, rec, meta)
        mentions = [d.by_uid.get(u) for u in meta.get(rec["id"], {}).get("mentions", [])]
        internal = not rec["thread_id"].startswith("soporte-")
        ctx = Ctx(rec["id"], prefer="employee" if internal else "client")
        ctx.push(apid, *mentions, *d.pids_in_text(rec.get("text", "")), *thread_ctx[rec["thread_id"]])
        new = dict(rec)
        new["text"] = engine.generalize(engine.text(rec.get("text", ""), ctx))
        new["attachments"] = [{**a, "filename": engine.text(a.get("filename", ""), ctx)} for a in rec.get("attachments", [])]
        new["author"] = anonymize_author(engine, rec.get("author", ""), apid, ctx)
        out.append(new)
    return out


def author_pid(engine: Engine, rec: dict, meta: dict[str, dict]) -> str | None:
    info = meta.get(rec["id"])
    if info:
        return None if info.get("bot") else engine.d.by_uid.get(info.get("uid", ""))
    author = rec.get("author", "")
    if not author or not engine.name_rx:
        return None
    m = engine.name_rx.fullmatch(fold(author))
    if not m:
        return None
    ctx = Ctx(rec["id"]).push(*engine.d.pids_in_text(rec.get("text", "")))
    resolved = engine._resolve_name(m.group(0), author, ctx)
    return resolved[0] if resolved else None


def anonymize_author(engine: Engine, author: str, pid: str | None, ctx: Ctx) -> str:
    if not pid:
        return author
    actx = Ctx(ctx.record_id).push(pid, *ctx.pids)
    new = engine.text(author, actx)
    if new == author:
        plain = engine.render_name(pid, "all", "first")
        engine._hit(pid, ctx, author, "name", plain)
        return plain
    return new


# --- docs ------------------------------------------------------------------------------------


def anonymize_docs(engine: Engine, docs: list[dict]) -> list[dict]:
    out = []
    for rec in docs:
        everything = "\n".join([rec.get("title", ""), rec.get("body", ""), rec.get("filename", "")] + list(rec.get("metadata", {}).values()))
        ctx = Ctx(rec["id"], prefer="employee").push(*engine.d.pids_in_text(everything), *engine.named_pids(everything))
        new = dict(rec)
        new["title"] = engine.text(rec.get("title", ""), ctx)
        body = engine.text(rec.get("body", ""), ctx)
        # The judge reads the whole document: an occupation in one paragraph and a year or place in
        # another still sit in the same record.
        placed = engine.has_place_or_year(body)
        new["body"] = "\n\n".join(engine.generalize(p, location_hint=placed) for p in body.split("\n\n"))
        new["filename"] = engine.text(rec.get("filename", ""), ctx)
        new["metadata"] = {k: engine.text(v, ctx) for k, v in rec.get("metadata", {}).items()}
        out.append(new)
    return out


# --- tables ----------------------------------------------------------------------------------


def anonymize_tables(engine: Engine, rows: list[dict]) -> list[dict]:
    employees = [pid for pid, p in engine.d.persons.items() if p.kind == "employee"]
    out = []
    for rec in rows:
        table = rec["table"]
        cols = dict(rec["columns"])
        if table == "clientes":
            cols = _client_row(engine, rec["id"], cols)
        elif table == "empleados":
            cols = _employee_row(engine, rec["id"], cols, employees)
        elif table == "pqrs":
            cols = _pqrs_row(engine, rec["id"], cols)
        elif table == "transacciones":
            pid = engine.d.by_clid.get(cols.get("cliente_id", ""))
            ctx = Ctx(rec["id"]).push(pid)
            if "descripcion" in cols:
                cols["descripcion"] = engine.text(cols["descripcion"], ctx)
        else:
            everything = " ".join(cols.values())
            ctx = Ctx(rec["id"]).push(*engine.d.pids_in_text(everything))
            cols = {k: engine.text(v, ctx) for k, v in cols.items()}
        out.append({**rec, "columns": cols})
    return out


def _row_person(engine: Engine, row_id: str) -> str | None:
    return engine.d.by_row.get(row_id)


def _full_name(engine: Engine, pid: str, ctx: Ctx, surface: str) -> str:
    new = engine.text(surface, Ctx(ctx.record_id).push(pid))
    if new == surface and surface:
        plain = engine.render_name(pid, "all", "all")
        engine._hit(pid, ctx, surface, "name", plain)
        return plain
    return new


def _cedula(engine: Engine, pid: str, ctx: Ctx, surface: str) -> str:
    if not digits(surface):
        return surface
    new = engine.cedula_for(pid, digits(surface))
    engine._hit(pid, ctx, surface, "cedula", new)
    return pour_digits(surface, new)


def _phone(engine: Engine, pid: str, ctx: Ctx, surface: str) -> str:
    d = digits(surface)
    if not d:
        return surface
    core = d[2:] if len(d) == 12 and d.startswith("57") else d
    new = engine.phone_for(pid, core)
    engine._hit(pid, ctx, surface, "phone", new)
    return pour_digits(surface, new)


def _email(engine: Engine, pid: str, ctx: Ctx, surface: str) -> str:
    if "@" not in surface:
        return surface
    new = engine.email_for(pid, surface.strip().lower())
    engine._hit(pid, ctx, surface, "email", new)
    return new


def _birth(engine: Engine, pid: str, ctx: Ctx, surface: str) -> str:
    if not surface:
        return surface
    new = engine.birth_for(pid, surface)
    engine._hit(pid, ctx, surface, "birth_iso", new)
    return new


def _client_row(engine: Engine, row_id: str, cols: dict) -> dict:
    pid = _row_person(engine, row_id)
    if not pid:
        return cols
    ctx = Ctx(row_id).push(pid)
    if cols.get("nombre_completo"):
        cols["nombre_completo"] = _full_name(engine, pid, ctx, cols["nombre_completo"])
    if "num_doc" in cols:
        cols["num_doc"] = _cedula(engine, pid, ctx, cols["num_doc"])
    if "correo" in cols:
        cols["correo"] = _email(engine, pid, ctx, cols["correo"])
    if "celular" in cols:
        cols["celular"] = _phone(engine, pid, ctx, cols["celular"])
    if cols.get("direccion"):
        new = engine.address_for(pid, cols["direccion"])
        engine._hit(pid, ctx, cols["direccion"], "address", new)
        cols["direccion"] = new
    if "fecha_nacimiento" in cols:
        cols["fecha_nacimiento"] = _birth(engine, pid, ctx, cols["fecha_nacimiento"])
    if cols.get("barrio"):
        city = cols.get("ciudad", "")
        options = sorted(engine.barrios_by_city.get(city, set()) - {cols["barrio"]})
        if options:
            cols["barrio"] = engine.r.get(engine.uid(pid), "barrio", lambda rng, a: rng.choice(options), unique=False)
    occupation = cols.get("ocupacion", "")
    if occupation:
        cols["ocupacion"] = SECTOR_BY_FOLD.get(fold(occupation).strip(), "profesional independiente")
    if cols.get("notas"):
        # The row itself carries city and join date, so any occupation in the notes completes the triple.
        nctx = Ctx(row_id).push(pid, *engine.d.pids_in_text(cols["notas"]))
        cols["notas"] = engine.generalize(
            engine.text(cols["notas"], nctx), location_hint=True, city=cols.get("ciudad"), notes=True,
            own_occupation=occupation,
        )
    return cols


def _employee_row(engine: Engine, row_id: str, cols: dict, employees: list[str]) -> dict:
    pid = _row_person(engine, row_id)
    if not pid:
        return cols
    ctx = Ctx(row_id).push(pid)
    if cols.get("nombre"):
        cols["nombre"] = _full_name(engine, pid, ctx, cols["nombre"])
    if "correo" in cols:
        cols["correo"] = _email(engine, pid, ctx, cols["correo"])
    if "celular" in cols:
        cols["celular"] = _phone(engine, pid, ctx, cols["celular"])
    if "documento" in cols:
        cols["documento"] = _cedula(engine, pid, ctx, cols["documento"])
    if "fecha_nacimiento" in cols:
        cols["fecha_nacimiento"] = _birth(engine, pid, ctx, cols["fecha_nacimiento"])
    if cols.get("reporta_a"):
        bctx = Ctx(row_id).push(*employees)
        cols["reporta_a"] = engine.text(cols["reporta_a"], bctx)
    return cols


def _pqrs_row(engine: Engine, row_id: str, cols: dict) -> dict:
    d = engine.d
    pid = d.by_clid.get(cols.get("cliente_id", ""))
    agent = d.by_handle.get(cols.get("agente", ""))
    ctx = Ctx(row_id).push(pid, agent)
    if cols.get("cedula"):
        ced = digits(cols["cedula"])
        owner = d.by_cedula.get(ced) or pid
        if owner:
            cols["cedula"] = _cedula(engine, owner, ctx, cols["cedula"])
        elif ced:
            cols["cedula"] = pour_digits(cols["cedula"], engine.cedula_for(None, ced))
    if cols.get("agente") and agent:
        new = engine.handle_for(agent, cols["agente"])
        engine._hit(agent, ctx, cols["agente"], "handle", new)
        cols["agente"] = new
    for k in ("descripcion", "respuesta"):
        if cols.get(k):
            tctx = Ctx(row_id).push(pid, agent, *d.pids_in_text(cols[k]))
            cols[k] = engine.generalize(engine.text(cols[k], tctx), location_hint=bool(cols.get("ciudad")))
    return cols


# --- whole corpus ----------------------------------------------------------------------------


def prepare_engine(corpus, registry: Registry) -> Engine:
    directory = build_directory(corpus)
    engine = Engine(directory, registry, barrios_by_city(corpus.tables))
    discover_people(engine, [("chats", corpus.chats), ("docs", corpus.docs), ("tables", corpus.tables)])
    return engine


def anonymize_corpus(engine: Engine, corpus) -> dict[str, list[dict]]:
    return {
        "chats": anonymize_chats(engine, corpus.chats, corpus.chat_meta),
        "docs": anonymize_docs(engine, corpus.docs),
        "tables": anonymize_tables(engine, corpus.tables),
    }
