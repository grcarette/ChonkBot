import asyncio
import discord
from utils.emojis import INDICATOR_EMOJIS

# Maximum number of individual mentions to show before truncating.
# Discord embed descriptions have a 4096-char limit; with ~22 chars per mention
# this cap keeps the embed readable and comfortably inside that limit.
_MENTION_CAP = 20
_MAX_MENTION_CHARS = 800  # budget for the mention block itself


class EventCheckinView(discord.ui.View):
    """
    Event-level check-in view posted to event-info before the bracket phase
    starts in a Swiss Filter event.  All players — regardless of which bracket
    they will end up in — check in here together.

    When every registered player has checked in (or a TO overrides), the view
    calls ``em.transition_to_brackets()`` to distribute players and start the
    bracket phase.
    """

    def __init__(self, em, pending_ids: list[str], timeout=None):
        super().__init__(timeout=timeout)
        self.em = em
        # Ordered list so the embed is stable across edits
        self.pending_ids: list[str] = list(pending_ids)
        self._pending_set: set[str] = set(pending_ids)
        self.checked_in: set[str] = set()
        self._lock = asyncio.Lock()
        self._ended = False

        btn = discord.ui.Button(
            label='Check in',
            style=discord.ButtonStyle.success,
            custom_id='event-checkin',
        )
        btn.callback = self.check_in
        self.add_item(btn)

    # ── Button callback ───────────────────────────────────────────────────────

    async def check_in(self, interaction: discord.Interaction):
        async with self._lock:
            if self._ended:
                await interaction.response.send_message(
                    'Check-in is already complete!', ephemeral=True
                )
                return

            user_id = str(interaction.user.id)
            is_to = self._is_to(interaction.user)

            if is_to:
                # TO override: mark all remaining players as checked in
                for pid in self.pending_ids:
                    self.checked_in.add(pid)
            else:
                if user_id not in self._pending_set:
                    await interaction.response.send_message(
                        "You're not registered for this event!", ephemeral=True
                    )
                    return
                if user_id in self.checked_in:
                    await interaction.response.send_message(
                        "You've already checked in!", ephemeral=True
                    )
                    return
                self.checked_in.add(user_id)

            all_done = len(self.checked_in) >= len(self.pending_ids)
            if all_done:
                self._ended = True

            embed = self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)

        # Outside the lock — only one coroutine reaches here because of _ended
        if all_done:
            self.stop()
            await interaction.message.delete()
            await self.em.transition_to_brackets()

    # ── Embed ─────────────────────────────────────────────────────────────────

    def generate_embed(self) -> discord.Embed:
        remaining = [pid for pid in self.pending_ids if pid not in self.checked_in]
        total_remaining = len(remaining)
        total = len(self.pending_ids)

        if not remaining:
            description = f"{INDICATOR_EMOJIS['green_check']} All players have checked in!"
        else:
            header = (
                'Click the button below to check in for the bracket phase.\n\n'
                'Players yet to check in:\n'
            )
            mention_block = self._build_mention_block(remaining)
            description = header + mention_block

        embed = discord.Embed(
            title='Bracket Phase Check-In',
            description=description,
            color=discord.Color.green(),
        )
        embed.set_footer(text=f'{total - total_remaining}/{total} checked in')
        return embed

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_mention_block(self, remaining: list[str]) -> str:
        """
        Build a newline-separated list of <@mention> strings, truncating with
        '... and X more' when the list exceeds _MENTION_CAP entries or the
        character budget.  Mirrors the pattern used in the event-info embed.
        """
        total = len(remaining)
        lines: list[str] = []
        used = 0

        for i, pid in enumerate(remaining):
            if i >= _MENTION_CAP:
                lines.append(f'*... and {total - i} more*')
                break

            mention = f'<@{pid}>'
            remaining_after = total - i - 1
            suffix = f'\n*... and {remaining_after} more*' if remaining_after > 0 else ''
            cost = len(mention) + (1 if lines else 0)  # +1 for the newline separator

            if used + cost + len(suffix) > _MAX_MENTION_CHARS:
                lines.append(f'*... and {total - i} more*')
                break

            lines.append(mention)
            used += cost

        return '\n'.join(lines)

    def _is_to(self, user: discord.Member) -> bool:
        """Return True if the interacting user has the event's TO role."""
        role_name = f"{self.em.event['name']} TO"
        to_role = discord.utils.get(self.em.guild.roles, name=role_name)
        if to_role is None:
            return False
        return to_role in user.roles
