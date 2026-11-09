from intakeagent.graph.extractors import RuleBasedExtractor, normalize_date
from intakeagent.schemas import missing_required


def test_rules_extract_every_required_healthcare_field(healthcare_transcript):
    rec = RuleBasedExtractor().extract(healthcare_transcript, "healthcare", None)
    assert missing_required(rec) == []
    assert rec.full_name.value == "Sarah Mitchell"
    assert rec.date_of_birth.value == "1986-03-04"
    assert rec.phone.value == "415-555-0134"
    assert rec.symptom_severity.value == "6/10"
    meds = {m.name: m for m in rec.medications.value}
    assert meds["metformin"].dose == "500 milligrams"
    assert meds["metformin"].frequency == "twice a day"
    assert rec.allergies.value[0].substance == "penicillin"
    assert rec.allergies.value[0].reaction == "hives"
    assert rec.insurance_payer.value == "Blue Shield"
    assert rec.insurance_member_id.value == "BS88213"


def test_rules_extract_every_required_legal_field(legal_transcript):
    rec = RuleBasedExtractor().extract(legal_transcript, "legal", None)
    assert missing_required(rec) == []
    assert rec.client_name.value == "Daniel Okafor"
    assert rec.email.value == "daniel.okafor@example.com"
    assert rec.matter_type.value == "Employment"
    assert rec.opposing_party.value == "Northwind Logistics"
    assert {d.date for d in rec.key_dates.value} == {"2025-06-12", "2025-06-20", "2025-07-15"}
    assert set(rec.conflict_check_names.value) >= {
        "Daniel Okafor",
        "Northwind Logistics",
        "Karen Blake",
    }
    assert rec.jurisdiction.value == "Newark, New Jersey"


def test_evidence_spans_point_into_transcript(healthcare_transcript):
    rec = RuleBasedExtractor().extract(healthcare_transcript, "healthcare", None)
    ev = rec.chief_complaint.evidence[0]
    assert ev.start >= 0
    assert healthcare_transcript[ev.start : ev.end].lower() == ev.quote.lower()


def test_merge_keeps_previous_values_when_new_turn_lacks_them():
    ex = RuleBasedExtractor()
    first = ex.extract("My name is Sarah Mitchell.", "healthcare", None)
    second = ex.extract("I take metformin 500 mg daily.", "healthcare", first)
    assert second.full_name.value == "Sarah Mitchell"
    assert second.medications.value[0].name == "metformin"


def test_negations_satisfy_required_lists():
    rec = RuleBasedExtractor().extract(
        "I have no known allergies and I'm not taking any medications.", "healthcare", None
    )
    assert rec.allergies.value[0].substance == "No known allergies"
    assert rec.medications.value[0].name == "None reported"


def test_normalize_date_formats():
    assert normalize_date("March 4th, 1986") == "1986-03-04"
    assert normalize_date("4 March 1986") == "1986-03-04"
    assert normalize_date("03/04/1986") == "1986-03-04"
    assert normalize_date("1986-03-04") == "1986-03-04"
    assert normalize_date("sometime in spring") == "sometime in spring"
