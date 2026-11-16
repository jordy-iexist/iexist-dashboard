"""robots.txt-matcher volgens de regels van Google (langste regel, Allow bij gelijkspel, * en $)."""
import unittest

from app.features.launch_checklist.services.robots_rules import parse_robots

URL = "https://www.klant.nl"


def check(robots: str, path: str, bot: str = "Googlebot"):
    return parse_robots(robots).check(bot, URL + path)


class LongestMatchTest(unittest.TestCase):
    def test_longer_allow_beats_disallow_root(self):
        robots = "User-agent: *\nDisallow: /\nAllow: /x/\n"
        self.assertEqual(check(robots, "/x/pagina"), (True, "Allow: /x/"))
        self.assertEqual(check(robots, "/y/pagina"), (False, "Disallow: /"))

    def test_longer_disallow_beats_allow_regardless_of_order(self):
        robots = "User-agent: *\nDisallow: /blog/concept/\nAllow: /blog/\n"
        self.assertEqual(check(robots, "/blog/concept/a"), (False, "Disallow: /blog/concept/"))
        self.assertEqual(check(robots, "/blog/a"), (True, "Allow: /blog/"))

    def test_allow_wins_a_tie(self):
        robots = "User-agent: *\nDisallow: /pagina\nAllow: /pagina\n"
        self.assertEqual(check(robots, "/pagina"), (True, "Allow: /pagina"))

    def test_no_matching_rule_is_allowed(self):
        self.assertEqual(check("User-agent: *\nDisallow: /wp-admin/\n", "/diensten/"), (True, None))


class WildcardTest(unittest.TestCase):
    def test_star_matches_query_strings(self):
        robots = "User-agent: *\nDisallow: /*?\n"
        self.assertEqual(check(robots, "/winkel?kleur=rood"), (False, "Disallow: /*?"))
        self.assertEqual(check(robots, "/winkel"), (True, None))

    def test_star_in_the_middle(self):
        robots = "User-agent: *\nDisallow: /*/feed/\n"
        self.assertFalse(check(robots, "/blog/feed/")[0])
        self.assertTrue(check(robots, "/blog/artikel/")[0])

    def test_dollar_anchors_the_end(self):
        robots = "User-agent: *\nDisallow: /*.pdf$\n"
        self.assertFalse(check(robots, "/docs/folder.pdf")[0])
        self.assertTrue(check(robots, "/docs/folder.pdf?v=2")[0])
        self.assertTrue(check(robots, "/docs/folder.pdf.html")[0])

    def test_dollar_on_exact_path(self):
        robots = "User-agent: *\nDisallow: /$\n"
        self.assertFalse(check(robots, "/")[0])
        self.assertTrue(check(robots, "/contact")[0])


class GroupTest(unittest.TestCase):
    ROBOTS = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: Googlebot\nDisallow: /intern/\n\n"
        "User-agent: bingbot\nUser-agent: Slurp\nDisallow: /zoeken/\n"
    )

    def test_specific_group_replaces_star(self):
        self.assertEqual(check(self.ROBOTS, "/diensten/", "Googlebot"), (True, None))
        self.assertEqual(check(self.ROBOTS, "/intern/x", "Googlebot"), (False, "Disallow: /intern/"))

    def test_user_agent_matching_is_case_insensitive_and_shared(self):
        self.assertEqual(check(self.ROBOTS, "/zoeken/a", "Bingbot"), (False, "Disallow: /zoeken/"))
        self.assertTrue(check(self.ROBOTS, "/intern/x", "Bingbot")[0])

    def test_falls_back_to_star(self):
        self.assertEqual(check(self.ROBOTS, "/diensten/", "PerplexityBot"), (False, "Disallow: /"))

    def test_suffixed_crawler_falls_back_to_its_base_group(self):
        self.assertFalse(check(self.ROBOTS, "/intern/x", "Googlebot-News")[0])
        self.assertTrue(check(self.ROBOTS, "/diensten/", "Googlebot-News")[0])

    def test_version_suffix_in_user_agent_is_ignored(self):
        robots = "User-agent: Googlebot/2.1\nDisallow: /a/\n"
        self.assertFalse(check(robots, "/a/b")[0])

    def test_groups_with_same_agent_are_merged(self):
        robots = "User-agent: Googlebot\nDisallow: /a/\n\nUser-agent: Googlebot\nDisallow: /b/\n"
        self.assertFalse(check(robots, "/a/x")[0])
        self.assertFalse(check(robots, "/b/x")[0])

    def test_empty_specific_group_allows_everything(self):
        robots = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow:\n"
        self.assertEqual(check(robots, "/alles/"), (True, None))

    def test_comments_and_sitemap_lines(self):
        robots = "# test\nUser-agent: * # iedereen\nSitemap: https://www.klant.nl/sitemap.xml\nDisallow: /tmp/ # tijdelijk\n"
        self.assertEqual(check(robots, "/tmp/a"), (False, "Disallow: /tmp/"))


class EmptyTest(unittest.TestCase):
    def test_empty_file_allows_everything(self):
        for robots in ("", None, "\n\n", "# alleen commentaar\n"):
            self.assertEqual(parse_robots(robots).check("Googlebot", URL + "/x"), (True, None))

    def test_empty_disallow_value_blocks_nothing(self):
        self.assertEqual(check("User-agent: *\nDisallow:\n", "/x"), (True, None))
        self.assertEqual(check("User-agent: *\nDisallow: \n", "/"), (True, None))


if __name__ == "__main__":
    unittest.main()
