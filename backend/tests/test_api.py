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
