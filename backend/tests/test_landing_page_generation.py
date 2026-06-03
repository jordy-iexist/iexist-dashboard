import unittest
from unittest.mock import Mock, patch

from app.features.landing_pages.services.generation.openai import (
    DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
    DEFAULT_LANDING_PAGE_REASONING_EFFORT,
    LandingPageOutputValidationError,
    generate_landing_page,
    validate_landing_page_output,
)


def _body(*, include_faq: bool = True) -> str:
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
        sections.extend(
            [
                "## Veelgestelde vragen",
                "",
                "### Hoe snel kan stucwerk worden uitgevoerd?",
                paragraph * 2,
                "### Wat bepaalt de prijs van stucwerk?",
                paragraph * 2,
            ]
        )
    return "\n".join(sections)


def _raw_output(body: str) -> str:
    return f"""---
meta_title: Glad stucwerk laten uitvoeren
meta_description: Vraag eenvoudig een offerte aan voor strak glad stucwerk in huis.
slug: glad-stucwerk
---

{body}
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

    def test_complete_output_passes(self):
        parsed = validate_landing_page_output(
            _raw_output(_body()),
            requested_length=500,
        )

        self.assertEqual(parsed[0], "Glad stucwerk laten uitvoeren")
        self.assertEqual(parsed[2], "glad-stucwerk")
        self.assertIn("## Veelgestelde vragen", parsed[3])

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


if __name__ == "__main__":
    unittest.main()
