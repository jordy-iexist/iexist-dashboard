import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.features.landing_pages.schemas import LandingPageGenerationSettingsUpdateRequest
from app.features.landing_pages.services.generation.openai import (
    DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
    DEFAULT_LANDING_PAGE_REASONING_EFFORT,
    LANDING_PAGE_END_MARKER,
    LandingPageOutputValidationError,
    generate_landing_page,
    validate_landing_page_output,
)


def _body(*, include_faq: bool = True, faq_count: int = 6) -> str:
    paragraph = (
        "Deze landingspagina legt helder uit wat de bezoeker moet weten voordat "
        "hij een offerte aanvraagt. De tekst gebruikt concrete voorbeelden, "
        "benoemt voordelen en sluit logisch aan op de zoekintentie van de lezer. "
    )
    sections = [
        "# Glad stucwerk laten uitvoeren",
        "",
        paragraph * 4,
        "## Waarom professioneel stucwerk belangrijk is",
        "",
        paragraph * 4,
        "## Kosten en planning",
        "",
        paragraph * 4,
    ]
    if include_faq:
        faq_sections = ["## Veelgestelde vragen", ""]
        for index in range(1, faq_count + 1):
            faq_sections.extend(
                [
                    f"### Welke vraag {index} past bij glad stucwerk?",
                    paragraph * 2,
                ]
            )
        sections.extend(faq_sections)
    return "\n".join(sections)


def _raw_output(body: str, *, include_end_marker: bool = True) -> str:
    marker = f"\n\n{LANDING_PAGE_END_MARKER}" if include_end_marker else ""
    return f"""---
meta_title: Glad stucwerk laten uitvoeren
meta_description: Vraag eenvoudig een offerte aan voor strak glad stucwerk in huis.
slug: glad-stucwerk
---

{body}{marker}
"""


