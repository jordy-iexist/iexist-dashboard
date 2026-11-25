import unittest
from datetime import datetime, timezone

from app.features.keywords.schemas import (
    Candidate,
    DomainChoice,
    DomainClass,
    Heatmap,
    ManualDomain,
    Overrides,
    Raw,
    RawCompetitor,
    RawMetrics,
    RawPrt,
    RawTop10,
    SerpHit,
    SourceInfo,
    Sources,
    TopicAssignment,
    TrackedKeyword,
    TrafficPoint,
)
from app.features.keywords.services import compute

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
SOURCES = Sources(
    ahrefs=SourceInfo(state="ok"), prt=SourceInfo(state="ok"),
    claude=SourceInfo(state="ok"), profile=SourceInfo(state="ok"),
)


def manual(*domains):
    return Overrides(manual=[ManualDomain(domain=d, added_by="u1", added_at=NOW) for d in domains])


def cand(domain, pct=0.0, shared=0, origin="ahrefs"):
    return Candidate(domain=domain, origin=origin, overlap_pct=pct, shared=shared)


def agg(type_="landelijk"):
    return DomainClass(type=type_, is_aggregator=True, reason="vergelijkingssite")


def plain(type_="regio"):
    return DomainClass(type=type_, reason="dienstverlener")


def snapshot(raw, items, top5, *, classes=None, overrides=None, topics=(), assignment=None, heatmap=None):
    return compute.build_snapshot(
        raw, customer_domain="klant.nl", items=items, classes=classes or {}, top5=top5,
        overrides=overrides or Overrides(), topics=list(topics), assignment=assignment,
        heatmap=heatmap, sources=SOURCES, warnings=["let op"],
    )


