import discord
from discord.ext import commands
from utils.messages import get_lobby_instructions
from utils.reaction_utils import create_reaction_flag

class LobbyHandler:
    def __init__(self, bot):
        self.bot = bot
        self.debug = True
    
    async def create_lobby(self, tournament_name='test', players=[], pool=None):
        guild = self.bot.guilds[0]
        organizer_role = discord.utils.get(guild.roles, name="Event Organizer")
        if self.debug == True:
            player1 = discord.utils.get(guild.members, id=1017833723506475069)
            player2 = discord.utils.get(guild.members, id=142798704703700992)
            players = [player1, player2]
            
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            organizer_role: discord.PermissionOverwrite(read_messages=True)
        }
        for player in players:
            overwrites[player] = discord.PermissionOverwrite(read_messages=True)
            
        lobby_id = await self.bot.dh.create_lobby(tournament_name, players, pool)
        lobby_channel = await guild.create_text_channel(name=lobby_id, overwrites=overwrites, category=None)
        await self.dh.add_channel_to_lobby(lobby_id, lobby_channel.id)
        
        lobby_instructions = await get_lobby_instructions(self.bot.dh, lobby_id, tournament_name)
        
        message = await lobby_channel.send(lobby_instructions)
        user_filter = [player.id for player in players]
        await create_reaction_flag(self.bot, message, 'match_checkin', user_filter=user_filter, require_all_to_react=True)
        
    async def advance_lobby(self, lobby_id):
        lobby = await self.bot.get_lobby(lobby_id=lobby_id)
        if lobby['stage'] == 'checkin':
            print('start stage bans')
        if lobby['stage'] == 'stage_bans':
            pass
        if lobby['stage'] == 'reporting':
            pass

        pass