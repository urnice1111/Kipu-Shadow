"""Who is who: one Person per real individual, linked across sources only by strong evidence.

Strong evidence is a shared email, cédula, phone, Slack uid or a table key (cliente_id,
employee id, radicado). A shared name alone never merges two people.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.core.lexicon import GIVEN, SURNAME_SET, gender_of
from app.core.text import digits, fold, norm_name

CL_ID = re.compile(r"\bCL-\d{3,}\b")
KP_ID = re.compile(r"\bKP-\d{2,}\b")
PQR_ID = re.compile(r"\bPQR-\d{4}-\d{3,}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
DIGIT_RUN = re.compile(r"\+?\d(?:[ .\-/]?\d)+")


def split_name(name: str) -> tuple[list[str], list[str]]:
    """Given names and surnames of a Spanish full name."""
    tokens = name.split()
    if len(tokens) <= 1:
        return tokens, []
    if len(tokens) == 2:
        return tokens[:1], tokens[1:]
    if len(tokens) == 3:
        second = fold(tokens[1])
        if second in GIVEN and second not in SURNAME_SET:
            return tokens[:2], tokens[2:]
        return tokens[:1], tokens[1:]
    return tokens[:-2], tokens[-2:]


# A form is the tokens of a name plus which parts of the person it covers:
# (given selector, surname selector) with "all", "first" or None.
FormKey = tuple[str, ...]


@dataclass
class Person:
    pid: str
    kind: str
    names: list[str] = field(default_factory=list)
    emails: set[str] = field(default_factory=set)
    cedulas: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    addresses: set[str] = field(default_factory=set)
    births: set[str] = field(default_factory=set)
    handles: set[str] = field(default_factory=set)
    uids: set[str] = field(default_factory=set)
    rows: set[str] = field(default_factory=set)

    def add_name(self, name: str) -> None:
        name = " ".join(name.split())
        if name and name not in self.names:
            self.names.append(name)
            self.names.sort(key=lambda n: (-len(n.split()), n))

    @property
    def canonical(self) -> str:
        return self.names[0] if self.names else ""

    @property
    def given(self) -> list[str]:
        return split_name(self.canonical)[0]

    @property
    def surnames(self) -> list[str]:
        return split_name(self.canonical)[1]

    @property
    def gender(self) -> str:
        return gender_of(self.given[0]) if self.given else "F"

    def registry_keys(self) -> list[str]:
        keys = [self.pid]
        keys += [f"uid:{u}" for u in sorted(self.uids)]
        keys += [f"email:{e}" for e in sorted(self.emails)]
        keys += [f"ced:{c}" for c in sorted(self.cedulas)]
        return keys

    def name_forms(self) -> dict[FormKey, tuple[str | None, str | None, bool]]:
        """Folded token tuples -> (given sel, surname sel, context_only)."""
        forms: dict[FormKey, tuple[str | None, str | None, bool]] = {}
        for name in self.names:
            g, s = split_name(name)
            g = [fold(t) for t in g]
            s = [fold(t) for t in s]
            if not g:
                continue

            def put(tokens, gsel, ssel, ctx_only):
                key = tuple(tokens)
                if key and key not in forms:
                    forms[key] = (gsel, ssel, ctx_only)

            if s:
                put(g + s, "all", "all", False)
                put(g + s[:1], "all", "first", False)
                if len(g) > 1:
                    put(g[:1] + s, "first", "all", False)
                    put(g[:1] + s[:1], "first", "first", False)
            put(g, "all", None, bool(s) or self.kind != "ext")
            if len(g) > 1:
                put(g[:1], "first", None, True)
        return forms


class Directory:
    def __init__(self):
        self.persons: dict[str, Person] = {}
        self.by_email: dict[str, str] = {}
        self.by_cedula: dict[str, str] = {}
        self.by_phone: dict[str, str] = {}
        self.by_handle: dict[str, str] = {}
        self.by_uid: dict[str, str] = {}
        self.by_row: dict[str, str] = {}
        self.by_clid: dict[str, str] = {}
        self.by_kp: dict[str, str] = {}
        self.by_radicado: dict[str, set[str]] = defaultdict(set)
        self.by_address: dict[str, str] = {}
        self.by_birth: dict[str, set[str]] = defaultdict(set)
        self.ambiguous_cedulas: set[str] = set()

    # --- building -----------------------------------------------------------------------

    def _index(self, person: Person) -> None:
        for e in person.emails:
            self.by_email.setdefault(e, person.pid)
        for c in person.cedulas:
            owner = self.by_cedula.setdefault(c, person.pid)
            if owner != person.pid:
                self.ambiguous_cedulas.add(c)
        for p in person.phones:
            self.by_phone.setdefault(p, person.pid)
        for h in person.handles:
            self.by_handle.setdefault(h, person.pid)
        for u in person.uids:
            self.by_uid[u] = person.pid
        for r in person.rows:
            self.by_row[r] = person.pid
        for a in person.addresses:
            self.by_address.setdefault(norm_name(a), person.pid)
        for b in person.births:
            self.by_birth[b].add(person.pid)

    def add(self, person: Person) -> Person:
        existing = self.persons.get(person.pid)
        if existing:
            for name in person.names:
                existing.add_name(name)
            for attr in ("emails", "cedulas", "phones", "addresses", "births", "handles", "uids", "rows"):
                getattr(existing, attr).update(getattr(person, attr))
            person = existing
        else:
            self.persons[person.pid] = person
        self._index(person)
        return person

    def find_strong(self, emails=(), cedulas=(), phones=()) -> str | None:
        for e in emails:
            if e in self.by_email:
                return self.by_email[e]
        for c in cedulas:
            if c in self.by_cedula and c not in self.ambiguous_cedulas:
                return self.by_cedula[c]
        for p in phones:
            if p in self.by_phone:
                return self.by_phone[p]
        return None

    def add_client_row(self, row_id: str, cols: dict[str, str]) -> Person:
        clid = cols.get("cliente_id", "")
        person = Person(pid=f"cl:{clid}", kind="client", rows={row_id})
        person.add_name(cols.get("nombre_completo", ""))
        _add_strong(person, cols.get("correo"), cols.get("num_doc"), cols.get("celular"))
        if cols.get("direccion"):
            person.addresses.add(cols["direccion"])
        if cols.get("fecha_nacimiento"):
            person.births.add(cols["fecha_nacimiento"])
        person = self.add(person)
        self.by_clid[clid] = person.pid
        return person

    def add_employee_row(self, row_id: str, cols: dict[str, str]) -> Person:
        kp = cols.get("id", "")
        person = Person(pid=f"emp:{kp}", kind="employee", rows={row_id})
        person.add_name(cols.get("nombre", ""))
        _add_strong(person, cols.get("correo"), cols.get("documento"), cols.get("celular"))
        if cols.get("fecha_nacimiento"):
            person.births.add(cols["fecha_nacimiento"])
        for e in person.emails:
            person.handles.add(e.split("@")[0])
        person = self.add(person)
        self.by_kp[kp] = person.pid
        return person

    def add_slack_users(self, users: list[dict], evidence: dict[str, dict] | None = None) -> None:
        """Link Slack profiles to table persons by email, then unique name, then thread evidence."""
        evidence = evidence or {}
        clients = [p for p in self.persons.values() if p.kind == "client"]
        slack_names = defaultdict(int)
        for u in users:
            if not u.get("is_bot") and not _is_employee_profile(u):
                slack_names[norm_name(_real_name(u))] += 1

        decided: dict[str, str | None] = {}
        pending: dict[str, list[Person]] = {}
        for u in users:
            if u.get("is_bot"):
                continue
            uid = u["id"]
            profile = u.get("profile") or {}
            name = _real_name(u)
            email = (profile.get("email") or "").strip().lower()
            phone = _phone_digits(profile.get("phone") or "")
            pid = self.find_strong(emails=[email] if email else [], phones=[phone] if phone else [])
            if pid is None and name and not _is_employee_profile(u):
                cands = [p for p in clients if _name_prefix(norm_name(name), p)]
                if len(cands) == 1 and slack_names[norm_name(name)] == 1:
                    pid = cands[0].pid
                elif cands:
                    pid = _pick_by_evidence(cands, evidence.get(uid))
                    if pid is None:
                        pending[uid] = cands
            decided[uid] = pid

        # Homonyms resolved by elimination: the only candidate row no other Slack profile took.
        taken = {pid for pid in decided.values() if pid}
        for uid, cands in pending.items():
            free = [p for p in cands if p.pid not in taken and not p.uids]
            if len(free) == 1:
                decided[uid] = free[0].pid
                taken.add(free[0].pid)

        for u in users:
            if u.get("is_bot"):
                continue
            uid = u["id"]
            profile = u.get("profile") or {}
            name = _real_name(u)
            email = (profile.get("email") or "").strip().lower()
            phone = _phone_digits(profile.get("phone") or "")
            pid = decided.get(uid)
            if pid is None and not name:
                continue
            person = Person(pid=pid or f"slack:{uid}", kind="slack", uids={uid})
            if name:
                person.add_name(name)
            if profile.get("display_name") and len(profile["display_name"].split()) >= 2:
                person.add_name(profile["display_name"])
            if email:
                person.emails.add(email)
            if phone:
                person.phones.add(phone)
            if u.get("name") and (pid or "").startswith("emp:"):
                person.handles.add(u["name"])
            self.add(person)

    def link_pqrs_row(self, row_id: str, cols: dict[str, str]) -> None:
        pid = self.by_clid.get(cols.get("cliente_id", ""))
        if pid:
            self.by_radicado[cols.get("radicado", "")].add(pid)
            ced = digits(cols.get("cedula", ""))
            if ced:
                self.persons[pid].cedulas.add(ced)
                self._index(self.persons[pid])

    def add_ext(self, name: str, key: str) -> Person:
        person = Person(pid=f"ext:{key}", kind="ext")
        person.add_name(name)
        return self.add(person)

    # --- lookups ------------------------------------------------------------------------

    def pids_in_text(self, text: str) -> list[str]:
        """Persons referenced by strong identifiers in a text (ids, emails, cédulas, phones)."""
        found: list[str] = []

        def push(pid):
            if pid and pid not in found:
                found.append(pid)

        for m in CL_ID.findall(text):
            push(self.by_clid.get(m))
        for m in KP_ID.findall(text):
            push(self.by_kp.get(m))
        for m in PQR_ID.findall(text):
            for pid in sorted(self.by_radicado.get(m, ())):
                push(pid)
        for m in EMAIL.findall(text):
            push(self.by_email.get(m.lower()))
        for m in DIGIT_RUN.findall(text):
            d = digits(m)
            if d in self.by_cedula and d not in self.ambiguous_cedulas:
                push(self.by_cedula[d])
            phone = d[2:] if len(d) == 12 and d.startswith("57") else d
            push(self.by_phone.get(phone))
        return found


def _add_strong(person: Person, email, cedula, phone) -> None:
    if email:
        person.emails.add(email.strip().lower())
    if cedula and digits(cedula):
        person.cedulas.add(digits(cedula))
    phone_d = _phone_digits(phone or "")
    if phone_d:
        person.phones.add(phone_d)


def _phone_digits(s: str) -> str:
    d = digits(s)
    if len(d) == 12 and d.startswith("57"):
        d = d[2:]
    return d if len(d) >= 7 else ""


def _real_name(u: dict) -> str:
    profile = u.get("profile") or {}
    return (u.get("real_name") or profile.get("real_name") or "").strip()


def _is_employee_profile(u: dict) -> bool:
    email = ((u.get("profile") or {}).get("email") or "").lower()
    return email.endswith("@kipupay.co")


def _name_prefix(slack_name: str, person: Person) -> bool:
    tokens = slack_name.split()
    for name in person.names:
        full = norm_name(name).split()
        if len(tokens) >= 2 and full[: len(tokens)] == tokens:
            return True
        g, s = split_name(name)
        gs = [fold(t) for t in g[:1] + s[:1]]
        if len(tokens) == 2 and tokens == gs:
            return True
    return False


def _pick_by_evidence(cands: list[Person], ev: dict | None) -> str | None:
    if not ev:
        return None
    hits = []
    for p in cands:
        score = 0
        score += len(p.cedulas & ev.get("digits", set()))
        score += len(p.phones & ev.get("digits", set()))
        score += len(p.emails & ev.get("emails", set()))
        score += sum(1 for r in p.rows if r.split(":", 1)[1] in ev.get("clids", set()))
        score += len(p.addresses & ev.get("addresses", set()))
        if score:
            hits.append((score, p.pid))
    hits.sort(reverse=True)
    if len(hits) == 1 or (len(hits) > 1 and hits[0][0] > hits[1][0]):
        return hits[0][1]
    return None


def thread_evidence(chats: list[dict], meta: dict[str, dict], radicado_clients: dict[str, set[str]]) -> dict[str, dict]:
    """Strong identifiers seen in every thread a Slack user writes in, keyed by uid."""
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for c in chats:
        by_thread[c["thread_id"]].append(c)
    out: dict[str, dict] = defaultdict(lambda: {"digits": set(), "emails": set(), "clids": set(), "addresses": set()})
    for msgs in by_thread.values():
        text = "\n".join(m["text"] for m in msgs)
        ev = {
            "digits": {d if not (len(d) == 12 and d.startswith("57")) else d[2:] for d in map(digits, DIGIT_RUN.findall(text))},
            "emails": {e.lower() for e in EMAIL.findall(text)},
            "clids": set(CL_ID.findall(text)),
        }
        for rad in PQR_ID.findall(text):
            ev["clids"].update(radicado_clients.get(rad, ()))
        for m in msgs:
            uid = meta.get(m["id"], {}).get("uid")
            if uid:
                for k, v in ev.items():
                    out[uid][k].update(v)
    return out


def build_directory(corpus) -> Directory:
    directory = Directory()
    pqrs_rows = []
    for rec in corpus.tables:
        cols = rec["columns"]
        if rec["table"] == "clientes":
            directory.add_client_row(rec["id"], cols)
        elif rec["table"] == "empleados":
            directory.add_employee_row(rec["id"], cols)
        elif rec["table"] == "pqrs":
            pqrs_rows.append(rec)
    for rec in pqrs_rows:
        directory.link_pqrs_row(rec["id"], rec["columns"])
    radicado_clients = {
        rec["columns"].get("radicado", ""): {rec["columns"].get("cliente_id", "")} for rec in pqrs_rows
    }
    evidence = thread_evidence(corpus.chats, corpus.chat_meta, radicado_clients)
    directory.add_slack_users(corpus.users, evidence)
    return directory
