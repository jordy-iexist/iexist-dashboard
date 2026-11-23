"""Concurrentieanalyse: eigen Google-poging (parser, fetch_google) en browser-herkansing page_html."""
import asyncio
import unittest
from pathlib import Path

from app.features.competitor_analysis.services.google_serp import (
    MSG_BLOCKED,
    MSG_BROWSER,
    MSG_CONSENT,
    BrowserSession,
    GoogleSerp,
    fetch_google,
    parse_serp_html,
    search_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "competitor"
SORRY_URL = "https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Dseo&hl=nl&q=TOKEN"
SERP_URL = "https://www.google.com/search?q=seo+bureau&hl=nl&gl=nl"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParseSerpHtmlTests(unittest.TestCase):
    def test_results_page_with_questions_and_ai_overview(self):
        serp = parse_serp_html(fixture("serp_with_questions.synthetic.html"), SERP_URL)
        self.assertEqual(serp.state, "ok")
        self.assertEqual(serp.message, "")
        # Ontdubbeld (hoofdletters/vraagteken), volgorde behouden.
        self.assertEqual(
            serp.questions,
            [
                "Wat kost een SEO bureau per maand?",
                "Wat doet een SEO-bureau precies?",
                "Is SEO uitbesteden het waard?",
                "Hoe kies ik een goed SEO bureau?",
            ],
        )
        self.assertTrue(serp.ai_overview)
        # Tekstfragment weg, dubbele en Google-eigen/relatieve links weg, organische resultaten niet mee.
        self.assertEqual(
            serp.ai_sources,
            [
                {"domain": "voorbeeld-bureau.nl", "url": "https://www.voorbeeld-bureau.nl/seo/"},
                {"domain": "frankwatching.com", "url": "https://www.frankwatching.com/archive/seo-uitbesteden/"},
            ],
        )

    def test_real_captcha_page_is_blocked(self):
        html = fixture("sorry_captcha.real.html")
        serp = parse_serp_html(html, SORRY_URL)
        self.assertEqual(serp.state, "blocked")
        self.assertEqual(serp.message, MSG_BLOCKED)
        self.assertEqual(serp.questions, [])
        # Ook zonder URL herkend aan de inhoud (captcha-form, "ongebruikelijk verkeer").
        self.assertEqual(parse_serp_html(html).state, "blocked")

    def test_unusual_traffic_text_is_blocked(self):
        html = "<html><body><p>Our systems have detected unusual traffic from your computer network.</p></body></html>"
        self.assertEqual(parse_serp_html(html, "https://www.google.com/search?q=x").state, "blocked")

    def test_consent_page_is_blocked(self):
        html = fixture("consent.synthetic.html")
        serp = parse_serp_html(html, "https://consent.google.com/ml?continue=https://www.google.com/search?q=seo")
        self.assertEqual(serp.state, "blocked")
        self.assertEqual(serp.message, MSG_CONSENT)
        # Ook als eindtoestand op een ander adres, herkend aan het formulier.
        self.assertEqual(parse_serp_html(html, SERP_URL).state, "blocked")

    def test_results_page_without_questions_is_empty(self):
        serp = parse_serp_html(fixture("serp_no_questions.synthetic.html"), SERP_URL)
        self.assertEqual(serp.state, "empty")
        self.assertEqual(serp.questions, [])
        self.assertFalse(serp.ai_overview)
        self.assertEqual(serp.ai_sources, [])
        self.assertEqual(serp.message, "")

    def test_questions_fallback_under_heading_without_data_q(self):
        html = """<html><body><div id="rso">
        <div role="heading">Mensen vragen ook</div>
        <div role="button"><span>Hoe lang duurt SEO?</span></div>
        <div role="button"><span>Wat is linkbuilding?</span></div>
        <div>Geen vraag hier</div>
        <div role="heading">Gerelateerde zoekopdrachten</div>
        <a href="/search?q=x">Wat is x?</a>
        </div></body></html>"""
        serp = parse_serp_html(html, SERP_URL)
        self.assertEqual(serp.state, "ok")
        self.assertEqual(serp.questions, ["Hoe lang duurt SEO?", "Wat is linkbuilding?"])
        self.assertFalse(serp.ai_overview)

    def test_max_eight_questions(self):
        pairs = "".join(f'<div data-q="Vraag nummer {i}?"></div>' for i in range(12))
        serp = parse_serp_html(f'<html><body><div id="search">{pairs}</div></body></html>', SERP_URL)
        self.assertEqual(len(serp.questions), 8)

    def test_unrecognised_page_is_error_and_garbage_never_raises(self):
        self.assertEqual(parse_serp_html("<html><body>Hallo</body></html>", SERP_URL).state, "error")
        for junk in ("", None, "<<<>>><div", "\x00\x01<a href='http://[::1'>"):
            serp = parse_serp_html(junk, SERP_URL)  # type: ignore[arg-type]
            self.assertIsInstance(serp, GoogleSerp)
            self.assertIn(serp.state, {"error", "empty", "blocked"})

    def test_search_url(self):
        self.assertEqual(search_url("seo bureau"), "https://www.google.com/search?q=seo+bureau&hl=nl&gl=nl")
        self.assertIn("hl=en&gl=us", search_url("seo agency", "US"))


class FakeSession:
    """Nep-BrowserSession: geeft per zoekwoord een vooraf gekozen resultaat (of gooit)."""

    def __init__(self, outcomes, *, enter_error=None, start_error=None, exit_error=None):
        self.outcomes = outcomes
        self.calls: list[str] = []
        self.enter_error = enter_error
        self.start_error = start_error
        self.exit_error = exit_error
        self.closed = False

    def __enter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    def __exit__(self, *exc):
        self.closed = True
        if self.exit_error:
            raise self.exit_error

    def google(self, keyword, *, country="nl", timeout=25):
        self.calls.append(keyword)
        outcome = self.outcomes.get(keyword, GoogleSerp(state="empty"))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FetchGoogleTests(unittest.TestCase):
    def run_fetch(self, session, keywords, **kwargs):
        sleeps: list[float] = []
        result = fetch_google(keywords, session_factory=lambda: session, sleep=sleeps.append, **kwargs)
        return result, sleeps

    def test_stops_after_first_block(self):
        ok = GoogleSerp(state="ok", questions=["Wat kost SEO?"])
        blocked = GoogleSerp.failed("blocked", MSG_BLOCKED)
        session = FakeSession({"a": ok, "b": blocked, "c": ok, "d": ok})
        result, sleeps = self.run_fetch(session, ["a", "b", "c", "d"], pause_seconds=3)
        self.assertEqual(session.calls, ["a", "b"])  # geen verdere verzoeken
        self.assertEqual([result[k].state for k in "abcd"], ["ok", "blocked", "blocked", "blocked"])
        self.assertEqual(result["c"].message, MSG_BLOCKED)
        self.assertEqual(result["d"].message, MSG_BLOCKED)
        self.assertEqual(sleeps, [3])  # alleen tussen a en b
        self.assertTrue(session.closed)

    def test_first_keyword_blocked_blocks_all(self):
        session = FakeSession({"a": GoogleSerp.failed("blocked", MSG_CONSENT)})
        result, _ = self.run_fetch(session, ["a", "b", "c"])
        self.assertEqual(session.calls, ["a"])
        self.assertTrue(all(r.state == "blocked" and r.message == MSG_CONSENT for r in result.values()))

    def test_exception_in_google_becomes_error_and_continues(self):
        session = FakeSession({"a": RuntimeError("kapot"), "b": GoogleSerp(state="ok", ai_overview=True)})
        result, _ = self.run_fetch(session, ["a", "b"])
        self.assertEqual(result["a"].state, "error")
        self.assertTrue(result["a"].message)
        self.assertEqual(result["b"].state, "ok")

    def test_browser_start_failure_gives_error_for_all(self):
        session = FakeSession({}, enter_error=RuntimeError("chromium ontbreekt"))
        result, _ = self.run_fetch(session, ["a", "b"])
        self.assertEqual(session.calls, [])
        self.assertEqual({k: (v.state, v.message) for k, v in result.items()},
                         {"a": ("error", MSG_BROWSER), "b": ("error", MSG_BROWSER)})

        def boom():
            raise OSError("geen browser")

        result = fetch_google(["x"], session_factory=boom, sleep=lambda s: None)
        self.assertEqual(result["x"].state, "error")

    def test_start_error_attribute_gives_error_for_all(self):
        session = FakeSession({}, start_error="Browser start niet")
        result, _ = self.run_fetch(session, ["a"])
        self.assertEqual(session.calls, [])
        self.assertEqual(result["a"].state, "error")

    def test_close_failure_and_odd_input_never_raise(self):
        session = FakeSession({"a": "geen GoogleSerp"}, exit_error=RuntimeError("sluiten mislukt"))
        result, _ = self.run_fetch(session, ["a", " a ", "", None, "b"])  # type: ignore[list-item]
        self.assertEqual(list(result), ["a", "b"])
        self.assertEqual(result["a"].state, "error")
        self.assertEqual(result["b"].state, "empty")
        self.assertEqual(fetch_google([], session_factory=lambda: session), {})


class FakeRequest:
    def __init__(self, url, redirected_from=None):
        self.url = url
        self.redirected_from = redirected_from


class FakeResponse:
    def __init__(self, status, request):
        self.status = status
        self.request = request


class FakePage:
    def __init__(self, response=None, error=None, final_url=None, html="<html>pagina</html>"):
        self.response = response
        self.error = error
        self.url = final_url or (response.request.url if response else "about:blank")
        self.html = html
        self.routed = False
        self.closed = False

    def route(self, pattern, handler):
        self.routed = True

    def goto(self, url, **kwargs):
        if self.error:
            raise self.error
        return self.response

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def content(self):
        return self.html

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.new_pages = 0

    def new_page(self):
        self.new_pages += 1
        return self.page


SAFE_URL = "https://93.184.215.14/pagina"  # publiek IP: geen DNS nodig


class PageHtmlTests(unittest.TestCase):
    def session_with(self, page):
        session = BrowserSession()
        session._context = FakeContext(page)
        return session

    def test_refuses_unsafe_urls_without_opening_a_page(self):
        page = FakePage(FakeResponse(200, FakeRequest(SAFE_URL)))
        session = self.session_with(page)
        for url in (
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://[::1]/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "",
            None,
        ):
            self.assertIsNone(session.page_html(url))  # type: ignore[arg-type]
        self.assertEqual(session._context.new_pages, 0)

    def test_returns_html_for_safe_url(self):
        page = FakePage(FakeResponse(200, FakeRequest(SAFE_URL)), html="<html><h1>Concurrent</h1></html>")
        session = self.session_with(page)
        self.assertEqual(session.page_html(SAFE_URL), "<html><h1>Concurrent</h1></html>")
        self.assertTrue(page.routed)
        self.assertTrue(page.closed)

    def test_http_error_status_gives_none(self):
        page = FakePage(FakeResponse(403, FakeRequest(SAFE_URL)))
        self.assertIsNone(self.session_with(page).page_html(SAFE_URL))
        self.assertTrue(page.closed)

    def test_redirect_to_internal_address_gives_none(self):
        chain = FakeRequest("http://169.254.169.254/latest/", redirected_from=FakeRequest(SAFE_URL))
        page = FakePage(FakeResponse(200, chain))
        self.assertIsNone(self.session_with(page).page_html(SAFE_URL))

    def test_navigation_error_gives_none(self):
        page = FakePage(error=RuntimeError("net::ERR_CONNECTION_RESET"))
        self.assertIsNone(self.session_with(page).page_html(SAFE_URL))
        self.assertTrue(page.closed)

    def test_route_guard_blocks_internal_subrequests(self):
        session = BrowserSession()

        class Route:
            def __init__(self, url, resource_type="script"):
                self.request = type("R", (), {"url": url, "resource_type": resource_type})()
                self.result = None

            def continue_(self):
                self.result = "continue"

            def abort(self, reason="failed"):
                self.result = "abort"

        cases = [
            ("https://93.184.215.14/app.js", "script", "continue"),
            ("http://127.0.0.1:8000/api/", "fetch", "abort"),
            ("https://93.184.215.14/foto.jpg", "image", "abort"),
        ]
        for url, kind, expected in cases:
            route = Route(url, kind)
            session._guard_route(route)
            self.assertEqual(route.result, expected, url)

    def test_without_browser_nothing_raises(self):
        session = BrowserSession()  # niet gestart
        self.assertIsNone(session.page_html(SAFE_URL))
        self.assertEqual(session.google("seo").state, "error")
        session.close()

    def test_inside_running_event_loop_is_start_error_not_exception(self):
        async def inside_loop():
            with BrowserSession() as session:
                return session.start_error, session.available, session.page_html(SAFE_URL), session.google("seo").state

        start_error, available, html, state = asyncio.run(inside_loop())
        self.assertTrue(start_error)
        self.assertFalse(available)
        self.assertIsNone(html)
        self.assertEqual(state, "error")
        # fetch_google met zo'n sessie: alles error.
        result = fetch_google(["a"], session_factory=lambda: _LoopSession(), sleep=lambda s: None)
        self.assertEqual(result["a"].state, "error")


class _LoopSession(BrowserSession):
    def __enter__(self):
        self.start_error = "Sync Playwright kan niet binnen een lopende event loop starten."
        return self


if __name__ == "__main__":
    unittest.main()
