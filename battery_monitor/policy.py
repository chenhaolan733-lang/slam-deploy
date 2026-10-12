"""Pure battery alarm policy; no ROS, playback, or hardware access."""
import math
import time


class Policy:
    def __init__(self, threshold=20):
        self.threshold = threshold
        self.latched = set()
        self.batteries = []
        self.last_received = None

    def update(self, message, now, wall_time=None):
        if message.get('schema') != 1 or message.get('event') != 'battery':
            raise ValueError('unsupported telemetry')
        age = message.get('source_age_seconds')
        if type(age) not in (int, float) or not math.isfinite(age) or not -2 <= age <= 5:
            raise ValueError('stale/invalid source timestamp')
        sent = message.get('sent_unix')
        wall_time = time.time() if wall_time is None else wall_time
        if type(sent) not in (int, float) or not math.isfinite(sent) or not -2 <= wall_time - sent <= 5:
            raise ValueError('stale transport data or robot/chassis clocks not synchronized')
        rows = message.get('batteries')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 16:
            raise ValueError('missing battery data')
        seen = set()
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('invalid battery row')
            ident, energy = row.get('id'), row.get('energy')
            if type(ident) is not int or not 0 <= ident <= 255 or ident in seen:
                raise ValueError('invalid/duplicate battery id')
            seen.add(ident)
            if type(energy) not in (int, float) or not math.isfinite(energy) or not 0 <= energy <= 100:
                raise ValueError('invalid energy percentage')
            for key in ('is_in_place', 'is_connected', 'is_charging'):
                if type(row.get(key)) is not bool:
                    raise ValueError('invalid boolean: ' + key)
            if type(row.get('error_code')) is not int or row['error_code'] < 0:
                raise ValueError('invalid error code')
            valid.append(dict(row))
        # Only mutate state once the full message passes validation.
        for row in valid:
            healthy = row['is_in_place'] and row['is_connected'] and row['error_code'] == 0
            if not healthy:
                continue
            if row['is_charging']:
                self.latched.discard(row['id'])
            elif row['energy'] < self.threshold:
                self.latched.add(row['id'])
        self.batteries = valid
        self.last_received = now

    def snapshot(self, now, stale_after=5):
        age = None if self.last_received is None else now - self.last_received
        fresh = age is not None and 0 <= age <= stale_after
        alarming = []
        faults = []
        for row in self.batteries:
            if not row['is_in_place'] or not row['is_connected'] or row['error_code'] != 0:
                faults.append(row['id'])
            elif fresh and row['id'] in self.latched and not row['is_charging']:
                alarming.append(row['id'])
        return {'state': 'NO_DATA' if not fresh else ('LOW_BATTERY' if alarming else ('BATTERY_FAULT' if faults else 'OK')),
                'data_age_seconds': None if age is None else round(age, 3),
                'alarming_ids': alarming, 'fault_ids': faults,
                'latched_ids': sorted(self.latched), 'batteries': self.batteries}

    def disconnect(self):
        self.last_received = None
