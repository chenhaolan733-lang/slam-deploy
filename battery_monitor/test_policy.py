import copy
import unittest
from policy import Policy


def message(energy=19, charging=False, ident=1):
    return {'schema': 1, 'event': 'battery', 'source_age_seconds': 0.1, 'sent_unix': 1000,
            'batteries': [{'id': ident, 'energy': energy, 'is_charging': charging,
                           'is_in_place': True, 'is_connected': True, 'error_code': 0}]}


class Tests(unittest.TestCase):
    def setUp(self):
        self.p = Policy()

    def update(self, msg, now=1):
        self.p.update(msg, now, wall_time=1000)
        return self.p.snapshot(now)

    def test_low(self):
        self.assertEqual(self.update(message())['alarming_ids'], [1])

    def test_threshold_exclusive(self):
        self.assertEqual(self.update(message(20))['alarming_ids'], [])

    def test_current_live_values(self):
        msg = message(34)
        msg['batteries'] += message(27, ident=2)['batteries']
        self.assertEqual(self.update(msg)['state'], 'OK')

    def test_charging_suppresses(self):
        self.assertEqual(self.update(message(1, True))['alarming_ids'], [])

    def test_charge_clears_latch(self):
        self.update(message())
        self.assertEqual(self.update(message(19, True))['latched_ids'], [])

    def test_unplug_below_threshold_rearms(self):
        self.update(message(10, True))
        self.assertEqual(self.update(message(10, False))['alarming_ids'], [1])

    def test_latch_until_charge_despite_energy_bounce(self):
        self.update(message())
        self.assertEqual(self.update(message(20))['alarming_ids'], [1])

    def test_two_packs_charge_one_other_continues(self):
        msg = message()
        msg['batteries'] += message(10, ident=2)['batteries']
        self.update(msg)
        msg['batteries'][0]['is_charging'] = True
        self.assertEqual(self.update(msg)['alarming_ids'], [2])

    def test_missing_disconnected_fault_not_low(self):
        for key, value in [('is_in_place', False), ('is_connected', False), ('error_code', 42)]:
            with self.subTest(key=key):
                msg = message(0)
                msg['batteries'][0][key] = value
                self.assertEqual(self.update(msg)['state'], 'BATTERY_FAULT')

    def test_missing_pack_does_not_keep_playing(self):
        self.update(message())
        self.assertEqual(self.update(message(90, ident=2))['alarming_ids'], [])

    def test_stale_stops_and_recovery_resumes(self):
        self.update(message())
        self.assertEqual(self.p.snapshot(7)['state'], 'NO_DATA')
        self.assertEqual(self.p.snapshot(7)['alarming_ids'], [])
        self.assertEqual(self.update(message(), 8)['alarming_ids'], [1])

    def test_disconnect(self):
        self.update(message())
        self.p.disconnect()
        self.assertEqual(self.p.snapshot(2)['state'], 'NO_DATA')

    def test_invalid_energy(self):
        for value in [None, -1, 101, True, '19', float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.update(message(value))

    def test_invalid_bool(self):
        for value in ['false', 'true', 0, 1, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.update(message(charging=value))

    def test_duplicate_ids(self):
        msg = message()
        msg['batteries'] *= 2
        with self.assertRaises(ValueError):
            self.update(msg)

    def test_stale_source(self):
        msg = message()
        msg['source_age_seconds'] = 20
        with self.assertRaises(ValueError):
            self.update(msg)

    def test_delayed_transport_and_clock_skew(self):
        for sent in [980, 1020, None, '1000']:
            msg = message()
            msg['sent_unix'] = sent
            with self.subTest(sent=sent), self.assertRaises(ValueError):
                self.update(msg)

    def test_invalid_message_does_not_partially_change_state(self):
        self.update(message())
        msg = message(19, True)
        msg['batteries'] += message(None, ident=2)['batteries']
        with self.assertRaises(ValueError):
            self.update(msg)
        self.assertEqual(self.p.snapshot(1)['alarming_ids'], [1])


if __name__ == '__main__':
    unittest.main()
