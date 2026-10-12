from analytics.database import get_connection


def initialize_guardian_storage():
    connection = get_connection()

    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guardian_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                incident_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                message_excerpt TEXT NOT NULL DEFAULT '',
                message_url TEXT NOT NULL DEFAULT '',
                violation_count INTEGER NOT NULL DEFAULT 0,
                deletion_status TEXT NOT NULL DEFAULT 'Not attempted',
                status TEXT NOT NULL DEFAULT 'open',
                detected_at REAL NOT NULL,
                resolved_at REAL
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_guardian_incidents_guild_detected
            ON guardian_incidents (guild_id, detected_at)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_guardian_incidents_member
            ON guardian_incidents (guild_id, user_id, detected_at)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guardian_violations (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                violation_count INTEGER NOT NULL DEFAULT 0,
                last_violation REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )

        connection.commit()

    finally:
        connection.close()


def record_guardian_incident(
    guild_id,
    user_id,
    channel_id,
    message_id,
    incident_type,
    reason,
    message_excerpt,
    message_url,
    violation_count,
    deletion_status,
    detected_at,
):
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO guardian_incidents (
                guild_id,
                user_id,
                channel_id,
                message_id,
                incident_type,
                reason,
                message_excerpt,
                message_url,
                violation_count,
                deletion_status,
                status,
                detected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                guild_id,
                user_id,
                channel_id,
                message_id,
                incident_type,
                reason,
                message_excerpt[:500],
                message_url,
                violation_count,
                deletion_status,
                detected_at,
            ),
        )

        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def get_guardian_incidents(guild_id, limit=25):
    safe_limit = max(1, min(int(limit), 100))
    connection = get_connection()

    try:
        return connection.execute(
            """
            SELECT *
            FROM guardian_incidents
            WHERE guild_id = ?
            ORDER BY detected_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, safe_limit),
        ).fetchall()

    finally:
        connection.close()


def resolve_guardian_incident(incident_id, guild_id):
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE guardian_incidents
            SET status = 'resolved',
                resolved_at = ?
            WHERE id = ?
              AND guild_id = ?
              AND status = 'open'
            """,
            (
                __import__("time").time(),
                incident_id,
                guild_id,
            ),
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()