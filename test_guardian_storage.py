
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics.database as database

from analytics.guardian_storage import (
    get_guardian_incidents,
    initialize_guardian_storage,
    record_guardian_incident,
    resolve_guardian_incident,
)
from moderation.violations import ViolationTracker


class TestGuardianStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.database_patch = patch.object(
            database,
            "DATABASE_PATH",
            self.database_path,
        )
        self.database_patch.start()

        initialize_guardian_storage()
        self.tracker = ViolationTracker()

    def tearDown(self):
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_violations_survive_tracker_restart(self):
        count = self.tracker.add_violation(100, 200)
        self.assertEqual(count, 1)

        restarted_tracker = ViolationTracker()

        self.assertEqual(
            restarted_tracker.get_violations(100, 200),
            1,
        )

    def test_violations_are_isolated_by_server(self):
        self.tracker.add_violation(100, 200)
        self.tracker.add_violation(300, 200)

        self.assertEqual(self.tracker.get_violations(100, 200), 1)
        self.assertEqual(self.tracker.get_violations(300, 200), 1)

        self.tracker.reset_user(100, 200)

        self.assertEqual(self.tracker.get_violations(100, 200), 0)
        self.assertEqual(self.tracker.get_violations(300, 200), 1)

    def test_old_violations_decay(self):
        self.tracker.add_violation(100, 200)
        self.tracker.add_violation(100, 200)

        connection = database.get_connection()

        try:
            connection.execute(
                """
                UPDATE guardian_violations
                SET last_violation = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (time.time() - 1201, 100, 200),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(self.tracker.get_violations(100, 200), 0)

    def test_incident_is_persisted_and_server_scoped(self):
        incident_id = record_guardian_incident(
            guild_id=100,
            user_id=200,
            channel_id=300,
            message_id=400,
            incident_type="duplicate_message",
            reason="Repeated messages",
            message_excerpt="Test message",
            message_url="https://discord.com/channels/100/300/400",
            violation_count=1,
            deletion_status="Success",
            detected_at=time.time(),
        )

        incidents = get_guardian_incidents(100)

        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["id"], incident_id)
        self.assertEqual(incidents[0]["user_id"], 200)
        self.assertEqual(get_guardian_incidents(999), [])

    def test_incident_can_be_resolved(self):
        incident_id = record_guardian_incident(
            guild_id=100,
            user_id=200,
            channel_id=300,
            message_id=400,
            incident_type="message_flood",
            reason="Too many messages",
            message_excerpt="Test",
            message_url="https://discord.com/channels/100/300/400",
            violation_count=1,
            deletion_status="Success",
            detected_at=time.time(),
        )

        self.assertTrue(resolve_guardian_incident(incident_id, 100))
        self.assertFalse(resolve_guardian_incident(incident_id, 100))
        self.assertFalse(resolve_guardian_incident(incident_id, 999))


if __name__ == "__main__":
    unittest.main()
