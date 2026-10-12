import time

from analytics.database import get_connection
from analytics.guardian_storage import initialize_guardian_storage


VIOLATION_DECAY_SECONDS = 10 * 60


class ViolationTracker:
    def __init__(self):
        initialize_guardian_storage()

    def _apply_decay(self, guild_id, user_id):
        now = time.time()
        connection = get_connection()

        try:
            row = connection.execute(
                """
                SELECT violation_count, last_violation
                FROM guardian_violations
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()

            if row is None:
                return 0

            count = row["violation_count"]
            last_violation = row["last_violation"]

            if count <= 0 or last_violation <= 0:
                connection.execute(
                    """
                    DELETE FROM guardian_violations
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                )
                connection.commit()
                return 0

            decay_amount = int(
                (now - last_violation) // VIOLATION_DECAY_SECONDS
            )

            if decay_amount <= 0:
                return count

            new_count = max(0, count - decay_amount)

            if new_count == 0:
                connection.execute(
                    """
                    DELETE FROM guardian_violations
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                )
                connection.commit()
                return 0

            connection.execute(
                """
                UPDATE guardian_violations
                SET violation_count = ?,
                    last_violation = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    new_count,
                    last_violation
                    + decay_amount * VIOLATION_DECAY_SECONDS,
                    guild_id,
                    user_id,
                ),
            )

            connection.commit()
            return new_count

        finally:
            connection.close()

    def add_violation(self, guild_id, user_id):
        self._apply_decay(guild_id, user_id)

        now = time.time()
        connection = get_connection()

        try:
            connection.execute(
                """
                INSERT INTO guardian_violations (
                    guild_id,
                    user_id,
                    violation_count,
                    last_violation
                )
                VALUES (?, ?, 1, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET
                    violation_count =
                        guardian_violations.violation_count + 1,
                    last_violation = excluded.last_violation
                """,
                (guild_id, user_id, now),
            )

            connection.commit()

            row = connection.execute(
                """
                SELECT violation_count
                FROM guardian_violations
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()

            return row["violation_count"]

        finally:
            connection.close()

    def get_violations(self, guild_id, user_id):
        return self._apply_decay(guild_id, user_id)

    def reset_user(self, guild_id, user_id):
        connection = get_connection()

        try:
            connection.execute(
                """
                DELETE FROM guardian_violations
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            connection.commit()

        finally:
            connection.close()

    def reset_guild(self, guild_id):
        connection = get_connection()

        try:
            connection.execute(
                """
                DELETE FROM guardian_violations
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            connection.commit()

        finally:
            connection.close()


violation_tracker = ViolationTracker()