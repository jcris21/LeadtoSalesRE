"""G8 identity capture: the deterministic name/DNI extractor that feeds the
Coordinator's identity gate. Core contract mirrors the generative extractor's:
recognition only — a message that does not carry a name must come back None,
never a guessed identity."""

from app.modules.lead_qualification.application.identity_extraction import (
    IdentityCapture,
    extract_identity,
)


class TestExplicitPatterns:
    def test_me_llamo(self):
        assert extract_identity("Me llamo Juan Pérez") == IdentityCapture(
            full_name="Juan Pérez"
        )

    def test_mi_nombre_es_title_cases_lowercase_input(self):
        assert extract_identity("mi nombre es maria lopez") == IdentityCapture(
            full_name="Maria Lopez"
        )

    def test_soy_single_name(self):
        assert extract_identity("Hola, soy Carlos") == IdentityCapture(full_name="Carlos")

    def test_name_and_dni_in_one_message(self):
        assert extract_identity(
            "Me llamo Ana Torres y mi DNI es 45678912"
        ) == IdentityCapture(full_name="Ana Torres", dni="45678912")

    def test_phone_number_is_not_a_dni(self):
        captured = extract_identity("Me llamo Ana, mi numero es 999888777")
        assert captured is not None
        assert captured.full_name == "Ana"
        assert captured.dni is None


class TestBareName:
    def test_bare_full_name(self):
        assert extract_identity("Juan Pérez") == IdentityCapture(full_name="Juan Pérez")

    def test_bare_name_with_dni(self):
        assert extract_identity("ana torres 45678912") == IdentityCapture(
            full_name="Ana Torres", dni="45678912"
        )

    def test_greeting_is_not_a_name(self):
        assert extract_identity("Hola! buenas tardes") is None

    def test_sentence_is_not_a_name(self):
        assert extract_identity("Estoy buscando un departamento para comprar") is None

    def test_single_bare_word_is_not_a_name(self):
        assert extract_identity("Miraflores") is None

    def test_dni_alone_is_not_enough(self):
        assert extract_identity("45678912") is None

    def test_empty_message(self):
        assert extract_identity("") is None
