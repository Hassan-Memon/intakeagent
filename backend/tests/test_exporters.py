import httpx
from fhir.resources.R4B.bundle import Bundle

from intakeagent.exporters import ClioExporter, ClioOAuthClient, FhirExporter, build_bundle
from intakeagent.exporters.clio import build_contact_payload, build_matter_payload
from intakeagent.graph.extractors import RuleBasedExtractor


def _patient(transcript):
    return RuleBasedExtractor().extract(transcript, "healthcare", None)


def _client(transcript):
    return RuleBasedExtractor().extract(transcript, "legal", None)


def test_fhir_bundle_is_a_valid_transaction_with_expected_resources(healthcare_transcript):
    bundle = build_bundle(_patient(healthcare_transcript), "sess-1")
    Bundle.model_validate(bundle)  # re-validates the whole thing against the FHIR profile
    assert bundle["type"] == "transaction"
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert types.count("Patient") == 1
    assert types.count("Encounter") == 1
    assert types.count("Condition") == 2  # chief complaint + type 2 diabetes
    assert types.count("AllergyIntolerance") == 1
    assert types.count("MedicationStatement") == 3  # metformin, lisinopril, amoxicillin
    assert types.count("Coverage") == 1
    assert all(e["request"]["method"] == "POST" for e in bundle["entry"])
    patient = next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient"
    )
    assert patient["birthDate"] == "1986-03-04"
    assert patient["name"][0]["family"] == "Mitchell"
    # Every reference points at a fullUrl inside the bundle.
    urls = {e["fullUrl"] for e in bundle["entry"]}
    for e in bundle["entry"]:
        for key in ("subject", "patient", "beneficiary", "encounter", "context"):
            if key in e["resource"]:
                assert e["resource"][key]["reference"] in urls


def test_fhir_exporter_dry_run_does_not_touch_network(healthcare_transcript):
    out = FhirExporter("https://hapi.fhir.org/baseR4", push=False).export(
        _patient(healthcare_transcript), "sess-2"
    )
    assert out["mode"] == "dry-run"
    assert out["resource_count"] == len(out["payload"]["entry"])


def test_fhir_exporter_push_uses_transaction_post(healthcare_transcript):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers["content-type"]
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})

    exporter = FhirExporter("https://fhir.example/baseR4", push=True)
    # Swap httpx.Client for a mocked transport.
    import intakeagent.exporters.fhir as fhir_mod

    original = fhir_mod.httpx.Client
    fhir_mod.httpx.Client = lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    try:
        out = exporter.export(_patient(healthcare_transcript), "sess-3")
    finally:
        fhir_mod.httpx.Client = original
    assert out["status_code"] == 200
    assert seen["url"] == "https://fhir.example/baseR4"
    assert seen["content_type"] == "application/fhir+json"
    assert out["response"]["type"] == "transaction-response"


def test_clio_payloads_have_v4_shape(legal_transcript):
    rec = _client(legal_transcript)
    contact = build_contact_payload(rec)
    assert contact["data"]["type"] == "Person"
    assert contact["data"]["first_name"] == "Daniel"
    assert contact["data"]["last_name"] == "Okafor"
    assert contact["data"]["phone_numbers"][0]["default_number"] is True
    assert contact["data"]["email_addresses"][0]["address"] == "daniel.okafor@example.com"
    matter = build_matter_payload(rec, 42)
    assert matter["data"]["client"] == {"id": 42}
    assert matter["data"]["status"] == "Pending"
    assert "Opposing party: Northwind Logistics" in matter["data"]["description"]
    assert "2025-07-15" in matter["data"]["description"]


def test_clio_mock_export_runs_conflict_check(legal_transcript):
    out = ClioExporter("https://app.clio.com").export(_client(legal_transcript), "sess-4")
    assert out["mode"] == "mock"
    assert out["contact"]["id"] > 0
    assert out["matter"]["client"]["id"] == out["contact"]["id"]
    names = {c["name"] for c in out["conflict_check"]}
    assert {"Daniel Okafor", "Northwind Logistics", "Karen Blake"} <= names