class CandidateTests(unittest.TestCase):
    def test_overlap_basis(self):
        self.assertEqual(compute.overlap_basis(Raw()), "ahrefs")
        self.assertEqual(compute.overlap_basis(Raw(serps={})), "ahrefs")
        # Een zoekwoord waarvoor Ahrefs geen SERP kent telt niet als steekproef.
        self.assertEqual(compute.overlap_basis(Raw(serps={"seo": []})), "ahrefs")
        hit = [SerpHit(domain="a.nl", position=1)]
        self.assertEqual(compute.overlap_basis(Raw(serps={"seo": hit})), "tracked")

    def test_empty_serp_does_not_lower_overlap(self):
        hit = [SerpHit(domain="a.nl", position=1)]
        raw = Raw(serps={"kw1": hit, "kw2": hit, "leeg": []})
        self.assertEqual(compute.sample_size(raw), 2)
        items = compute.candidates(raw, customer_domain="klant.nl", manual_domains=[])
        self.assertEqual([(i.domain, i.shared, i.overlap_pct) for i in items], [("a.nl", 2, 100.0)])

    def test_ahrefs_basis(self):
        raw = Raw(competitors=[
            RawCompetitor(domain="a.nl", domain_rating=40.0, keywords_common=30, share=8.44),
            RawCompetitor(domain="klein.nl", keywords_common=4, share=0.5),
            RawCompetitor(domain="handklein.nl", keywords_common=2, share=0.2),
            RawCompetitor(domain="shop.klant.nl", keywords_common=900, share=60.0),
            RawCompetitor(domain="klant.nl", keywords_common=900, share=60.0),
        ])
        items = compute.candidates(
            raw, customer_domain="https://www.klant.nl/", manual_domains=["handklein.nl", "www.nieuw.nl"]
        )
        self.assertEqual(
            [(i.domain, i.origin, i.shared, i.overlap_pct) for i in items],
            [("a.nl", "ahrefs", 30, 8.4), ("handklein.nl", "manual", 2, 0.2), ("nieuw.nl", "manual", 0, 0.0)],
        )
        self.assertEqual(items[0].domain_rating, 40.0)

    def test_tracked_basis(self):
        serps = {
            "kw1": [SerpHit(domain="a.nl", position=2, title="A1"), SerpHit(domain="x.nl", position=1, title="X"),
                    SerpHit(domain="a.nl", position=5, title="A2")],
            "kw2": [SerpHit(domain="a.nl", position=3, title="A1"), SerpHit(domain="y.nl", position=1),
                    SerpHit(domain="x.nl", position=4, title="X")],
            "kw3": [SerpHit(domain="y.nl", position=2), SerpHit(domain="a.nl", position=1, title="A3"),
                    SerpHit(domain="z.nl", position=9)],
            "kw4": [SerpHit(domain="a.nl", position=1, title="A4"), SerpHit(domain="klant.nl", position=2)],
        }
        raw = Raw(serps=serps, competitors=[
            RawCompetitor(domain="a.nl", domain_rating=50.0, keywords_common=2, share=0.1),
            RawCompetitor(domain="nooit.nl", keywords_common=50, share=10.0),
        ])
        items = compute.candidates(raw, customer_domain="klant.nl", manual_domains=["hand.nl"])
        by_domain = {i.domain: i for i in items}
        # nooit.nl staat in geen enkele SERP en valt af; hand.nl blijft met 0.
        self.assertEqual(list(by_domain), ["a.nl", "hand.nl", "y.nl", "x.nl", "z.nl"])
        self.assertEqual((by_domain["a.nl"].shared, by_domain["a.nl"].overlap_pct), (4, 100.0))
        self.assertEqual(by_domain["a.nl"].origin, "ahrefs")
        self.assertEqual(by_domain["a.nl"].domain_rating, 50.0)
        self.assertEqual(by_domain["a.nl"].titles, ["A1", "A2", "A3"])
        self.assertEqual((by_domain["hand.nl"].shared, by_domain["hand.nl"].origin), (0, "manual"))
        # x.nl en y.nl elk 2 SERP's; y.nl gemiddeld positie 1,5 tegen x.nl 2,5, dus y eerst.
        self.assertEqual((by_domain["x.nl"].shared, by_domain["x.nl"].overlap_pct), (2, 50.0))
        self.assertEqual(by_domain["z.nl"].overlap_pct, 25.0)
        self.assertEqual(by_domain["y.nl"].origin, "tracked")
        self.assertNotIn("klant.nl", by_domain)

    def test_tracked_found_domains_capped(self):
        serps = {f"kw{i}": [SerpHit(domain=f"d{j}.nl", position=j + 1) for j in range(20) if j <= i + 10]
                 for i in range(10)}
        items = compute.candidates(Raw(serps=serps), customer_domain="klant.nl", manual_domains=[])
        self.assertEqual(len(items), compute.TRACKED_CANDIDATES_MAX)
        self.assertEqual(items[0].domain, "d0.nl")
        self.assertNotIn("d19.nl", [i.domain for i in items])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            cand("a.nl", 30.0, 100), cand("b.nl", 20.0, 80), cand("c.nl", 20.0, 90),
            cand("d.nl", 10.0, 50), cand("e.nl", 10.0, 50), cand("f.nl", 5.0, 40),
            cand("vergelijk.nl", 40.0, 200), cand("hand2.nl", 1.0, 1, "manual"),
            cand("hand1.nl", 0.0, 0, "manual"),
        ]

    def test_manual_first_then_overlap(self):
        top = compute.select_top5(self.items, {"vergelijk.nl": agg()}, manual("hand1.nl", "hand2.nl"))
        self.assertEqual(top, ["hand1.nl", "hand2.nl", "a.nl", "c.nl", "b.nl"])

    def test_tie_breaks_on_shared_then_name(self):
        top = compute.select_top5(self.items[:6], {}, Overrides())
        self.assertEqual(top, ["a.nl", "c.nl", "b.nl", "d.nl", "e.nl"])

    def test_override_beats_claude_both_ways(self):
        overrides = manual("hand1.nl", "hand2.nl")
        overrides.domains = {
            "vergelijk.nl": DomainChoice(excluded=False),  # Claude: vergelijkingssite, gebruiker: telt mee
            "a.nl": DomainChoice(excluded=True),  # Claude: geen oordeel tegen, gebruiker: uitgesloten
            "hand1.nl": DomainChoice(type="lokaal", excluded=True),
        }
        classes = {"vergelijk.nl": agg(), "a.nl": plain()}
        top = compute.select_top5(self.items, classes, overrides)
        self.assertEqual(top, ["hand2.nl", "vergelijk.nl", "c.nl", "b.nl", "d.nl"])
        self.assertEqual(compute.shown_excluded(self.items, classes, overrides), ["a.nl", "hand1.nl"])

    def test_shown_excluded_capped_but_manual_always(self):
        items = [cand(f"x{i}.nl", 1.0, 100 - i) for i in range(7)] + [cand("hand.nl", 0.0, 0, "manual")]
        classes = {i.domain: agg() for i in items}
        self.assertEqual(
            compute.shown_excluded(items, classes, manual("hand.nl")),
            ["x0.nl", "x1.nl", "x2.nl", "x3.nl", "x4.nl", "hand.nl"],
        )


