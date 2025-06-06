import discord
import re
import aiohttp
from io import BytesIO

from utils.discord_preset_colors import get_random_color
from utils.color_utils import discord_color_from_hex

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
        if self.message == None:
            channel = await self.tm.get_channel('event-info')
            embed = await self.generate_embed()
            self.message = await channel.send(view=self.info_display_view, embed=embed)
        for component in self.message.components:
            for item in component.children:
                if isinstance(item, discord.Button):
                    if item.style == discord.ButtonStyle.link:
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
        
        organizer_list = []
        for user_id in tournament['organizers']:
            user = discord.utils.get(self.tm.guild.members, id=user_id)
            organizer_list.append(user.mention)
        organizer_list = "\n-".join(organizer_list)
        description = (
            f"**Date: **{tournament['date']}\n"
            f"**Format: **{tournament['format']}\n"
            f"**TO's:**\n-{organizer_list}\n"
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
    
    async def post_stages(self):
        tournament = await self.tm.get_tournament()
        channel = await self.tm.get_channel('stagelist')
        
        for stage_code in tournament['stagelist']:
            stage = await self.dh.get_stage(code=stage_code)
            
            if stage:
                description = (
                    f"Creator: {stage['creator']}\n"
                    f"Code: {stage['code']}\n"
                )
                embed = discord.Embed(
                    title=f"{stage['name']}",
                    description=description,
                    color=get_random_color()
                )
                
                image_path = self.image_handler.retrieve_image(stage['code'], stage['imgur'])
                attachment_filename = f"{stage['code']}.jpg"
                with open(image_path, 'rb') as image_file:
                    file = discord.File(image_file, filename=attachment_filename)
                    embed.set_image(url=f"attachment://{attachment_filename}")
                
                    await channel.send(embed=embed, file=file)
                
