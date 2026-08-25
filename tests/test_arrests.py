import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build import render_arrests_content
from scripts.update_arrests import build_dataset


class ArrestDatasetTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
        self.officers = [
            {'character_id': 101, 'name': 'First Officer', 'rank': 'Officer'},
            {'character_id': 202, 'name': 'Second Deputy', 'rank': 'Deputy'},
        ]
        self.names = {
            101: 'First Officer',
            202: 'Second Deputy',
            303: 'Test Suspect',
            404: 'Test Corporation',
            505: 'Test Ship',
            606: 'J123456',
            707: 'Police Ship',
            808: 'Very Expensive Suspect',
            909: 'Very Expensive Corporation',
            1001: 'Very Expensive Ship',
        }

    def make_killmail(
        self,
        killmail_id=9001,
        occurred_at=None,
        npc=False,
        victim_id=303,
        corporation_id=404,
        ship_type_id=505,
        solar_system_id=606,
        total_value=1_500_000,
    ):
        occurred_at = occurred_at or self.now - timedelta(hours=1)
        return {
            'killmail_id': killmail_id,
            'killmail_time': occurred_at.isoformat().replace('+00:00', 'Z'),
            'solar_system_id': solar_system_id,
            'victim': {
                'character_id': victim_id,
                'corporation_id': corporation_id,
                'ship_type_id': ship_type_id,
            },
            'attackers': [
                {
                    'character_id': 101,
                    'damage_done': 100,
                    'final_blow': False,
                    'ship_type_id': 707,
                },
                {
                    'character_id': 202,
                    'damage_done': 200,
                    'final_blow': True,
                    'ship_type_id': 707,
                },
            ],
            'zkb': {'npc': npc, 'totalValue': total_value, 'points': 5},
        }

    def test_shared_killmail_is_deduplicated_and_both_personnel_receive_credit(self):
        killmail = self.make_killmail()
        dataset = build_dataset(self.officers, [killmail, killmail], self.names, self.now)

        self.assertEqual(dataset['summary']['arrests'], 1)
        self.assertEqual(dataset['summary']['suspects'], 1)
        self.assertEqual(dataset['summary']['systems_protected'], 1)
        self.assertEqual(dataset['summary']['total_value'], 1_500_000)
        self.assertEqual(len(dataset['arrests'][0]['officers']), 2)
        self.assertEqual(dataset['rankings'][0]['character_id'], 202)
        self.assertEqual(dataset['rankings'][0]['final_blows'], 1)
        self.assertEqual(dataset['rankings'][1]['arrests'], 1)
        self.assertEqual(dataset['dirtbags'][0]['arrests'], 1)
        self.assertEqual(dataset['hotspots'][0]['system_id'], 606)
        self.assertEqual(dataset['hotspots'][0]['arrests'], 1)

    def test_old_and_npc_killmails_are_excluded(self):
        old_killmail = self.make_killmail(9002, self.now - timedelta(days=8))
        npc_killmail = self.make_killmail(9003, npc=True)
        dataset = build_dataset(self.officers, [old_killmail, npc_killmail], self.names, self.now)

        self.assertEqual(dataset['summary']['arrests'], 0)
        self.assertTrue(all(officer['arrests'] == 0 for officer in dataset['rankings']))

    def test_systems_protected_counts_unique_arrest_systems(self):
        dataset = build_dataset(
            self.officers,
            [
                self.make_killmail(9001, solar_system_id=606),
                self.make_killmail(9002, solar_system_id=606),
                self.make_killmail(9003, solar_system_id=607),
            ],
            {**self.names, 607: 'J654321'},
            self.now,
        )

        self.assertEqual(dataset['summary']['systems_protected'], 2)

    def test_rendered_content_escapes_public_names(self):
        dataset = build_dataset(
            self.officers,
            [self.make_killmail()],
            {**self.names, 303: '<Test Suspect>'},
            self.now,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        self.assertIn('&lt;Test Suspect&gt;', rendered)
        self.assertNotIn('<Test Suspect>', rendered)
        self.assertNotIn('Rolling seven days ending', rendered)
        self.assertIn('<span>Rolling seven days</span>', rendered)
        self.assertIn('<span>Last refreshed Aug 24, 2026 at 01:00 UTC</span>', rendered)
        self.assertIn('https://zkillboard.com/kill/9001/', rendered)

    def test_rankings_only_display_personnel_meeting_the_five_arrest_quota(self):
        dataset = build_dataset(
            self.officers,
            [self.make_killmail(killmail_id) for killmail_id in range(9001, 9006)],
            self.names,
            self.now,
        )
        next(officer for officer in dataset['rankings'] if officer['name'] == 'Second Deputy')['arrests'] = 4
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        self.assertIn('<h2 id="arrest-rankings-title">Rankings</h2>', rendered)
        self.assertIn('First Officer', rendered)
        rankings_markup = rendered.split('<section class="top-dirtbags"', 1)[0]
        self.assertNotIn('Second Deputy', rankings_markup)
        self.assertIn('For those meeting or exceeding the quota of 5 arrests per week', rendered)

    def test_dirtbags_sort_by_arrests_then_value_and_link_their_biggest_loss(self):
        repeat_offender_small = self.make_killmail(9001, total_value=2_000_000)
        repeat_offender_big = self.make_killmail(9002, total_value=3_000_000)
        expensive_first_timer = self.make_killmail(
            9003,
            victim_id=808,
            corporation_id=909,
            ship_type_id=1001,
            total_value=100_000_000,
        )
        dataset = build_dataset(
            self.officers,
            [repeat_offender_small, repeat_offender_big, expensive_first_timer],
            self.names,
            self.now,
        )

        self.assertEqual(dataset['dirtbags'][0]['character_id'], 303)
        self.assertEqual(dataset['dirtbags'][0]['arrests'], 2)
        self.assertEqual(dataset['dirtbags'][0]['total_value'], 5_000_000)
        self.assertEqual(dataset['dirtbags'][0]['most_expensive_loss']['killmail_id'], 9002)
        self.assertEqual(dataset['dirtbags'][1]['character_id'], 808)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        dirtbag_markup = rendered.split('<section class="top-dirtbags"', 1)[1]
        self.assertLess(dirtbag_markup.index('Test Suspect'), dirtbag_markup.index('Very Expensive Suspect'))
        self.assertIn('https://zkillboard.com/kill/9002/', dirtbag_markup)
        self.assertIn('<h2 id="top-dirtbags-title">Top 10 Dirtbags</h2>', dirtbag_markup)
        self.assertIn('<th class="arrest-number" scope="col">Case value</th>', dirtbag_markup)
        self.assertIn('<th class="arrest-number public-record" scope="col">Public Record</th>', dirtbag_markup)
        self.assertNotIn('>Total value<', dirtbag_markup)
        self.assertNotIn('Most expensive loss', dirtbag_markup)

    def test_dirtbag_rankings_are_capped_at_ten(self):
        killmails = [
            self.make_killmail(10_000 + index, victim_id=20_000 + index)
            for index in range(11)
        ]
        dataset = build_dataset(self.officers, killmails, self.names, self.now)

        self.assertEqual(len(dataset['dirtbags']), 10)

    def test_hotspots_rank_systems_and_link_the_highest_value_killmail(self):
        dataset = build_dataset(
            self.officers,
            [
                self.make_killmail(9001, solar_system_id=606, total_value=2_000_000),
                self.make_killmail(9002, solar_system_id=606, total_value=3_000_000),
                self.make_killmail(9003, solar_system_id=607, total_value=100_000_000),
            ],
            {**self.names, 607: 'J654321'},
            self.now,
        )

        self.assertEqual(dataset['hotspots'][0]['system_id'], 606)
        self.assertEqual(dataset['hotspots'][0]['arrests'], 2)
        self.assertEqual(dataset['hotspots'][0]['total_value'], 5_000_000)
        self.assertEqual(dataset['hotspots'][0]['top_killmail']['killmail_id'], 9002)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        hotspot_markup = rendered.split('<section class="dirtbag-hotspots"', 1)[1]
        self.assertIn('<h2 id="dirtbag-hotspots-title">Dirtbag Hotspots</h2>', hotspot_markup)
        self.assertIn('Top 5 systems by arrests, then total case value.', hotspot_markup)
        self.assertIn('https://zkillboard.com/system/606/', hotspot_markup)
        self.assertIn('https://zkillboard.com/kill/9002/', hotspot_markup)
        self.assertLess(hotspot_markup.index('J123456'), hotspot_markup.index('J654321'))

    def test_hotspot_rankings_are_capped_at_five(self):
        killmails = [
            self.make_killmail(
                10_000 + index,
                victim_id=20_000 + index,
                solar_system_id=30_000 + index,
            )
            for index in range(6)
        ]
        dataset = build_dataset(self.officers, killmails, self.names, self.now)

        self.assertEqual(len(dataset['hotspots']), 5)

    def test_empty_seed_renders_before_the_first_actions_refresh(self):
        empty_dataset = {
            'schema_version': 4,
            'generated_at': None,
            'window': {'start': None, 'end': None, 'seconds': 604800},
            'summary': {'arrests': 0, 'suspects': 0, 'systems_protected': 0, 'total_value': 0},
            'rankings': [],
            'dirtbags': [],
            'hotspots': [],
            'arrests': [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(empty_dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        self.assertIn('Awaiting the first GitHub Actions refresh', rendered)
        self.assertIn('<strong>0</strong><span>Systems protected</span>', rendered)
        self.assertIn('No personnel met the weekly arrest quota.', rendered)
        self.assertIn('No dirtbags were arrested during this reporting period.', rendered)
        self.assertIn('No protected systems were recorded during this reporting period.', rendered)


if __name__ == '__main__':
    unittest.main()