class UniverseTests(unittest.TestCase):
    def test_order_dedupe_and_cap(self):
        raw = Raw(
            prt=RawPrt(state="ok", rows=[
                TrackedKeyword(keyword="laag", volume=10), TrackedKeyword(keyword="Hoog", volume=500),
                TrackedKeyword(keyword="geen volume"),
            ]),
            top10={
                "klant.nl": RawTop10(keywords=["k1", "gedeeld", "hoog"]),
                "a.nl": RawTop10(keywords=["a1", "a2", "gedeeld", "drie"]),
                "b.nl": RawTop10(keywords=["drie", "b1"]),
                "c.nl": RawTop10(keywords=["drie"]),
                "niet.nl": RawTop10(keywords=["niet in de vijf"]),
            },
        )
        universe = compute.keyword_universe(raw, customer_domain="klant.nl", top5=["a.nl", "b.nl", "c.nl"])
        self.assertEqual(
            universe, ["Hoog", "laag", "geen volume", "drie", "gedeeld", "k1", "a1", "a2", "b1"]
        )

    def test_caps(self):
        raw = Raw(
            prt=RawPrt(state="ok", rows=[TrackedKeyword(keyword=f"t{i}", volume=i) for i in range(200)]),
            top10={"a.nl": RawTop10(keywords=[f"a{i}" for i in range(1000)])},
        )
        universe = compute.keyword_universe(raw, customer_domain="klant.nl", top5=["a.nl"])
        self.assertEqual(len(universe), compute.UNIVERSE_MAX)
        self.assertEqual(universe[0], "t199")
        self.assertEqual(sum(1 for k in universe if k.startswith("t")), compute.TRACKED_KEYWORDS_MAX)


KWS = [f"dienst {i}" for i in range(100)]
FIVE = ["c1.nl", "c2.nl", "c3.nl", "c4.nl", "c5.nl"]


def heat_raw(**extra):
    top10 = {"klant.nl": RawTop10(keywords=KWS[:9])}
    for domain, hits in zip(FIVE, (10, 24, 25, 49, 50)):
        top10[domain] = RawTop10(keywords=KWS[:hits])
    top10.update(extra)
    # De rest van de zoekwoorden komt als gevolgd zoekwoord zonder positie in de verzameling.
    prt = RawPrt(state="ok", rows=[TrackedKeyword(keyword=k) for k in KWS[50:]])
    return Raw(top10=top10, prt=prt)


