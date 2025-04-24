import discord
from utils.discord_preset_colors import get_random_color
from utils.color_utils import discord_color_from_hex

from ui.config_control.info_display import InfoDisplayView
from ui.link_view import LinkView

class TournamentInfoDisplay:
    def __init__(self, tournament_control):
        self.tc = tournament_control
        self.tm = self.tc.tm
        self.message = None
        self.info_display_view = None
    
    async def initialize_display(self):
        self.info_display_view = InfoDisplayView(self)
        self.message = await self.get_display_message()
        if self.message == None:
            channel = await self.tm.get_channel('event-info')
            embed = await self.generate_embed()
            self.message = await channel.send(view=self.info_display_view, embed=embed)
        for component in self.message.components:
            for item in component.children:
                print(item)
                if isinstance(item, discord.Button):
                    print('yee')
                    if item.style == discord.ButtonStyle.link:
                        print('yeahhh')
                        await self.add_link(item.label, item.url)
        await self.update_display()
    
    async def update_display(self):
        embed = await self.generate_embed()
        await self.message.edit(view=self.info_display_view, embed=embed)
    
    async def generate_embed(self):
        tournament = await self.tm.get_tournament()
        if 'color' in tournament['config']:
            color = discord_color_from_hex(tournament['config']['color'])
        else:
            color = get_random_color()
        description = (
            f"**Date: **{tournament['date']}\n"
            f"**Format: **{tournament['format']}\n"
            f"**Organized By: **{tournament['organizer']}\n"
        )
        embed = discord.Embed(
            title=f"{tournament['name']}",
            description=description,
            color=color
        )
        return embed
    
    async def add_link(self, link_label, link_url):
        channel = await self.tm.get_channel('event-info')
        await self.info_display_view.add_link(link_label, link_url)
        await self.update_display()
    
    async def get_display_message(self):
        channel = await self.tm.get_channel('event-info')
        bot_id = self.tm.bot.id
        tournament = await self.tm.get_tournament()
        
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id == bot_id and message.embeds:
                embed = message.embeds[0]
                if tournament['name'] in embed.title:
                    return message
            
        return None