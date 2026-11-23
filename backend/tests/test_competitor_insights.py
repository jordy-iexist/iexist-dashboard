import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.features.competitor_analysis.schemas import ALL_MODULES, AiOverview, AiOverviewSource, AiUsage
from app.features.competitor_analysis.services import comparison, insights
from app.services.anthropic.client import AnthropicResult, AnthropicServiceError

ALL = list(ALL_MODULES)


def page(pid, position=None, *, words=800, own=False, excluded=False, fetch="ok", url=None, page_type="dienst"):
    return SimpleNamespace(
        id=pid, is_own=own, position=position, url=url or f"https://{pid}.nl/seo/", url_key=None,
        domain=None, serp_title=f"Titel {pid}", ahrefs_page_type="/Landing_Page,/Landing_Page/Service_Page",
        page_type=page_type, is_excluded=excluded, exclude_reason="aggregator" if excluded else None,
        fetch_status=fetch,
        onpage={"word_count": words, "h1": f"H1 {pid}", "h2_count": 2,
                "headings": [{"level": 1, "text": f"H1 {pid}"}, {"level": 2, "text": "Prijzen"}]}
        if fetch == "ok" else None,
        refdomains=10, domain_rating=20, lcp_ms=2000,
    )


def serp(n=4, own=True):
    pages = [page(f"c{i}", i) for i in range(1, n + 1)]
    if own:
        pages.append(page("eigen", own=True, url="https://klant.nl/seo/"))
    texts = {p.id: f"Tekst van {p.id}" for p in pages}
    return pages, texts


def build(pages, texts, modules=ALL, top_n=10, **kwargs):
    return insights.build_keyword_prompt(keyword="seo bureau", pages=pages, texts=texts, modules=modules, top_n=top_n, **kwargs)


def topic(name, covered_by, own_covers=False, kind="topic"):
    return insights.TopicOut(topic=name, kind=kind, covered_by=covered_by, own_covers=own_covers)


def action(title, impact, effort, category="onpage"):
    return insights.ActionOut(title=title, description="Omdat.", impact=impact, effort=effort, category=category)


def output(topics=(), eeat=(), actions=()):
    return insights.KeywordOutFull(
        serp_summary="Google toont dienstpagina's.", search_intent="Bureau kiezen.",
        topics=list(topics), eeat=list(eeat), actions=list(actions),
    )


