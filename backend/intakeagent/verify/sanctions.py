"""Sanctions screening for legal intake, matched entirely on your own machine.

Before a firm opens a matter it should know whether the client or anyone on the other side
is on a sanctions list. The lists are public; the names in an intake are confidential. So the
lists are downloaded once and every comparison happens locally. No client name is sent to
any screening service.

Sources (all free, no key):

* OFAC Specially Designated Nationals list, with aliases (U.S. Treasury)
* OFAC Consolidated (non-SDN) sanctions list, with aliases
* UN Security Council Consolidated List

Download and normalise them into one JSON file::

    uv run python -m intakeagent.verify.sanctions refresh --out data/sanctions.json

and point ``SANCTIONS_LIST_PATH`` at it. DEMO_MODE uses a short, clearly fictional list bundled
with the package so the demo can show a match without naming a real person or company.

Matching is fuzzy on purpose: transliterations and typos ("Logistix" for "Logistics") are how
real hits get missed. Names are normalised (case, accents, punctuation, legal suffixes such as
LLC or FZE), split into tokens and scored on how well the tokens of each side are covered by
the other. A score is a reason to look, not a finding: the reviewer decides.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

DATA_DIR = Path(__file__).parent / "data"
DEMO_LIST_PATH = DATA_DIR / "demo_sanctions.json"

POSSIBLE = 0.85  # worth a look
STRONG = 0.97  # near-identical name

OFAC_SOURCES = {
    "OFAC SDN": (
        "https://www.treasury.gov/ofac/downloads/sdn.csv",
        "https://www.treasury.gov/ofac/downloads/alt.csv",
    ),
    "OFAC Consolidated": (
        "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv",
        "https://www.treasury.gov/ofac/downloads/consolidated/cons_alt.csv",
    ),
}
UN_SOURCE = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "inc", "incorporated", "co", "company", "corp", "corporation",
    "plc", "sa", "gmbh", "ag", "bv", "nv", "llp", "lp", "fze", "fzco", "fzc", "jsc", "pjsc",
    "ojsc", "cjsc", "ooo", "sarl", "srl", "spa", "pte", "pty", "the", "of", "and",
}  # fmt: skip


def normalize_name(name: str) -> list[str]:
    """Lowercase, strip accents and punctuation, drop legal suffixes; return tokens."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return [t for t in s.split() if t not in LEGAL_SUFFIXES]


def _token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) < 3 or len(b) < 3:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def name_score(query: list[str], candidate: list[str]) -> float:
    """How well two token lists cover each other. 1.0 means same tokens in any order.

    The query side weighs more: every word the client said should be accounted for, while a
    list entry may carry extra given names or a trading suffix.
    """
    if not query or not candidate:
        return 0.0
    q_cov = sum(max(_token_sim(q, c) for c in candidate) for q in query) / len(query)
    c_cov = sum(max(_token_sim(c, q) for q in query) for c in candidate) / len(candidate)
    return 0.7 * q_cov + 0.3 * c_cov


@dataclass
class SanctionsEntry:
    id: str
    list: str
    name: str
    type: str  # "individual" | "entity" | "vessel" | "aircraft" | ""
    program: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class SanctionsList:
    name: str
    generated_at: str
    entries: list[SanctionsEntry]
    demo: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)
    _index: dict[str, set[int]] = field(default_factory=dict, repr=False)
    _tokens: list[list[tuple[str, list[str]]]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        index: dict[str, set[int]] = defaultdict(set)
        for i, entry in enumerate(self.entries):
            names = [(n, normalize_name(n)) for n in [entry.name, *entry.aliases]]
            self._tokens.append(names)
            for _, toks in names:
                for t in toks:
                    if len(t) >= 3:
                        index[t[:3]].add(i)
        self._index = dict(index)

    @classmethod
    def load(cls, path: str | Path) -> SanctionsList:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=data.get("name", "Sanctions list"),
            generated_at=data.get("generated_at", ""),
            demo=bool(data.get("demo", False)),
            sources=data.get("sources", []),
            entries=[SanctionsEntry(**e) for e in data.get("entries", [])],
        )

    @classmethod
    def demo_list(cls) -> SanctionsList:
        return cls.load(DEMO_LIST_PATH)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "generated_at": self.generated_at,
            "entry_count": len(self.entries),
            "demo": self.demo,
            "sources": [s.get("name") for s in self.sources],
        }

    def search(self, name: str, limit: int = 3) -> list[dict[str, Any]]:
        query = normalize_name(name)
        if not query:
            return []
        # Blocking: only score entries that share a 3-letter token prefix with at least two of
        # the query's tokens (or the only one). Fuzzy matches almost always keep the prefix
        # ("Logistix"/"Logistics", "Mohamed"/"Mohammed"), and this cuts the work ~10x.
        prefixes = {t[:3] for t in query if len(t) >= 3}
        hits: dict[int, int] = defaultdict(int)
        for p in prefixes:
            for i in self._index.get(p, ()):
                hits[i] += 1
        need = min(2, len(prefixes))
        candidates = [i for i, n in hits.items() if n >= need]
        scored: list[dict[str, Any]] = []
        for i in candidates:
            best_name, best = "", 0.0
            for raw, toks in self._tokens[i]:
                s = name_score(query, toks)
                if s > best:
                    best_name, best = raw, s
            # A one-word query ("Blake") against a list is noise, not screening.
            if best >= POSSIBLE and (len(query) > 1 or best >= STRONG):
                e = self.entries[i]
                scored.append(
                    {
                        "entry_id": e.id,
                        "list": e.list,
                        "listed_name": e.name,
                        "matched_name": best_name,
                        "type": e.type,
                        "program": e.program,
                        "score": round(best, 3),
                    }
                )
        scored.sort(key=lambda m: m["score"], reverse=True)
        return scored[:limit]


