from intakeagent.redaction import redact, rehydrate_record, rehydrate_text


def test_redacts_phone_email_and_ids():
    text = (
        "Call me on 415-555-0134 or email sarah@example.com. "
        "My SSN is 123-45-6789, my CNIC is 42101-1234567-1 "
        "and my Emirates ID is 784-1990-1234567-1."
    )
    red = redact(text)
    assert "415-555-0134" not in red.text
    assert "sarah@example.com" not in red.text
    assert "123-45-6789" not in red.text
    assert "42101-1234567-1" not in red.text
    assert "784-1990-1234567-1" not in red.text
    assert "[PHONE_1]" in red.text
    assert "[EMAIL_1]" in red.text
    assert red.text.count("[ID_") == 3


def test_redacts_names_dob_and_address_but_keeps_clinical_content():
    text = (
        "My name is Sarah Mitchell and I was born on March 4th, 1986. "
        "I live at 220 Maple Street, Oakland. I'm allergic to penicillin."
    )
    red = redact(text)
    assert "Sarah Mitchell" not in red.text
    assert "March 4th, 1986" not in red.text
    assert "220 Maple Street" not in red.text
    assert "allergic to penicillin" in red.text  # clinical content survives
    assert red.mapping["[NAME_1]"] == "Sarah Mitchell"


def test_same_value_gets_same_placeholder():
    red = redact("My name is Karen Blake. Karen Blake, my manager Karen Blake, signed it.")
    assert red.text.count("[NAME_1]") >= 2
    assert len({v for v in red.mapping.values()}) == 1


def test_rehydrate_restores_values_in_nested_structures():
    red = redact("My name is Daniel Okafor, phone 212-555-0188.")
    data = {"client_name": {"value": "[NAME_1]"}, "contacts": [{"phone": "[PHONE_1]"}]}
    out = rehydrate_record(data, red.mapping)
    assert out["client_name"]["value"] == "Daniel Okafor"
    assert out["contacts"][0]["phone"] == "212-555-0188"
    assert rehydrate_text(red.text, red.mapping).startswith("My name is Daniel Okafor")


def test_no_phi_means_no_changes():
    text = "I have had a headache since yesterday."
    red = redact(text)
    assert red.text == text
    assert red.count == 0
