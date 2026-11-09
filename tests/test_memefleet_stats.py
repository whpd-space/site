import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from build import memefleet_rankings, render_memefleet_leaderboards, render_memefleet_stats
from scripts.update_memefleet_stats import (
    build_memefleet_dataset,
    fleet_window,
    history_source,
    main,
    merge_memefleet_datasets,
    recent_months,
)


class MemeFleetStatsTests(unittest.TestCase):
    def test_legacy_history_is_backfilled_and_failed_names_preserve_previous_file(self):
        kill = self.make_killmail(1, datetime(2026, 8, 23, 18, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fleets.json'
            original = json.dumps({'fleets': [{'date': '2026-08-23', 'systems_protected': 1, 'pilots': [{'character_id': 1, 'final_blows': 1, 'pod_kills': 0}]}]})
            path.write_text(original)
            with patch('sys.argv', ['update_memefleet_stats.py', '--output', str(path)]), \
                 patch('scripts.update_memefleet_stats.month_range', return_value=[(2026, 8)]) as months, \
                 patch('scripts.update_memefleet_stats.fetch_month_kills', return_value=[kill]), \
                 patch('scripts.update_memefleet_stats.resolve_names', side_effect=RuntimeError('ESI unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'ESI unavailable'):
                    main()
                months.assert_called_once()
                self.assertEqual(path.read_text(), original)
            with patch('sys.argv', ['update_memefleet_stats.py', '--output', str(path)]), \
                 patch('scripts.update_memefleet_stats.month_range', return_value=[(2026, 8)]), \
                 patch('scripts.update_memefleet_stats.fetch_month_kills', return_value=[kill]), \
                 patch('scripts.update_memefleet_stats.resolve_names', return_value={1: 'Pilot One', 2: 'Pilot Two'}):
                main()
            result = json.loads(path.read_text())
            self.assertEqual(result['schema_version'], 4)
            self.assertEqual(result['pilot_names']['1'], 'Pilot One')
            self.assertEqual(len(result['fleets'][0]['pilots']), 2)

    def test_pilot_counts_deduplicate_kills_and_count_both_capsule_types(self):
        kills = []
        for kill_id, ship_type in enumerate((670, 33328, 777), 1):
            kill = self.make_killmail(kill_id, datetime(2026, 8, 23, 18, tzinfo=timezone.utc))
            kill['victim']['ship_type_id'] = ship_type
            kill['attackers'][0]['final_blow'] = True
            kill['attackers'].append(dict(kill['attackers'][0]))
            kill['attackers'].append({'final_blow': False})
            kills.append(kill)
        dataset = build_memefleet_dataset(kills + kills, datetime(2026, 8, 24, tzinfo=timezone.utc))
        pilots = dataset['fleets'][0]['pilots']
        self.assertEqual(pilots, [
            {'character_id': 1, 'arrests': 3, 'final_blows': 3, 'pod_kills': 2},
            {'character_id': 2, 'arrests': 3, 'final_blows': 0, 'pod_kills': 2},
        ])
        ranks = memefleet_rankings(dataset['fleets'], {})
        self.assertEqual([p['attendance'] for p in ranks['attendance']], [1, 1])
        self.assertEqual([p['rank'] for p in ranks['pod_kills']], [1, 1])

    def test_years_ties_and_incremental_replacement(self):
        def fleet(day, blows):
            return {'date': day, 'pilots': [
                {'character_id': 1, 'arrests': blows + 1, 'final_blows': blows, 'pod_kills': 1},
                {'character_id': 2, 'arrests': 1, 'final_blows': 0, 'pod_kills': 1},
            ]}
        existing = {'fleets': [fleet('2025-12-28', 2), fleet('2026-01-04', 99)]}
        refreshed = {'fleets': [fleet('2026-01-04', 3)]}
        merged = merge_memefleet_datasets(existing, refreshed, [(2026, 1)])
        all_time = memefleet_rankings(merged['fleets'], {'1': 'Zed', '2': 'Amy'})
        year = memefleet_rankings(merged['fleets'], {}, '2026')
        self.assertEqual(all_time['final_blows'][0]['final_blows'], 5)
        self.assertEqual(year['final_blows'][0]['final_blows'], 3)
        self.assertEqual(all_time['arrests'][0]['arrests'], 7)
        self.assertEqual(year['arrests'][0]['arrests'], 4)
        self.assertEqual([p['name'] for p in all_time['attendance']], ['Amy', 'Zed'])
        self.assertEqual([p['rank'] for p in all_time['attendance']], [1, 1])
        self.assertEqual(len(all_time['final_blows']), 1)
        self.assertEqual(memefleet_rankings(merged['fleets'], {}, '2024')['attendance'], [])

    def test_leaderboard_rendering_escapes_names_and_handles_missing_history(self):
        dataset = build_memefleet_dataset([
            self.make_killmail(1, datetime(2026, 8, 23, 18, tzinfo=timezone.utc))
        ], datetime(2026, 8, 24, tzinfo=timezone.utc))
        dataset['pilot_names'] = {'1': '<script>bad</script>'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fleets.json'
            path.write_text(json.dumps(dataset))
            rendered = render_memefleet_leaderboards(path)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', rendered)
            self.assertIn('data-period="all"', rendered)
            self.assertIn('data-metric="arrests"', rendered)
            self.assertIn('data-period="2026"', rendered)
            self.assertIn('No recorded activity for this ranking.', rendered)
            self.assertNotIn('—', rendered)
            del dataset['fleets'][0]['pilots']
            path.write_text(json.dumps(dataset))
            self.assertIn('awaiting', render_memefleet_leaderboards(path))

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
            'Participants is the maximum headcount on a single arrest during each fleet.',
            rendered,
        )


if __name__ == '__main__':
    unittest.main()
