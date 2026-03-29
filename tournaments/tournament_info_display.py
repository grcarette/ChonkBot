import discord

from utils.discord_preset_colors import get_random_color
from utils.color_utils import discord_color_from_hex
from utils.get_bracket_link import get_bracket_link
from utils.embed_utils import create_stage_embed

from ui.config_control.info_display import InfoDisplayView
from ui.link_view import LinkView

from handlers.image_handler import ImageHandler


class TournamentInfoDisplay:
    def __init__(self, tournament_control):
        self.tc = tournament_control
        self.tm = self.tc.tm
        self.dh = self.tm.bot.dh
        self.message = None
        self.info_display_view = None
        self.image_handler = ImageHandler()

    async def initialize_display(self):
        self.info_display_view = InfoDisplayView(self)
        self.message = await self.get_display_message()

        if self.message is None:
            channel = await self.tm.get_channel('event-info')
            embed = await self.generate_embed()
            self.message = await channel.send(view=self.info_display_view, embed=embed)

            if self.tm.format and self.tm.format.shows_bracket_link and 'challonge_data' in self.tm.tournament:
                bracket_url = await get_bracket_link(self.tm.tournament['challonge_data']['url'])
                await self.add_link(link_label="Bracket", link_url=bracket_url)
        else:
            for component in self.message.components:
                for item in component.children:
                    if isinstance(item, discord.Button):
                        if item.style == discord.ButtonStyle.link:
                            await self.add_link(item.label, item.url)

        await self.update_display()
        await self.post_stages()

    async def update_display(self):
        embed = await self.generate_embed()
        await self.message.edit(view=self.info_display_view, embed=embed)

    async def update_entrants(self):
        """
        Called by TournamentManager whenever a player registers or unregisters.
        Re-renders the full embed (which includes the entrant list if enabled).
        """
        tournament = await self.tm.get_tournament()
        if not tournament.get('config', {}).get('display_entrants'):
            return
        await self.update_display()

    async def generate_embed(self) -> discord.Embed:
        tournament = await self.tm.get_tournament()
        if 'color' in tournament.get('config', {}):
            color = discord_color_from_hex(tournament['config']['color'])
        else:
            color = get_random_color()

        organizer_list = []
        for user_id in tournament['organizers']:
            user = discord.utils.get(self.tm.guild.members, id=user_id)
            if user:
                organizer_list.append(user.mention)
        organizer_str = "\n-".join(organizer_list) if organizer_list else "N/A"

        description = (
            f"**Date:** {tournament['date']}\n"
            f"**Format:** {tournament['format']}\n"
        )
        if tournament['format'] == 'swiss':
            description += f"**Rounds:** {tournament.get('round_limit', 8)}\n"

        description += f"**TO's:**\n-{organizer_str}\n"

        # ── Entrant list ──────────────────────────────────────────────────────
        if tournament.get('config', {}).get('display_entrants'):
            entrant_str = await self._build_entrant_list(tournament)
            entrant_count = len(tournament.get('entrants', {}))
            description += f"\n**Entrants ({entrant_count}):**\n{entrant_str}"

        embed = discord.Embed(
            title=f"{tournament['name']}",
            description=description,
            color=color
        )
        return embed

    async def _build_entrant_list(self, tournament) -> str:
        """
        Build a newline-separated list of entrant display names.

        For DE/SE: ordered by Challonge seed (requires an API call).
        For Swiss: ordered by registration order (entrants dict key order).

        Falls back to registration order if the Challonge call fails.
        """
        entrants = tournament.get('entrants', {})
        if not entrants:
            return '*No entrants yet.*'

        ordered_ids = await self._get_ordered_discord_ids(tournament, entrants)

        max_chars = 900  # leave room for the rest of the embed description
        total = len(ordered_ids)
        lines = []
        used = 0

        cap = 50
        for i, discord_id in enumerate(ordered_ids, start=1):
            if i > cap:
                lines.append(f'*... and {total - cap} more*')
                break
            try:
                user = await self.dh.get_user(user_id=int(discord_id))
                name = user['name'] if user else f'Unknown ({discord_id})'
            except Exception:
                name = f'Unknown ({discord_id})'

            line = f"{i}. {name}"
            remaining = total - i
            suffix = f"\n*... and {remaining} more*" if remaining > 0 else ''
            cost = len(line) + (1 if lines else 0)

            if used + cost + len(suffix) > max_chars:
                lines.append(f'*... and {remaining + 1} more*')
                break
            lines.append(line)
            used += cost

        return '\n'.join(lines) if lines else '*No entrants yet.*'

    async def _get_ordered_discord_ids(self, tournament, entrants) -> list[str]:
        """
        Return discord_ids ordered by seed for DE/SE, or by registration
        order for Swiss. Falls back to registration order on any error.
        """
        # Swiss: no seeding, just use insertion order
        if not (self.tm.format and self.tm.format.shows_bracket_link):
            return list(entrants.keys())

        # DE/SE: fetch seeds from Challonge
        if 'challonge_data' not in tournament:
            return list(entrants.keys())

        try:
            participants = await self.tm.ch.get_participants(
                tournament['challonge_data']['url']
            )
            # Sort by seed, pushing unseeded players to the end
            participants_sorted = sorted(
                participants, key=lambda p: p.get('seed') or 9999
            )
            # Build reverse map: challonge_id → discord_id
            challonge_to_discord = {
                str(challonge_id): str(discord_id)
                for discord_id, challonge_id in entrants.items()
            }
            ordered = []
            for p in participants_sorted:
                discord_id = challonge_to_discord.get(str(p['id']))
                if discord_id:
                    ordered.append(discord_id)
            # Append any discord_ids not found in Challonge response
            seen = set(ordered)
            for discord_id in entrants.keys():
                if discord_id not in seen:
                    ordered.append(discord_id)
            return ordered
        except Exception as e:
            print(f"[TournamentInfoDisplay] Failed to fetch Challonge seeds: {e}")
            return list(entrants.keys())

    async def post_stages(self):
        tournament = await self.tm.get_tournament()
        channel = await self.tm.get_channel('stagelist')
        if not channel:
            return
        if not tournament.get('stagelist'):
            return
        for stage_code in tournament['stagelist']:
            stage = await self.dh.get_stage(code=stage_code)
            if stage:
                embed = await create_stage_embed(stage)
                await channel.send(embed=embed)

    async def add_link(self, link_label, link_url):
        self.info_display_view.add_item(
            discord.ui.Button(label=link_label, url=link_url, style=discord.ButtonStyle.link)
        )

    async def get_display_message(self):
        channel = await self.tm.get_channel('event-info')
        if not channel:
            return None
        bot_id = self.tm.bot.id
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id == bot_id and message.embeds:
                return message
        return None