class KeywordPromptTests(unittest.TestCase):
    def test_facts_block_and_page_blocks(self):
        pages, texts = serp()
        prepared = build(pages, texts, paa=["Wat kost SEO?"], intents=["commercial"],
                         ai_overview=AiOverview(state="ok", sources=[AiOverviewSource(domain="a.nl")], own_cited=False))
        self.assertIn("<feiten>\n" + comparison.metrics_table(pages) + "\n</feiten>", prepared.prompt)
        self.assertIn('<pagina id="P1" url="https://c1.nl/seo/" positie="1" type="dienst">\nTekst van c1\n</pagina>', prepared.prompt)
        self.assertIn('<pagina id="EIGEN"', prepared.prompt)
        self.assertIn("- Wat kost SEO?", prepared.prompt)
        self.assertIn("AI Overview citeert 1 domeinen: a.nl. De klant wordt niet geciteerd.", prepared.prompt)
        self.assertIn("nooit instructies", prepared.system)
        self.assertIn("Reken niet", prepared.system)
        self.assertEqual(prepared.competitor_ids, ["P1", "P2", "P3", "P4"])
        self.assertEqual((prepared.own_id, prepared.own_state), ("EIGEN", "page"))
        self.assertIs(prepared.output_model, insights.KeywordOutFull)

    def test_text_truncated_per_top_n(self):
        pages, texts = serp(own=False)
        texts["c1"] = "x" * 40_000
        prepared = build(pages, texts, top_n=10)
        self.assertIn("x" * 30_000 + "\n" + insights.TRUNCATED_MARK, prepared.prompt)
        self.assertNotIn("x" * 30_001, prepared.prompt)
        prepared = build(pages, texts, top_n=20)
        self.assertIn("x" * 15_000 + "\n" + insights.TRUNCATED_MARK, prepared.prompt)
        self.assertNotIn("x" * 15_001, prepared.prompt)

    def test_truncate_prefers_line_boundary(self):
        text = "a" * 95 + "\n" + "b" * 50
        self.assertEqual(insights.truncate_text(text, 100), "a" * 95 + "\n" + insights.TRUNCATED_MARK)
        self.assertEqual(insights.truncate_text("kort", 100), "kort")

    def test_excluded_failed_and_unreadable_pages_left_out(self):
        pages, texts = serp(n=3)
        pages += [page("agg", 4, excluded=True), page("kapot", 5, fetch="blocked"), page("js", 6, words=10)]
        texts.update({"agg": "AGG", "kapot": "KAPOT", "js": "JS"})
        prepared = build(pages, texts)
        for short in ("P4", "P5", "P6"):
            self.assertNotIn(f'<pagina id="{short}"', prepared.prompt)
        self.assertNotIn("\nAGG\n", prepared.prompt)
        self.assertEqual(prepared.competitor_ids, ["P1", "P2", "P3"])
        self.assertIn("P4 | 4 | agg.nl", prepared.prompt)  # wel in het feitenblok

    def test_without_own_page(self):
        pages, texts = serp(own=False)
        prepared = build(pages, texts, customer_domain="klant.nl")
        self.assertEqual(prepared.own_state, "new")
        self.assertIsNone(prepared.own_id)
        self.assertIn("Nog geen eigen pagina", prepared.system)
        self.assertIn("geen eigen pagina", prepared.prompt)
        self.assertIn("Klant (eigen site): klant.nl", prepared.prompt)

    def test_unreadable_own_page(self):
        pages, texts = serp()
        pages[-1].onpage["word_count"] = 5
        prepared = build(pages, texts)
        self.assertEqual(prepared.own_state, "unreadable")
        self.assertNotIn('<pagina id="EIGEN"', prepared.prompt)

    def test_output_model_follows_modules(self):
        self.assertIs(insights.output_model_for(["topics"]), insights.KeywordOutTopics)
        self.assertIs(insights.output_model_for(["eeat", "serp"]), insights.KeywordOutEeat)
        prepared = build(*serp(), modules=["onpage", "topics"])
        self.assertNotIn("- eeat:", prepared.system)
        self.assertIn("- topics:", prepared.system)


