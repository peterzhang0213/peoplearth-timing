import concurrent.futures
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
import unittest

import server
from test_server import TimingApiTests


class NanxiTests(unittest.TestCase):
    setUp = TimingApiTests.setUp
    tearDown = TimingApiTests.tearDown
    request_json = TimingApiTests.request_json
    assert_post_error = TimingApiTests.assert_post_error

    def register(self, bib, females=None, card=None):
        code = bib[0]
        config = server.nanxi_rules.CATEGORIES[code]
        return self.request_json('/api/participants', {
            'raceId': 'nanxi-race-20260920' if code in 'FG' else 'nanxi-race-20260919',
            'bibNumber': bib, 'cardCode': card or 'BAND-' + bib,
            'athleteName': '选手' if config[2] == 1 else '测试队伍',
            'entryType': config[1], 'memberNames': [f'队员 {i+1}' for i in range(config[2])],
            'femaleCount': females,
        })['participant']

    def checkpoint(self, entry, index, method='nfc', seconds=None):
        profile = server.get_race_profile(entry['race_id'])
        timestamp = datetime(2026, 9, 19, tzinfo=timezone.utc) + timedelta(seconds=index * 300 if seconds is None else seconds)
        payload = {'raceId':entry['race_id'], 'stationId':profile['checkpoints'][index],
                   'deviceId':'test-judge' if method == 'manual' else f'reader-{index}',
                   'eventTime':timestamp.isoformat(), 'timingMode':'manual'}
        if method == 'manual':
            return self.request_json('/api/manual-checkpoints', {**payload, 'participantId':entry['id'], 'adminCode':'test-clear-code-1234'})
        return self.request_json('/api/timing-events', {**payload, 'cardCode':entry['card_code'], 'eventId':f"{entry['id']}-{entry['card_code']}-{index}-{seconds}"})

    def test_seven_categories_and_day_validation(self):
        for code in 'ABCDEFG':
            entry = self.register(code+'-001', 1)
            self.assertEqual(entry['category_code'], code)
        error = self.assert_post_error('/api/participants', {'raceId':'nanxi-race-20260919', 'bibNumber':'F-002', 'cardCode':'NEW', 'athleteName':'Pair', 'entryType':'doubles', 'memberNames':['一','二'], 'femaleCount':1}, 400)
        self.assertIn('日期', error['error'])
        self.assert_post_error('/api/participants', {'raceId':'nanxi-race-20260920', 'bibNumber':'G-002', 'cardCode':'NEW', 'athleteName':'Team', 'entryType':'team', 'memberNames':['一','二','三','四']}, 400)

    def test_fixed_bibs_unique_and_rebinding_preserves_history(self):
        entry = self.register('A-001')
        self.checkpoint(entry, 0)
        self.assert_post_error('/api/participants', {'raceId':entry['race_id'], 'bibNumber':'A-001', 'cardCode':'OTHER', 'athleteName':'重复'}, 400)
        updated = self.request_json('/api/update-participant', {'raceId':entry['race_id'], 'participantId':entry['id'], 'cardCode':'REPLACEMENT', 'bibNumber':'A-001', 'entryType':'individual', 'athleteName':'新姓名', 'confirmation':'UPDATE_PARTICIPANT', 'adminCode':'test-clear-code-1234'})['participant']
        self.assertEqual(updated['id'],entry['id'])
        self.assertEqual(self.checkpoint(entry, 1)['status'], 'unbound_card')
        self.assertEqual(self.checkpoint(updated, 1)['status'], 'accepted')
        result = self.request_json('/api/leaderboard?raceId='+entry['race_id'])['leaderboard'][0]
        self.assertIsNotNone(result['startTime'])

    def test_eight_stations_can_mix_inputs_and_handle_simultaneous_confirmation(self):
        entry=self.register('C-001')
        self.checkpoint(entry,0,'manual')
        def write(method):
            try: return self.checkpoint(entry,1,method)['status']
            except HTTPError as error: return error.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            statuses=list(pool.map(write,['nfc','manual']))
        self.assertEqual(statuses.count('accepted'),1)
        self.assertEqual(self.checkpoint(entry,3)['status'],'wrong_checkpoint')
        self.assertEqual(self.checkpoint(entry,2,seconds=100)['status'],'invalid_progress')
        for index in range(2,9): self.assertEqual(self.checkpoint(entry,index,'manual' if index%2 else 'nfc')['status'],'accepted')
        result=self.request_json('/api/leaderboard?raceId='+entry['race_id'])['leaderboard'][0]
        self.assertEqual(result['elapsedMs'],2400000)
        self.assertEqual(result['categoryRank'],1)
        self.assertEqual(len(result['stationSplits']),8)
        self.assertTrue(all(ms==300000 for ms in result['stationSplits'].values()))

    def test_relay_deduction_penalty_and_independent_ranks(self):
        entries=[self.register('F-001',0),self.register('F-002',1),self.register('G-001',3),self.register('G-002',4)]
        for entry in entries:
            for index in range(9): self.checkpoint(entry,index)
        self.request_json('/api/result-adjustments',{'raceId':entries[1]['race_id'],'participantId':entries[1]['id'],'adjustmentSeconds':60,'reason':'罚时','adminCode':'test-clear-code-1234'})
        result={row['bibNumber']:row for row in self.request_json('/api/leaderboard?raceId='+entries[0]['race_id'])['leaderboard']}
        self.assertEqual(result['F-002']['elapsedMs'],2160000)
        self.assertEqual(result['F-002']['deductionMs'],300000)
        self.assertEqual(result['F-002']['penaltyMs'],60000)
        self.assertEqual(result['F-002']['categoryRank'],1)
        self.assertEqual(result['F-001']['categoryRank'],2)
        self.assertEqual(result['G-001']['deductionMs'],600000)
        self.assertEqual(result['G-001']['categoryRank'],1)
        self.assertEqual(result['G-002']['categoryRank'],1)

    def test_manual_results_rank_by_final_time_and_unfinished_have_no_rank(self):
        a=self.register('A-001'); b=self.register('A-002'); self.register('B-001')
        for index in range(9):self.checkpoint(a,index)
        self.request_json('/api/manual-results',{'raceId':b['race_id'],'participantId':b['id'],'entryMode':'elapsed','elapsedSeconds':1200,'reason':'备用计时','adminCode':'test-clear-code-1234'})
        results={row['bibNumber']:row for row in self.request_json('/api/leaderboard?raceId='+a['race_id'])['leaderboard']}
        self.assertEqual(results['A-002']['categoryRank'],1)
        self.assertEqual(results['A-001']['categoryRank'],2)
        self.assertIsNone(results['B-001']['categoryRank'])

    def test_station_roles_and_custom_count_persist(self):
        profile=server.get_race_profile('nanxi-race-20260919')
        self.assertEqual(server.judge_role_checkpoints(profile,'station_8'),['END'])
        self.assertEqual(server.judge_role_checkpoints(profile,'station_9'),[])
        profile['station_count']=10;profile['checkpoints']=server.build_station_boundary_checkpoints(10)
        server.save_race_profile(profile);server.init_db()
        self.assertEqual(server.get_race_profile(profile['race_id'])['station_count'],10)

    def test_both_days_ready_gun_start_and_all_input_combinations(self):
        for day, category in ((19, 'A'), (20, 'F')):
            race_id = f'nanxi-race-202609{day}'
            profile = self.request_json('/api/race-config?raceId=' + race_id)['race']
            self.assertEqual(profile['stationCount'], 8)
            self.assertEqual(profile['checkpoints'], server.build_station_boundary_checkpoints(8))
            entries = [self.register(f'{category}-{index:03d}', 0) for index in range(1, 4)]
            for index, entry in enumerate(entries):
                ready = self.request_json('/api/start-checkins', {
                    'raceId': race_id, 'cardCode': entry['card_code'],
                    'deviceId': 'start-nfc' if index == 0 else 'manual-judge',
                })
                self.assertEqual(ready['status'], 'start_ready')
            before = self.request_json('/api/leaderboard?raceId=' + race_id)['leaderboard']
            self.assertTrue(all(row['startTime'] is None for row in before))
            self.assertEqual(self.request_json('/api/timing-events?raceId=' + race_id)['events'], [])
            start_time = datetime(2026, 9, day, 1, tzinfo=timezone.utc)
            self.request_json('/api/start-race', {
                'raceId': race_id, 'participantIds': [entry['id'] for entry in entries],
                'startedAt': start_time.isoformat(), 'adminCode': 'test-clear-code-1234',
            })
            # All NFC, all manual, and alternating inputs must have identical splits.
            for station in range(1, 9):
                station_id = profile['checkpoints'][station]
                auth = self.request_json('/api/judge-auth', {
                    'raceId': race_id, 'username': f'station_{station}', 'password': f'station{station}',
                })
                self.assertEqual(auth['allowedCheckpoints'], [station_id])
                for index, entry in enumerate(entries):
                    manual = index == 1 or (index == 2 and station % 2 == 0)
                    payload = {
                        'raceId': race_id, 'stationId': station_id, 'timingMode': 'manual',
                        'deviceId': f'station-{station}',
                        'eventTime': (start_time + timedelta(minutes=station * 5)).isoformat(),
                    }
                    if manual:
                        result = self.request_json('/api/manual-checkpoints', {
                            **payload, 'participantId': entry['id'], 'judgeToken': auth['judgeToken'],
                        })
                    else:
                        result = self.request_json('/api/timing-events', {
                            **payload, 'cardCode': entry['card_code'],
                        })
                    self.assertEqual(result['status'], 'accepted')
            results = self.request_json('/api/leaderboard?raceId=' + race_id)['leaderboard']
            for result in results:
                self.assertEqual(result['status'], 'finished')
                self.assertEqual(result['elapsedMs'], 2400000)
                self.assertEqual(list(result['stationSplits'].values()), [300000] * 8)

    def test_device_bindings_are_independent_by_day_and_manual_needs_no_reader(self):
        for day in (19, 20):
            race_id = f'nanxi-race-202609{day}'
            for index, assignment in enumerate(server.build_station_boundary_checkpoints(8)):
                result = self.request_json('/api/device-bindings', {
                    'raceId': race_id, 'deviceId': f'phone-{index}', 'assignment': assignment,
                })
                self.assertEqual(result['binding']['assignment'], assignment)
            self.assert_post_error('/api/device-bindings', {
                'raceId': race_id, 'deviceId': 'other-phone', 'assignment': 'END',
            }, 409)
            bindings = self.request_json('/api/device-bindings?raceId=' + race_id)['bindings']
            self.assertEqual(len(bindings), 9)
        self.request_json('/api/device-bindings/unbind', {
            'raceId': 'nanxi-race-20260919', 'deviceId': 'phone-8', 'adminCode': 'test-clear-code-1234',
        })
        self.assertEqual(len(self.request_json('/api/device-bindings?raceId=nanxi-race-20260920')['bindings']), 9)

    def test_selected_category_and_member_bibs_are_saved_and_queryable(self):
        result = self.request_json('/api/participants', {
            'raceId': 'nanxi-race-20260919', 'categoryCode': 'E',
            'bibNumber': 'TEAM-QUERY-19', 'cardCode': 'BAND-TEAM-19',
            'athleteName': '混合组', 'entryType': 'doubles',
            'memberNames': ['甲', '乙'], 'memberBibNumbers': ['M-1901', 'M-1902'],
        })['participant']
        self.assertEqual(result['category_code'], 'E')
        self.assertEqual(result['member_bib_numbers'], ['M-1901', 'M-1902'])
        leaderboard = self.request_json('/api/leaderboard?raceId=nanxi-race-20260919')['leaderboard']
        saved = next(row for row in leaderboard if row['bibNumber'] == 'TEAM-QUERY-19')
        self.assertEqual(saved['categoryCode'], 'E')
        self.assertEqual(saved['memberBibNumbers'], ['M-1901', 'M-1902'])
        self.assert_post_error('/api/participants', {
            'raceId': 'nanxi-race-20260919', 'categoryCode': 'A',
            'bibNumber': 'M-1901', 'cardCode': 'BAND-OTHER',
            'athleteName': '重复号码', 'entryType': 'individual',
            'memberNames': ['重复号码'],
        }, 400)

    def test_explicit_mens_division_overrides_bib_prefix_and_survives_rebinding(self):
        for number in range(15, 21):
            bib = f'C-{number:03d}'
            with self.subTest(bib=bib):
                entry = self.request_json('/api/participants', {
                    'raceId': 'nanxi-race-20260919', 'categoryCode': 'A',
                    'bibNumber': bib, 'cardCode': 'MENS-' + bib,
                    'athleteName': '男子选手', 'entryType': 'individual',
                    'memberNames': ['男子选手'], 'memberBibNumbers': [bib],
                })['participant']
                self.assertEqual(entry['category_code'], 'A')
                self.assertEqual(entry['female_count'], 0)
                updated = self.request_json('/api/update-participant', {
                    'raceId': entry['race_id'], 'participantId': entry['id'],
                    'bibNumber': bib, 'cardCode': 'MENS-REPLACEMENT-' + bib,
                    'athleteName': '男子选手', 'entryType': 'individual',
                    'confirmation': 'UPDATE_PARTICIPANT', 'adminCode': 'test-clear-code-1234',
                })['participant']
                self.assertEqual(updated['id'], entry['id'])
                self.assertEqual(updated['category_code'], 'A')
                self.assertEqual(updated['member_bib_numbers'], [bib])
        # The six confirmed numbers must not reclassify other C-prefixed entries.
        self.register('C-014')
        self.register('C-021')
        rows = self.request_json('/api/leaderboard?raceId=nanxi-race-20260919')['leaderboard']
        by_bib = {row['bibNumber']: row for row in rows}
        for number in range(15, 21):
            bib = f'C-{number:03d}'
            self.assertEqual(by_bib[bib]['categoryCode'], 'A')
            self.assertEqual(by_bib[bib]['memberBibNumbers'], [bib])
        for bib in ('C-014', 'C-021'):
            self.assertEqual(by_bib[bib]['categoryCode'], 'C')
            self.assertEqual(by_bib[bib]['entryType'], 'doubles')

    def test_legacy_binding_without_category_accepts_confirmed_c_mens_singles(self):
        entry = self.request_json('/api/participants', {
            'raceId': 'nanxi-race-20260919', 'bibNumber': 'C-015',
            'cardCode': 'LEGACY-C-015', 'athleteName': '旧页面男单',
            'entryType': 'individual', 'memberNames': ['旧页面男单'],
        })['participant']
        self.assertEqual(entry['category_code'], 'A')
        self.assertEqual(entry['female_count'], 0)

    def test_day19_doubles_name_is_optional_and_day20_relay_name_is_required(self):
        for category in 'CDE':
            payload = {
                'raceId': 'nanxi-race-20260919', 'categoryCode': category,
                'bibNumber': category + '-201', 'cardCode': 'PAIR-' + category,
                'athleteName': ' ', 'entryType': 'doubles',
                'memberNames': ['成员甲', '成员乙'],
                'memberBibNumbers': [category + '-201', category + '-202'],
            }
            entry = self.request_json('/api/participants', payload)['participant']
            self.assertEqual(entry['athlete_name'], '成员甲 / 成员乙')
            updated = self.request_json('/api/update-participant', {
                **payload, 'participantId': entry['id'], 'memberNames': ['成员甲', '成员丙'],
                'confirmation': 'UPDATE_PARTICIPANT', 'adminCode': 'test-clear-code-1234',
            })['participant']
            self.assertEqual(updated['athlete_name'], '成员甲 / 成员丙')
        for category, members in [('F', ['甲', '乙']), ('G', ['甲', '乙', '丙', '丁'])]:
            payload = {
                'raceId': 'nanxi-race-20260920', 'categoryCode': category,
                'bibNumber': category + '-201', 'cardCode': 'RELAY-' + category,
                'athleteName': '', 'entryType': 'doubles' if category == 'F' else 'team',
                'memberNames': members, 'femaleCount': 1,
            }
            self.assert_post_error('/api/participants', payload, 400)
            saved = self.request_json('/api/participants', {**payload, 'athleteName': '接力队'})['participant']
            self.assertEqual(saved['athlete_name'], '接力队')

    def test_nanxi_station_accounts_are_provisioned_for_both_days(self):
        for race_id in ('nanxi-race-20260919', 'nanxi-race-20260920'):
            auth = self.request_json('/api/judge-auth', {
                'raceId': race_id,
                'username': 'station_1',
                'password': 'station1',
            })
            self.assertEqual(auth['role'], 'station_1')
            self.assertEqual(auth['allowedCheckpoints'], ['STATION_2_START'])
            finish = self.request_json('/api/judge-auth', {
                'raceId': race_id,
                'username': 'station_8',
                'password': 'station8',
            })
            self.assertEqual(finish['allowedCheckpoints'], ['END'])

    def test_delete_nanxi_test_data_removes_only_generated_records(self):
        test_entry = self.register('A-001', card='NANXI-TEST-A-001')
        normal_entry = self.register('A-002', card='NANXI-LIVE-A-002')
        self.checkpoint(test_entry, 0)
        self.checkpoint(normal_entry, 0)
        deleted = self.request_json('/api/delete-nanxi-test-data', {
            'raceId': 'nanxi-race-20260919',
            'confirmation': 'DELETE_NANXI_TEST_DATA',
            'adminCode': 'test-clear-code-1234',
        })
        self.assertEqual(deleted['deleted']['participants'], 1)
        participants = self.request_json('/api/participants?raceId=nanxi-race-20260919')['participants']
        self.assertEqual([row['card_code'] for row in participants], ['NANXI-LIVE-A-002'])
        events = self.request_json('/api/timing-events?raceId=nanxi-race-20260919')['events']
        self.assertEqual([row['card_code'] for row in events], ['NANXI-LIVE-A-002'])


if __name__ == '__main__': unittest.main()
