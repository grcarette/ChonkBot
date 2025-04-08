import discord

from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.reaction_flags import *
from utils.errors import UserNotFoundError

from ui.random_level import LevelRatingView, LevelRatingButton

LEVEL_SHARING_CHANNEL_ID = 1357434250034675895

class MessageHandler:
    def __init__(self, bot):
        self.bot = bot
        
    async def send_level_message(self, level_data, interaction, add_rating=False):
        message_content = await self.get_level_message(level_data)
        user = interaction.user
        if add_rating:
            view = await LevelRatingView.create(user, self.bot, level_data['code'])
            await interaction.response.send_message(message_content, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(message_content, ephemeral=True)
            
    async def submit_level(self, level_data):
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.channels, id=LEVEL_SHARING_CHANNEL_ID)
        
        message_content = await self.get_level_message(level_data)
        view = LevelRatingButton(self.bot)
        message = await channel.send(message_content, view=view)
        return message.id
        
    async def get_level_message(self, level_data):
        guild = self.bot.guilds[0]
        try:
            creator = await self.bot.dh.get_user(user_id=level_data['creator'])
            creator_user = discord.utils.get(guild.members, id=creator['user_id'])
            creator_name = creator_user.mention
        except UserNotFoundError:
            creator_name = level_data['creator']
            
        rating = await self.bot.dh.get_level_rating(level_data['code'], upvotes_only=True)
        message_content = (
            f"# {level_data['name']}\n"
            f"**{level_data['type']} - **{INDICATOR_EMOJIS['thumbs_up']} {rating}\n"
            f"Creator: {creator_name}\n"
            f"Code: {level_data['code']}\n"
            f"{level_data['imgur']}"
            )
        return message_content
