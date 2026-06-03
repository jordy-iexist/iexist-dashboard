import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.features.landing_pages.schemas import LandingPageGenerationSettingsUpdateRequest
from app.features.landing_pages.services.generation.csv import (
    DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE,
    build_landing_page_prompt,
    extract_template_placeholders,
    get_missing_prompt_values,
    map_row_to_landing_page_fields,
    normalize_landing_page_prompt_template,
    validate_landing_page_mapping,
)
from app.features.landing_pages.services.generation.openai import (
    DEFAULT_LANDING_PAGE_MAX_OUTPUT_TOKENS,
    DEFAULT_LANDING_PAGE_REASONING_EFFORT,
    LANDING_PAGE_END_MARKER,
    LandingPageGenerationResult,
    LandingPageOutputValidationError,
    _sanitize_continuation_chunk,
    _stitch_output_parts,
    _trim_to_clean_boundary,
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


def _make_response(output_text: str, *, status: str = "completed", incomplete_reason: str = "") -> Mock:
    """Build a minimal response mock that won't crash _extract_reasoning_tokens."""
    response = Mock()
    response.output_text = output_text
    response.status = status
    response.incomplete_details = {"reason": incomplete_reason} if incomplete_reason else {}
    response.usage = None
    return response


class LandingPagePromptTemplateTests(unittest.TestCase):
    def test_empty_landing_page_template_uses_default_prompt(self):
        self.assertEqual(
            normalize_landing_page_prompt_template(""),
            DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE,
        )

    def test_landing_page_template_placeholders_are_extracted(self):
        self.assertEqual(
            extract_template_placeholders(
                "Schrijf voor {website} over {onderwerp}. Gebruik {website}."
            ),
            ["website", "onderwerp"],
        )

    def test_landing_page_template_rejects_invalid_braces(self):
        with self.assertRaisesRegex(ValueError, "ongeldige accolades"):
            extract_template_placeholders("Schrijf over {onderwerp")

    def test_landing_page_template_rejects_empty_placeholder(self):
        with self.assertRaisesRegex(ValueError, "Lege placeholder"):
            extract_template_placeholders("Schrijf over {}")

    def test_landing_page_mapping_validates_against_dynamic_headers(self):
        mapping = validate_landing_page_mapping(
            {"website": "Site", "onderwerp": "Topic"},
            ["Site", "Topic"],
            ["website", "onderwerp"],
        )

        self.assertEqual(mapping, {"website": "Site", "onderwerp": "Topic"})

        row = map_row_to_landing_page_fields(
            {"Site": "example.nl", "Topic": "Stucwerk"},
            mapping,
            ["website", "onderwerp"],
        )
        self.assertEqual(row, {"website": "example.nl", "onderwerp": "Stucwerk"})
        self.assertEqual(get_missing_prompt_values(row, ["website", "onderwerp"]), [])

    def test_landing_page_prompt_is_built_from_custom_template(self):
        prompt = build_landing_page_prompt(
            {"website": "example.nl", "onderwerp": "Stucwerk"},
            "Schrijf voor {website} over {onderwerp}.",
        )

        self.assertEqual(prompt, "Schrijf voor example.nl over Stucwerk.")


class LandingPageOutputValidationTests(unittest.TestCase):
    def test_generate_landing_page_uses_landing_page_defaults(self):
        response = _make_response(_raw_output(_body()))

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
        first_response = _make_response(
            _raw_output(_body(), include_end_marker=False),
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
        continuation_response = _make_response(LANDING_PAGE_END_MARKER)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, continuation_response],
        ) as create_response:
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertIsInstance(result, LandingPageGenerationResult)
        self.assertEqual(create_response.call_count, 2)
        continuation_input = create_response.call_args.kwargs["input"]
        self.assertIn("GEEN nieuwe frontmatter", continuation_input)
        self.assertIn("Sla geen secties over", continuation_input)
        parsed = validate_landing_page_output(result.text, requested_length=500)
        self.assertIn("## Veelgestelde vragen", parsed[3])

    def test_generate_landing_page_continues_when_end_marker_is_missing(self):
        first_response = _make_response(_raw_output(_body(), include_end_marker=False))
        continuation_response = _make_response(LANDING_PAGE_END_MARKER)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, continuation_response],
        ) as create_response:
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertEqual(create_response.call_count, 2)
        validate_landing_page_output(result.text, requested_length=500)

    def test_generate_landing_page_fails_after_continuations_stay_incomplete(self):
        responses = []
        for _ in range(3):
            responses.append(
                _make_response(
                    _raw_output(_body(), include_end_marker=False),
                    status="incomplete",
                    incomplete_reason="max_output_tokens",
                )
            )

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
            responses.append(_make_response(_raw_output(_body(), include_end_marker=False)))

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=responses,
        ):
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        with self.assertRaisesRegex(
            LandingPageOutputValidationError,
            "missing_end_marker",
        ):
            validate_landing_page_output(result.text, requested_length=500)

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

    # --- New tests for robust continuation ---

    def test_continuation_strips_duplicate_frontmatter(self):
        """Continuation chunk that re-emits frontmatter must not pollute the body."""
        first_response = _make_response(_raw_output(_body(), include_end_marker=False))
        # Second attempt re-emits a full document with frontmatter (model confusion).
        second_response = _make_response(_raw_output(_body(), include_end_marker=True))

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, second_response],
        ):
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        # Only one frontmatter block should be present at the very beginning.
        count_meta_title = result.text.count("meta_title:")
        self.assertEqual(count_meta_title, 1, "Duplicate frontmatter key found in stitched output")

        # The frontmatter block must be at the start, not buried in the body.
        self.assertTrue(result.text.strip().startswith("---"), "Output must start with YAML frontmatter")

    def test_continuation_trims_mid_sentence_tail_before_stitching(self):
        """A hanging half-sentence at the end of attempt 1 must not appear in the final output."""
        paragraph = (
            "Deze landingspagina legt helder uit wat de bezoeker moet weten voordat "
            "hij een offerte aanvraagt. De tekst gebruikt concrete voorbeelden, "
            "benoemt voordelen en sluit logisch aan op de zoekintentie van de lezer. "
        )
        # Build a body that ends abruptly mid-word after a colon on a new line.
        body_truncated = "\n".join([
            "# Glad stucwerk laten uitvoeren",
            "",
            paragraph * 4,
            "## Waarom professioneel stucwerk belangrijk is",
            "",
            paragraph * 4,
            "## Kosten en planning",
            "",
            "De kosten hangen af van verschillende factoren zoals oppervlakte, afwerking en",
        ])
        first_part = _raw_output(body_truncated, include_end_marker=False)
        # Second attempt continues cleanly and finishes the page.
        faq_continuation = "\n".join([
            "de locatie.\n",
            "## Veelgestelde vragen",
            "",
        ] + [
            f"### Welke vraag {i} past bij glad stucwerk?\n{paragraph * 2}"
            for i in range(1, 7)
        ] + [f"\n{LANDING_PAGE_END_MARKER}"])

        first_response = _make_response(first_part)
        second_response = _make_response(faq_continuation)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, second_response],
        ):
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        # The dangling fragment "en" should not be left as the last word of a dead-end line.
        # Specifically, there should not be a naked "en\n\n" in the middle of the text followed
        # immediately by the FAQ heading.
        body_start = result.text.find("---\n\n", result.text.find("---") + 3)
        body_section = result.text[body_start:] if body_start != -1 else result.text
        self.assertNotIn(
            "en\n\n## Veelgestelde",
            body_section,
            "Mid-sentence tail must be trimmed before the FAQ continuation is appended",
        )

    def test_continuation_overlap_is_dedupliceerd(self):
        """If attempt 2 starts by repeating the tail of attempt 1, the overlap must be removed."""
        paragraph = (
            "Deze landingspagina legt helder uit wat de bezoeker moet weten voordat "
            "hij een offerte aanvraagt. De tekst gebruikt concrete voorbeelden, "
            "benoemt voordelen en sluit logisch aan op de zoekintentie van de lezer. "
        )
        body_part1 = "\n".join([
            "# Glad stucwerk laten uitvoeren",
            "",
            paragraph * 4,
            "## Waarom professioneel stucwerk belangrijk is",
            "",
            paragraph * 2,
        ])
        repeated_tail = paragraph  # last paragraph of part 1
        faq_body = "\n".join([
            "## Veelgestelde vragen",
            "",
        ] + [
            f"### Welke vraag {i} past bij glad stucwerk?\n{paragraph * 2}"
            for i in range(1, 7)
        ])
        body_part2 = repeated_tail + "\n\n" + faq_body

        first_response = _make_response(_raw_output(body_part1, include_end_marker=False))
        second_response = _make_response(body_part2 + f"\n\n{LANDING_PAGE_END_MARKER}")

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, second_response],
        ):
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        # Count occurrences of the repeated_tail phrase — should appear only once.
        occurrences = result.text.count(repeated_tail.strip())
        self.assertEqual(
            occurrences, 1,
            f"Repeated tail appears {occurrences} times; overlap deduplication failed",
        )

    def test_continuation_prompt_instructs_no_new_frontmatter(self):
        """The continuation prompt must forbid re-emitting YAML frontmatter."""
        first_response = _make_response(_raw_output(_body(), include_end_marker=False))
        second_response = _make_response(LANDING_PAGE_END_MARKER)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, second_response],
        ) as create_response:
            generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        continuation_input = create_response.call_args_list[1].kwargs["input"]
        self.assertIn(
            "GEEN nieuwe frontmatter",
            continuation_input,
            "Continuation prompt must explicitly forbid new frontmatter",
        )
        self.assertIn(
            "Sla geen secties over",
            continuation_input,
            "Continuation prompt must instruct the model not to skip sections",
        )
        self.assertNotIn(
            "voeg ontbrekende FAQ-vragen toe",
            continuation_input,
            "FAQ-bias phrase must be removed from continuation prompt",
        )

    def test_result_tracks_attempts_and_continuation_flag(self):
        """LandingPageGenerationResult must correctly report attempt count and was_continued."""
        single_response = _make_response(_raw_output(_body()))

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            return_value=single_response,
        ):
            result = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertEqual(result.attempts, 1)
        self.assertFalse(result.was_continued)

        # Two attempts needed
        first_response = _make_response(_raw_output(_body(), include_end_marker=False))
        second_response = _make_response(LANDING_PAGE_END_MARKER)

        with patch(
            "app.features.landing_pages.services.generation.openai.create_response",
            side_effect=[first_response, second_response],
        ):
            result2 = generate_landing_page("Schrijf een landingspagina", user_id="user-1")

        self.assertEqual(result2.attempts, 2)
        self.assertTrue(result2.was_continued)


