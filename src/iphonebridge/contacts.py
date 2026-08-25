"""Contacts cache — pull vCards from iPhone via PBAP, store in SQLite,
resolve phone numbers to display names.

PBAP API quirk (per spike/RESULTS.md §4): use `Select(location, phonebook)`
not `SetFolder`. Then `PullAll(targetfile, filters)`.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import tempfile
import time
import unicodedata
from contextlib import closing
from pathlib import Path

import dbus

from iphonebridge import config
from iphonebridge.bus import obex
from iphonebridge.events import normalize_phone
from iphonebridge.obex.sessions import SessionManager

log = logging.getLogger(__name__)


# ---- vCard parsing ------------------------------------------------------

_VCARD_BLOCK = re.compile(
    r"BEGIN:VCARD(?P<body>.*?)END:VCARD", re.DOTALL | re.IGNORECASE
)

def _parse_vcards(blob: str) -> list[tuple[str | None, list[tuple[str, str]], list[str]]]:
    """Return [(full_name, [(phone_norm, phone_raw), ...], [email_lower, ...]), ...].

    The raw TEL string is kept because it is the only record of whether
    the contact carries an explicit country code. Prefixing "+" to a
    national number invents a foreign one: "+" plus a 10-digit US number
    is a Netherlands address, and the message goes to a stranger.
    """
    out: list[tuple[str | None, list[tuple[str, str]], list[str]]] = []
    for m in _VCARD_BLOCK.finditer(blob):
        body = m.group("body")
        fn: str | None = None
        phones: list[tuple[str, str]] = []
        emails: list[str] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.upper().startswith("FN:"):
                fn = line[3:].strip() or None
            elif line.upper().startswith("TEL"):
                # forms: TEL:1234, TEL;TYPE=CELL:1234, TEL;TYPE=CELL,VOICE:1234
                _, _, val = line.partition(":")
                norm = normalize_phone(val)
                if norm:
                    phones.append((norm, val.strip()))
            elif line.upper().startswith("EMAIL"):
                # forms: EMAIL:a@b, EMAIL;TYPE=INTERNET:a@b
                _, _, val = line.partition(":")
                val = val.strip().lower()
                if val and "@" in val:
                    emails.append(val)
        if fn or phones or emails:
            out.append((fn, phones, emails))
    return out


def sendable_number(raw: str | None, norm: str) -> str:
    """The form to hand the phone: keep a country code, never invent one.

    A raw TEL beginning with "+" is already international, so the
    normalized digits get the "+" back. Anything else is national (or a
    short code) and goes out bare, letting the iPhone apply its own
    region. Rows predating the phone_raw column fall back to a length
    test until the next contacts refresh.
    """
    if raw is not None:
        return ("+" + norm) if raw.strip().startswith("+") else norm
    return ("+" + norm) if len(norm) >= 11 else norm


# ---- SQLite schema ------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name    TEXT NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS phones (
    phone_norm   TEXT NOT NULL,
    phone_raw    TEXT,
    contact_id   INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    UNIQUE(phone_norm, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_phones_norm ON phones(phone_norm);

CREATE TABLE IF NOT EXISTS emails (
    email_norm   TEXT NOT NULL,
    contact_id   INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    UNIQUE(email_norm, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_emails_norm ON emails(email_norm);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def _open_db() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.CONTACTS_DB)
    conn.executescript(_SCHEMA)
    # phone_raw was added after the first release; older caches lack it
    # until the next refresh.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(phones)")}
    if "phone_raw" not in cols:
        conn.execute("ALTER TABLE phones ADD COLUMN phone_raw TEXT")
    return conn


def _fold(s: str) -> str:
    """Casefold and strip accents for matching: "María" -> "maria"."""
    decomposed = unicodedata.normalize("NFD", s.strip())
    return "".join(ch for ch in decomposed
                   if not unicodedata.combining(ch)).casefold()


# ---- PBAP pull ----------------------------------------------------------

def pull_phonebook(sessions: SessionManager, *, max_contacts: int = 65535) -> int:
    """Pull the iPhone's main phonebook over PBAP and return contact count.

    Replaces the local cache atomically (transaction).
    """
    pbap = obex(sessions.pbap_path, "org.bluez.obex.PhonebookAccess1")
    log.info("PBAP Select(int, pb)")
    pbap.Select("int", "pb")

    out = Path(tempfile.mkdtemp(prefix="iphonebridge_pb_")) / "pb.vcf"
    log.info("PBAP PullAll → %s (max=%d)", out, max_contacts)
    ret = pbap.PullAll(
        str(out),
        {"MaxListCount": dbus.UInt16(max_contacts),
         "Format": dbus.String("Vcard30")},
    )
    transfer_path = str(ret[0]) if isinstance(ret, (tuple, list)) else str(ret)

    # Wait for transfer to complete (poll properties)
    tprops = obex(transfer_path, "org.freedesktop.DBus.Properties")
    for _ in range(600):  # up to 60s for huge phonebooks
        try:
            status = str(tprops.Get("org.bluez.obex.Transfer1", "Status"))
        except dbus.exceptions.DBusException:
            status = "gone"
            break
        if status in ("complete", "error"):
            break
        time.sleep(0.1)
    log.info("transfer status: %s, file size: %d bytes",
             status, out.stat().st_size if out.exists() else 0)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("PBAP transfer wrote no file")

    blob = out.read_text(errors="replace")
    parsed = _parse_vcards(blob)
    log.info("parsed %d contacts from %d bytes", len(parsed), out.stat().st_size)

    now = time.time()
    with closing(_open_db()) as db:
        with db:  # transaction
            db.execute("DELETE FROM contacts")
            db.execute("DELETE FROM phones")
            db.execute("DELETE FROM emails")
            for fn, phones, emails in parsed:
                if not fn and not phones and not emails:
                    continue
                cur = db.execute(
                    "INSERT INTO contacts(full_name, updated_at) VALUES (?, ?)",
                    (fn or "", now),
                )
                cid = cur.lastrowid
                for norm, raw in phones:
                    db.execute(
                        "INSERT OR IGNORE INTO phones"
                        "(phone_norm, phone_raw, contact_id) VALUES (?, ?, ?)",
                        (norm, raw, cid),
                    )
                for e in emails:
                    db.execute(
                        "INSERT OR IGNORE INTO emails(email_norm, contact_id) "
                        "VALUES (?, ?)",
                        (e, cid),
                    )
            db.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES "
                "('last_pull', ?), ('count', ?)",
                (str(now), str(len(parsed))),
            )

    # Clean up the temp file
    try:
        out.unlink()
        out.parent.rmdir()
    except OSError:
        pass

    return len(parsed)


# ---- Lookup -------------------------------------------------------------

class ContactsResolver:
    """In-process cache + SQLite-backed resolver. Cheap to construct.

    The instance is the stable handle held by event listeners — call
    `refresh()` to reload from disk in place, don't replace the object,
    otherwise bound `resolve` methods become stale.
    """

    def __init__(self) -> None:
        self._mem: dict[str, str] = {}
        self._mem_email: dict[str, str] = {}
        self._warm()

    def _warm(self) -> None:
        try:
            with closing(_open_db()) as db:
                for phone, name in db.execute(
                    "SELECT p.phone_norm, c.full_name "
                    "FROM phones p JOIN contacts c ON c.id = p.contact_id "
                    "WHERE c.full_name != ''"
                ):
                    self._mem[phone] = name
                for email, name in db.execute(
                    "SELECT e.email_norm, c.full_name "
                    "FROM emails e JOIN contacts c ON c.id = e.contact_id "
                    "WHERE c.full_name != ''"
                ):
                    self._mem_email[email] = name
        except sqlite3.Error as e:
            log.warning("contacts cache warm failed: %s", e)

    def refresh(self) -> int:
        """Re-read the SQLite cache into memory. Returns new count."""
        self._mem.clear()
        self._mem_email.clear()
        self._warm()
        return len(self._mem)

    def find_by_name(self, query: str) -> list[tuple[str, str]]:
        """Reverse lookup — name substring → list of (display_name, number).

        The number comes back ready to send: an explicit country code is
        preserved, never fabricated (see sendable_number).

        Case- and accent-insensitive: "mari" matches "María" and vice
        versa. SQLite's LIKE/LOWER only fold ASCII, so the matching runs
        in Python over the (small) contact set. Prefix matches sort ahead
        of mid-name matches so the likely target survives a display cap.
        """
        q = _fold(query or "")
        if not q:
            return []
        rows: list[tuple[str, str]] = []
        try:
            with closing(_open_db()) as db:
                rows = [
                    (name, sendable_number(raw, norm))
                    for name, norm, raw in db.execute(
                        "SELECT c.full_name, p.phone_norm, p.phone_raw "
                        "FROM contacts c JOIN phones p ON p.contact_id = c.id "
                        "WHERE c.full_name != '' "
                        "ORDER BY c.full_name")
                ]
        except sqlite3.Error as e:
            log.warning("contacts find_by_name failed: %s", e)
            return []
        out: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for name, phone in rows:
            folded = _fold(name)
            if q not in folded or (name, phone) in seen:
                continue
            seen.add((name, phone))
            out.append((name, phone))
        out.sort(key=lambda np: (not _fold(np[0]).startswith(q), _fold(np[0])))
        return out

    def resolve(self, raw: str | None) -> str | None:
        # An address with @ is an email handle (iMessage via Apple ID) —
        # phone normalization would just strip it to nothing.
        if raw and "@" in raw:
            return self._mem_email.get(raw.strip().lower())
        norm = normalize_phone(raw)
        if not norm:
            return None
        # Match exact, or suffix-match (US numbers might be stored 10 vs 11 digit
        # depending on whether the country code +1 was included). Match in BOTH
        # directions: a 10-digit incoming might match an 11-digit stored, and
        # vice versa.
        if norm in self._mem:
            return self._mem[norm]
        if len(norm) >= 10:
            tail = norm[-10:]
            for k, v in self._mem.items():
                if k.endswith(tail):
                    return v
        return None

    def count(self) -> int:
        return len(self._mem)
