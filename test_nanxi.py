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

    def test_nine_stations_can_mix_inputs_and_handle_simultaneous_confirmation(self):
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
        for index in range(2,10): self.assertEqual(self.checkpoint(entry,index,'manual' if index%2 else 'nfc')['status'],'accepted')
        result=self.request_json('/api/leaderboard?raceId='+entry['race_id'])['leaderboard'][0]
        self.assertEqual(result['elapsedMs'],2700000)
        self.assertEqual(result['categoryRank'],1)
        self.assertEqual(len(result['stationSplits']),9)
        self.assertTrue(all(ms==300000 for ms in result['stationSplits'].values()))

    def test_relay_deduction_penalty_and_independent_ranks(self):
        entries=[self.register('F-001',0),self.register('F-002',1),self.register('G-001',3),self.register('G-002',4)]
        for entry in entries:
            for index in range(10): self.checkpoint(entry,index)
        self.request_json('/api/result-adjustments',{'raceId':entries[1]['race_id'],'participantId':entries[1]['id'],'adjustmentSeconds':60,'reason':'罚时','adminCode':'test-clear-code-1234'})
        result={row['bibNumber']:row for row in self.request_json('/api/leaderboard?raceId='+entries[0]['race_id'])['leaderboard']}
        self.assertEqual(result['F-002']['elapsedMs'],2460000)
        self.assertEqual(result['F-002']['deductionMs'],300000)
        self.assertEqual(result['F-002']['penaltyMs'],60000)
        self.assertEqual(result['F-002']['categoryRank'],1)
        self.assertEqual(result['F-001']['categoryRank'],2)
        self.assertEqual(result['G-001']['deductionMs'],600000)
        self.assertEqual(result['G-001']['categoryRank'],1)
        self.assertEqual(result['G-002']['categoryRank'],1)

    def test_manual_results_rank_by_final_time_and_unfinished_have_no_rank(self):
        a=self.register('A-001'); b=self.register('A-002'); self.register('B-001')
        for index in range(10):self.checkpoint(a,index)
        self.request_json('/api/manual-results',{'raceId':b['race_id'],'participantId':b['id'],'entryMode':'elapsed','elapsedSeconds':1200,'reason':'备用计时','adminCode':'test-clear-code-1234'})
        results={row['bibNumber']:row for row in self.request_json('/api/leaderboard?raceId='+a['race_id'])['leaderboard']}
        self.assertEqual(results['A-002']['categoryRank'],1)
        self.assertEqual(results['A-001']['categoryRank'],2)
        self.assertIsNone(results['B-001']['categoryRank'])

    def test_station_roles_and_custom_count_persist(self):
        profile=server.get_race_profile('nanxi-race-20260919')
        self.assertEqual(server.judge_role_checkpoints(profile,'station_9'),['END'])
        self.assertEqual(server.judge_role_checkpoints(profile,'station_10'),[])
        profile['station_count']=10;profile['checkpoints']=server.build_station_boundary_checkpoints(10)
        server.save_race_profile(profile);server.init_db()
        self.assertEqual(server.get_race_profile(profile['race_id'])['station_count'],10)


if __name__ == '__main__': unittest.main()
