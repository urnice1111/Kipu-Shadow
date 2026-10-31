"""Persistent pseudonyms. A person keeps every pseudonym it was ever given.

People are found by any of their keys (table key, Slack uid, keyed hash of email or cédula),
so a known person that shows up with a new identifier keeps the same pseudonyms. Values are
generated from a secret-seeded RNG and stored the first time they are needed.
"""

import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import string
import threading
from pathlib import Path

from app.core.lexicon import PERSONAL_EMAIL_DOMAINS, PSEUDO_FEMALE, PSEUDO_MALE, PSEUDO_SURNAMES
from app.core.text import digits, fold, strip_accents

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (uid TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS person_keys (key TEXT PRIMARY KEY, uid TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS used_values (kind TEXT, value TEXT, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS value_map (kind TEXT, key TEXT, value TEXT, PRIMARY KEY (kind, key));
"""

STREET_TYPES = ["Calle", "Carrera", "Cl", "Cra", "Diagonal", "Transversal", "Avenida", "Kr"]
ADDRESS_EXTRAS = ["", "", " apto 302", " apto 1104", " casa 12", " of 501", " int 2", " apto 704"]
PHONE_PREFIXES = ["300", "301", "302", "304", "305", "310", "311", "312", "313", "314", "315",
                  "316", "317", "318", "319", "320", "321", "322", "323", "324", "350"]


class Registry:
    def __init__(self, path: Path, secret: bytes | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.secret = secret or _load_secret(self.path.parent / "secret.key")
        self.forbidden: set[str] = set()

    # --- keys -------------------------------------------------------------------------

    def hkey(self, kind: str, value: str) -> str:
        mac = hmac.new(self.secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:24]
        return f"{kind}:{mac}"

    def person_key(self, raw_key: str) -> str:
        """Table keys stay readable (they are not PII); identifiers are stored as HMACs."""
        kind, _, value = raw_key.partition(":")
        if kind in ("cl", "emp", "uid"):
            return raw_key
        return self.hkey(kind, value)

    def person_uid(self, raw_keys: list[str]) -> str:
        keys = [self.person_key(k) for k in raw_keys]
        with self._lock:
            uid = None
            for k in keys:
                row = self.db.execute("SELECT uid FROM person_keys WHERE key=?", (k,)).fetchone()
                if row:
                    uid = row[0]
                    break
            if uid is None:
                n = self.db.execute("SELECT COUNT(*) FROM people").fetchone()[0] + 1
                uid = f"p_{n:04d}"
                while self.db.execute("SELECT 1 FROM people WHERE uid=?", (uid,)).fetchone():
                    n += 1
                    uid = f"p_{n:04d}"
                self.db.execute("INSERT INTO people (uid, data) VALUES (?, '{}')", (uid,))
            for k in keys:
                self.db.execute("INSERT OR IGNORE INTO person_keys (key, uid) VALUES (?, ?)", (k, uid))
            self.db.commit()
            return uid

    # --- per person values ------------------------------------------------------------

    def _data(self, uid: str) -> dict:
        row = self.db.execute("SELECT data FROM people WHERE uid=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _save(self, uid: str, data: dict) -> None:
        self.db.execute("UPDATE people SET data=? WHERE uid=?", (json.dumps(data, ensure_ascii=False), uid))
        self.db.commit()

    def _rng(self, *parts: str) -> random.Random:
        seed = hmac.new(self.secret, "|".join(parts).encode(), hashlib.sha256).digest()
        return random.Random(seed)

    def _claim(self, kind: str, value: str) -> bool:
        try:
            self.db.execute("INSERT INTO used_values (kind, value) VALUES (?, ?)", (kind, fold(value)))
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, uid: str, field: str, make, unique: bool = True) -> str:
        """Return the stored value or create it once with make(rng, attempt)."""
        with self._lock:
            data = self._data(uid)
            if field in data:
                return data[field]
            for attempt in range(200):
                value = make(self._rng(uid, field, str(attempt)), attempt)
                if value is None:
                    continue
                if fold(value) in self.forbidden:
                    continue
                if not unique or self._claim(field.split(":")[0], value):
                    data[field] = value
                    self._save(uid, data)
                    return value
            raise RuntimeError(f"no se pudo generar {field} único")

    def name(self, uid: str, gender: str, n_given: int) -> dict:
        """Pseudonym name parts, fixed at first use."""
        with self._lock:
            data = self._data(uid)
            if "name" in data:
                return data["name"]

            def make(rng, attempt):
                pool = PSEUDO_FEMALE if gender == "F" else PSEUDO_MALE
                given = rng.sample(pool, max(1, min(n_given, 2)))
                surnames = rng.sample(PSEUDO_SURNAMES, 2)
                short = " ".join(given + surnames[:1])
                if fold(short) in self.forbidden or fold(" ".join(given + surnames)) in self.forbidden:
                    return None
                return json.dumps({"given": given, "surnames": surnames, "gender": gender}, ensure_ascii=False)

            for attempt in range(500):
                raw = make(self._rng(uid, "name", str(attempt)), attempt)
                if raw is None:
                    continue
                parts = json.loads(raw)
                short = " ".join(parts["given"] + parts["surnames"][:1])
                if self._claim("name", short):
                    data["name"] = parts
                    self._save(uid, data)
                    return parts
            raise RuntimeError("sin seudónimos de nombre disponibles")

    # --- values not tied to a person (unknown plates, accounts, phones...) -------------

    def value(self, kind: str, original: str, make, pass_attempt: bool = False) -> str:
        key = self.hkey(kind, original)
        with self._lock:
            row = self.db.execute("SELECT value FROM value_map WHERE kind=? AND key=?", (kind, key)).fetchone()
            if row and fold(row[0]) not in self.forbidden:
                return row[0]
            # A stored value that now equals some real value seen later would be a leak: regenerate.
            first = 0 if not row else 1000
            for attempt in range(first, first + 200):
                rng = self._rng(kind, key, str(attempt))
                value = make(rng, attempt) if pass_attempt else make(rng)
                if value is None or fold(value) in self.forbidden or value == original:
                    continue
                if self._claim(kind, value):
                    self.db.execute(
                        "INSERT OR REPLACE INTO value_map (kind, key, value) VALUES (?, ?, ?)", (kind, key, value)
                    )
                    self.db.commit()
                    return value
            raise RuntimeError(f"no se pudo generar {kind}")

    def close(self) -> None:
        self.db.close()


def _load_secret(path: Path) -> bytes:
    if path.is_file():
        return bytes.fromhex(path.read_text().strip())
    key = secrets.token_bytes(32)
    path.write_text(key.hex())
    return key


# --- generators ---------------------------------------------------------------------------


def ascii_lower(s: str) -> str:
    return strip_accents(s).lower().replace(" ", "")


def make_cedula(original: str):
    n = len(digits(original)) or 10

    def make(rng, attempt):
        first = "1" if n == 10 else rng.choice("3456789")
        value = first + "".join(rng.choice(string.digits) for _ in range(n - 1))
        orig = digits(original)
        if orig and (value == orig or value[-6:] in orig or orig[-6:] in value):
            return None
        return value

    return make


def make_phone(original: str):
    def make(rng, attempt):
        value = rng.choice(PHONE_PREFIXES) + "".join(rng.choice(string.digits) for _ in range(7))
        orig = digits(original)[-10:]
        if value == orig or value[-6:] in orig:
            return None
        return value

    return make


def make_address(rng, attempt=0) -> str:
    street = rng.choice(STREET_TYPES)
    main = rng.randint(1, 160)
    letter = rng.choice(["", "", "", "A", "B", " Bis", " Sur"])
    return f"{street} {main}{letter} # {rng.randint(1, 140)}-{rng.randint(1, 99)}{rng.choice(ADDRESS_EXTRAS)}"


def make_birth(original: str):
    def make(rng, attempt):
        try:
            year = int(original[:4])
        except ValueError:
            year = 1985
        year += rng.choice([-4, -3, -2, -1, 1, 2, 3, 4])
        value = f"{year:04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        return None if value == original else value

    return make


def make_email(parts: dict, corporate_domain: str | None):
    given = [ascii_lower(g) for g in parts["given"]]
    surnames = [ascii_lower(s) for s in parts["surnames"]]

    def make(rng, attempt):
        suffix = "" if attempt == 0 else str(rng.randint(2, 99))
        if corporate_domain:
            return f"{given[0]}.{surnames[0]}{suffix}@{corporate_domain}"
        return f"{given[0][0]}{surnames[0]}{suffix}@{rng.choice(PERSONAL_EMAIL_DOMAINS)}"

    return make


def make_handle(parts: dict, dotted: bool):
    given = [ascii_lower(g) for g in parts["given"]]
    surnames = [ascii_lower(s) for s in parts["surnames"]]

    def make(rng, attempt):
        suffix = "" if attempt == 0 else str(rng.randint(2, 99))
        if dotted:
            return f"{given[0]}.{surnames[0]}{suffix}"
        return f"{given[0][0]}{surnames[0]}{suffix}"

    return make


def make_like(original: str):
    """Same shape: letters to random letters, digits to random digits."""

    def make(rng):
        out = []
        for c in original:
            if c.isdigit():
                out.append(rng.choice(string.digits))
            elif c.isalpha():
                letter = rng.choice(string.ascii_uppercase)
                out.append(letter if c.isupper() else letter.lower())
            else:
                out.append(c)
        return "".join(out)

    return make
