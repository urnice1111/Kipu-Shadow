"""Replacement engine: find spans, resolve who they belong to, write pseudonyms in place.

Only the personal fragments change; the rest of each text stays byte for byte.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.core import detect
from app.core.identities import Directory, Person, split_name
from app.core.lexicon import COMMON_WORD_NAMES, GIVEN, KEPT_TERMS, OCCUPATION_SECTOR, ROLE_EMAIL_LOCALS, SURNAME_SET
from app.core.registry import (
    Registry,
    make_address,
    make_birth,
    make_cedula,
    make_email,
    make_handle,
    make_like,
    make_phone,
)
from app.core.text import digits, fold, has_accents, norm_name, pour_digits, strip_accents

PERSONAL_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "yahoo.es", "hotmail.es"}
SEP = r"(?:\s+|[_.\-])"


@dataclass
class Ctx:
    record_id: str
    pids: list[str] = field(default_factory=list)
    prefer: str = "client"

    def push(self, *pids):
        for pid in pids:
            if pid and pid not in self.pids:
                self.pids.append(pid)
        return self


@dataclass
class Hit:
    records: set = field(default_factory=set)
    originals: set = field(default_factory=set)
    used: dict = field(default_factory=lambda: defaultdict(Counter))


class Engine:
    def __init__(self, directory: Directory, registry: Registry, barrios: dict[str, set[str]] | None = None):
        self.d = directory
        self.r = registry
        self.barrios_by_city = barrios or {}
        self.barrio_city: dict[str, str] = {}
        for city, bs in self.barrios_by_city.items():
            for b in bs:
                if fold(b) != fold(city):
                    self.barrio_city.setdefault(fold(b), city)
        self.hits: dict[str, Hit] = defaultdict(Hit)
        self.kept_hits: dict[str, set] = defaultdict(set)
        self.kept_surface: dict[str, set] = defaultdict(set)
        self._uid_cache: dict[str, str] = {}
        self.rebuild()

    # --- setup --------------------------------------------------------------------------

    def rebuild(self) -> None:
        """(Re)compile matchers after the directory changes."""
        self.forms: dict[tuple, list[tuple[str, str | None, str | None, bool]]] = defaultdict(list)
        kept_folded = {fold(t) for t in KEPT_TERMS}
        for pid, p in self.d.persons.items():
            for key, (gsel, ssel, ctx_only) in p.name_forms().items():
                if " ".join(key) in kept_folded:
                    continue
                self.forms[key].append((pid, gsel, ssel, ctx_only))
        keys = sorted(self.forms, key=lambda k: (len(k), sum(map(len, k))), reverse=True)
        if keys:
            body = "|".join(SEP.join(map(re.escape, k)) for k in keys)
            self.name_rx = re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9@])")
        else:
            self.name_rx = None
        self.by_initial: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pid, p in self.d.persons.items():
            if p.given and p.surnames:
                self.by_initial[(fold(p.given[0])[0], fold(p.surnames[0]))].append(pid)
        handles = [h for h in self.d.by_handle if len(h) >= 5]
        self.handle_rx = (
            re.compile(r"(?<![\w.])(?:" + "|".join(map(re.escape, sorted(handles, key=len, reverse=True))) + r")(?![\w@])")
            if handles
            else None
        )
        addresses = sorted(self.d.by_address, key=len, reverse=True)
        self.address_rx = (
            re.compile("|".join(r"\s+".join(map(re.escape, a.split())) for a in addresses)) if addresses else None
        )
        learned_given, learned_surnames = set(), set()
        for p in self.d.persons.values():
            if p.kind != "ext":
                g, s = split_name(p.canonical)
                learned_given.update(fold(t) for t in g)
                learned_surnames.update(fold(t) for t in s)
        self.surname_names = SURNAME_SET | learned_surnames
        self.given_names = GIVEN | (learned_given - self.surname_names)
        self.barrio_rx = detect.compile_terms(self.barrio_city)
        self.city_rx = detect.compile_terms(set(self.barrios_by_city) | detect.MAJOR_CITIES)
        forbidden = set()
        for p in self.d.persons.values():
            for key in p.name_forms():
                if len(key) >= 2:
                    forbidden.add(" ".join(key))
            forbidden.update(p.emails, p.cedulas, p.phones, p.handles, p.births)
            forbidden.update(fold(a) for a in p.addresses)
        self.r.forbidden = forbidden

    def uid(self, pid: str) -> str:
        if pid not in self._uid_cache:
            self._uid_cache[pid] = self.r.person_uid(self.d.persons[pid].registry_keys())
        return self._uid_cache[pid]

    # --- pseudonym values -------------------------------------------------------------

    def name_parts(self, pid: str) -> dict:
        p = self.d.persons[pid]
        return self.r.name(self.uid(pid), p.gender, len(p.given) or 1)

    def render_name(self, pid: str, gsel, ssel) -> str:
        p = self.d.persons[pid]
        parts = self.name_parts(pid)
        given = parts["given"] if gsel == "all" else parts["given"][:1]
        if ssel == "all":
            surnames = parts["surnames"][: max(1, min(2, len(p.surnames)))]
        elif ssel == "first":
            surnames = parts["surnames"][:1]
        else:
            surnames = []
        return " ".join(given + surnames)

    def email_for(self, pid: str | None, original: str) -> str:
        """Keyed by the original address; built from the owner's pseudonym when the owner is known."""
        low = original.strip().lower()
        domain = low.split("@")[-1]
        corporate = None if domain in PERSONAL_DOMAINS else domain
        if pid:
            return self.r.value("email", low, make_email(self.name_parts(pid), corporate), pass_attempt=True)

        def make_random(rng):
            from app.core.lexicon import PERSONAL_EMAIL_DOMAINS, PSEUDO_FEMALE, PSEUDO_SURNAMES

            g = strip_accents(rng.choice(PSEUDO_FEMALE)).lower()
            s = strip_accents(rng.choice(PSEUDO_SURNAMES)).lower()
            if corporate:
                return f"{g}.{s}{rng.randint(1, 99)}@{domain}"
            return f"{g[0]}{s}{rng.randint(1, 99)}@{rng.choice(PERSONAL_EMAIL_DOMAINS)}"

        return self.r.value("email", low, make_random)

    def handle_for(self, pid: str, original: str) -> str:
        dotted = "." in original
        return self.r.get(self.uid(pid), "handle:dot" if dotted else "handle:short", make_handle(self.name_parts(pid), dotted))

    # Identifiers are keyed by their original value, not by owner, so they stay the same
    # whether or not a later run links them to a different (or newly known) person.

    def phone_for(self, pid: str | None, original: str) -> str:
        core = digits(original)[-10:]
        return self.r.value("phone", core, lambda rng: make_phone(core)(rng, 0))

    def cedula_for(self, pid: str | None, original: str) -> str:
        d = digits(original)
        return self.r.value("cedula", d, lambda rng: make_cedula(d)(rng, 0))

    def address_for(self, pid: str | None, original: str) -> str:
        return self.r.value("address", norm_name(original), make_address)

    def birth_for(self, pid: str | None, original: str) -> str:
        return self.r.value("birth", original, lambda rng: make_birth(original)(rng, 0))

    # --- bookkeeping ------------------------------------------------------------------

    def _hit(self, pid: str, ctx: Ctx, surface: str, kind: str, value: str) -> None:
        h = self.hits[pid]
        h.records.add(ctx.record_id)
        h.originals.add(surface)
        h.used[kind][value] += 1

    # --- the text pass ----------------------------------------------------------------

    def text(self, text: str, ctx: Ctx) -> str:
        if not text:
            return text
        folded = fold(text)
        spans: list[tuple[int, int, str]] = []
        taken: list[tuple[int, int]] = []

        def free(s, e):
            return all(e <= a or s >= b for a, b in taken)

        def claim(s, e, replacement):
            if s < e and free(s, e):
                taken.append((s, e))
                if replacement is not None and replacement != text[s:e]:
                    spans.append((s, e, replacement))
                return True
            return False

        # 1. emails, written and spelled out
        for m in detect.EMAIL.finditer(text):
            claim(m.start(), m.end(), self._email(m.group(0), ctx))
        for m in detect.SPELLED_EMAIL.finditer(folded):
            email = detect.spelled_to_email(m.group(1), m.group(2))
            new = self._email(email, ctx, surface=text[m.start() : m.end()])
            claim(m.start(), m.end(), detect.email_to_spelled(new) if new != email else None)

        # 2. addresses
        if self.address_rx:
            for m in self.address_rx.finditer(folded):
                pid = self.d.by_address.get(norm_name(m.group(0)))
                if pid and free(m.start(), m.end()):
                    claim(m.start(), m.end(), self._address(pid, text[m.start() : m.end()], ctx))
        for m in detect.ADDRESS.finditer(text):
            if not free(m.start(), m.end()):
                continue
            pid = self.d.by_address.get(norm_name(m.group(0)))
            if pid:
                claim(m.start(), m.end(), self._address(pid, m.group(0), ctx))
            else:
                new = self.address_for(None, m.group(0))
                claim(m.start(), m.end(), new)
                self._attach(ctx, m.group(0), "address", new)

        # 3. passports, birth dates of known people, then other numbers: cédulas, phones, accounts
        for m in detect.PASSPORT.finditer(text):
            if any(w in detect.preceding(folded, m.start(), 60) for w in detect.PASSPORT_WORDS):
                new = self.r.value("passport", m.group(0), make_like(m.group(0)))
                if claim(m.start(), m.end(), new):
                    self._attach(ctx, m.group(0), "passport", new)
        for m in detect.DATE.finditer(text):
            if free(m.start(), m.end()):
                new = self._birth(m, ctx)
                if new:
                    claim(m.start(), m.end(), new)
        for m in detect.PROSE_DATE.finditer(text):
            if free(m.start(), m.end()):
                new = self._birth(m, ctx, prose=True)
                if new:
                    claim(m.start(), m.end(), new)
        for m in detect.DIGIT_RUN.finditer(text):
            if free(m.start(), m.end()):
                claim(m.start(), m.end(), self._number(m.group(0), m.start(), folded, ctx))

        # 4. plates
        for m in detect.PLATE.finditer(text):
            if m.group(1) not in detect.NOT_PLATE_PREFIX:
                core = re.sub(r"[ -]", "", m.group(0))
                new = pour_chars(m.group(0), self.r.value("plate", core, make_like(core)))
                if claim(m.start(), m.end(), new):
                    self._attach(ctx, m.group(0), "plate", new)

        # 5. Slack-style handles of employees
        if self.handle_rx:
            for m in self.handle_rx.finditer(folded):
                pid = self.d.by_handle.get(m.group(0))
                if pid:
                    new = self.handle_for(pid, m.group(0))
                    if claim(m.start(), m.end(), new):
                        self._hit(pid, ctx, text[m.start() : m.end()], "handle", new)

        # 6. names of known (and discovered) people, then initials and @handles built from names
        named: list[str] = []
        last_owner: dict[tuple, tuple[str, int]] = {}
        if self.name_rx:
            for m in self.name_rx.finditer(folded):
                surface = text[m.start() : m.end()]
                key = tuple(re.split(SEP, m.group(0)))
                resolved = self._resolve_name(m.group(0), surface, ctx, detect.preceding(folded, m.start(), 25), text, m.start(), m.end())
                prev = last_owner.get(key)
                if resolved and prev and not detect.SENTENCE_END.search(text[prev[1] : m.start()]):
                    # The same ambiguous name twice in one sentence names two different people.
                    others = sorted({c[0] for c in self.forms.get(key, []) if not c[3]} - {prev[0]})
                    if prev[0] == resolved[0] and len(others) == 1:
                        alt = next(c for c in self.forms[key] if c[0] == others[0])
                        resolved = (alt[0], alt[1], alt[2])
                if resolved:
                    pid, gsel, ssel = resolved
                    plain = self.render_name(pid, gsel, ssel)
                    new = style_like(surface, plain, self.d.persons[pid].canonical)
                    if claim(m.start(), m.end(), new):
                        self._hit(pid, ctx, surface, "name", plain)
                        named.append(pid)
                        if len({c[0] for c in self.forms.get(key, []) if not c[3]}) >= 2:
                            last_owner[key] = (pid, m.end())
        for m in detect.INITIAL_NAME.finditer(text):
            resolved = self._resolve_initial(m, ctx)
            if resolved:
                pid, end, two = resolved
                parts = self.name_parts(pid)
                new = f"{parts['given'][0][0]}. {parts['surnames'][0]}" + (f" {parts['surnames'][1]}" if two else "")
                if claim(m.start(), end, new):
                    self._hit(pid, ctx, text[m.start() : end], "initial", new)
                    named.append(pid)
        for m in detect.HANDLE_TOKEN.finditer(text):
            if not free(m.start(), m.end()):
                continue
            pid = self._handle_owner(m.group(1), named + ctx.pids)
            if pid:
                new = "@" + self.handle_for(pid, m.group(1))
                if claim(m.start(), m.end(), new):
                    self._hit(pid, ctx, m.group(0), "handle", new[1:])

        # 7. organizations, places and public figures we keep on purpose
        if detect.KEPT:
            for m in detect.KEPT.finditer(folded):
                if free(m.start(), m.end()) and text[m.start()].isupper():
                    term = fold(text[m.start() : m.end()])
                    self.kept_hits[" ".join(term.split())].add(ctx.record_id)
                    self.kept_surface[" ".join(term.split())].add(text[m.start() : m.end()])
                    taken.append((m.start(), m.end()))

        out = text
        for s, e, new in sorted(spans, reverse=True):
            out = out[:s] + new + out[e:]
        return out

    def _resolve_name(self, matched: str, surface: str, ctx: Ctx, before: str = "", text: str = "", start: int = 0, end: int = 0):
        key = tuple(re.split(SEP, matched))
        cands = self.forms.get(key, [])
        upper = surface[:1].isupper()
        owners = {c[0] for c in cands}
        if len(owners) >= 2 and text:
            pid = None
            if len(key) >= 2:
                pid = self._evidence_owner(text, start, end, owners) or self._occupation_owner(text, start, end, owners)
            if pid:
                c = next(c for c in cands if c[0] == pid)
                return c[0], c[1], c[2]
            pre, post = fold(text[max(0, start - 25) : start]), fold(text[end : end + 30])
            if detect.AGENT_BEFORE.search(pre) or detect.AGENT_AFTER.search(post):
                kind = "employee"
            elif detect.CLIENT_BEFORE.search(pre) or detect.CLIENT_AFTER.search(post):
                kind = "client"
            else:
                kind = None
            if kind:
                same_kind = [c for c in cands if self.d.persons[c[0]].kind == kind]
                if same_kind:
                    cands = same_kind
        in_ctx = [c for c in cands if c[0] in ctx.pids]
        if in_ctx:
            in_ctx.sort(key=lambda c: ctx.pids.index(c[0]))
            pid, gsel, ssel, ctx_only = in_ctx[0]
            if ctx_only and not upper:
                common = len(key) == 1 and key[0] in COMMON_WORD_NAMES
                if common and not detect.GREETING_BEFORE.search(before):
                    return None
            return pid, gsel, ssel
        loose = [c for c in cands if not c[3] or (len(key) >= 2 and upper)]
        if loose:
            preferred = "emp" if ctx.prefer == "employee" else "cl"
            loose.sort(key=lambda c: (c[3], c[0].split(":")[0] != preferred, c[0]))
            pid, gsel, ssel, _ = loose[0]
            return pid, gsel, ssel
        # A bare capitalized first name in internal text names a colleague when only one employee has it.
        if ctx.prefer == "employee" and upper and len(key) == 1 and not detect.PLACE_OR_QUOTE_BEFORE.search(before):
            emps = [c for c in cands if self.d.persons[c[0]].kind == "employee"]
            if len({c[0] for c in emps}) == 1:
                pid, gsel, ssel, _ = emps[0]
                return pid, gsel, ssel
        return None

    def _evidence_owner(self, text: str, start: int, end: int, owners: set[str]) -> str | None:
        """The candidate whose identifier sits closest to the mention, in its table row or paragraph."""
        lo, hi = max(0, start - 90), min(len(text), end + 70)
        line_lo = text.rfind("\n", 0, start) + 1
        line_hi = text.find("\n", end)
        line_hi = len(text) if line_hi == -1 else line_hi
        if text[line_lo:start].lstrip().startswith("|"):
            lo, hi = line_lo, line_hi
        else:
            para = text.rfind("\n\n", lo, start)
            lo = para if para != -1 else lo
            para = text.find("\n\n", end, hi)
            hi = para if para != -1 else hi
        window = text[lo:hi]
        best: dict[bool, dict[str, int]] = {True: {}, False: {}}
        for pid, s, e, strong in self.d.evidence(window, fold(window)):
            if pid not in owners:
                continue
            s, e = s + lo, e + lo
            dist = start - e if e <= start else (s - end) + 15 if s >= end else 0
            if dist < best[strong].get(pid, 10**6):
                best[strong][pid] = dist
        for strong in (True, False):
            ranked = sorted(best[strong].items(), key=lambda kv: kv[1])
            if ranked and (len(ranked) == 1 or ranked[0][1] < ranked[1][1]):
                return ranked[0][0]
        return None

    def _occupation_owner(self, text: str, start: int, end: int, owners: set[str]) -> str | None:
        """The only candidate whose occupation (or its sector) is named next to the mention."""
        known = getattr(self.d, "occupation", {})
        if not detect.OCCUPATIONS or not any(pid in known for pid in owners):
            return None
        lo, hi = max(0, start - 120), min(len(text), end + 120)
        para = text.rfind("\n\n", lo, start)
        lo = para if para != -1 else lo
        para = text.find("\n\n", end, hi)
        hi = para if para != -1 else hi
        sector_by_fold = {fold(k): v for k, v in OCCUPATION_SECTOR.items()}
        named = {" ".join(m.group(0).split()) for m in detect.OCCUPATIONS.finditer(fold(text[lo:hi]))}
        if not named:
            return None
        sectors = {sector_by_fold[n] for n in named}
        matches = [
            pid for pid in owners
            if pid in known and (fold(known[pid]) in named or sector_by_fold.get(fold(known[pid])) in sectors)
        ]
        return matches[0] if len(matches) == 1 else None

    def _resolve_initial(self, m: re.Match, ctx: Ctx):
        """Owner of "M. Jiménez": a person in context, else the only person with that initial and surname."""
        cands = self.by_initial.get((fold(m.group(1)), fold(m.group(2))), [])
        if not cands:
            return None
        in_ctx = [pid for pid in ctx.pids if pid in cands]
        pid = in_ctx[0] if in_ctx else (cands[0] if len(cands) == 1 else None)
        if not pid:
            return None
        p = self.d.persons[pid]
        two = bool(m.group(3)) and len(p.surnames) > 1 and fold(m.group(3)) == fold(p.surnames[1])
        return pid, (m.end(3) if two else m.end(2)), two

    def _handle_owner(self, handle: str, preferred: list[str]) -> str | None:
        """Person whose name builds this handle (arojas, ana.rojas, ana_rojas), preferring those just named."""
        h = handle.lower()

        def builds(p: Person) -> bool:
            if not (p.given and p.surnames):
                return False
            g, s = strip_accents(fold(p.given[0])), strip_accents(fold(p.surnames[0]))
            return h in (g[0] + s, f"{g}.{s}", f"{g}_{s}", g + s)

        for pid in preferred:
            if pid and pid in self.d.persons and builds(self.d.persons[pid]):
                return pid
        owners = [pid for pid, p in self.d.persons.items() if builds(p)]
        return owners[0] if len(owners) == 1 else None

    def named_pids(self, text: str) -> list[str]:
        """People named without ambiguity in a text: a multi-word name with one owner, or a known handle."""
        found: list[str] = []
        if not text:
            return found
        folded = fold(text)
        if self.name_rx:
            for m in self.name_rx.finditer(folded):
                key = tuple(re.split(SEP, m.group(0)))
                owners = {c[0] for c in self.forms.get(key, []) if not c[3]}
                if len(key) >= 2 and len(owners) == 1:
                    pid = owners.pop()
                    if pid not in found:
                        found.append(pid)
        if self.handle_rx:
            for m in self.handle_rx.finditer(folded):
                pid = self.d.by_handle.get(m.group(0))
                if pid and pid not in found:
                    found.append(pid)
        return found

    def _email(self, email: str, ctx: Ctx, surface: str | None = None) -> str:
        surface = surface or email
        low = email.lower()
        local = low.split("@")[0]
        pid = self.d.by_email.get(low)
        if pid:
            new = self.email_for(pid, low)
            self._hit(pid, ctx, surface, "email", new)
            return new
        if local in ROLE_EMAIL_LOCALS:
            return email
        new = self.email_for(None, low)
        self._attach(ctx, surface, "email", new)
        return new

    def _birth(self, m: re.Match, ctx: Ctx, prose: bool = False) -> str | None:
        iso = detect.prose_date_iso(m) if prose else detect.date_to_iso(m)
        pids = self.d.by_birth.get(iso or "")
        if not pids:
            return None
        in_ctx = [p for p in ctx.pids if p in pids]
        pid = in_ctx[0] if in_ctx else (next(iter(pids)) if len(pids) == 1 else None)
        if not pid:
            return None
        new = self.birth_for(pid, iso)
        self._hit(pid, ctx, m.group(0), "birth_iso", new)
        return detect.prose_date_like(new, m) if prose else detect.iso_like(new, m)

    def _address(self, pid: str, surface: str, ctx: Ctx) -> str:
        new = self.address_for(pid, surface)
        self._hit(pid, ctx, surface, "address", new)
        return new

    def _number(self, run: str, start: int, folded: str, ctx: Ctx) -> str | None:
        d = digits(run)
        core = d[2:] if len(d) == 12 and d.startswith("57") else d
        pid = self.d.by_cedula.get(d)
        if pid and d in self.d.ambiguous_cedulas:
            for cand in ctx.pids:
                person = self.d.persons.get(cand)
                if person and d in person.cedulas:
                    pid = cand
                    break
        if pid:
            new = self.cedula_for(pid, d)
            self._hit(pid, ctx, run, "cedula", new)
            return pour_digits(run, new)
        pid = self.d.by_phone.get(core)
        if pid:
            new = self.phone_for(pid, core)
            self._hit(pid, ctx, run, "phone", new)
            return pour_digits(run, new)
        before = detect.preceding(folded, start)
        if detect.DATE_LIKE.fullmatch(run):
            return None
        if len(core) == 10 and core.startswith("3") and not re.search(r"\$|cop|pesos", before[-6:]):
            new = self.phone_for(None, core)
            self._attach(ctx, run, "phone", new)
            return pour_digits(run, new)
        if 6 <= len(d) <= 10 and detect.CEDULA_CONTEXT.search(before):
            new = self.cedula_for(None, d)
            self._attach(ctx, run, "cedula", new)
            return pour_digits(run, new)
        if len(d) >= 6 and detect.ACCOUNT_CONTEXT.search(before) and not detect.AMOUNT.fullmatch(run):
            kind = "passport" if "pasaporte" in before else "account"
            new = self.r.value(kind, run, make_like(run))
            self._attach(ctx, run, kind, new)
            return new
        return None

    def _attach(self, ctx: Ctx, surface: str, kind: str, value: str) -> None:
        """Identifiers with no known owner go to the record's main person when it is a customer."""
        if ctx.pids and self.d.persons.get(ctx.pids[0]) and self.d.persons[ctx.pids[0]].kind != "employee":
            self._hit(ctx.pids[0], ctx, surface, kind, value)

    # --- names discovered in free text ---------------------------------------------------

    def discover(self, text: str, lowercase_ok: bool = False) -> list[str]:
        """Unknown multi-word person names in text, skipping known people and kept terms."""
        if not text:
            return []
        folded = fold(text)
        blocked = []
        if self.name_rx:
            # A known given name alone ("Kelly") must not hide an unknown full name ("Kelly Marulanda").
            blocked += [(m.start(), m.end()) for m in self.name_rx.finditer(folded) if len(re.split(SEP, m.group(0))) >= 2]
        if detect.KEPT:
            blocked += [(m.start(), m.end()) for m in detect.KEPT.finditer(folded)]
        blocked += [(m.start(), m.end()) for m in detect.EMAIL.finditer(text)]
        found = []
        for s, e in detect.find_names(text, lowercase_ok, self.given_names, self.surname_names):
            if any(not (e <= a or s >= b) for a, b in blocked):
                continue
            found.append(re.sub(r"[_\s]+", " ", text[s:e]))
        return found

    # --- quasi-identifiers ----------------------------------------------------------------

    def has_place_or_year(self, text: str) -> bool:
        folded = fold(text)
        return bool(
            detect.YEAR.search(text)
            or (self.city_rx and self.city_rx.search(folded))
            or (self.barrio_rx and any(text[m.start()].isupper() for m in self.barrio_rx.finditer(folded)))
        )

    def generalize(
        self,
        text: str,
        location_hint: bool = False,
        city: str | None = None,
        notes: bool = False,
        own_occupation: str | None = None,
    ) -> str:
        """Break occupation + place + year combinations: occupation to sector, barrio to city, year vague.

        notes: free text of a person's own row, where a capitalized occupation opening a sentence is theirs.
        own_occupation: that row's occupation; its head word ("conductor" of "conductor de plataforma") counts too.
        """
        if not text or not detect.OCCUPATIONS:
            return text
        folded = fold(text)
        sector_by_fold = {fold(k): v for k, v in OCCUPATION_SECTOR.items()}
        occ: list[tuple[int, int, str]] = []
        for m in detect.OCCUPATIONS.finditer(folded):
            if _occupation_mention(text, m.start(), m.end(), notes):
                occ.append((m.start(), m.end(), sector_by_fold[" ".join(m.group(0).split())]))
        head = _occupation_head(own_occupation)
        if head:
            sector = sector_by_fold.get(fold(own_occupation.strip()), "profesional independiente")
            for m in re.finditer(rf"(?<![a-z]){re.escape(head)}(?![a-z])", folded):
                if all(m.end() <= s or m.start() >= e for s, e, _ in occ) and _occupation_mention(text, m.start(), m.end(), notes):
                    occ.append((m.start(), m.end(), sector))
        if not occ:
            return text
        barrios = [m for m in self.barrio_rx.finditer(folded) if text[m.start()].isupper()] if self.barrio_rx else []
        years = list(detect.YEAR.finditer(text))
        cities = list(self.city_rx.finditer(folded)) if self.city_rx else []
        if not (barrios or years or location_hint or cities):
            return text
        spans = []
        for s, e, sector in occ:
            spans.append((s, e, sector[:1].upper() + sector[1:] if text[s].isupper() else sector))
        for m in barrios:
            spans.append((m.start(), m.end(), self.barrio_city.get(m.group(0), city or text[m.start() : m.end()])))
        for m in years:
            spans.append((m.start(), m.end(), "hace unos años"))
        out = text
        last = len(text) + 1
        for s, e, new in sorted(spans, reverse=True):
            if e <= last:
                out = out[:s] + new + out[e:]
                last = s
        return out