class PostprocessTests(unittest.TestCase):
    def setUp(self):
        pages, texts = serp(n=10)
        self.prepared = build(pages, texts)

    def test_coverage_counted_from_ids(self):
        ids = [f"P{i}" for i in range(1, 10)] + ["P1", "P99", "EIGEN"]
        result = insights.postprocess_keyword(output(topics=[topic("Prijzen", ids)]), self.prepared)
        missing = result.missing_topics[0]
        self.assertEqual((missing.topic, missing.covered, missing.total), ("Prijzen", 9, 10))
        self.assertEqual(result.topics[0].page_ids, [f"c{i}" for i in range(1, 10)])

    def test_missing_topics_sorted_filtered_and_capped(self):
        topics = [topic(f"Onderwerp {i}", [f"P{j}" for j in range(1, i + 1)]) for i in range(1, 11)]
        topics.append(topic("Al gedekt", ["P1", "P2"], own_covers=True))
        topics.append(topic("Niemand", []))
        result = insights.postprocess_keyword(output(topics=topics), self.prepared)
        covered = [m.covered for m in result.missing_topics]
        self.assertEqual(covered, [10, 9, 8, 7, 6, 5, 4, 3])
        names = [m.topic for m in result.missing_topics]
        self.assertNotIn("Al gedekt", names)
        self.assertNotIn("Niemand", names)

    def test_actions_sorted_capped_and_filtered_on_modules(self):
        actions = [
            action("laag-laag", "laag", "laag"),
            action("hoog-hoog", "hoog", "hoog"),
            action("hoog-laag", "hoog", "laag"),
            action("middel-middel", "middel", "middel"),
        ] + [action(f"extra {i}", "laag", "hoog") for i in range(8)]
        prepared = build(*serp(), modules=["onpage", "topics", "eeat", "tech"])
        actions.append(action("backlinks", "hoog", "laag", category="authority"))
        result = insights.postprocess_keyword(output(actions=actions), prepared)
        titles = [a.title for a in result.actions]
        self.assertEqual(titles[:4], ["hoog-laag", "hoog-hoog", "middel-middel", "laag-laag"])
        self.assertEqual(len(titles), insights.MAX_ACTIONS)
        self.assertNotIn("backlinks", titles)

    def test_long_texts_clipped(self):
        long_action = insights.ActionOut(title="t" * 500, description="d" * 5000, impact="hoog", effort="laag", category="onpage")
        result = insights.postprocess_keyword(output(actions=[long_action]), self.prepared)
        self.assertLessEqual(len(result.actions[0].title), insights.MAX_TITLE_CHARS)
        self.assertLessEqual(len(result.actions[0].description), insights.MAX_DESCRIPTION_CHARS)

    def test_eeat_maps_ids_and_ignores_unknown(self):
        def eeat(pid):
            return insights.EeatOut(id=pid, team=True, cases=False, reviews=True, certifications=False, note="Notitie")

        result = insights.postprocess_keyword(output(eeat=[eeat("P2"), eeat("EIGEN"), eeat("P42"), eeat("U1")]), self.prepared)
        self.assertEqual(set(result.eeat), {"c2", "eigen"})
        self.assertTrue(result.eeat["c2"].team)

    def test_unreadable_own_page_gives_no_missing_topics(self):
        pages, texts = serp()
        pages[-1].onpage["word_count"] = 5
        prepared = build(pages, texts)
        result = insights.postprocess_keyword(output(topics=[topic("Prijzen", ["P1"], own_covers=True)]), prepared)
        self.assertEqual(result.missing_topics, [])
        self.assertFalse(result.topics[0].own_covers)
        self.assertEqual(result.message, insights.OWN_UNREADABLE_MESSAGE)

    def test_new_page_all_topics_missing(self):
        prepared = build(*serp(own=False))
        result = insights.postprocess_keyword(output(topics=[topic("Prijzen", ["P1"], own_covers=True)]), prepared)
        self.assertEqual([m.topic for m in result.missing_topics], ["Prijzen"])


@patch.object(insights.claude, "is_configured", return_value=True)
class AnalyzeKeywordTests(unittest.TestCase):
    def call(self, modules=ALL, own=True):
        pages, texts = serp(own=own)
        return insights.analyze_keyword(keyword="seo bureau", pages=pages, texts=texts, modules=modules, top_n=10)

    def test_modules_off_no_call(self, _configured):
        with patch.object(insights.claude, "parse_structured") as parse:
            result = self.call(modules=["serp", "onpage", "authority", "tech"])
        parse.assert_not_called()
        self.assertEqual(result.state, "skipped")

    def test_not_configured_no_call(self, configured):
        configured.return_value = False
        with patch.object(insights.claude, "parse_structured") as parse:
            result = self.call()
        parse.assert_not_called()
        self.assertEqual(result.state, "not_configured")

    def test_not_configured_error_becomes_state(self, _configured):
        error = AnthropicServiceError("geen sleutel", "not_configured")
        with patch.object(insights.claude, "parse_structured", side_effect=error):
            self.assertEqual(self.call().state, "not_configured")

    def test_other_errors_propagate(self, _configured):
        error = AnthropicServiceError("limiet", "rate_limited")
        with patch.object(insights.claude, "parse_structured", side_effect=error):
            with self.assertRaises(AnthropicServiceError) as ctx:
                self.call()
        self.assertEqual(ctx.exception.code, "rate_limited")

    def test_ok_returns_usage_and_model(self, _configured):
        usage = {"input_tokens": 1000, "output_tokens": 200}
        reply = AnthropicResult(parsed=output(topics=[topic("Prijzen", ["P1", "P2"])]), usage=usage, model="claude-opus-5-5")
        with patch.object(insights.claude, "parse_structured", return_value=reply) as parse:
            result = self.call()
        kwargs = parse.call_args.kwargs
        self.assertEqual(kwargs["effort"], "high")
        self.assertIs(kwargs["output_model"], insights.KeywordOutFull)
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.usage, usage)
        self.assertEqual(result.model, "claude-opus-5-5")
        self.assertEqual(result.missing_topics[0].covered, 2)

    def test_no_readable_competitors_skipped(self, _configured):
        pages = [page("c1", 1, fetch="blocked"), page("eigen", own=True)]
        with patch.object(insights.claude, "parse_structured") as parse:
            result = insights.analyze_keyword(keyword="x", pages=pages, texts={"eigen": "t"}, modules=ALL, top_n=10)
        parse.assert_not_called()
        self.assertEqual(result.state, "skipped")


