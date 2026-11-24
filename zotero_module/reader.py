"""Read a local Zotero library without touching it.

Zotero keeps its database (``zotero.sqlite``) open and locked while it runs, so
this module never opens the live file: it copies the database (and its
write-ahead log, which holds the most recent changes) to a temporary folder and
reads the copy.  Nothing is ever written to the Zotero data folder.

The data folder is found in this order: the ``ZOTERO_DATA_DIR`` environment
variable, then ``~/Zotero`` (the default on macOS, Windows and Linux), then
``~/Documents/Zotero``.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional


class ZoteroError(Exception):
    """The Zotero library cannot be found or read."""


def find_zotero_data_dir() -> Optional[Path]:
    """The Zotero data folder (the one that contains zotero.sqlite), or None."""
    candidates = []
    env = os.environ.get("ZOTERO_DATA_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    home = Path.home()
    if os.name == "nt" and os.environ.get("USERPROFILE"):
        candidates.append(Path(os.environ["USERPROFILE"]) / "Zotero")
    candidates += [home / "Zotero", home / "Documents" / "Zotero"]
    for c in candidates:
        if (c / "zotero.sqlite").is_file():
            return c
    return None


_LINK_LINKED_FILE = 2
_LINK_LINKED_URL = 3


def _year(date: str) -> str:
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date or "")
    return m.group(1) if m else ""


class ZoteroReader:
    """Collections and items of a Zotero library, read from a snapshot of its database.

    The snapshot is refreshed when the live database changes (checked on each
    call, at most every few seconds).
    """

    def __init__(self, data_dir: Optional[Path] = None, cache_seconds: float = 3.0):
        self.data_dir = Path(data_dir) if data_dir else find_zotero_data_dir()
        if not self.data_dir or not (self.data_dir / "zotero.sqlite").is_file():
            raise ZoteroError(
                "Zotero library not found. Install Zotero, or set ZOTERO_DATA_DIR to the "
                "folder that contains zotero.sqlite.")
        self._tmp = Path(tempfile.mkdtemp(prefix="ra-zotero-"))
        self._snapshot_sig = None
        self._checked_at = 0.0
        self._lock = threading.Lock()      # the reader is shared by request and sync threads
        self._snap_n = 0
        self._current_db: Optional[Path] = None
        self._cache_seconds = cache_seconds
        self._base_dir = self._linked_base_dir()

    # -- snapshot ---------------------------------------------------------
    def _signature(self):
        sig = []
        for name in ("zotero.sqlite", "zotero.sqlite-wal"):
            p = self.data_dir / name
            try:
                st = p.stat()
                sig.append((name, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((name, None, None))
        return tuple(sig)

    def _refresh_snapshot(self) -> Path:
        """Path of an up-to-date, fully written snapshot. Must hold ``self._lock``.

        Each refresh copies into a new folder, so a connection opened on an older
        snapshot (by another thread) never sees its files replaced or deleted.
        """
        now = time.time()
        db = self._current_db
        if db is not None and db.exists() and now - self._checked_at <= self._cache_seconds:
            return db
        sig = self._signature()
        if db is not None and db.exists() and sig == self._snapshot_sig:
            self._checked_at = now
            return db
        self._snap_n += 1
        snap = self._tmp / f"snap-{self._snap_n}"
        try:
            snap.mkdir(parents=True, exist_ok=True)
            new_db = snap / "zotero.sqlite"
            shutil.copy2(self.data_dir / "zotero.sqlite", new_db)
            wal = self.data_dir / "zotero.sqlite-wal"
            if wal.exists():
                shutil.copy2(wal, snap / "zotero.sqlite-wal")
        except OSError as e:
            shutil.rmtree(snap, ignore_errors=True)
            raise ZoteroError(f"Could not read the Zotero database: {e}") from e
        self._current_db = new_db
        self._snapshot_sig = sig
        self._checked_at = now          # only once the copy is complete
        # Best effort: drop snapshots older than the previous one (connections are short-lived).
        for old in self._tmp.glob("snap-*"):
            try:
                n = int(old.name.split("-", 1)[1])
            except ValueError:
                continue
            if n < self._snap_n - 1:
                shutil.rmtree(old, ignore_errors=True)
        return new_db

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            db = self._refresh_snapshot()
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        return con

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def __del__(self):  # pragma: no cover - best effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _linked_base_dir(self) -> Optional[Path]:
        """Base folder for 'attachments:' relative links (Zotero preference)."""
        # The preference lives in the Zotero profile's prefs.js, whose location
        # varies by system; only an explicit ZOTERO_BASE_DIR is used.
        base = os.environ.get("ZOTERO_BASE_DIR")
        return Path(base).expanduser() if base else None

    # -- collections ------------------------------------------------------
    def collections(self) -> List[Dict]:
        """All collections with their full path ('Parent / Child') and item count."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT c.collectionID, c.collectionName, c.parentCollectionID, c.key, c.libraryID, "
                "  (SELECT COUNT(*) FROM collectionItems ci "
                "     WHERE ci.collectionID = c.collectionID "
                "       AND ci.itemID NOT IN (SELECT itemID FROM deletedItems)) AS n "
                "FROM collections c").fetchall()
            groups = {}
            try:
                for g in con.execute("SELECT libraryID, name FROM groups"):
                    groups[g["libraryID"]] = g["name"]
            except sqlite3.Error:
                pass
            try:
                deleted = {r[0] for r in con.execute("SELECT collectionID FROM deletedCollections")}
            except sqlite3.Error:
                deleted = set()
        by_id = {r["collectionID"]: r for r in rows}

        def path(cid):
            parts, seen = [], set()
            while cid in by_id and cid not in seen:
                seen.add(cid)
                parts.append(by_id[cid]["collectionName"])
                cid = by_id[cid]["parentCollectionID"]
            return " / ".join(reversed(parts))

        def in_trash(cid):
            seen = set()
            while cid in by_id and cid not in seen:
                if cid in deleted:
                    return True
                seen.add(cid)
                cid = by_id[cid]["parentCollectionID"]
            return False

        out = []
        for r in rows:
            if in_trash(r["collectionID"]):
                continue
            parent = by_id.get(r["parentCollectionID"])
            out.append({
                "key": r["key"],
                "name": r["collectionName"],
                "path": path(r["collectionID"]),
                "parent_key": parent["key"] if parent else None,
                "library": groups.get(r["libraryID"], "My Library"),
                "item_count": r["n"],
            })
        out.sort(key=lambda c: (c["library"] != "My Library", c["library"].lower(), c["path"].lower()))
        return out

    def collection(self, key: str) -> Optional[Dict]:
        return next((c for c in self.collections() if c["key"] == key), None)

    # -- items --------------------------------------------------------------
    def collection_items(self, key: str, include_subcollections: bool = False) -> List[Dict]:
        """Regular items of a collection (no notes or attachments), with their PDF files."""
        with self._connect() as con:
            row = con.execute("SELECT collectionID, libraryID FROM collections WHERE key = ?", (key,)).fetchone()
            if not row:
                raise ZoteroError(f"Zotero collection {key!r} not found.")
            ids = [row["collectionID"]]
            if include_subcollections:
                frontier = list(ids)
                while frontier:
                    q = ",".join("?" * len(frontier))
                    frontier = [r[0] for r in con.execute(
                        f"SELECT collectionID FROM collections WHERE parentCollectionID IN ({q})", frontier)]
                    frontier = [c for c in frontier if c not in ids]
                    ids += frontier
            q = ",".join("?" * len(ids))
            item_ids = [r[0] for r in con.execute(
                f"SELECT DISTINCT ci.itemID FROM collectionItems ci "
                f"JOIN items i ON i.itemID = ci.itemID "
                f"JOIN itemTypes t ON t.itemTypeID = i.itemTypeID "
                f"WHERE ci.collectionID IN ({q}) "
                f"  AND t.typeName NOT IN ('note', 'attachment', 'annotation') "
                f"  AND ci.itemID NOT IN (SELECT itemID FROM deletedItems) "
                f"ORDER BY ci.orderIndex, ci.itemID", ids)]
            return [self._item(con, iid) for iid in item_ids]

    def _item(self, con: sqlite3.Connection, item_id: int) -> Dict:
        head = con.execute(
            "SELECT i.key, t.typeName FROM items i JOIN itemTypes t ON t.itemTypeID = i.itemTypeID "
            "WHERE i.itemID = ?", (item_id,)).fetchone()
        fields = {r["fieldName"]: r["value"] for r in con.execute(
            "SELECT f.fieldName, v.value FROM itemData d "
            "JOIN fields f ON f.fieldID = d.fieldID "
            "JOIN itemDataValues v ON v.valueID = d.valueID WHERE d.itemID = ?", (item_id,))}
        creators = []
        for r in con.execute(
                "SELECT c.firstName, c.lastName, ct.creatorType FROM itemCreators ic "
                "JOIN creators c ON c.creatorID = ic.creatorID "
                "JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID "
                "WHERE ic.itemID = ? ORDER BY ic.orderIndex", (item_id,)):
            if r["creatorType"] in ("author", "editor", "contributor") or not creators:
                creators.append({"given": r["firstName"] or "", "family": r["lastName"] or "",
                                 "type": r["creatorType"]})
        authors = [c for c in creators if c["type"] == "author"] or creators
        attachments = []
        for r in con.execute(
                "SELECT i.key, a.path, a.contentType, a.linkMode FROM itemAttachments a "
                "JOIN items i ON i.itemID = a.itemID "
                "WHERE a.parentItemID = ? AND a.itemID NOT IN (SELECT itemID FROM deletedItems)",
                (item_id,)):
            path = self._attachment_path(r["key"], r["path"], r["linkMode"])
            attachments.append({
                "key": r["key"],
                "content_type": r["contentType"] or "",
                "path": str(path) if path else None,
                "exists": bool(path and path.is_file()),
            })
        tags = [r[0] for r in con.execute(
            "SELECT t.name FROM itemTags it JOIN tags t ON t.tagID = it.tagID WHERE it.itemID = ?", (item_id,))]
        doi = (fields.get("DOI") or "").strip()
        if not doi:
            m = re.search(r"\b10\.\d{4,9}/\S+", fields.get("extra") or "")
            doi = m.group(0).rstrip(".") if m else ""
        return {
            "key": head["key"],
            "item_type": head["typeName"],
            "title": fields.get("title", ""),
            "authors": [{"given": a["given"], "family": a["family"]} for a in authors],
            "year": _year(fields.get("date", "")),
            "date": fields.get("date", ""),
            "journal": fields.get("publicationTitle") or fields.get("bookTitle")
                       or fields.get("proceedingsTitle") or fields.get("websiteTitle") or "",
            "volume": fields.get("volume", ""),
            "issue": fields.get("issue", ""),
            "pages": fields.get("pages", ""),
            "doi": doi,
            "url": fields.get("url", ""),
            "abstract": fields.get("abstractNote", ""),
            "tags": tags,
            "attachments": attachments,
        }

    def _attachment_path(self, key: str, path: Optional[str], link_mode: int) -> Optional[Path]:
        if not path or link_mode == _LINK_LINKED_URL:
            return None
        if path.startswith("storage:"):
            return self.data_dir / "storage" / key / path[len("storage:"):]
        if path.startswith("attachments:"):
            return self._base_dir / path[len("attachments:"):] if self._base_dir else None
        p = Path(path)
        return p if p.is_absolute() else None

    @staticmethod
    def pdf_of(item: Dict) -> Optional[Path]:
        """The item's first PDF attachment that exists on disk."""
        for a in item.get("attachments", []):
            if a.get("exists") and (a.get("content_type") == "application/pdf"
                                    or str(a.get("path", "")).lower().endswith(".pdf")):
                return Path(a["path"])
        return None
