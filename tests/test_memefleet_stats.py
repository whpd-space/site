import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from build import render_memefleet_stats
from scripts.update_memefleet_stats import (
    build_memefleet_dataset,
    fleet_window,
    history_source,
    merge_memefleet_datasets,
    recent_months,
)


class MemeFleetStatsTests(unittest.TestCase):
    @staticmethod
    def make_killmail(
        killmail_id,
        occurred_at,
        total_value=1_000_000,
        attacker_ids=(1, 2),
        solar_system_id=31000001,
        npc=False,
    ):
        return {
            'killmail_id': killmail_id,
            'killmail_time': occurred_at.isoformat().replace('+00:00', 'Z'),
            'solar_system_id': solar_system_id,
            'victim': {'character_id': 999, 'corporation_id': 888, 'ship_type_id': 777},
            'attackers': [{'character_id': character_id} for character_id in attacker_ids],
            'zkb': {'npc': npc, 'totalValue': total_value},
        }

    def test_fleet_window_automatically_adjusts_for_dst(self):
        winter_start, winter_end = fleet_window(datetime(2026, 1, 4, 18, 0, tzinfo=timezone.utc))
        summer_start, summer_end = fleet_window(datetime(2026, 7, 5, 17, 0, tzinfo=timezone.utc))

        self.assertEqual(winter_start.isoformat(), '2026-01-04T13:00:00-05:00')
        self.assertEqual(winter_end.astimezone(timezone.utc).hour, 20)
        self.assertEqual(summer_start.isoformat(), '2026-07-05T13:00:00-04:00')
        self.assertEqual(summer_end.astimezone(timezone.utc).hour, 19)

    def test_history_uses_only_the_official_whpd_alliance(self):
        self.assertEqual(history_source(2020, 7), ('allianceID', 99010102))
        self.assertEqual(history_source(2026, 8), ('allianceID', 99010102))

    def test_incremental_refresh_uses_two_months_and_preserves_older_fleets(self):
        self.assertEqual(recent_months(datetime(2026, 1, 4).date()), [(2025, 12), (2026, 1)])
        existing = {
            'history_start': '2019-01-01',
            'fleets': [
                {'date': '2019-10-27', 'total_value': 5},
                {'date': '2026-07-05', 'total_value': 1},
                {'date': '2026-06-28', 'total_value': 2},
            ],
        }
        refreshed = {
            'history_start': '2019-01-01',
            'fleets': [
                {'date': '2026-08-02', 'total_value': 3},
                {'date': '2026-07-05', 'total_value': 4},
            ],
        }

        merged = merge_memefleet_datasets(existing, refreshed, [(2026, 7), (2026, 8)])

        self.assertEqual(
            [(fleet['date'], fleet['total_value']) for fleet in merged['fleets']],
            [('2026-08-02', 3), ('2026-07-05', 4), ('2026-06-28', 2)],
        )

    def test_weekly_stats_deduplicate_and_calculate_max_participants(self):
        first = self.make_killmail(
            1001,
            datetime(2026, 8, 23, 17, 30, tzinfo=timezone.utc),
            total_value=1_000_000,
        )
        second = self.make_killmail(
            1002,
            datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc),
            total_value=2_000_000,
            attacker_ids=(1, 2, 3),
            solar_system_id=31000002,
        )
        third = self.make_killmail(
            1005,
            datetime(2026, 8, 23, 18, 15, tzinfo=timezone.utc),
            total_value=3_000_000,
            solar_system_id=31000002,
        )
        outside_window = self.make_killmail(
            1003,
            datetime(2026, 8, 23, 19, 1, tzinfo=timezone.utc),
            total_value=50_000_000,
        )
        zero_value_week = self.make_killmail(
            1004,
            datetime(2026, 8, 16, 17, 30, tzinfo=timezone.utc),
            total_value=0,
        )
        dataset = build_memefleet_dataset(
            [first, first, second, third, outside_window, zero_value_week],
            datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(dataset['fleets']), 1)
        fleet = dataset['fleets'][0]
        self.assertEqual(fleet['date'], '2026-08-23')
        self.assertEqual(fleet['participants_max'], 3)
        self.assertEqual(fleet['systems_protected'], 2)
        self.assertEqual(fleet['arrests'], 3)
        self.assertEqual(fleet['total_value'], 6_000_000)
        self.assertEqual(fleet['timezone'], 'EDT')

    def test_in_progress_fleet_is_not_published(self):
        killmail = self.make_killmail(
            1001,
            datetime(2026, 8, 23, 17, 30, tzinfo=timezone.utc),
        )
        dataset = build_memefleet_dataset(
            [killmail],
            datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(dataset['fleets'], [])

    def test_rendered_table_contains_all_requested_columns(self):
        killmail = self.make_killmail(
            1001,
            datetime(2026, 8, 23, 17, 30, tzinfo=timezone.utc),
        )
        dataset = build_memefleet_dataset(
            [killmail],
            datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'memefleets.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_memefleet_stats(data_file)

        self.assertIn('August 23, 2026', rendered)
        self.assertIn('Participants', rendered)
        self.assertNotIn('Participants (max)', rendered)
        self.assertIn('Systems Protected', rendered)
        self.assertIn('Arrests', rendered)
        self.assertIn('Total Cases Value', rendered)
        self.assertNotIn('Total arrest value', rendered)
        self.assertIn(
            'Participants is based on the maximum number of participants recorded on a single arrest during each fleet.',
            rendered,
        )


if __name__ == '__main__':
    unittest.main()