def test_clio_live_export_posts_contact_then_matter(legal_transcript):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path.endswith("/contacts.json") and request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if request.url.path.endswith("/contacts.json"):
            return httpx.Response(201, json={"data": {"id": 7, "name": "Daniel Okafor"}})
        return httpx.Response(201, json={"data": {"id": 99, "display_number": "00099-Okafor"}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    out = ClioExporter("https://app.clio.com", access_token="tok", http=http).export(
        _client(legal_transcript), "sess-5"
    )
    assert out["mode"] == "live"
    assert out["matter"]["id"] == 99
    assert ("POST", "/api/v4/contacts.json") in calls
    assert ("POST", "/api/v4/matters.json") in calls
    assert calls.index(("POST", "/api/v4/contacts.json")) < calls.index(
        ("POST", "/api/v4/matters.json")
    )


def test_clio_oauth_flow():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert request.url.path == "/oauth/token"
        if "grant_type=authorization_code" in body:
            return httpx.Response(
                200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
            )
        assert "grant_type=refresh_token" in body
        return httpx.Response(200, json={"access_token": "a2", "expires_in": 3600})

    client = ClioOAuthClient(
        "https://app.clio.com",
        "cid",
        "secret",
        "http://localhost:8000/oauth/clio/callback",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    url, state = client.authorize_url()
    assert url.startswith("https://app.clio.com/oauth/authorize?")
    assert "response_type=code" in url and f"state={state}" in url
    token = client.exchange_code("code123")
    assert token.access_token == "a1" and token.refresh_token == "r1"
    assert client.refresh("r1").access_token == "a2"


def test_fhir_bundle_carries_reviewer_accepted_codes(healthcare_transcript):
    record = _patient(healthcare_transcript)
    rx = {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "6809",
          "display": "metformin"}  # fmt: skip
    icd = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "R10.31",
           "display": "Right lower quadrant pain"}  # fmt: skip
    data = record.model_dump()
    data["codes"]["medications"] = {"metformin": rx, "a name that was edited away": rx}
    data["codes"]["chief_complaint"] = {record.chief_complaint.value: icd}
    record = type(record).model_validate(data)

    bundle = build_bundle(record, "sess-codes")
    Bundle.model_validate(bundle)
    meds = [
        e["resource"]["medicationCodeableConcept"]
        for e in bundle["entry"]
        if e["resource"]["resourceType"] == "MedicationStatement"
    ]
    by_text = {m["text"]: m for m in meds}
    assert by_text["metformin"]["coding"] == [rx]
    assert "coding" not in by_text["lisinopril"]  # not accepted, stays text-only
    complaint = next(
        e["resource"]["code"]
        for e in bundle["entry"]
        if e["resource"]["resourceType"] == "Condition"
        and e["resource"]["category"][0]["coding"][0]["code"] == "encounter-diagnosis"
    )
    assert complaint["coding"] == [icd]


def test_clio_matter_records_sanctions_screening(legal_transcript):
    screening = {
        "status": "ok",
        "list": {"name": "Demo list", "generated_at": "2026-11-13"},
        "results": [
            {"name": "Daniel Okafor", "role": "client", "status": "clear", "matches": []},
            {
                "name": "Northwind Logistics",
                "role": "opposing party",
                "status": "possible_match",
                "matches": [
                    {"matched_name": "NORTHWIND LOGISTIX", "list": "Demo list", "score": 0.912}
                ],
            },
        ],
    }
    out = ClioExporter("https://app.clio.com").export(
        _client(legal_transcript), "sess-s", screening=screening
    )
    assert out["sanctions_screening"] == screening
    desc = out["matter"]["description"]
    assert "Sanctions screening against Demo list (as of 2026-11-13):" in desc
    assert "Daniel Okafor (client): no match" in desc
    assert "possible match to NORTHWIND LOGISTIX [Demo list], score 0.91" in desc
