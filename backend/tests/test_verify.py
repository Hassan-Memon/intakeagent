"""Verification: terminology coding, allergy cross-check, ICD-10 suggestions, sanctions.

Everything runs offline: the bundled snapshot, the fictional demo sanctions list, and an
``httpx.MockTransport`` standing in for NLM so the live client's parsing is still exercised.
"""

from pathlib import Path

import httpx
import pytest

from intakeagent.graph.extractors import RuleBasedExtractor
from intakeagent.schemas import PatientIntake
from intakeagent.stt.stub import SCRIPTS
from intakeagent.verify import build_verifier
from intakeagent.verify.clinical import complaint_query, verify_patient
from intakeagent.verify.sanctions import (
    DEMO_LIST_PATH,
    SanctionsList,
    name_score,
    normalize_name,
    parse_ofac,
    parse_un,
    screen_names,
)
from intakeagent.verify.terminology import (
    FRONTEND_SNAPSHOT_PATH,
    ICD10CM_SYSTEM,
    RXNORM_SYSTEM,
    SNAPSHOT_PATH,
    FallbackTerminologyClient,
    NlmTerminologyClient,
    OfflineTerminologyClient,
)

FRONTEND_SANCTIONS = (
    Path(__file__).resolve().parents[2] / "frontend" / "lib" / "demo" / "data" / "sanctions.json"
)


@pytest.fixture(scope="module")
def offline() -> OfflineTerminologyClient:
    return OfflineTerminologyClient()


def _patient(meds: list[str], allergies: list[str], complaint: str = "") -> PatientIntake:
    return PatientIntake(
        medications={"value": [{"name": m} for m in meds]},
        allergies={"value": [{"substance": a} for a in allergies]},
        chief_complaint={"value": complaint or None},
    )


# -- terminology -----------------------------------------------------------------


def test_complaint_query_rewrites_lay_terms():
    assert complaint_query("sharp pain in my lower right side") == "pain right lower quadrant"
    assert complaint_query("my stomach ache") == "abdominal pain"
    assert complaint_query("I've been throwing up") == "vomiting"


def test_offline_lookup_handles_brands_doses_and_typos(offline):
    assert offline.lookup_drug("Tylenol").name == "acetaminophen"
    assert offline.lookup_drug("metformin 500").rxcui == "6809"
    assert offline.lookup_drug("amoxicilin").rxcui == "723"  # one letter missing
    assert offline.lookup_drug("unobtainium") is None


def test_offline_icd_ranks_phrase_matches_first(offline):
    hits = offline.search_icd10("type 2 diabetes")
    assert hits and all("Type 2 diabetes" in h.display for h in hits)
    assert offline.search_icd10("right lower quadrant pain")[0].code == "R10.31"


def test_demo_patient_gets_codes_and_a_penicillin_flag(offline):
    record = RuleBasedExtractor().extract(" ".join(SCRIPTS["healthcare"]), "healthcare", None)
    out = verify_patient(record, offline)

    meds = {m["input"]: m for m in out["medications"]}
    assert meds["metformin"]["match"] == {
        "system": RXNORM_SYSTEM,
        "code": "6809",
        "display": "metformin",
    }
    assert meds["amoxicillin"]["confidence"] >= 0.9
    assert out["chief_complaint"]["suggestions"][0]["code"] == "R10.31"
    assert out["chief_complaint"]["suggestions"][0]["system"] == ICD10CM_SYSTEM

    assert len(out["flags"]) == 1
    flag = out["flags"][0]
    assert flag["kind"] == "allergy_class"
    assert "amoxicillin" in flag["title"] and "penicillin" in flag["title"]
    assert "Penicillin" in flag["detail"]


def test_same_ingredient_is_a_high_severity_flag(offline):
    out = verify_patient(_patient(["Advil 200 mg"], ["ibuprofen"]), offline)
    assert [f["kind"] for f in out["flags"]] == ["allergy_ingredient"]
    assert out["flags"][0]["severity"] == "high"


def test_class_words_and_shared_classes_are_flagged(offline):
    sulfa = verify_patient(_patient(["Bactrim"], ["sulfa"]), offline)
    assert sulfa["flags"] and "Sulfonamide" in sulfa["flags"][0]["detail"]
    nsaid = verify_patient(_patient(["naproxen"], ["ibuprofen"]), offline)
    assert nsaid["flags"] and "Nonsteroidal" in nsaid["flags"][0]["detail"]