class LandingPageOutputValidationTests(unittest.TestCase):
    def test_generate_landing_page_uses_landing_page_defaults(self):
        response = Mock()
        response.output_text = _raw_output(_body())

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            return_value=response,
        ) as create_response:
            generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        kwargs = create_response.call_args.kwargs
        self.assertEqual(
            kwargs["max_output_tokens"],
            DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(
            kwargs["reasoning"],
            {"effort": DEFAULT_LANDING_PAGE_REASONING_EFFORT},
        )
        self.assertEqual(DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS, 20000)

    def test_generate_landing_page_continues_after_openai_incomplete_response(self):
        first_response = Mock()
        first_response.status = "incomplete"
        first_response.incomplete_details = {"reason": "max_output_tokens"}
        first_response.output_text = _raw_output(_body(), include_end_marker=False)
        continuation_response = Mock()
        continuation_response.status = "completed"
        continuation_response.output_text = LANDING_PAGE_END_MARKER

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, continuation_response],
        ) as create_response:
            raw = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertEqual(create_response.call_count, 2)
        self.assertIn("Ga exact verder waar de tekst stopte", create_response.call_args.kwargs["input"])
        parsed = validate_landing_page_output(raw, requested_length=500)
        self.assertIn("## Veelgestelde vragen", parsed[3])

    def test_generate_landing_page_continues_when_end_marker_is_missing(self):
        first_response = Mock()
        first_response.status = "completed"
        first_response.output_text = _raw_output(_body(), include_end_marker=False)
        continuation_response = Mock()
        continuation_response.status = "completed"
        continuation_response.output_text = LANDING_PAGE_END_MARKER

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, continuation_response],
        ) as create_response:
            raw = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertEqual(create_response.call_count, 2)
        validate_landing_page_output(raw, requested_length=500)

    def test_generate_landing_page_fails_after_continuations_stay_incomplete(self):
        responses = []
        for _ in range(3):
            response = Mock()
            response.status = "incomplete"
            response.incomplete_details = {"reason": "max_output_tokens"}
            response.output_text = _raw_output(_body(), include_end_marker=False)
            responses.append(response)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=responses,
        ):
            with self.assertRaisesRegex(
                LandingPageOutputValidationError,
                "openai_incomplete:max_output_tokens",
            ):
                generate_landing_page("Schrijf een landingspagina", user_id="user-1")

    def test_complete_output_passes(self):
        parsed = validate_landing_page_output(
            _raw_output(_body()),
            requested_length=500,
        )

        self.assertEqual(parsed[0], "Glad stucwerk laten uitvoeren")
        self.assertEqual(parsed[2], "glad-stucwerk")
        self.assertIn("## Veelgestelde vragen", parsed[3])
        self.assertNotIn(LANDING_PAGE_END_MARKER, parsed[3])

    def test_empty_output_fails(self):
        with self.assertRaisesRegex(LandingPageOutputValidationError, "empty_output"):
            validate_landing_page_output("")

    def test_intro_only_fails(self):
        raw = _raw_output("# Glad stucwerk\n\nKorte intro zonder verdere uitwerking.")

        with self.assertRaisesRegex(LandingPageOutputValidationError, "too_short"):
            validate_landing_page_output(raw)

    def test_missing_frontmatter_fails(self):
        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_or_incomplete_frontmatter",
        ):
            validate_landing_page_output(_body())

    def test_incomplete_frontmatter_fails(self):
        raw = """---
meta_title: Glad stucwerk laten uitvoeren
slug: glad-stucwerk
---

"""
        raw += _body()

        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_or_incomplete_frontmatter",
        ):
            validate_landing_page_output(raw)

    def test_missing_faq_fails(self):
        with self.assertRaisesRegex(LandingPageOutputValidationError, "missing_faq"):
            validate_landing_page_output(_raw_output(_body(include_faq=False)))

    def test_too_few_faq_questions_fails(self):
        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "too_few_faq_questions:2_min_6",
        ):
            validate_landing_page_output(_raw_output(_body(faq_count=2)))

    def test_missing_end_marker_fails(self):
        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_end_marker",
        ):
            validate_landing_page_output(
                _raw_output(_body(), include_end_marker=False)
            )

    def test_mid_faq_truncation_fails_without_end_marker(self):
        paragraph = (
            "Deze tekst is lang genoeg om de minimumcontrole te halen en bevat "
            "koppen, uitleg en een FAQ-sectie, maar de laatste vraag wordt bewust "
            "afgebroken zodat alleen de eindmarker dit betrouwbaar kan afvangen. "
        )
        body = "\n".join(
            [
                "# Betonlook stucwerk",
                "",
                paragraph * 4,
                "## Voordelen van betonlook stucwerk",
                "",
                paragraph * 4,
                "## Veelgestelde vragen",
                "",
                "### Is betonlook stucwerk geschikt voor de badkamer?",
                paragraph * 3,
                "### Zoek je betonlook stucwerk voor natte ruimtes?",
                paragraph * 3,
                "### Hoe onderhoud je betonlook stucwerk?",
                paragraph * 3,
                "### Wat kost betonlook stucwerk gemiddeld?",
                paragraph * 3,
                "### Wanneer kies je betonlook stucwerk?",
                paragraph * 3,
                "### Kan betonlook stucwerk over tegels?",
                "Dan",
            ]
        )

        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_end_marker",
        ):
            validate_landing_page_output(
                _raw_output(body, include_end_marker=False)
            )

    def test_three_complete_parts_without_end_marker_still_fail_validation(self):
        responses = []
        for _ in range(3):
            response = Mock()
            response.status = "completed"
            response.output_text = _raw_output(_body(), include_end_marker=False)
            responses.append(response)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=responses,
        ):
            raw = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_end_marker",
        ):
            validate_landing_page_output(raw, requested_length=500)

    def test_generation_settings_rejects_too_few_max_output_tokens(self):
        with self.assertRaises(ValidationError):
            LandingPageGenerationSettingsUpdateRequest(max_output_tokens=999)

    def test_generation_settings_rejects_too_many_max_output_tokens(self):
        with self.assertRaises(ValidationError):
            LandingPageGenerationSettingsUpdateRequest(max_output_tokens=50001)

    def test_generation_settings_accepts_null_and_valid_max_output_tokens(self):
        self.assertIsNone(
            LandingPageGenerationSettingsUpdateRequest().max_output_tokens
        )
        self.assertEqual(
            LandingPageGenerationSettingsUpdateRequest(
                max_output_tokens=50000
            ).max_output_tokens,
            50000,
        )


if __name__ == "__main__":
    unittest.main()
