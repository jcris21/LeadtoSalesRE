"""Generative fallback extractor (G1): recognition contract — a dimension the
message does not contain comes back as null and is never persisted; model
output is schema-validated against the domain enums before it becomes a
`ProfilePatch`. The Gemini client is exercised through httpx.MockTransport,
never the network."""

import json

import httpx
import pytest

from app.modules.lead_qualification.domain.models import (
    MoneyRange,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.generative_extractor import (
    GeminiGenerativeExtractor,
    build_generative_extractor,
    validated_patch,
)

ALL_DIMENSIONS = (
    "budget",
    "locations",
    "property_type",
    "timeline",
    "must_haves",
    "financing_type",
    "decision_maker_mode",
)


def test_validated_patch_happy_path():
    raw = json.dumps(
        {
            "budget": {"minimum": 250000, "maximum": 250000},
            "locations": ["Miraflores"],
            "property_type": "apartment",
            "timeline": "3_months",
            "must_haves": ["cochera"],
            "financing_type": None,
            "decision_maker_mode": None,
        }
    )
    patch = validated_patch(raw, ALL_DIMENSIONS)
    assert patch is not None
    assert patch.budget == MoneyRange(minimum=250000.0, maximum=250000.0)
    assert patch.locations == ("Miraflores",)
    assert patch.property_type is PropertyType.APARTMENT
    assert patch.timeline is Timeline.THREE_MONTHS
    assert patch.must_haves == ("cochera",)
    assert patch.financing_type is None  # null stays null — nothing invented


def test_validated_patch_drops_hallucinated_enum_value():
    raw = json.dumps({"property_type": "castle", "timeline": "3_months"})
    patch = validated_patch(raw, ALL_DIMENSIONS)
    assert patch is not None
    assert patch.property_type is None  # unknown enum dropped, not persisted
    assert patch.timeline is Timeline.THREE_MONTHS


def test_validated_patch_ignores_dimensions_that_were_not_requested():
    raw = json.dumps({"budget": {"minimum": 100000, "maximum": 200000}})
    # budget already captured -> not among the missing dimensions
    assert validated_patch(raw, ("timeline", "must_haves")) is None


def test_validated_patch_rejects_non_json_and_invalid_amounts():
    assert validated_patch("no soy json", ALL_DIMENSIONS) is None
    assert (
        validated_patch(json.dumps({"budget": {"minimum": -5, "maximum": 0}}), ALL_DIMENSIONS)
        is None
    )


def test_validated_patch_tolerates_markdown_fences():
    raw = '```json\n{"property_type": "house"}\n```'
    patch = validated_patch(raw, ALL_DIMENSIONS)
    assert patch is not None and patch.property_type is PropertyType.HOUSE


def test_build_generative_extractor_disabled_without_key():
    assert build_generative_extractor(None, "gemini-2.5-flash") is None
    assert build_generative_extractor("test-key", "gemini-2.5-flash") is not None


def _gemini_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(payload)}], "role": "model"}}
            ]
        },
    )


@pytest.mark.asyncio
async def test_gemini_extractor_parses_and_validates_model_output():
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return _gemini_response({"property_type": "apartment", "timeline": None})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = GeminiGenerativeExtractor("test-key", "gemini-2.5-flash", client)

    patch = await extractor.extract(
        text="algo chico para vivir cerca del mar",
        missing_dimensions=("property_type", "timeline"),
    )
    assert patch is not None and patch.property_type is PropertyType.APARTMENT

    request = seen_requests[0]
    assert request.url.path.endswith("/models/gemini-2.5-flash:generateContent")
    body = json.loads(request.content)
    assert "property_type, timeline" in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert request.headers["x-goog-api-key"] == "test-key"


@pytest.mark.asyncio
async def test_gemini_extractor_returns_none_on_terminal_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = GeminiGenerativeExtractor("test-key", "gemini-2.5-flash", client)

    patch = await extractor.extract(text="hola", missing_dimensions=ALL_DIMENSIONS)
    assert patch is None
