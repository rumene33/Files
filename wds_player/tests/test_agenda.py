import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import agenda
import timeplaner
from settings import Settings, new_timer


class TestAgendaData(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        shutil.copy(os.path.join(os.path.dirname(__file__), "TimePlaner_sample.xml"),
                    os.path.join(self.d, "TimePlaner.xml"))
        self.pl = timeplaner.PlanRunner([self.d], lambda *a: 0, lambda: 0)
        self.pl.reload()

    def test_dated_timer_only_on_its_day(self):
        st = Settings()
        tm = new_timer(); tm["date"] = "2026-10-23"; tm["h"] = 12; tm["end_on"] = True; tm["eh"] = 14
        st.timers = [tm]
        rows = agenda.day_rows(st, None, date(2026, 10, 23))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["at"], "12:00:00")
        self.assertEqual(rows[0]["end"], 14 * 3600)
        self.assertEqual(agenda.day_rows(st, None, date(2026, 10, 30)), [])

    def test_month_and_year_counts(self):
        st = Settings()
        tm = new_timer(); tm["date"] = "2026-10-23"
        w = new_timer(); w["days"] = [0]               # всеки понеделник
        st.timers = [tm, w]
        mc = agenda.month_counts(st, None, 2026, 10)
        self.assertEqual(mc[23], 1)
        self.assertEqual(mc[5], 1)                      # 05.10.2026 е понеделник
        self.assertEqual(sum(mc.values()), 1 + 4)       # 4 понеделника (5,12,19,26) + датата
        yc = agenda.year_counts(st, None, 2026)
        self.assertEqual(yc[10], 5)

    def test_planner_rows_and_shift(self):
        st = Settings()
        rows = agenda.day_rows(st, self.pl, date(2026, 10, 23))
        self.assertTrue(any(r["kind"] == "plan" for r in rows))
        self.assertTrue(any(r["kind"] == "stop" for r in rows))
        self.assertEqual(agenda.shift("month", date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(agenda.shift("year", date(2024, 2, 29), 1), date(2025, 2, 28))
        self.assertEqual(agenda.shift("day", date(2026, 12, 31), 1), date(2027, 1, 1))
        self.assertEqual(agenda.shift("month", date(2026, 1, 15), -1), date(2025, 12, 15))

    def test_year_day_counts_match_month_totals(self):
        st = Settings(); st.planner_enabled = True
        per_day = agenda.year_day_counts(st, self.pl, 2026)
        self.assertEqual(len(per_day), 365)
        self.assertEqual(agenda.year_counts(st, self.pl, 2026, per_day), agenda.year_counts(st, self.pl, 2026))
        self.assertEqual(sum(n for d, n in per_day.items() if d.month == 10),
                         sum(agenda.month_counts(st, self.pl, 2026, 10).values()))

    def test_counts_do_not_search_show_files(self):
        """Месец/година не четат папката с шоута (иначе на Pi „Програма“ блокира интерфейса)."""
        st = Settings(); st.planner_enabled = True
        orig, calls = timeplaner.find_show, []
        timeplaner.find_show = lambda *a: calls.append(a)
        try:
            agenda.year_counts(st, self.pl, 2026)
            self.assertEqual(calls, [])
            agenda.day_rows(st, self.pl, date(2026, 10, 23))
            self.assertTrue(calls)                      # денят все пак показва липсващите шоута
        finally:
            timeplaner.find_show = orig


if __name__ == "__main__":
    unittest.main()
