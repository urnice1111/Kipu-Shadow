"""Detectors that find spans in a text. They only locate; the engine decides replacements."""

import re
from collections.abc import Iterator

from app.core.lexicon import GIVEN, KEPT_TERMS, NOT_NAME_WORDS, OCCUPATION_SECTOR, SURNAME_SET
from app.core.text import fold

EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

_SPELL_SEP = r"(?:punto|guion bajo|guion|raya|underscore)"
SPELLED_EMAIL = re.compile(
    rf"(?<![a-z0-9])([a-z0-9]+(?:\s+{_SPELL_SEP}\s+[a-z0-9]+)*)\s+arroba\s+([a-z0-9]+(?:\s+punto\s+[a-z0-9]+)+)(?![a-z0-9])"
)

DIGIT_RUN = re.compile(r"(?<![\d\-])\+?\d(?:[ .\-/]?\d){5,}(?!\d)")

DATE = re.compile(
    r"(?<![\d\-/.])(?:(?P<y>19\d\d|20[0-2]\d)-(?P<m>\d\d)-(?P<d>\d\d)"
    r"|(?P<d2>\d{1,2})(?P<sep>[/.\-])(?P<m2>\d{1,2})(?P=sep)(?P<y2>19\d\d|20[0-2]\d))(?![\d\-/])"
)


def date_to_iso(m: re.Match) -> str | None:
    if m.group("y"):
        return f"{m.group('y')}-{m.group('m')}-{m.group('d')}"
    try:
        return f"{m.group('y2')}-{int(m.group('m2')):02d}-{int(m.group('d2')):02d}"
    except (TypeError, ValueError):
        return None


def iso_like(iso: str, m: re.Match) -> str:
    """Write an ISO date in the same layout as the matched date."""
    if m.group("y"):
        return iso
    y, mo, d = iso.split("-")
    sep = m.group("sep")
    day = d if len(m.group("d2")) == 2 else str(int(d))
    month = mo if len(m.group("m2")) == 2 else str(int(mo))
    return f"{day}{sep}{month}{sep}{y}"

AMOUNT = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?")
CEDULA_CONTEXT = re.compile(
    r"(cedula|c\.\s?c\.?|\bcc\b|documento|identificacion|nuip|\bti\b|\bce\b|\bid\b|id number|national id|identity)[^0-9]{0,25}$"
)
ACCOUNT_CONTEXT = re.compile(
    r"(cuenta|credito|obligacion|producto|tarjeta|pasaporte|poliza|contrato|account|card|passport|policy|loan)[^0-9]{0,25}$"
)
PASSPORT_WORDS = ("pasaporte", "passport")

STREET = r"(?:Calle|Cl|Cll|Carrera|Cra|Kr|Kra|Avenida|Av|Ak|Ac|Diagonal|Dg|Transversal|Tv|Trans)"
ADDRESS = re.compile(
    rf"\b{STREET}\.?\s*\d+\s?[A-Za-z]?(?:\s+(?:Bis|Sur|Norte|Este))?(?:\s+[A-Z])?\s*(?:#|No\.?|N°|Nº)\s*\d+\s?[A-Za-z]?(?:\s+Bis)?\s*-\s*\d+"
    r"(?:\s+(?:Sur|Norte|Este))?(?:,?\s+(?:apto|apt|apartamento|of|oficina|casa|int|interior|torre|bloque|piso|local)\.?\s*\d+[A-Za-z]?)*",
    re.IGNORECASE,
)

PLATE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3})[ -]?(\d{3}|\d{2}[A-Z])(?![A-Za-z0-9])")
DATE_LIKE = re.compile(r"(?:19|20)\d\d(?:[-/.]\d{1,2}){1,2}|\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d\d")
NOT_PLATE_PREFIX = {
    "PQR", "INC", "KPI", "CEO", "CTO", "CFO", "COO", "PSE", "SIC", "NIT", "COP", "USD", "BOG", "MDE", "CLO",
    "IVA", "SMS", "PDF", "RUT", "API", "SLA", "NPS", "OTP", "PIN", "ATM", "DIAN", "EPM", "CDT", "GMF",
}
PASSPORT = re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,2}\d{6,8}(?![A-Za-z0-9])")

YEAR = re.compile(r"(?<![\d\-/.])(?:19[4-9]\d|20[0-2]\d)(?![\d\-/])")

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def compile_terms(terms, flags=0) -> re.Pattern | None:
    folded = sorted({fold(t) for t in terms if t}, key=len, reverse=True)
    if not folded:
        return None
    body = "|".join(r"[\s_.\-]+".join(map(re.escape, t.split())) for t in folded)
    return re.compile(rf"(?<![a-z0-9@])(?:{body})(?![a-z0-9@])", flags)


KEPT = compile_terms(KEPT_TERMS)
MAJOR_CITIES = {
    "Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga", "Cartagena", "Pereira", "Manizales",
    "Santa Marta", "Cúcuta", "Ibagué", "Villavicencio", "Pasto", "Montería", "Neiva", "Armenia", "Popayán",
}
OCCUPATIONS = compile_terms(OCCUPATION_SECTOR)


def spelled_to_email(local: str, domain: str) -> str:
    local = re.sub(r"\s+guion bajo\s+|\s+underscore\s+", "_", local)
    local = re.sub(r"\s+(?:guion|raya)\s+", "-", local)
    local = re.sub(r"\s+punto\s+", ".", local)
    domain = re.sub(r"\s+punto\s+", ".", domain)
    return f"{local}@{domain}"


def email_to_spelled(email: str) -> str:
    local, _, domain = email.partition("@")
    spell = lambda s: s.replace(".", " punto ").replace("_", " guion bajo ").replace("-", " guion ")
    return f"{spell(local)} arroba {spell(domain)}"


def find_names(
    text: str, lowercase_ok: bool = False, given: set[str] = GIVEN, surnames: set[str] = SURNAME_SET
) -> Iterator[tuple[int, int]]:
    """Unknown person names: a given name followed by surnames, e.g. 'Brayan Gómez' or 'MARIA GONZALEZ'."""
    GIVEN, SURNAME_SET = given, surnames
    words = [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(text)]
    i = 0
    while i < len(words):
        s, e, w = words[i]
        fw = fold(w)
        if fw in GIVEN and fw not in NOT_NAME_WORDS and (w[0].isupper() or lowercase_ok):
            j = i + 1
            end = e
            has_surname = False
            while j < len(words) and j - i < 5:
                ps, pe, pw = words[j]
                gap = text[end:ps]
                if not re.fullmatch(r"[ _]{1,2}" if lowercase_ok else r" {1,2}", gap):
                    break
                fpw = fold(pw)
                if not (pw[0].isupper() or lowercase_ok):
                    break
                if fpw in SURNAME_SET or (fpw not in GIVEN and not lowercase_ok and len(pw) >= 3 and fpw not in NOT_NAME_WORDS):
                    has_surname = True
                elif fpw not in GIVEN:
                    break
                end = pe
                j += 1
            if has_surname:
                yield s, end
                i = j
                continue
        i += 1


def preceding(folded: str, start: int, width: int = 40) -> str:
    return folded[max(0, start - width) : start]