def test_unrelated_and_non_drug_allergies_do_not_flag(offline):
    out = verify_patient(_patient(["metformin", "lisinopril"], ["latex", "penicillin"]), offline)
    assert out["flags"] == []
    assert out["allergies"][0]["status"] == "not_a_drug"


def _nlm_transport() -> httpx.MockTransport:
    """Canned NLM responses in the real shapes (captured from the live APIs)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        if path.endswith("/approximateTerm.json"):
            return httpx.Response(
                200,
                json={
                    "approximateGroup": {
                        "candidate": [
                            {"rxcui": "151392", "rank": "1", "source": "MMSL"},
                            {"rxcui": "151392", "rank": "1", "name": "Augmentin",
                             "source": "RXNORM"},
                        ]
                    }
                },
            )  # fmt: skip
        if path.endswith("/151392/properties.json"):
            return httpx.Response(
                200, json={"properties": {"rxcui": "151392", "name": "Augmentin", "tty": "BN"}}
            )
        if path.endswith("/151392/related.json"):
            return httpx.Response(
                200,
                json={
                    "relatedGroup": {
                        "conceptGroup": [
                            {
                                "tty": "IN",
                                "conceptProperties": [
                                    {"rxcui": "48203", "name": "clavulanate"},
                                    {"rxcui": "723", "name": "amoxicillin"},
                                ],
                            }
                        ]
                    }
                },
            )
        if path.endswith("/rxclass/class/byRxcui.json"):
            assert params["relaSource"] == "DAILYMED"
            classes = {
                "723": [("has_epc", "N0000175497", "Penicillin-class Antibacterial")],
                "48203": [("has_epc", "N0000175583", "beta Lactamase Inhibitor")],
            }[params["rxcui"]]
            return httpx.Response(
                200,
                json={
                    "rxclassDrugInfoList": {
                        "rxclassDrugInfo": [
                            {"rela": r, "rxclassMinConceptItem": {"classId": i, "className": n}}
                            for r, i, n in classes
                        ]
                    }
                },
            )
        if "icd10cm" in path:
            assert params["terms"] == "right lower quadrant"
            return httpx.Response(
                200, json=[1, ["R10.31"], None, [["R10.31", "Right lower quadrant pain"]]]
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_live_client_parses_nlm_responses():
    client = NlmTerminologyClient(http=httpx.Client(transport=_nlm_transport()))
    info = client.lookup_drug("augmentin")
    assert info.rxcui == "151392" and info.name == "Augmentin"
    assert {i.display for i in info.ingredients} == {"amoxicillin", "clavulanate"}
    assert "Penicillin-class Antibacterial" in {c.name for c in info.classes}
    assert client.search_icd10("right lower quadrant")[0].code == "R10.31"


def test_fallback_uses_snapshot_when_nlm_is_down(offline):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    live = NlmTerminologyClient(http=httpx.Client(transport=httpx.MockTransport(down)))
    client = FallbackTerminologyClient(live, offline)
    assert client.mode == "live"
    assert client.lookup_drug("lisinopril").rxcui == "29046"
    assert client.mode == "offline"


def test_frontend_snapshot_matches_backend():
    assert FRONTEND_SNAPSHOT_PATH.read_text(encoding="utf-8") == SNAPSHOT_PATH.read_text(
        encoding="utf-8"
    ), "run: uv run python -m intakeagent.verify.terminology snapshot"


# -- sanctions -------------------------------------------------------------------


def test_normalize_name_drops_accents_punctuation_and_suffixes():
    assert normalize_name("Société Générale SA") == ["societe", "generale"]
    assert normalize_name("NORTHWIND LOGISTIX TRADING FZE") == ["northwind", "logistix", "trading"]
    assert normalize_name("Acme Holdings LLC") == ["acme", "holdings"]


def test_name_score_is_order_insensitive_and_typo_tolerant():
    assert name_score(["jordan", "sample"], ["sample", "jordan"]) == 1.0
    assert name_score(["northwind", "logistics"], ["northwind", "logistix"]) > 0.9
    assert name_score(["karen", "blake"], ["northwind", "logistix"]) < 0.5


def test_demo_list_flags_near_match_and_clears_others():
    result = screen_names(
        SanctionsList.demo_list(),
        [("Daniel Okafor", "client"), ("Northwind Logistics", "opposing party"), ("Blake", "x")],
    )
    by_name = {r["name"]: r for r in result["results"]}
    assert by_name["Daniel Okafor"]["status"] == "clear"
    assert by_name["Northwind Logistics"]["status"] == "possible_match"
    assert by_name["Northwind Logistics"]["matches"][0]["matched_name"] == "NORTHWIND LOGISTIX"
    assert by_name["Blake"]["status"] == "clear"  # one-word names are not screened as hits
    assert result["list"]["demo"] is True


def test_exact_listed_name_is_a_strong_match():
    result = screen_names(SanctionsList.demo_list(), [("Jordan Quinn Sample", "client")])
    assert result["results"][0]["status"] == "strong_match"


def test_missing_list_is_reported_not_silently_clear():
    result = screen_names(None, [("Anyone", "client")])
    assert result["status"] == "unavailable"
    assert result["results"] == []


def test_parse_ofac_and_un_formats():
    sdn = (
        '36,"AEROCARIBBEAN AIRLINES",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- \n'
        '9640,"ABU TEIR, Mohammed","individual","NS-PLC",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,x\n'
    )
    alt = '36,12,"aka","AERO-CARIBBEAN",-0- \n'
    entries = parse_ofac("OFAC SDN", sdn, alt)
    assert entries[0].name == "AEROCARIBBEAN AIRLINES"
    assert entries[0].type == "entity" and entries[0].program == "CUBA"
    assert entries[0].aliases == ["AERO-CARIBBEAN"]
    assert entries[1].type == "individual"

    xml = """<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><DATAID>1</DATAID>
      <FIRST_NAME>ERIC</FIRST_NAME><SECOND_NAME>BADEGE</SECOND_NAME>
      <UN_LIST_TYPE>DRC</UN_LIST_TYPE><REFERENCE_NUMBER>CDi.001</REFERENCE_NUMBER>
      <INDIVIDUAL_ALIAS><ALIAS_NAME>E. B.</ALIAS_NAME></INDIVIDUAL_ALIAS>
      </INDIVIDUAL></INDIVIDUALS><ENTITIES><ENTITY><DATAID>2</DATAID>
      <FIRST_NAME>EXAMPLE TRADING</FIRST_NAME><REFERENCE_NUMBER>X.1</REFERENCE_NUMBER>
      </ENTITY></ENTITIES></CONSOLIDATED_LIST>"""
    un = parse_un(xml)
    assert [(e.name, e.type, e.id) for e in un] == [
        ("ERIC BADEGE", "individual", "UN:CDi.001"),
        ("EXAMPLE TRADING", "entity", "UN:X.1"),
    ]
    assert un[0].aliases == ["E. B."]


def test_frontend_demo_sanctions_list_matches_backend():
    assert FRONTEND_SANCTIONS.read_text(encoding="utf-8") == DEMO_LIST_PATH.read_text(
        encoding="utf-8"
    )


# -- verifier facade ---------------------------------------------------------------


def test_verifier_reports_sources_and_legal_flags():
    verifier = build_verifier(demo_mode=True, terminology_provider="auto", sanctions_list_path="")
    record = RuleBasedExtractor().extract(" ".join(SCRIPTS["legal"]), "legal", None)
    out = verifier.verify("legal", record.model_dump())
    assert out["sources"][0]["mode"] == "demo"
    assert [f["kind"] for f in out["flags"]] == ["sanctions_match"]
    assert out["flags"][0]["fields"] == ["opposing_party"]

    health = verifier.verify("healthcare", PatientIntake().model_dump())
    assert health["sources"][0]["mode"] == "offline"
    assert health["flags"] == []


def test_production_without_list_reports_unavailable(tmp_path):
    verifier = build_verifier(
        demo_mode=False,
        terminology_provider="offline",
        sanctions_list_path=str(tmp_path / "missing.json"),
    )
    out = verifier.verify("legal", {"client_name": {"value": "Daniel Okafor"}})
    assert out["sanctions"]["status"] == "unavailable"
    assert out["errors"] and out["flags"] == []


def test_class_allergies_are_not_coded_as_products(offline):
    out = verify_patient(_patient(["Bactrim"], ["sulfa drugs"]), offline)
    assert out["allergies"][0]["status"] == "drug_class"
    assert out["allergies"][0]["match"] is None
    assert out["flags"][0]["kind"] == "allergy_class"


def test_strength_without_unit_still_resolves(offline):
    out = verify_patient(_patient(["Advil 400"], ["naproxen"]), offline)
    assert out["medications"][0]["match"]["display"] == "ibuprofen"
    assert out["flags"] and "Nonsteroidal" in out["flags"][0]["detail"]
