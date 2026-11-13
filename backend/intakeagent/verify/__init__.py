"""Verification: public reference data checked against an intake before a human approves it.

* Healthcare: medications coded to RxNorm, allergy cross-check by ingredient and drug class,
  ICD-10-CM suggestions for the chief complaint and conditions (NLM, see ``terminology``).
* Legal: every party name screened against OFAC and UN sanctions lists, locally
  (see ``sanctions``).

Everything here produces *suggestions and flags* for the review screen. Nothing edits the
record, nothing blocks approval, and a missing data source is reported, never hidden.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intakeagent.schemas import LegalIntake, PatientIntake
from intakeagent.verify.clinical import verify_patient
from intakeagent.verify.sanctions import SanctionsList, normalize_name, screen_names
from intakeagent.verify.terminology import (
    FallbackTerminologyClient,
    NlmTerminologyClient,
    OfflineTerminologyClient,
    TerminologyClient,
)

log = logging.getLogger(__name__)

LEGAL_ROLES = {
    "client_name": "client",
    "opposing_party": "opposing party",
    "conflict_check_names": "named party",
}


class Verifier:
    def __init__(
        self, terminology: TerminologyClient | None, sanctions: SanctionsList | None
    ) -> None:
        self.terminology = terminology
        self.sanctions = sanctions

    def __call__(self, vertical: str, record: dict[str, Any]) -> dict[str, Any]:
        return self.verify(vertical, record)

    def verify(self, vertical: str, record: dict[str, Any]) -> dict[str, Any]:
        checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        if vertical == "healthcare":
            return {"vertical": vertical, "checked_at": checked_at, **self._clinical(record)}
        if vertical == "legal":
            return {"vertical": vertical, "checked_at": checked_at, **self._legal(record)}
        return {"vertical": vertical, "checked_at": checked_at, "flags": [], "sources": []}

    def _clinical(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.terminology is None:
            return {"sources": [], "flags": [], "errors": ["terminology checks disabled"]}
        client = self.terminology
        if isinstance(client, FallbackTerminologyClient):
            client.degraded = False  # report this run's mode, not a past outage
        result = verify_patient(PatientIntake(**record), client)
        mode = client.mode
        result["sources"] = [
            {"name": "RxNorm + RxClass (U.S. National Library of Medicine)", "mode": mode},
            {"name": "ICD-10-CM (NLM Clinical Tables)", "mode": mode},
        ]
        return result

    def screen(self, record: LegalIntake) -> dict[str, Any]:
        parties: list[tuple[str, str]] = []
        if record.client_name.value:
            parties.append((record.client_name.value, "client"))
        if record.opposing_party.value:
            parties.append((record.opposing_party.value, "opposing party"))
        for name in record.conflict_check_names.value or []:
            parties.append((name, "named party"))
        return screen_names(self.sanctions, parties)

    def _legal(self, record: dict[str, Any]) -> dict[str, Any]:
        intake = LegalIntake(**record)
        screening = self.screen(intake)
        role_fields = {v: k for k, v in LEGAL_ROLES.items()}
        flags = []
        for r in screening["results"]:
            if r["status"] == "clear":
                continue
            top = r["matches"][0]
            program = f", program {top['program']}" if top.get("program") else ""
            flags.append(
                {
                    "id": f"sanctions:{' '.join(normalize_name(r['name']))}",
                    "kind": "sanctions_match",
                    "severity": "high" if r["status"] == "strong_match" else "warning",
                    "title": f"{r['name']} ({r['role']}) resembles a sanctions-list entry",
                    "detail": f"Closest entry: {top['matched_name']} ({top['list']}{program}), "
                    f"similarity {top['score']:.2f}. Confirm identity (date of birth, address, "
                    "nationality, registration number) before opening the matter. A similar "
                    "name is not a match on its own.",
                    "fields": [role_fields.get(r["role"], "conflict_check_names")],
                }
            )
        lst = screening.get("list") or {}
        sources = (
            [
                {
                    "name": lst.get("name", "Sanctions list"),
                    "mode": "demo" if lst.get("demo") else "local",
                    "as_of": lst.get("generated_at"),
                }
            ]
            if screening["status"] == "ok"
            else []
        )
        errors = [screening["message"]] if screening["status"] != "ok" else []
        return {"sanctions": screening, "flags": flags, "sources": sources, "errors": errors}


def build_verifier(
    *, demo_mode: bool, terminology_provider: str, sanctions_list_path: str
) -> Verifier:
    offline = OfflineTerminologyClient()
    terminology: TerminologyClient
    if terminology_provider == "offline" or (terminology_provider == "auto" and demo_mode):
        terminology = offline
    else:
        terminology = FallbackTerminologyClient(NlmTerminologyClient(), offline)

    sanctions: SanctionsList | None = None
    if demo_mode:
        sanctions = SanctionsList.demo_list()
    elif sanctions_list_path and Path(sanctions_list_path).exists():
        sanctions = SanctionsList.load(sanctions_list_path)
    else:
        log.warning(
            "No sanctions list at %s; legal screening will report 'unavailable'. Run "
            "`python -m intakeagent.verify.sanctions refresh`.",
            sanctions_list_path,
        )
    return Verifier(terminology, sanctions)


__all__ = ["Verifier", "build_verifier"]
