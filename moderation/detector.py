
import re
import time
from collections import defaultdict, deque


class SpamDetector:
    def __init__(
        self,
        max_messages=5,
        time_window=5,
        duplicate_limit=3,
        incident_cooldown=5,
    ):
        self.max_messages = max_messages
        self.time_window = time_window
        self.duplicate_limit = duplicate_limit
        self.incident_cooldown = incident_cooldown
        self.message_history = defaultdict(deque)
        self.duplicate_history = defaultdict(deque)
        self.active_incidents = {}
        self.last_message_time = {}

    def _normalize_content(self, content):
        normalized = content.casefold().strip()
        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = " ".join(normalized.split())

        if normalized:
            return normalized

        return " ".join(content.casefold().split())

    def check_message(self, guild_id, user_id, content):
        now = time.time()
        key = (guild_id, user_id)

        last_message = self.last_message_time.get(key)

        if (
            last_message is not None
            and now - last_message > self.incident_cooldown
        ):
            self.active_incidents.pop(key, None)

        self.last_message_time[key] = now

        history = self.message_history[key]

        while history and now - history[0] > self.time_window:
            history.popleft()

        history.append(now)

        duplicate_history = self.duplicate_history[key]

        while (
            duplicate_history
            and now - duplicate_history[0][0] > self.time_window
        ):
            duplicate_history.popleft()

        normalized_content = self._normalize_content(content)
        duplicate_history.append((now, normalized_content))

        duplicate_count = sum(
            1
            for _, previous_content in duplicate_history
            if previous_content == normalized_content
        )

        message_flood = len(history) >= self.max_messages
        duplicate_message = duplicate_count >= self.duplicate_limit

        if not message_flood and not duplicate_message:
            return {
                "is_spam": False,
                "type": None,
                "reason": None,
                "new_incident": False,
                "message_count": len(history),
                "duplicate_count": duplicate_count,
            }

        if message_flood:
            incident_type = "message_flood"
            reason = (
                f"User sent {len(history)} messages "
                f"within {self.time_window} seconds."
            )
        else:
            incident_type = "duplicate_message"
            reason = (
                "User sent the same normalized message "
                f"{duplicate_count} times within "
                f"{self.time_window} seconds."
            )

        new_incident = key not in self.active_incidents
        self.active_incidents[key] = now

        return {
            "is_spam": True,
            "type": incident_type,
            "reason": reason,
            "new_incident": new_incident,
            "message_count": len(history),
            "duplicate_count": duplicate_count,
        }

    def reset_user(self, guild_id, user_id):
        key = (guild_id, user_id)

        self.message_history.pop(key, None)
        self.duplicate_history.pop(key, None)
        self.active_incidents.pop(key, None)
        self.last_message_time.pop(key, None)