class HeatmapTests(unittest.TestCase):
    def test_cell_levels_on_boundaries(self):
        raw = heat_raw()
        # Lokaal: 4 zoekwoorden -> te weinig; een zoekwoord buiten de verzameling telt niet mee.
        assignment = TopicAssignment(
            services={"SEO": KWS + ["niet in de verzameling"], "Leeg": []}, local=KWS[:4],
        )
        snap = snapshot(raw, [cand(d, 10.0, 10) for d in FIVE], FIVE, topics=["SEO", "Leeg"], assignment=assignment)
        heat = snap.heatmap
        self.assertEqual(heat.state, "ok")
        self.assertEqual([c.domain for c in heat.columns], ["klant.nl", *FIVE])
        self.assertTrue(heat.columns[0].is_customer)
        seo = heat.rows[0]
        self.assertEqual((seo.topic, seo.kind, seo.keywords), ("SEO", "service", 100))
        self.assertEqual([c.pct for c in seo.cells], [9, 10, 24, 25, 49, 50])
        self.assertEqual([c.level for c in seo.cells], [0, 1, 1, 2, 2, 3])
        self.assertEqual((heat.rows[1].topic, heat.rows[1].cells), ("Leeg", []))
        local = heat.rows[2]
        self.assertEqual((local.topic, local.kind, local.keywords, local.cells), ("Lokaal", "local", 4, []))
        self.assertEqual((heat.universe.total, heat.universe.tracked, heat.universe.assigned), (100, 50, 100))
        self.assertEqual(snap.summary.state, "skipped")

    def test_prt_leads_for_customer_and_rounding_half_up(self):
        words = [f"w{i}" for i in range(8)]
        raw = Raw(
            prt=RawPrt(state="ok", rows=[
                TrackedKeyword(keyword="w0", rank=15),  # Ahrefs zegt top 10, PRT niet
                TrackedKeyword(keyword="w1", rank=4),  # Ahrefs zegt niets, PRT wel
                TrackedKeyword(keyword="w2", rank=None),
                *[TrackedKeyword(keyword=f"w{i}") for i in range(4, 8)],
            ]),
            top10={"klant.nl": RawTop10(keywords=["w0", "w3"]), "c1.nl": RawTop10(keywords=["w0"])},
        )
        snap = snapshot(raw, [cand("c1.nl", 5.0, 5)], ["c1.nl"], topics=["Dienst"],
                        assignment=TopicAssignment(services={"dienst": words}))
        cells = snap.heatmap.rows[0].cells
        # Klant: w1 (PRT) + w3 (Ahrefs) = 2 van 8 = 25%; c1: 1 van 8 = 12,5% -> 13.
        self.assertEqual([c.pct for c in cells], [25, 13])
        self.assertEqual(snap.heatmap.universe.tracked, 7)

    def test_truncated_column(self):
        raw = heat_raw(**{
            "c4.nl": RawTop10(keywords=KWS[:49], truncated=True, checked=KWS[49:]),  # alles nagevraagd
            "c5.nl": RawTop10(keywords=KWS[:50], truncated=True, checked=KWS[50:99]),  # één ontbreekt
        })
        snap = snapshot(raw, [cand(d) for d in FIVE], FIVE, topics=["SEO"],
                        assignment=TopicAssignment(services={"SEO": KWS}))
        flags = {c.domain: c.truncated for c in snap.heatmap.columns}
        self.assertEqual(flags, {"klant.nl": False, "c1.nl": False, "c2.nl": False, "c3.nl": False,
                                 "c4.nl": False, "c5.nl": True})

    def test_no_assignment_or_nothing_assigned(self):
        raw = heat_raw()
        for assignment in (None, TopicAssignment(services={"SEO": ["onbekend"]})):
            heat = snapshot(raw, [], [], topics=["SEO"], assignment=assignment).heatmap
            self.assertEqual(heat.state, "no_keywords")
            self.assertTrue(heat.message)
            self.assertEqual((heat.columns, heat.rows), ([], []))
            self.assertEqual(heat.universe.assigned, 0)

    def test_given_heatmap_is_kept(self):
        given = Heatmap(state="no_profile", message="Vul het klantprofiel in.")
        snap = snapshot(heat_raw(), [], [], heatmap=given, assignment=TopicAssignment(services={"SEO": KWS}))
        self.assertEqual(snap.heatmap, given)


