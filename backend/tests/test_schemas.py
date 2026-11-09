from intakeagent.schemas import (
    Evidence,
    Extracted,
    LegalIntake,
    PatientIntake,
    field_specs,
    missing_required,
)


def test_field_specs_expose_required_and_question_metadata():
    specs = {s.name: s for s in field_specs(PatientIntake)}
    assert specs["full_name"].required is True
    assert specs["email"].required is False
    assert "name" in specs["full_name"].question.lower()
    assert specs["medications"].kind == "list"
    assert specs["chief_complaint"].group == "visit"


def test_missing_required_lists_empty_required_fields_in_order():
    record = PatientIntake()
    missing = missing_required(record)
    assert missing[0] == "full_name"
    assert "email" not in missing
    assert "allergies" in missing


def test_missing_required_shrinks_as_values_arrive():
    record = PatientIntake(
        full_name=Extracted(value="Sarah Mitchell", evidence=[Evidence(quote="my name is Sarah")]),
        allergies=Extracted(value=[{"substance": "penicillin"}]),
    )
    missing = missing_required(record)
    assert "full_name" not in missing
    assert "allergies" not in missing
    assert "phone" in missing


def test_empty_string_and_empty_list_count_as_missing():
    assert not Extracted(value="   ").present
    assert not Extracted(value=[]).present
    assert Extracted(value=0).present


def test_legal_schema_round_trips_through_dict():
    rec = LegalIntake(key_dates=Extracted(value=[{"label": "fired", "date": "2025-06-12"}]))
    again = LegalIntake(**rec.model_dump())
    assert again.key_dates.value[0].date == "2025-06-12"
    assert "conflict_check_names" in missing_required(again)
