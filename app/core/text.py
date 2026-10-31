"""Text helpers. fold() keeps string length so spans found in it map to the original."""

import re
import unicodedata

_FOLD_CACHE: dict[str, str] = {}


def _fold_char(c: str) -> str:
    base = unicodedata.normalize("NFD", c)[0] if c else c
    low = base.lower()
    return low if len(low) == 1 else base


def fold(s: str) -> str:
    out = _FOLD_CACHE.get(s)
    if out is None:
        out = "".join(_fold_char(c) for c in s)
        if len(_FOLD_CACHE) > 200_000:
            _FOLD_CACHE.clear()
        _FOLD_CACHE[s] = out
    return out


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def has_accents(s: str) -> bool:
    return strip_accents(s) != s


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def norm_name(s: str) -> str:
    return " ".join(fold(s).split())


def pour_digits(template: str, new_digits: str) -> str:
    """Write new_digits into the digit slots of template, keeping its separators and prefix."""
    slots = sum(c.isdigit() for c in template)
    if slots == len(new_digits) + 2 and digits(template).startswith("57"):
        new_digits = "57" + new_digits
    if slots != len(new_digits):
        return new_digits
    it = iter(new_digits)
    return "".join(next(it) if c.isdigit() else c for c in template)


# --- Port of the judge's matching (validar.mjs) used by the auditor -------------------------

_ESPACIO = "\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "В": "B", "Н": "H", "К": "K", "М": "M", "Т": "T", "ο": "o", "α": "a", "ρ": "p", "ν": "v", "ι": "i",
    "ℓ": "l", "ı": "i", "ɑ": "a",
}
_RX_CONF = re.compile("[" + "".join(_CONFUSABLES) + "]")
_RX_SEP_DIG = re.compile(rf"(?<=\d)[{_ESPACIO}.,'\u2019`\u00b4\u00b7/\-\u2013\u2014_](?=\d)")
_RX_TEXTO = re.compile(r"^[\w .'_-]+$")


def _clean(s: str) -> str:
    base = _RX_CONF.sub(lambda m: _CONFUSABLES[m.group(0)], unicodedata.normalize("NFKC", s))
    out = []
    for c in base:
        if unicodedata.category(c) == "Cf":
            continue
        out.append(" " if (unicodedata.category(c) == "Zs" or c in "\t\r\n\v\f") else c)
    return re.sub(r" {2,}", " ", "".join(out))


def judge_norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", _clean(s)) if unicodedata.category(c) != "Mn")
    return s.lower().replace("ß", "ss").replace("ς", "σ").replace("ſ", "s")


def judge_compact_digits(s: str) -> str:
    return _RX_SEP_DIG.sub("", _clean(s))


def judge_contains(haystack_norm: str, haystack_compact: str, needle: str) -> bool:
    """Same decision as contiene() in validar.mjs, given pre-normalized haystacks."""
    if not needle:
        return False
    d = digits(needle)
    if d and len(d) >= 6 and len(d) >= 0.6 * len(needle) and not re.search(r"[a-zA-Z]", needle):
        candidates = {d}
        if len(d) == 12 and d.startswith("57"):
            candidates.add(d[2:])
        return any(
            c in haystack_compact and re.search(rf"(?<!\d)(?:57)?{re.escape(c)}(?!\d)", haystack_compact)
            for c in candidates
        )
    n = judge_norm(needle)
    if n.split() and n.split()[0] not in haystack_norm:
        return False
    if _RX_TEXTO.match(n) and re.search(r"[a-z]", n):
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", haystack_norm):
            return True
        words = n.split()
        if len(words) >= 2 and all(len(w) >= 3 for w in words):
            pattern = f"[{_ESPACIO}]*".join(map(re.escape, words))
            return bool(re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", haystack_norm))
        return False
    return n in haystack_norm


def is_loose_name(s: str) -> bool:
    """validar.mjs skips single capitalized words when checking leaked originals."""
    return bool(s) and " " not in s and "@" not in s and not re.search(r"\d", s) and s[0].isupper()
