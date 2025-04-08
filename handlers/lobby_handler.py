import discord
from discord.ext import commands
from utils.messages import get_lobby_instructions, get_stage_ban_message
from utils.reaction_utils import create_reaction_flag, create_numerical_reaction
from utils.emojis import NUMBER_EMOJIS, EMOJI_NUMBERS, INDICATOR_EMOJIS
import random

class LobbyHandler:
    def __init__(self, bot):
        self.bot = bot
        self.debug = True
    
    async def create_lobby(self, tournament_name='test', players=[], pool=None):
        guild = self.bot.guilds[0]
        organizer_role = discord.utils.get(guild.roles, name="Event Organizer")
        if self.debug == True:
            player1 = discord.utils.get(guild.members, id=462393872035872784)
            player2 = discord.utils.get(guild.members, id=142798704703700992)
            players = [player1, player2]
            
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            organizer_role: discord.PermissionOverwrite(read_messages=True)
        }
        for player in players:
            overwrites[player] = discord.PermissionOverwrite(read_messages=True)
            
        lobby_id = await self.bot.dh.create_lobby(tournament_name, players, pool)
        lobby_name = f"Lobby {lobby_id}"
        lobby_channel = await guild.create_text_channel(name=lobby_name, overwrites=overwrites, category=None)
        await self.bot.dh.add_channel_to_lobby(lobby_id, lobby_channel.id)
        lobby = await self.bot.dh.get_lobby(channel_id=lobby_channel.id)
        await self.advance_lobby(lobby)
        
    async def advance_lobby(self):
        pass

    