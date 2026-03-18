import discord
import re
import aiohttp
from io import BytesIO

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

            # Only add bracket link for non-swiss events
            if not self.tm.is_swiss and 'challonge_data' in self.tm.tournament:
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

    async def generate_embed(self):
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

        embed = discord.Embed(
            title=f"{tournament['name']}",
            description=description,
            color=color
        )
        return embed

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