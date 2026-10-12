
import time
from collections import defaultdict


VIOLATION_DECAY_SECONDS = 10 * 60


class ViolationTracker:
    def __init__(self):
        self.violations = defaultdict(dict)

    def _get_record(self, guild_id, user_id):
        guild_records = self.violations.get(guild_id)

        if guild_records is None:
            return None

        return guild_records.get(user_id)

    def _apply_decay(self, guild_id, user_id):
        record = self._get_record(guild_id, user_id)

        if record is None:
            return

        count = record["count"]
        last_violation = record["last_violation"]

        if count <= 0 or last_violation <= 0:
            return

        elapsed = time.time() - last_violation
        decay_amount = int(elapsed // VIOLATION_DECAY_SECONDS)

        if decay_amount <= 0:
            return

        new_count = max(0, count - decay_amount)

        if new_count == 0:
            self.reset_user(guild_id, user_id)
            return

        record["count"] = new_count
        record["last_violation"] += (
            decay_amount * VIOLATION_DECAY_SECONDS
        )

    def add_violation(self, guild_id, user_id):
        self._apply_decay(guild_id, user_id)

        guild_records = self.violations[guild_id]
        record = guild_records.get(user_id)

        if record is None:
            record = {
                "count": 0,
                "last_violation": 0.0,
            }
            guild_records[user_id] = record

        record["count"] += 1
        record["last_violation"] = time.time()

        return record["count"]

    def get_violations(self, guild_id, user_id):
        self._apply_decay(guild_id, user_id)

        record = self._get_record(guild_id, user_id)

        if record is None:
            return 0

        return record["count"]

    def reset_user(self, guild_id, user_id):
        guild_records = self.violations.get(guild_id)

        if guild_records is None:
            return

        guild_records.pop(user_id, None)

        if not guild_records:
            self.violations.pop(guild_id, None)

    def reset_guild(self, guild_id):
        self.violations.pop(guild_id, None)


violation_tracker = ViolationTracker()
