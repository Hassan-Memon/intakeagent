"""Clio exporter (Clio Manage API v4).

Produces a ``Contact`` (type Person) and a ``Matter`` payload in the exact JSON envelope Clio
expects (``{"data": {...}}``), plus a conflict check that searches existing contacts for every
name the intake surfaced.

Modes:

* mock (default): payloads are built and returned with fake ids. No network.
* live: when ``CLIO_ACCESS_TOKEN`` (or client id + secret + refresh token) is configured, the
  exporter calls ``POST /api/v4/contacts.json`` and ``POST /api/v4/matters.json`` on the
  configured region host. Clio's developer sandbox uses the same API surface.

OAuth2 is the standard authorization-code flow:

    GET  {base}/oauth/authorize?response_type=code&client_id=...&redirect_uri=...&state=...
    POST {base}/oauth/token  grant_type=authorization_code&code=...&client_id=...&client_secret=...
    POST {base}/oauth/token  grant_type=refresh_token&refresh_token=...

Tokens expire; ``ClioOAuthClient.refresh`` handles that. Tokens are never persisted by this
module; store them in your secret manager and pass them in via environment.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from intakeagent.schemas import LegalIntake


@dataclass
class ClioToken:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "bearer"
    obtained_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ClioOAuthClient:
    """Minimal OAuth2 client for Clio. Works against any regional host."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http or httpx.Client(timeout=30)

    def authorize_url(self, state: str | None = None) -> tuple[str, str]:
        """Return (url, state). ``state`` protects against CSRF on the callback."""
        state = state or secrets.token_urlsafe(16)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{self.base_url}/oauth/authorize?{urlencode(params)}", state

    def exchange_code(self, code: str) -> ClioToken:
        resp = self._http.post(
            f"{self.base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
            },
        )
        resp.raise_for_status()
        return ClioToken(**{k: v for k, v in resp.json().items() if k in ClioToken.__annotations__})

    def refresh(self, refresh_token: str) -> ClioToken:
        resp = self._http.post(
            f"{self.base_url}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        return ClioToken(**{k: v for k, v in resp.json().items() if k in ClioToken.__annotations__})


def _split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def build_contact_payload(record: LegalIntake) -> dict[str, Any]:
    """Clio v4 Contact (Person) payload."""
    first, last = _split_name(record.client_name.value or "Unknown Client")
    data: dict[str, Any] = {"type": "Person", "first_name": first, "last_name": last}
    if record.phone.value:
        data["phone_numbers"] = [
            {"name": "Mobile", "number": record.phone.value, "default_number": True}
        ]
    if record.email.value:
        data["email_addresses"] = [
            {"name": "Home", "address": record.email.value, "default_email": True}
        ]
    if record.address.value:
        data["addresses"] = [{"name": "Home", "street": record.address.value}]
    return {"data": data}


def build_matter_payload(record: LegalIntake, client_id: int | str) -> dict[str, Any]:
    """Clio v4 Matter payload. Opposing party and dates go into description and custom notes."""
    key_dates = record.key_dates.value or []
    lines = [record.matter_description.value or "Intake via IntakeAgent."]
    if record.opposing_party.value:
        lines.append(f"Opposing party: {record.opposing_party.value}")
    if record.jurisdiction.value:
        lines.append(f"Jurisdiction: {record.jurisdiction.value}")
    for kd in key_dates:
        label = kd.label if hasattr(kd, "label") else kd["label"]
        date = kd.date if hasattr(kd, "date") else kd["date"]
        lines.append(f"Key date: {label}: {date}")
    if record.urgency.value:
        lines.append(f"Urgency: {record.urgency.value}")
    data: dict[str, Any] = {
        "client": {"id": client_id},
        "description": "\n".join(lines),
        "status": "Pending",
        "open_date": datetime.now(UTC).date().isoformat(),
        "billable": True,
    }
    if record.matter_type.value:
        # Clio expects a practice_area id; we pass the name so a mapping layer can resolve it.
        data["practice_area"] = {"name": record.matter_type.value}
    if record.jurisdiction.value:
        data["location"] = record.jurisdiction.value
    return {"data": data}


class ClioExporter:
    name = "clio"

    def __init__(
        self,
        base_url: str,
        access_token: str = "",
        http: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = access_token
        self._http = http or httpx.Client(timeout=30)

    @property
    def live(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def conflict_check(self, names: list[str]) -> list[dict[str, Any]]:
        """Search existing contacts for each name. Mock mode reports zero hits."""
        results: list[dict[str, Any]] = []
        for name in names:
            if not self.live:
                results.append({"name": name, "hits": [], "mode": "mock"})
                continue
            resp = self._http.get(
                f"{self._base_url}/api/v4/contacts.json",
                params={"query": name, "fields": "id,name,type"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            results.append({"name": name, "hits": resp.json().get("data", []), "mode": "live"})
        return results

    def export(self, record: LegalIntake, session_id: str) -> dict[str, Any]:
        contact_payload = build_contact_payload(record)
        conflicts = self.conflict_check(record.conflict_check_names.value or [])
        if not self.live:
            contact_id = 100000 + (abs(hash(session_id)) % 899999)
            matter_payload = build_matter_payload(record, contact_id)
            return {
                "target": "clio",
                "mode": "mock",
                "server": self._base_url,
                "contact": {"id": contact_id, **contact_payload["data"]},
                "matter": {
                    "id": contact_id + 1,
                    "display_number": f"{datetime.now(UTC).year}-{contact_id % 10000:05d}",
                    **matter_payload["data"],
                },
                "conflict_check": conflicts,
                "payloads": {"contact": contact_payload, "matter": matter_payload},
            }

        c = self._http.post(
            f"{self._base_url}/api/v4/contacts.json",
            json=contact_payload,
            headers=self._headers(),
        )
        c.raise_for_status()
        contact = c.json()["data"]
        matter_payload = build_matter_payload(record, contact["id"])
        m = self._http.post(
            f"{self._base_url}/api/v4/matters.json",
            json=matter_payload,
            headers=self._headers(),
        )
        m.raise_for_status()
        return {
            "target": "clio",
            "mode": "live",
            "server": self._base_url,
            "contact": contact,
            "matter": m.json()["data"],
            "conflict_check": conflicts,
            "payloads": {"contact": contact_payload, "matter": matter_payload},
        }
