"""Maanden en periodes van het maandrapport (features/monthly_report/services/periods.py)."""
import unittest
from datetime import date, datetime, timezone

from app.features.monthly_report.services import periods as p


class ParseMonthTest(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(p.parse_month("2026-11"), (2026, 11))
        self.assertEqual(p.parse_month("2026-01"), (2026, 1))
        for value in ("2026-13", "2026-00", "2026-1", "26-11", "2026/11", "", "november", "2026-11-01", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.parse_month(value)

    def test_previous_and_shift(self):
        self.assertEqual(p.previous_month("2026-11"), "2026-10")
        self.assertEqual(p.previous_month("2026-01"), "2025-12")
        self.assertEqual(p.shift_month("2026-12", 1), "2027-01")
        self.assertEqual(p.shift_month("2026-11", -16), "2025-07")

    def test_months_back(self):
        today = date(2026, 11, 25)
        self.assertEqual(p.months_back("2026-11", today), 0)
        self.assertEqual(p.months_back("2026-12", today), -1)
        self.assertEqual(p.months_back("2025-07", today), 16)
        self.assertEqual(p.months_back("2025-06", today), 17)

    def test_first_and_last_day(self):
        self.assertEqual(p.last_day("2026-02"), date(2026, 2, 28))
        self.assertEqual(p.last_day("2028-02"), date(2028, 2, 29))
        self.assertEqual(p.last_day("2026-12"), date(2026, 12, 31))


class BoundsTest(unittest.TestCase):
    def test_month_bounds_in_amsterdam(self):
        utc = timezone.utc
        # Wintertijd (UTC+1).
        self.assertEqual(p.month_bounds_utc("2026-11"),
                         (datetime(2026, 10, 31, 23, 0, tzinfo=utc), datetime(2026, 11, 30, 23, 0, tzinfo=utc)))
        # Zomertijd (UTC+2).
        self.assertEqual(p.month_bounds_utc("2026-07"),
                         (datetime(2026, 6, 30, 22, 0, tzinfo=utc), datetime(2026, 7, 31, 22, 0, tzinfo=utc)))
        # Maart: begint in wintertijd, eindigt in zomertijd.
        self.assertEqual(p.month_bounds_utc("2026-03"),
                         (datetime(2026, 2, 28, 23, 0, tzinfo=utc), datetime(2026, 3, 31, 22, 0, tzinfo=utc)))
        # Januari: begin in het jaar ervoor (UTC).
        self.assertEqual(p.month_bounds_utc("2026-01")[0], datetime(2025, 12, 31, 23, 0, tzinfo=utc))

    def test_today_local(self):
        self.assertEqual(p.today_local(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)), date(2026, 12, 1))
        self.assertEqual(p.today_local(datetime(2026, 11, 30, 22, 30, tzinfo=timezone.utc)), date(2026, 11, 30))


class GscSpansTest(unittest.TestCase):
    def test_running_month_is_shortened_by_lag(self):
        spans = p.gsc_spans("2026-11", date(2026, 11, 25), 3)
        self.assertEqual(spans["current"], (date(2026, 11, 1), date(2026, 11, 22)))
        self.assertEqual(spans["previous"], (date(2026, 10, 1), date(2026, 10, 22)))
        self.assertFalse(spans["complete"])

    def test_complete_month(self):
        spans = p.gsc_spans("2026-11", date(2026, 12, 3), 3)
        self.assertEqual(spans["current"], (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual(spans["previous"], (date(2026, 10, 1), date(2026, 10, 30)))
        self.assertTrue(spans["complete"])
        # Een dag eerder mist de laatste dag nog.
        spans = p.gsc_spans("2026-11", date(2026, 12, 2), 3)
        self.assertEqual((spans["current"][1], spans["complete"]), (date(2026, 11, 29), False))

    def test_january_compares_with_december(self):
        spans = p.gsc_spans("2026-01", date(2026, 3, 1), 3)
        self.assertEqual(spans["current"], (date(2026, 1, 1), date(2026, 1, 31)))
        self.assertEqual(spans["previous"], (date(2025, 12, 1), date(2025, 12, 31)))

    def test_march_comparison_is_capped_at_end_of_february(self):
        spans = p.gsc_spans("2026-03", date(2026, 4, 10), 3)
        self.assertEqual(spans["current"], (date(2026, 3, 1), date(2026, 3, 31)))
        self.assertEqual(spans["previous"], (date(2026, 2, 1), date(2026, 2, 28)))
        spans = p.gsc_spans("2026-02", date(2026, 3, 10), 3)
        self.assertEqual(spans["current"], (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(spans["previous"], (date(2026, 1, 1), date(2026, 1, 28)))

    def test_first_days_of_a_month(self):
        for day in (1, 2, 3):
            with self.subTest(day=day):
                self.assertIsNone(p.gsc_spans("2026-12", date(2026, 12, day), 3))
        spans = p.gsc_spans("2026-12", date(2026, 12, 4), 3)
        self.assertEqual(spans["current"], (date(2026, 12, 1), date(2026, 12, 1)))
        self.assertEqual(spans["previous"], (date(2026, 11, 1), date(2026, 11, 1)))
        # Zonder vertraging telt vandaag mee.
        self.assertEqual(p.gsc_spans("2026-12", date(2026, 12, 1), 0)["current"],
                         (date(2026, 12, 1), date(2026, 12, 1)))

    def test_future_month(self):
        self.assertIsNone(p.gsc_spans("2027-01", date(2026, 12, 20), 3))


class PrtWindowTest(unittest.TestCase):
    def test_window(self):
        self.assertTrue(p.prt_window_open("2026-11", date(2026, 11, 1)))
        self.assertTrue(p.prt_window_open("2026-11", date(2026, 11, 30)))
        self.assertTrue(p.prt_window_open("2026-11", date(2026, 12, 7)))
        self.assertFalse(p.prt_window_open("2026-11", date(2026, 12, 8)))
        self.assertFalse(p.prt_window_open("2026-11", date(2026, 10, 31)))
        self.assertTrue(p.prt_window_open("2025-12", date(2026, 1, 7)))
        self.assertFalse(p.prt_window_open("2025-12", date(2026, 1, 8)))
        self.assertEqual((p.PRT_WINDOW_DAYS, p.MAX_MONTHS_BACK), (7, 16))


if __name__ == "__main__":
    unittest.main()