class SnapshotTests(unittest.TestCase):
    def test_rows_metrics_and_kpis(self):
        raw = Raw(
            metrics={
                "klant.nl": RawMetrics(domain_rating=30.0, org_keywords=800, org_keywords_1_3=40,
                                       org_keywords_4_10=60, org_traffic=1200),
                "a.nl": RawMetrics(domain_rating=50.0, org_keywords=900, org_keywords_1_3=10, org_traffic=10),
                "b.nl": RawMetrics(domain_rating=20.0),
                "c.nl": RawMetrics(domain_rating=None),
                "d.nl": RawMetrics(domain_rating=70.0),
            },
            traffic_history=[TrafficPoint(date="2026-09-01", org_traffic=900),
                             TrafficPoint(date="2026-10-01", org_traffic=1000),
                             TrafficPoint(date="2026-11-01", org_traffic=1083)],
        )
        items = [cand("a.nl", 10.0, 20), cand("b.nl", 20.0, 30), cand("c.nl", 5.0, 5),
                 cand("d.nl", 7.5, 10), cand("vergelijk.nl", 50.0, 99), cand("hand.nl", 0.0, 0, "manual")]
        items[2].domain_rating = 44.0  # valt terug op de DR uit organic-competitors
        classes = {"vergelijk.nl": agg(), "a.nl": plain("landelijk")}
        overrides = manual("hand.nl")
        overrides.domains = {"hand.nl": DomainChoice(excluded=False)}
        top5 = ["a.nl", "b.nl", "c.nl", "d.nl"]
        snap = snapshot(raw, items, top5, classes=classes, overrides=overrides)

        self.assertEqual([c.domain for c in snap.competitors], [*top5, "vergelijk.nl", "hand.nl"])
        self.assertEqual([c.in_top5 for c in snap.competitors], [True] * 4 + [False, False])
        a = snap.competitors[0]
        self.assertEqual((a.ai_type, a.ai_reason, a.organic_keywords, a.top10_keywords, a.traffic),
                         ("landelijk", "dienstverlener", 900, None, 10))
        self.assertIsNone(snap.competitors[1].ai_type)
        self.assertEqual(snap.competitors[2].domain_rating, 44.0)
        self.assertTrue(snap.competitors[4].ai_is_aggregator)
        kpis = snap.kpis
        self.assertEqual((kpis.organic_keywords.value, kpis.organic_keywords.top10), (800, 100))
        self.assertEqual((kpis.organic_traffic.value, kpis.organic_traffic.change_pct), (1200, 8.3))
        self.assertEqual(kpis.domain_rating.value, 30.0)
        self.assertEqual(kpis.domain_rating.competitor_median, 47.0)  # mediaan van 20, 44, 50, 70
        self.assertEqual((kpis.top5_overlap.pct, kpis.top5_overlap.shared_avg), (10.6, 16))
        self.assertEqual((snap.competitors_state, snap.overlap_basis, snap.tracked_sample), ("ok", "ahrefs", 0))
        self.assertEqual(snap.warnings, ["let op"])

    def test_traffic_change_edge_cases(self):
        for history in ([], [TrafficPoint(date="2026-11-01", org_traffic=5)],
                        [TrafficPoint(date="2026-10-01", org_traffic=0), TrafficPoint(date="2026-11-01", org_traffic=5)]):
            self.assertIsNone(snapshot(Raw(traffic_history=history), [], []).kpis.organic_traffic.change_pct)
        drop = [TrafficPoint(date="2026-10-01", org_traffic=200), TrafficPoint(date="2026-11-01", org_traffic=150)]
        self.assertEqual(snapshot(Raw(traffic_history=drop), [], []).kpis.organic_traffic.change_pct, -25.0)

    def test_empty_without_competitors(self):
        snap = snapshot(Raw(serps={"seo": []}), [], [])
        self.assertEqual(snap.competitors_state, "empty")
        self.assertTrue(snap.competitors_message)
        self.assertIsNone(snap.kpis.domain_rating.competitor_median)
        self.assertIsNone(snap.kpis.top5_overlap.pct)
        self.assertIsNone(snap.kpis.top5_overlap.shared_avg)
        self.assertIsNone(snap.kpis.organic_keywords.value)
        # De enige SERP is leeg en telt niet als steekproef: de basis blijft Ahrefs.
        self.assertEqual((snap.overlap_basis, snap.tracked_sample), ("ahrefs", 0))

    def test_unit_estimate(self):
        self.assertEqual(compute.unit_estimate(with_heatmap=False), 300)
        # 300 + zes domeinen x (300 voor de top 10-lijst + 150 voor de nacontrole)
        self.assertEqual(compute.unit_estimate(with_heatmap=True), 3000)


if __name__ == "__main__":
    unittest.main()
