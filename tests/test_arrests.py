import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import call, patch

from build import render_arrests_content, render_donuts_recipient
from scripts.update_arrests import (
    WHPD_ALLIANCE_ID, ZKILL_PAGE_LIMIT, build_dataset, collect_name_ids,
    fetch_alliance_kills, fetch_current_member_ids, main,
)


class ArrestDatasetTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
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
                    'alliance_id': WHPD_ALLIANCE_ID,
                    'damage_done': 100,
                    'final_blow': False,
                    'ship_type_id': 707,
                },
                {
                    'character_id': 202,
                    'alliance_id': WHPD_ALLIANCE_ID,
                    'damage_done': 200,
                    'final_blow': True,
                    'ship_type_id': 707,
                },
            ],
            'zkb': {'npc': npc, 'totalValue': total_value, 'points': 5},
        }

    def test_shared_killmail_is_deduplicated_and_both_personnel_receive_credit(self):
        killmail = self.make_killmail()
        dataset = build_dataset([killmail, killmail], self.names, self.now, current_member_ids={101, 202})

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
        dataset = build_dataset([old_killmail, npc_killmail], self.names, self.now, current_member_ids={101, 202})

        self.assertEqual(dataset['summary']['arrests'], 0)
        self.assertEqual(dataset['rankings'], [])

    def test_new_alliance_participants_need_no_local_roster_entry(self):
        dataset = build_dataset([self.make_killmail()], self.names, self.now, current_member_ids={101, 202})

        personnel = {officer['character_id']: officer for officer in dataset['rankings']}
        self.assertEqual(set(personnel), {101, 202})
        self.assertEqual(personnel[202]['name'], 'Second Deputy')

    def test_non_whpd_activity_is_excluded(self):
        for alliance_id in (12345, None):
            with self.subTest(alliance_id=alliance_id):
                shared = self.make_killmail()
                shared['attackers'][1]['alliance_id'] = alliance_id
                former_only = self.make_killmail(9002, victim_id=808, solar_system_id=999)
                former_only['attackers'] = [shared['attackers'][1]]
                dataset = build_dataset([shared, former_only], self.names, self.now, current_member_ids={101, 202})

                self.assertEqual(dataset['summary'], {
                    'arrests': 1, 'suspects': 1, 'systems_protected': 1,
                    'total_value': 1_500_000,
                })
                self.assertEqual([o['character_id'] for o in dataset['rankings']], [101])
                self.assertEqual(dataset['rankings'][0]['final_blows'], 0)
                self.assertEqual([o['character_id'] for o in dataset['arrests'][0]['officers']], [101])
                self.assertEqual([d['character_id'] for d in dataset['dirtbags']], [303])
                self.assertEqual([h['system_id'] for h in dataset['hotspots']], [606])

    def test_affiliation_is_checked_on_each_killmail(self):
        before_departure = self.make_killmail()
        after_departure = self.make_killmail(9002)
        after_departure['attackers'][1]['alliance_id'] = 12345
        dataset = build_dataset([before_departure, after_departure], self.names, self.now, current_member_ids={101, 202})

        personnel = {officer['character_id']: officer for officer in dataset['rankings']}
        self.assertEqual(dataset['summary']['arrests'], 2)
        self.assertEqual(personnel[101]['arrests'], 2)
        self.assertEqual(personnel[202]['arrests'], 1)
        self.assertEqual(personnel[202]['final_blows'], 1)
        self.assertEqual(personnel[202]['case_value'], 1_500_000)

    def test_departed_member_gets_no_credit_for_earlier_whpd_kills(self):
        shared = self.make_killmail()
        former_only = self.make_killmail(9002, victim_id=808, solar_system_id=999)
        former_only['attackers'] = [former_only['attackers'][1]]
        dataset = build_dataset([shared, former_only], self.names, self.now,
                                current_member_ids={101})

        self.assertEqual(dataset['summary'], {
            'arrests': 1, 'suspects': 1, 'systems_protected': 1, 'total_value': 1_500_000,
        })
        self.assertEqual([o['character_id'] for o in dataset['rankings']], [101])
        self.assertEqual([o['character_id'] for o in dataset['arrests'][0]['officers']], [101])
        self.assertEqual(dataset['rankings'][0]['final_blows'], 0)
        self.assertEqual([d['character_id'] for d in dataset['dirtbags']], [303])
        self.assertEqual([h['system_id'] for h in dataset['hotspots']], [606])

    def test_alliance_losses_and_npc_attackers_do_not_create_arrests(self):
        loss = self.make_killmail()
        loss['victim']['alliance_id'] = WHPD_ALLIANCE_ID
        loss['attackers'] = [
            {'character_id': 999, 'alliance_id': 12345},
            {'alliance_id': WHPD_ALLIANCE_ID},
        ]
        dataset = build_dataset([loss], self.names, self.now, current_member_ids={101, 202})

        self.assertEqual(dataset['summary']['arrests'], 0)
        self.assertEqual(dataset['rankings'], [])

    def test_names_are_requested_for_discovered_alliance_attackers(self):
        killmail = self.make_killmail()
        killmail['attackers'].append({'character_id': 999, 'ship_type_id': 888})
        ids = collect_name_ids([killmail])

        self.assertTrue({101, 202, 303, 404, 505, 606, 707}.issubset(ids))
        self.assertNotIn(999, ids)
        self.assertNotIn(888, ids)

    def test_donuts_recipient_is_the_top_ranked_personnel_member(self):
        dataset = build_dataset(
            [self.make_killmail()],
            self.names,
            self.now,
            current_member_ids={101, 202},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_donuts_recipient(data_file)

        self.assertIn("Today's Donuts Recipient", rendered)
        self.assertIn('Second Deputy', rendered)
        self.assertIn('https://zkillboard.com/character/202/', rendered)
        self.assertIn('<strong>1</strong><small>Final blows</small>', rendered)

    def test_systems_protected_counts_unique_arrest_systems(self):
        dataset = build_dataset(
            [
                self.make_killmail(9001, solar_system_id=606),
                self.make_killmail(9002, solar_system_id=606),
                self.make_killmail(9003, solar_system_id=607),
            ],
            {**self.names, 607: 'J654321'},
            self.now,
            current_member_ids={101, 202},
        )

        self.assertEqual(dataset['summary']['systems_protected'], 2)

    def test_rendered_content_escapes_public_names(self):
        dataset = build_dataset(
            [self.make_killmail()],
            {**self.names, 303: '<Test Suspect>'},
            self.now,
            current_member_ids={101, 202},
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

    def test_weekly_property_seized_uses_one_decimal_place(self):
        dataset = build_dataset(
            [self.make_killmail(total_value=3_020_000_000)],
            self.names,
            self.now,
            current_member_ids={101, 202},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / 'arrests.json'
            data_file.write_text(json.dumps(dataset), encoding='utf-8')
            rendered = render_arrests_content(data_file)

        summary_markup = rendered.split('<section class="arrest-rankings"', 1)[0]
        self.assertIn('<strong>3.0b</strong><span>Property seized</span>', summary_markup)

    def test_rankings_only_display_personnel_meeting_the_five_arrest_quota(self):
        dataset = build_dataset(
            [self.make_killmail(killmail_id) for killmail_id in range(9001, 9006)],
            self.names,
            self.now,
            current_member_ids={101, 202},
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
            [repeat_offender_small, repeat_offender_big, expensive_first_timer],
            self.names,
            self.now,
            current_member_ids={101, 202},
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
        dataset = build_dataset(killmails, self.names, self.now, current_member_ids={101, 202})

        self.assertEqual(len(dataset['dirtbags']), 10)

    def test_hotspots_rank_systems_and_link_the_highest_value_killmail(self):
        dataset = build_dataset(
            [
                self.make_killmail(9001, solar_system_id=606, total_value=2_000_000),
                self.make_killmail(9002, solar_system_id=606, total_value=3_000_000),
                self.make_killmail(9003, solar_system_id=607, total_value=100_000_000),
            ],
            {**self.names, 607: 'J654321'},
            self.now,
            current_member_ids={101, 202},
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
        dataset = build_dataset(killmails, self.names, self.now, current_member_ids={101, 202})

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


class ArrestFetchTests(unittest.TestCase):
    @patch('scripts.update_arrests.time.sleep')
    @patch('scripts.update_arrests.request_json')
    def test_stats_determine_current_membership(self, request, sleep):
        request.side_effect = [
            {'info': {'id': 101, 'name': 'Current', 'allianceID': WHPD_ALLIANCE_ID}},
            {'info': {'id': 202, 'name': 'Former', 'alliance_id': 99015331}},
            {'info': {'id': 303, 'name': 'Unaffiliated'}},
            {'info': {'id': 404, 'name': 'Current too', 'alliance_id': WHPD_ALLIANCE_ID}},
        ]
        self.assertEqual(fetch_current_member_ids([404, 101, 101, 202, 303]), {101, 404})
        self.assertEqual(request.call_args_list, [
            call(f'https://zkillboard.com/api/stats/characterID/{character_id}/kills/')
            for character_id in (101, 202, 303, 404)
        ])
        self.assertEqual(sleep.call_count, 3)

    @patch('scripts.update_arrests.request_json')
    def test_invalid_stats_are_not_treated_as_departures(self, request):
        for response in ({'error': 'Unavailable'}, [], {'info': {}},
                         {'info': {'id': 999, 'name': 'Wrong character'}}):
            with self.subTest(response=response):
                request.return_value = response
                with self.assertRaisesRegex(RuntimeError, 'unexpected character stats'):
                    fetch_current_member_ids([101])

    @patch('scripts.update_arrests.fetch_current_member_ids', side_effect=RuntimeError('Stats unavailable'))
    @patch('scripts.update_arrests.fetch_alliance_kills', return_value=[])
    def test_failed_membership_check_preserves_the_previous_report(self, fetch, members):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'arrests.json'
            output.write_text('previous report', encoding='utf-8')
            with patch('sys.argv', ['update_arrests.py', '--output', str(output)]):
                with self.assertRaisesRegex(RuntimeError, 'Stats unavailable'):
                    main()
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous report')

    @patch('scripts.update_arrests.time.sleep')
    @patch('scripts.update_arrests.request_json')
    def test_fetches_alliance_pages_and_deduplicates_boundary_records(self, request, sleep):
        first_page = [{'killmail_id': number} for number in range(ZKILL_PAGE_LIMIT)]
        request.side_effect = [first_page, [first_page[-1], {'killmail_id': 9999}]]

        kills = fetch_alliance_kills()

        self.assertEqual(len(kills), ZKILL_PAGE_LIMIT + 1)
        self.assertEqual(kills[-1]['killmail_id'], 9999)
        self.assertEqual(request.call_args_list, [
            call('https://zkillboard.com/api/kills/w-space/allianceID/99010102/pastSeconds/604800/page/1/'),
            call('https://zkillboard.com/api/kills/w-space/allianceID/99010102/pastSeconds/604800/page/2/'),
        ])
        sleep.assert_called_once_with(1)

    @patch('scripts.update_arrests.request_json', return_value={'error': 'Unavailable'})
    def test_error_response_is_not_treated_as_an_empty_report(self, request):
        with self.assertRaisesRegex(RuntimeError, 'unexpected response'):
            fetch_alliance_kills()

    @patch('scripts.update_arrests.MAX_ZKILL_PAGES', 1)
    @patch('scripts.update_arrests.request_json')
    def test_pagination_limit_fails_instead_of_publishing_partial_totals(self, request):
        request.return_value = [{'killmail_id': number} for number in range(ZKILL_PAGE_LIMIT)]
        with self.assertRaisesRegex(RuntimeError, 'pagination limit'):
            fetch_alliance_kills()

    @patch('scripts.update_arrests.fetch_current_member_ids', return_value={101, 202})
    @patch('scripts.update_arrests.resolve_names')
    @patch('scripts.update_arrests.fetch_alliance_kills')
    def test_main_discovers_personnel_without_local_configuration(self, fetch, resolve, members):
        fixture = ArrestDatasetTests()
        fixture.setUp()
        killmail = fixture.make_killmail(occurred_at=datetime.now(timezone.utc) - timedelta(hours=1))
        fetch.return_value = [killmail]
        resolve.return_value = fixture.names
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'arrests.json'
            with patch('sys.argv', ['update_arrests.py', '--output', str(output)]):
                main()
            dataset = json.loads(output.read_text(encoding='utf-8'))

        self.assertEqual(dataset['source']['alliance_id'], WHPD_ALLIANCE_ID)
        self.assertEqual(dataset['summary']['arrests'], 1)
        self.assertEqual({o['character_id'] for o in dataset['rankings']}, {101, 202})
        fetch.assert_called_once_with()
        members.assert_called_once_with({101, 202})
        self.assertTrue({101, 202}.issubset(resolve.call_args.args[0]))

    @patch('scripts.update_arrests.fetch_alliance_kills', side_effect=RuntimeError('Unavailable'))
    def test_failed_refresh_preserves_the_previous_report(self, fetch):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'arrests.json'
            output.write_text('previous report', encoding='utf-8')
            with patch('sys.argv', ['update_arrests.py', '--output', str(output)]):
                with self.assertRaisesRegex(RuntimeError, 'Unavailable'):
                    main()
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous report')


if __name__ == '__main__':
    unittest.main()
