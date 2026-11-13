"""End-to-end over HTTP and WebSocket in DEMO_MODE."""

import json

from intakeagent.stt.stub import SCRIPTS


def test_health_reports_demo_mode(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_mode"] is True
    assert body["llm"] == "stub"
    assert body["stt"] == "stub"
    assert body["clio_mode"] == "mock"


def test_full_healthcare_flow_over_rest(client):
    created = client.post("/sessions", json={"vertical": "healthcare"}).json()
    sid = created["id"]
    assert created["status"] == "recording"
    assert created["next_question"]
    assert any(f["name"] == "full_name" and f["required"] for f in created["field_specs"])

    for line in SCRIPTS["healthcare"]:
        r = client.post(f"/sessions/{sid}/text", json={"text": line})
        assert r.status_code == 200
    turn = r.json()
    assert turn["missing_fields"] == []
    assert "thank you" in turn["next_question"].lower()

    fin = client.post(f"/sessions/{sid}/finish")
    assert fin.status_code == 200
    assert fin.json()["status"] == "awaiting_approval"
    assert fin.json()["interrupt"]["record"]["full_name"]["value"] == "Sarah Mitchell"

    # Audio is refused after finish.
    assert client.post(f"/sessions/{sid}/text", json={"text": "more"}).status_code == 409
    # Export before approval is refused.
    assert client.post(f"/sessions/{sid}/export?target=fhir").status_code == 409

    session = client.get(f"/sessions/{sid}").json()
    edited = session["record"]
    edited["phone"]["value"] = "415-555-0199"
    appr = client.post(f"/sessions/{sid}/approve", json={"record": edited})
    assert appr.status_code == 200
    assert appr.json()["status"] == "approved"
    assert appr.json()["record"]["record"]["phone"]["value"] == "415-555-0199"

    exp = client.post(f"/sessions/{sid}/export?target=fhir")
    assert exp.status_code == 200
    assert exp.json()["mode"] == "dry-run"
    assert exp.json()["payload"]["resourceType"] == "Bundle"

    records = client.get("/records").json()
    assert records[0]["session_id"] == sid
    assert records[0]["export_target"] == "fhir"

    actions = [e["action"] for e in client.get(f"/sessions/{sid}/audit").json()]
    assert actions[0] == "session.created"
    assert "record.approved" in actions
    assert "record.exported" in actions


def test_legal_flow_with_export_on_approve(client):
    sid = client.post("/sessions", json={"vertical": "legal"}).json()["id"]
    for line in SCRIPTS["legal"]:
        client.post(f"/sessions/{sid}/text", json={"text": line})
    client.post(f"/sessions/{sid}/finish")
    appr = client.post(f"/sessions/{sid}/approve", json={"export_target": "clio"})
    assert appr.status_code == 200
    assert appr.json()["status"] == "exported"
    result = appr.json()["record"]["export_result"]
    assert result["mode"] == "mock"
    assert result["contact"]["last_name"] == "Okafor"
    assert client.get(f"/sessions/{sid}").json()["status"] == "exported"


def test_wrong_vertical_export_is_reported(client):
    sid = client.post("/sessions", json={"vertical": "legal"}).json()["id"]
    client.post(f"/sessions/{sid}/text", json={"text": SCRIPTS["legal"][0]})
    client.post(f"/sessions/{sid}/finish")
    client.post(f"/sessions/{sid}/approve", json={})
    out = client.post(f"/sessions/{sid}/export?target=fhir").json()
    assert "error" in out


def test_unknown_session_404(client):
    assert client.get("/sessions/nope").status_code == 404
    assert client.post("/sessions/nope/finish").status_code == 404


def test_schema_endpoint(client):
    body = client.get("/schemas/legal").json()
    names = [f["name"] for f in body["fields"]]
    assert names[0] == "client_name"
    assert "properties" in body["json_schema"]


def test_websocket_audio_and_finish(client):
    sid = client.post("/sessions", json={"vertical": "healthcare"}).json()["id"]
    with client.websocket_connect(f"/ws/intake/{sid}") as ws:
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        assert ready["stt"] == "stub"

        ws.send_text(json.dumps({"type": "audio_meta", "mime": "audio/webm;codecs=opus"}))
        ws.send_bytes(b"\x1aE\xdf\xa3fake-webm")  # stub ignores content

        seen = {}
        while "question" not in seen:
            msg = json.loads(ws.receive_text())
            seen[msg["type"]] = msg
        assert seen["transcript"]["segment"]["text"].startswith("Hi, my name is Sarah")
        assert seen["extraction"]["record"]["full_name"]["value"] == "Sarah Mitchell"
        assert seen["question"]["field"] == "phone"

        ws.send_text(json.dumps({"type": "text", "text": SCRIPTS["healthcare"][4]}))
        seen = {}
        while "question" not in seen:
            msg = json.loads(ws.receive_text())
            seen[msg["type"]] = msg
        assert seen["extraction"]["record"]["phone"]["value"] == "415-555-0134"

        ws.send_text(json.dumps({"type": "finish"}))
        while True:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "awaiting_approval":
                break
        assert msg["review_url"] == f"/review/{sid}"
        assert "chief_complaint" in msg["missing_fields"]

    assert client.get(f"/sessions/{sid}").json()["status"] == "awaiting_approval"


def test_websocket_unknown_session_closes(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/ws/intake/nope"):
        pass
    assert exc.value.code == 4404


def _finished(client, vertical):
    sid = client.post("/sessions", json={"vertical": vertical}).json()["id"]
    for line in SCRIPTS[vertical]:
        client.post(f"/sessions/{sid}/text", json={"text": line})
    return sid, client.post(f"/sessions/{sid}/finish").json()


def test_finish_attaches_verification_to_the_interrupt(client):
    _, fin = _finished(client, "healthcare")
    verification = fin["interrupt"]["verification"]
    assert [f["kind"] for f in verification["flags"]] == ["allergy_class"]
    assert verification["chief_complaint"]["suggestions"][0]["code"] == "R10.31"


def test_verify_endpoint_rechecks_an_edited_record(client):
    sid, fin = _finished(client, "healthcare")
    record = fin["interrupt"]["record"]
    record["medications"]["value"] = [{"name": "metformin"}]  # reviewer removed amoxicillin
    out = client.post(f"/sessions/{sid}/verify", json={"record": record}).json()
    assert out["flags"] == []
    stored = client.post(f"/sessions/{sid}/verify").json()  # stored record still has it
    assert len(stored["flags"]) == 1

    bad = client.post(f"/sessions/{sid}/verify", json={"record": {"medications": 3}})
    assert bad.status_code == 422
    actions = [e["action"] for e in client.get(f"/sessions/{sid}/audit").json()]
    assert actions.count("record.verified") == 2


def test_approve_audits_acknowledged_flags_and_exports_codes(client):
    sid, fin = _finished(client, "healthcare")
    flag_id = fin["interrupt"]["verification"]["flags"][0]["id"]
    record = fin["interrupt"]["record"]
    record["codes"]["medications"]["metformin"] = {
        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
        "code": "6809",
        "display": "metformin",
    }
    appr = client.post(
        f"/sessions/{sid}/approve",
        json={"record": record, "export_target": "fhir", "acknowledged_flags": [flag_id]},
    )
    assert appr.status_code == 200
    bundle = appr.json()["record"]["export_result"]["payload"]
    codings = [
        e["resource"]["medicationCodeableConcept"].get("coding")
        for e in bundle["entry"]
        if e["resource"]["resourceType"] == "MedicationStatement"
    ]
    assert [c[0]["code"] for c in codings if c] == ["6809"]
    approved = next(
        e for e in client.get(f"/sessions/{sid}/audit").json() if e["action"] == "record.approved"
    )
    assert approved["detail"]["acknowledged_flags"] == [flag_id]


def test_legal_verification_and_clio_export_carry_screening(client):
    sid, fin = _finished(client, "legal")
    sanctions = fin["interrupt"]["verification"]["sanctions"]
    statuses = {r["name"]: r["status"] for r in sanctions["results"]}
    assert statuses["Daniel Okafor"] == "clear"
    assert statuses["Northwind Logistics"] == "possible_match"
    assert sanctions["list"]["demo"] is True

    appr = client.post(f"/sessions/{sid}/approve", json={"export_target": "clio"}).json()
    result = appr["record"]["export_result"]
    assert result["sanctions_screening"]["status"] == "ok"
    assert "Sanctions screening against" in result["matter"]["description"]


def test_health_reports_verification_sources(client):
    body = client.get("/health").json()
    assert body["terminology"] == "offline"
    assert body["sanctions_list"]["demo"] is True