def screen_names(sanctions: SanctionsList | None, parties: list[tuple[str, str]]) -> dict[str, Any]:
    """Screen (name, role) pairs. Without a list the result says so: never a silent 'clear'."""
    if sanctions is None:
        return {
            "status": "unavailable",
            "list": None,
            "message": "No sanctions list loaded. Run `python -m intakeagent.verify.sanctions "
            "refresh` and set SANCTIONS_LIST_PATH.",
            "results": [],
        }
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for name, role in parties:
        key = " ".join(normalize_name(name))
        if not key or key in seen:
            continue
        seen.add(key)
        matches = sanctions.search(name)
        top = matches[0]["score"] if matches else 0.0
        status = "strong_match" if top >= STRONG else "possible_match" if matches else "clear"
        results.append({"name": name, "role": role, "status": status, "matches": matches})
    return {"status": "ok", "list": sanctions.describe(), "results": results}


# ---------------------------------------------------------------------------
# Refresh: download the public lists and write one normalised JSON file
# ---------------------------------------------------------------------------


def _clean(v: str) -> str:
    v = (v or "").strip()
    return "" if v == "-0-" else v


def parse_ofac(list_name: str, primary_csv: str, alias_csv: str) -> list[SanctionsEntry]:
    entries: dict[str, SanctionsEntry] = {}
    for row in csv.reader(io.StringIO(primary_csv)):
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        ent = row[0].strip()
        entries[ent] = SanctionsEntry(
            id=f"{list_name}:{ent}",
            list=list_name,
            name=_clean(row[1]),
            type=_clean(row[2]) or "entity",
            program=_clean(row[3]),
        )
    for row in csv.reader(io.StringIO(alias_csv)):
        if len(row) < 4:
            continue
        ent = row[0].strip()
        alias = _clean(row[3])
        if ent in entries and alias:
            entries[ent].aliases.append(alias)
    return [e for e in entries.values() if e.name]


def parse_un(xml_text: str) -> list[SanctionsEntry]:
    root = ET.fromstring(xml_text)
    out: list[SanctionsEntry] = []

    def text(node: ET.Element, tag: str) -> str:
        child = node.find(tag)
        return (child.text or "").strip() if child is not None and child.text else ""

    for kind, tag, alias_tag in (
        ("individual", ".//INDIVIDUAL", "INDIVIDUAL_ALIAS"),
        ("entity", ".//ENTITY", "ENTITY_ALIAS"),
    ):
        for node in root.iterfind(tag):
            parts = [text(node, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME")]
            name = " ".join(p for p in parts if p)
            if not name:
                continue
            aliases = [
                text(a, "ALIAS_NAME") for a in node.iterfind(alias_tag) if text(a, "ALIAS_NAME")
            ]
            out.append(
                SanctionsEntry(
                    id=f"UN:{text(node, 'REFERENCE_NUMBER') or text(node, 'DATAID')}",
                    list="UN Consolidated",
                    name=name,
                    type=kind,
                    program=text(node, "UN_LIST_TYPE"),
                    aliases=aliases,
                )
            )
    return out


def refresh(out_path: Path, http: httpx.Client | None = None) -> dict[str, Any]:
    http = http or httpx.Client(timeout=120, follow_redirects=True)
    entries: list[SanctionsEntry] = []
    sources: list[dict[str, Any]] = []
    for list_name, (prim_url, alt_url) in OFAC_SOURCES.items():
        prim = http.get(prim_url)
        prim.raise_for_status()
        alt = http.get(alt_url)
        alt.raise_for_status()
        parsed = parse_ofac(list_name, prim.text, alt.text)
        entries.extend(parsed)
        sources.append({"name": list_name, "url": prim_url, "count": len(parsed)})
    un = http.get(UN_SOURCE)
    un.raise_for_status()
    parsed = parse_un(un.text)
    entries.extend(parsed)
    sources.append({"name": "UN Consolidated", "url": UN_SOURCE, "count": len(parsed)})

    data = {
        "name": "OFAC SDN + OFAC Consolidated + UN Consolidated",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "demo": False,
        "sources": sources,
        "entries": [e.__dict__ for e in entries],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m intakeagent.verify.sanctions")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="download OFAC and UN lists into one JSON file")
    r.add_argument("--out", default="data/sanctions.json")
    s = sub.add_parser("screen", help="screen names against a list file")
    s.add_argument("names", nargs="+")
    s.add_argument("--list", default=str(DEMO_LIST_PATH))
    args = parser.parse_args(argv)

    if args.cmd == "refresh":
        data = refresh(Path(args.out))
        for src in data["sources"]:
            print(f"{src['name']}: {src['count']} entries")
        print(f"wrote {args.out}")
        return 0
    result = screen_names(SanctionsList.load(args.list), [(n, "query") for n in args.names])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