def _occupation_mention(text: str, start: int, end: int, notes: bool = False) -> bool:
    """Lowercase occupations count anywhere. A capitalized one only opens a sentence and is followed by
    punctuation ("Arquitecto, cliente desde 2022."), so job titles in tables and signatures stay; in a
    person's own notes it only has to open one."""
    if text[start].islower():
        return True
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith("|"):
        return False
    opens = not text[:start].strip() or re.search(r"[.!?:;\n]\s*$", text[:start])
    return bool(opens and (notes or re.match(r"\s*[,.;:]", text[end:])))


def _occupation_head(occupation: str | None) -> str | None:
    """Head word of "X de Y" occupations: someone who is "conductor de plataforma" writes "conductor"."""
    if not occupation or " de " not in occupation:
        return None
    head = fold(occupation.strip().split()[0])
    return head if len(head) >= 5 else None


def style_like(surface: str, plain: str, canonical: str) -> str:
    """Write a pseudonym in the same casing and separators as the text it replaces."""
    sep_match = re.search(r"[_.\-]", surface)
    if sep_match and " " not in surface:
        sep = sep_match.group(0)
        tokens = strip_accents(plain).split()
        if surface[:1].isupper():
            return sep.join(t.capitalize() for t in tokens)
        return sep.join(t.lower() for t in tokens)
    if surface.isupper() and len(surface) > 1:
        base = plain if has_accents(surface) else strip_accents(plain)
        return _keep_breaks(surface, base.upper())
    if surface.islower():
        base = plain if has_accents(surface) else strip_accents(plain)
        return _keep_breaks(surface, base.lower())
    by_fold = {fold(t): t for t in canonical.split()}
    matched = [by_fold.get(fold(t), "") for t in re.split(r"[\s_.\-]+", surface)]
    if not has_accents(surface) and any(has_accents(t) for t in matched):
        return _keep_breaks(surface, strip_accents(plain))
    return _keep_breaks(surface, plain)


def pour_chars(template: str, new: str) -> str:
    """Write the letters and digits of new into the alphanumeric slots of template."""
    it = iter(new)
    return "".join(next(it, c) if c.isalnum() else c for c in template)


def _keep_breaks(surface: str, plain: str) -> str:
    """A name wrapped across lines keeps its line break."""
    if "\n" not in surface:
        return plain
    seps = re.findall(r"\s+", surface)
    tokens = plain.split()
    out = tokens[0]
    for i, tok in enumerate(tokens[1:]):
        out += (seps[i] if i < len(seps) else " ") + tok
    return out
