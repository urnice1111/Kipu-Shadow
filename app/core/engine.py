"""Replacement engine: find spans, resolve who they belong to, write pseudonyms in place.

Only the personal fragments change; the rest of each text stays byte for byte.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.core import detect
from app.core.identities import Directory, Person, split_name
from app.core.lexicon import GIVEN, KEPT_TERMS, OCCUPATION_SECTOR, ROLE_EMAIL_LOCALS, SURNAME_SET
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

        # 6. names of known (and discovered) people
        if self.name_rx:
            for m in self.name_rx.finditer(folded):
                surface = text[m.start() : m.end()]
                resolved = self._resolve_name(m.group(0), surface, ctx)
                if resolved:
                    pid, gsel, ssel = resolved
                    plain = self.render_name(pid, gsel, ssel)
                    new = style_like(surface, plain, self.d.persons[pid].canonical)
                    if claim(m.start(), m.end(), new):
                        self._hit(pid, ctx, surface, "name", plain)

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

    def _resolve_name(self, matched: str, surface: str, ctx: Ctx):
        key = tuple(re.split(SEP, matched))
        cands = self.forms.get(key, [])
        in_ctx = [c for c in cands if c[0] in ctx.pids]
        if in_ctx:
            in_ctx.sort(key=lambda c: ctx.pids.index(c[0]))
            pid, gsel, ssel, ctx_only = in_ctx[0]
            if ctx_only and not surface[:1].isupper():
                return None
            return pid, gsel, ssel
        loose = [c for c in cands if not c[3] or (len(key) >= 2 and surface[:1].isupper())]
        if not loose:
            return None
        preferred = "emp" if ctx.prefer == "employee" else "cl"
        loose.sort(key=lambda c: (c[3], c[0].split(":")[0] != preferred, c[0]))
        pid, gsel, ssel, _ = loose[0]
        return pid, gsel, ssel

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

    def _birth(self, m: re.Match, ctx: Ctx) -> str | None:
        iso = detect.date_to_iso(m)
        pids = self.d.by_birth.get(iso or "")
        if not pids:
            return None
        in_ctx = [p for p in ctx.pids if p in pids]
        pid = in_ctx[0] if in_ctx else (next(iter(pids)) if len(pids) == 1 else None)
        if not pid:
            return None
        new = self.birth_for(pid, iso)
        self._hit(pid, ctx, m.group(0), "birth_iso", new)
        return detect.iso_like(new, m)

    def _address(self, pid: str, surface: str, ctx: Ctx) -> str:
        new = self.address_for(pid, surface)
        self._hit(pid, ctx, surface, "address", new)
        return new

    def _number(self, run: str, start: int, folded: str, ctx: Ctx) -> str | None:
        d = digits(run)
        core = d[2:] if len(d) == 12 and d.startswith("57") else d
        pid = self.d.by_cedula.get(d) if d not in self.d.ambiguous_cedulas else None
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
            blocked += [(m.start(), m.end()) for m in self.name_rx.finditer(folded)]
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

    def generalize(self, text: str, location_hint: bool = False, city: str | None = None) -> str:
        """Break occupation + place + year combinations: occupation to sector, barrio to city, year vague."""
        if not text or not detect.OCCUPATIONS:
            return text
        folded = fold(text)
        occ = [m for m in detect.OCCUPATIONS.finditer(folded) if text[m.start()].islower()]
        if not occ:
            return text
        barrios = [m for m in self.barrio_rx.finditer(folded) if text[m.start()].isupper()] if self.barrio_rx else []
        years = list(detect.YEAR.finditer(text))
        cities = list(self.city_rx.finditer(folded)) if self.city_rx else []
        if not (barrios or years or location_hint or cities):
            return text
        spans = []
        sector_by_fold = {fold(k): v for k, v in OCCUPATION_SECTOR.items()}
        for m in occ:
            spans.append((m.start(), m.end(), sector_by_fold[" ".join(m.group(0).split())]))
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