class TrimToCleanBoundaryTests(unittest.TestCase):
    def test_trims_at_sentence_end(self):
        text = "Eerste zin.\nTweede zin. Dit is een halve"
        kept, tail = _trim_to_clean_boundary(text)
        self.assertIn("Tweede zin.", kept)
        self.assertEqual(tail, "Dit is een halve")

    def test_full_sentence_returns_empty_tail(self):
        text = "Eerste zin.\nTweede zin compleet."
        kept, tail = _trim_to_clean_boundary(text)
        self.assertFalse(tail, "No tail expected when text ends on clean boundary")

    def test_falls_back_to_blank_line(self):
        text = "Paragraph one.\n\nIncomplete sentence without"
        kept, tail = _trim_to_clean_boundary(text)
        self.assertIn("Paragraph one", kept)

    def test_returns_full_text_when_no_boundary(self):
        text = "kein-boundary-anywhere"
        kept, tail = _trim_to_clean_boundary(text)
        self.assertEqual(kept, text)
        self.assertEqual(tail, "")


class SanitizeContinuationChunkTests(unittest.TestCase):
    def test_strips_leading_frontmatter(self):
        chunk = "---\nmeta_title: Test\nmeta_description: Desc\nslug: test\n---\n\n# Body here\n"
        result = _sanitize_continuation_chunk(chunk, "")
        self.assertNotIn("meta_title", result)
        self.assertIn("Body here", result)

    def test_strips_duplicate_h1_matching_first_part(self):
        first_h1 = "# Glad stucwerk laten uitvoeren\n"
        chunk = "# Glad stucwerk laten uitvoeren\n\nVerder met de tekst."
        result = _sanitize_continuation_chunk(chunk, first_h1)
        self.assertNotIn("# Glad stucwerk laten uitvoeren", result)
        self.assertIn("Verder met de tekst", result)

    def test_preserves_different_h2(self):
        first_h1 = "# Glad stucwerk laten uitvoeren\n"
        chunk = "## Veelgestelde vragen\n\nAntwoord hier."
        result = _sanitize_continuation_chunk(chunk, first_h1)
        self.assertIn("## Veelgestelde vragen", result)


class StitchOutputPartsTests(unittest.TestCase):
    def test_single_part_returned_as_is(self):
        parts = ["Alleen dit."]
        self.assertEqual(_stitch_output_parts(parts), "Alleen dit.")

    def test_overlap_is_removed(self):
        shared = "gedeelde tekst die overlapt"
        part1 = f"Begin van pagina. {shared}"
        part2 = f"{shared} en daarna verder."
        result = _stitch_output_parts([part1, part2])
        self.assertEqual(result.count(shared), 1, "Overlap must appear exactly once")

    def test_empty_parts_ignored(self):
        result = _stitch_output_parts(["deel een.", "", "  ", "deel twee."])
        self.assertIn("deel een", result)
        self.assertIn("deel twee", result)

    def test_empty_list_returns_empty(self):
        self.assertEqual(_stitch_output_parts([]), "")


if __name__ == "__main__":
    unittest.main()