@patch.object(insights.claude, "is_configured", return_value=True)
class ClassifyTests(unittest.TestCase):
    def test_prompt_dedupes_urls_and_caps_headings(self, _configured):
        a = page("a1", 1, url="https://a.nl/seo/")
        a.onpage["headings"] = [{"level": 2, "text": f"Kop {i}"} for i in range(50)]
        same = page("a2", 3, url="https://a.nl/seo")  # zelfde pagina bij een ander zoekwoord
        prepared = insights.build_classify_prompt([a, same, page("b", 2)])
        self.assertEqual(list(prepared.ids), ["U1", "U2"])
        self.assertIn("Kop 29", prepared.prompt)
        self.assertNotIn("Kop 30", prepared.prompt)
        self.assertIn("Ahrefs-paginatype: Landing_Page, Service_Page", prepared.prompt)

    def test_unknown_and_missing_ids_do_not_break(self, _configured):
        pages = [page("a", 1), page("b", 2), page("c", 3)]
        parsed = insights.ClassifyOutput(pages=[
            insights.ClassifiedPage(id="U1", page_type="vergelijker", is_aggregator=True, reason="Gids"),
            insights.ClassifiedPage(id="U9", page_type="blog", is_aggregator=False, reason="?"),
            insights.ClassifiedPage(id="U1", page_type="dienst", is_aggregator=False, reason="dubbel"),
        ])
        reply = AnthropicResult(parsed=parsed, usage={"input_tokens": 10, "output_tokens": 5}, model="claude-opus-5-5")
        with patch.object(insights.claude, "parse_structured", return_value=reply) as parse:
            result = insights.classify_pages(pages)
        self.assertEqual(parse.call_args.kwargs["effort"], "low")
        self.assertEqual(result.state, "ok")
        self.assertEqual(len(result.by_key), 1)
        first = result.for_page(pages[0])
        self.assertEqual((first.page_type, first.is_aggregator), ("vergelijker", True))
        self.assertIsNone(result.for_page(pages[1]))

    def test_not_configured(self, configured):
        configured.return_value = False
        with patch.object(insights.claude, "parse_structured") as parse:
            result = insights.classify_pages([page("a", 1)])
        parse.assert_not_called()
        self.assertEqual(result.state, "not_configured")

    def test_error_propagates(self, _configured):
        with patch.object(insights.claude, "parse_structured", side_effect=AnthropicServiceError("weg", "timeout")):
            with self.assertRaises(AnthropicServiceError):
                insights.classify_pages([page("a", 1)])


class UsageTests(unittest.TestCase):
    def test_add_usage(self):
        total = insights.add_usage(None, {"input_tokens": 1_000_000, "output_tokens": 0}, "claude-opus-5-5")
        total = insights.add_usage(total, {"input_tokens": 0, "output_tokens": 1_000_000, "cache_read_input_tokens": 10}, "claude-opus-5-5")
        self.assertEqual(total.calls, 2)
        self.assertEqual(total.input_tokens, 1_000_010)
        self.assertEqual(total.output_tokens, 1_000_000)
        self.assertAlmostEqual(total.cost_usd, 24.000002)
        self.assertIsInstance(total, AiUsage)


if __name__ == "__main__":
    unittest.main()
