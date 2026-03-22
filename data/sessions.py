from datetime import datetime, timezone


class SessionMethodsMixin:
    """
    MongoDB mixin for session management.
    Expects self.session_collection to be set by the DataHandler.
    """

    async def create_session(
        self,
        token: str,
        discord_user_id: int,
        discord_username: str,
        avatar: str | None,
        expires_at: datetime,
    ) -> None:
        """Insert a new session document."""
        await self.session_collection.insert_one({
            'token': token,
            'discord_user_id': discord_user_id,
            'discord_username': discord_username,
            'avatar': avatar,
            'expires_at': expires_at,
            'created_at': datetime.now(timezone.utc),
        })

    async def get_session(self, token: str) -> dict | None:
        """Return the session document for a given token, or None."""
        return await self.session_collection.find_one({'token': token})

    async def delete_session(self, token: str) -> None:
        """Delete a session by token (logout)."""
        await self.session_collection.delete_one({'token': token})

    async def delete_expired_sessions(self) -> int:
        """Remove all expired sessions. Returns the count deleted."""
        result = await self.session_collection.delete_many({
            'expires_at': {'$lt': datetime.now(timezone.utc)}
        })
        return result.deleted_count