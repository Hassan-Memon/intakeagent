"""Clinical terminology lookups: RxNorm for drugs, ICD-10-CM for problems.

Two interchangeable clients implement :class:`TerminologyClient`:

* :class:`NlmTerminologyClient` calls the U.S. National Library of Medicine's free public APIs:
  RxNav (``approximateTerm``, ``related``, ``properties``), RxClass (pharmacologic and
  chemical classes from DailyMed) and Clinical Tables (ICD-10-CM search). No key is needed.
  NLM asks clients to stay under 20 requests per second per IP; one intake makes a few dozen
  calls at most, and every response is cached in-process.
* :class:`OfflineTerminologyClient` answers from a snapshot bundled with the package
  (``verify/data/terminology_snapshot.json``). DEMO_MODE and the tests use it so they never
  touch the network, and the live client falls back to it when NLM is unreachable.

The snapshot is generated from the live APIs, not typed by hand::

    uv run python -m intakeagent.verify.terminology snapshot

Only drug names and a stop-word-stripped chief complaint ever leave the process. Never a name,
date of birth, phone number or transcript.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from intakeagent.schemas.base import Coding

log = logging.getLogger(__name__)

RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10CM_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT_PATH = DATA_DIR / "terminology_snapshot.json"
# The browser demo ships the same snapshot; ``snapshot`` writes both and a test keeps them equal.
FRONTEND_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[3] / "frontend" / "lib" / "demo" / "data" / "terminology.json"
)

# Relations from RxClass (DailyMed source) that describe what a drug *is*: its established
# pharmacologic class and chemical structure. MED-RT's ``ci_chemclass`` looks similar but means
# "contraindicated with", so it is deliberately not used here.
CLASS_RELAS = {"has_epc", "has_chemical_structure"}


class DrugClass(BaseModel):
    id: str
    name: str
    source: str  # RxClass relaSource, "DAILYMED"


class DrugInfo(BaseModel):
    """What RxNorm knows about a drug name as spoken by a patient."""

    query: str
    rxcui: str
    name: str
    ingredients: list[Coding] = Field(default_factory=list)
    classes: list[DrugClass] = Field(default_factory=list)

    @property
    def coding(self) -> Coding:
        return Coding(system=RXNORM_SYSTEM, code=self.rxcui, display=self.name)


class TerminologyClient(Protocol):
    name: str
    mode: str  # "live" | "offline"

    def lookup_drug(self, term: str) -> DrugInfo | None: ...

    def search_icd10(self, query: str, limit: int = 5) -> list[Coding]: ...


class TerminologyUnavailable(RuntimeError):
    """The live service could not be reached; callers fall back or report it."""


def normalize_term(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]+", " ", text.lower())).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_term(a), normalize_term(b)).ratio()


# ---------------------------------------------------------------------------
# Live: NLM RxNav, RxClass, Clinical Tables
# ---------------------------------------------------------------------------


class NlmTerminologyClient:
    name = "nlm"
    mode = "live"

    RXNAV = "https://rxnav.nlm.nih.gov/REST"
    CLINICAL_TABLES = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"

    def __init__(self, http: httpx.Client | None = None, timeout: float = 8.0) -> None:
        self._http = http or httpx.Client(
            timeout=timeout, headers={"User-Agent": "intakeagent (open source intake agent)"}
        )
        self._cache: dict[str, Any] = {}

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        key = url + json.dumps(params or {}, sort_keys=True)
        if key in self._cache:
            return self._cache[key]
        try:
            resp = self._http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TerminologyUnavailable(f"{url}: {exc}") from exc
        self._cache[key] = data
        return data

    def _classes(self, rxcui: str) -> list[DrugClass]:
        out: dict[str, DrugClass] = {}
        for source in ("DAILYMED",):
            data = self._get(
                f"{self.RXNAV}/rxclass/class/byRxcui.json",
                {"rxcui": rxcui, "relaSource": source},
            )
            infos = (data.get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo") or []
            for info in infos:
                if info.get("rela") not in CLASS_RELAS:
                    continue
                item = info.get("rxclassMinConceptItem") or {}
                cid, cname = item.get("classId"), item.get("className")
                if cid and cname and cid not in out:
                    out[cid] = DrugClass(id=cid, name=cname, source=source)
        return list(out.values())

    def lookup_drug(self, term: str) -> DrugInfo | None:
        term = term.strip()
        if not term:
            return None
        data = self._get(f"{self.RXNAV}/approximateTerm.json", {"term": term, "maxEntries": 5})
        candidates = (data.get("approximateGroup") or {}).get("candidate") or []
        if not candidates:
            return None
        # Candidates come from several vocabularies. Some (e.g. a retired MMSL concept for
        # "Bactrim DS") have no current RxNorm properties, so prefer RXNORM-sourced candidates
        # by rank and take the first one RxNorm still knows.
        ordered = sorted(
            candidates,
            key=lambda c: (c.get("source") != "RXNORM", int(c.get("rank", 99))),
        )
        rxcui, prop, tried = "", {}, set()
        for cand in ordered:
            if cand["rxcui"] in tried:
                continue
            tried.add(cand["rxcui"])
            props = self._get(f"{self.RXNAV}/rxcui/{cand['rxcui']}/properties.json")
            if (props.get("properties") or {}).get("name"):
                rxcui, prop = str(cand["rxcui"]), props["properties"]
                break
        if not rxcui:
            return None
        name = prop["name"]
        tty = prop.get("tty")

        ingredients: list[Coding] = []
        if tty == "IN":
            ingredients.append(Coding(system=RXNORM_SYSTEM, code=rxcui, display=name))
        else:
            related = self._get(f"{self.RXNAV}/rxcui/{rxcui}/related.json", {"tty": "IN"})
            for group in (related.get("relatedGroup") or {}).get("conceptGroup") or []:
                for concept in group.get("conceptProperties") or []:
                    ingredients.append(
                        Coding(system=RXNORM_SYSTEM, code=concept["rxcui"], display=concept["name"])
                    )

        classes: dict[str, DrugClass] = {}
        for ing in ingredients or [Coding(system=RXNORM_SYSTEM, code=rxcui, display=name)]:
            for cls in self._classes(ing.code):
                classes.setdefault(cls.id, cls)
        return DrugInfo(
            query=term,
            rxcui=rxcui,
            name=name,
            ingredients=ingredients,
            classes=list(classes.values()),
        )

    def search_icd10(self, query: str, limit: int = 5) -> list[Coding]:
        if not query.strip():
            return []
        data = self._get(
            self.CLINICAL_TABLES, {"sf": "code,name", "terms": query, "maxList": limit}
        )
        # Response shape: [total, [codes], extra, [[code, name], ...]]
        rows = data[3] if isinstance(data, list) and len(data) > 3 and data[3] else []
        return [Coding(system=ICD10CM_SYSTEM, code=r[0], display=r[1]) for r in rows[:limit]]


# ---------------------------------------------------------------------------
# Offline: a snapshot of the same answers, bundled with the package
# ---------------------------------------------------------------------------


class OfflineTerminologyClient:
    name = "snapshot"
    mode = "offline"

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        if snapshot is None:
            snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.generated_at: str = snapshot.get("generated_at", "")
        self._drugs = [DrugInfo(**d) for d in snapshot.get("drugs", [])]
        self._aliases: dict[str, str] = {
            normalize_term(k): v for k, v in snapshot.get("aliases", {}).items()
        }
        self._icd = [Coding(system=ICD10CM_SYSTEM, **row) for row in snapshot.get("icd10cm", [])]

    def lookup_drug(self, term: str) -> DrugInfo | None:
        norm = normalize_term(term)
        if not norm:
            return None
        norm = self._aliases.get(norm, norm)
        best: tuple[float, DrugInfo] | None = None
        for drug in self._drugs:
            names = [drug.query, drug.name, *(i.display for i in drug.ingredients)]
            for candidate in names:
                cand = normalize_term(candidate)
                score = 1.0 if cand == norm else similarity(norm, cand)
                # "metformin 500 mg" should still find "metformin".
                if cand and re.search(rf"\b{re.escape(cand)}\b", norm):
                    score = max(score, 0.95)
                if best is None or score > best[0]:
                    best = (score, drug)
        if best is None or best[0] < 0.8:
            return None
        return best[1].model_copy(update={"query": term})

    def search_icd10(self, query: str, limit: int = 5) -> list[Coding]:
        """Mimic Clinical Tables: every query word must prefix a word of the name.

        Names containing the query as a phrase rank first, then shorter (less specific) names.
        """
        norm = normalize_term(query)
        words = norm.split()
        if not words:
            return []
        hits: list[tuple[int, int, Coding]] = []
        for row in self._icd:
            name = normalize_term(row.display)
            name_words = name.split()
            if all(any(nw.startswith(w) for nw in name_words) for w in words):
                phrase = 0 if re.search(rf"\b{re.escape(norm)}", name) else 1
                hits.append((phrase, len(name), row))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [h[2] for h in hits[:limit]]


class FallbackTerminologyClient:
    """Live NLM first; the bundled snapshot when NLM is unreachable."""

    name = "nlm+snapshot"

    def __init__(self, live: TerminologyClient, offline: TerminologyClient) -> None:
        self._live = live
        self._offline = offline
        self.degraded = False

    @property
    def mode(self) -> str:
        return "offline" if self.degraded else "live"

    def lookup_drug(self, term: str) -> DrugInfo | None:
        try:
            return self._live.lookup_drug(term)
        except TerminologyUnavailable as exc:
            log.warning("NLM unavailable (%s); using snapshot", exc)
            self.degraded = True
            return self._offline.lookup_drug(term)

    def search_icd10(self, query: str, limit: int = 5) -> list[Coding]:
        try:
            return self._live.search_icd10(query, limit)
        except TerminologyUnavailable as exc:
            log.warning("NLM unavailable (%s); using snapshot", exc)
            self.degraded = True
            return self._offline.search_icd10(query, limit)


# ---------------------------------------------------------------------------
# Snapshot generator: python -m intakeagent.verify.terminology snapshot
# ---------------------------------------------------------------------------

SNAPSHOT_DRUGS = [
    "metformin", "lisinopril", "amoxicillin", "augmentin", "penicillin g", "cephalexin",
    "azithromycin", "doxycycline", "ciprofloxacin", "sulfamethoxazole", "ibuprofen", "naproxen",
    "aspirin", "acetaminophen", "codeine", "tramadol", "morphine", "atorvastatin", "simvastatin",
    "amlodipine", "losartan", "hydrochlorothiazide", "metoprolol", "levothyroxine", "omeprazole",
    "albuterol", "sertraline", "fluoxetine", "insulin glargine", "warfarin", "prednisone",
    "gabapentin", "cetirizine", "montelukast",
]  # fmt: skip

# Spoken or allergy-style names that should resolve to a snapshot entry.
SNAPSHOT_ALIASES = {
    "penicillin": "penicillin g",
    "tylenol": "acetaminophen",
    "paracetamol": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "aleve": "naproxen",
    "lipitor": "atorvastatin",
    "synthroid": "levothyroxine",
    "zoloft": "sertraline",
    "prozac": "fluoxetine",
    "bactrim": "sulfamethoxazole",
    "keflex": "cephalexin",
    "lantus": "insulin glargine",
}

SNAPSHOT_ICD_QUERIES = [
    "right lower quadrant pain", "abdominal pain", "headache", "migraine", "chest pain",
    "low back pain", "cough", "fever", "acute pharyngitis", "shortness breath", "dizziness",
    "nausea vomiting", "rash", "type 2 diabetes", "essential hypertension", "asthma", "anxiety",
    "depression", "hypothyroidism", "urinary tract infection", "insomnia", "fatigue",
    "knee pain", "otalgia", "sinusitis", "allergic rhinitis",
]  # fmt: skip


def build_snapshot(client: NlmTerminologyClient | None = None) -> dict[str, Any]:
    from datetime import UTC, datetime

    client = client or NlmTerminologyClient()
    drugs = []
    for term in SNAPSHOT_DRUGS:
        info = client.lookup_drug(term)
        if info is None:
            print(f"  no RxNorm match for {term!r}", file=sys.stderr)
            continue
        drugs.append(info.model_copy(update={"query": term}).model_dump())
    icd: dict[str, dict[str, str]] = {}
    for q in SNAPSHOT_ICD_QUERIES:
        for c in client.search_icd10(q, limit=6):
            icd.setdefault(c.code, {"code": c.code, "display": c.display})
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "NLM RxNav, RxClass (DailyMed) and Clinical Tables ICD-10-CM",
        "drugs": drugs,
        "aliases": SNAPSHOT_ALIASES,
        "icd10cm": sorted(icd.values(), key=lambda r: r["code"]),
    }


def _main(argv: list[str]) -> int:
    if argv[:1] != ["snapshot"]:
        print("usage: python -m intakeagent.verify.terminology snapshot", file=sys.stderr)
        return 2
    snap = build_snapshot()
    text = json.dumps(snap, indent=1, ensure_ascii=False) + "\n"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH} ({len(snap['drugs'])} drugs, {len(snap['icd10cm'])} codes)")
    if FRONTEND_SNAPSHOT_PATH.parent.parent.exists():
        FRONTEND_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_SNAPSHOT_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {FRONTEND_SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(_main(sys.argv[1:]))
