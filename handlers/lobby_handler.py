import discord
from discord.ext import commands
from utils.messages import get_lobby_instructions, get_stage_ban_message
from utils.reaction_utils import create_reaction_flag, create_numerical_reaction
from utils.emojis import NUMBER_EMOJIS, EMOJI_NUMBERS, INDICATOR_EMOJIS
import random

from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton

DEFAULT_STAGE_BANS = 2

class LobbyHandler:
    def __init__(self, bot):
        self.bot = bot
        self.debug = True
    
    async def create_lobby(self, tournament_name='test', players=[], stage=None, pool=None):
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
            
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        
        if stage == None:
            stages = tournament['stagelist']
            stage_bans = DEFAULT_STAGE_BANS
        else:
            stages = [stage]
            stage_bans = False
            
        print(stage_bans)
        lobby_id = await self.bot.dh.create_lobby(tournament, players, stages, stage_bans, pool)
        lobby_name = f"Lobby {lobby_id}"
        lobby_channel = await guild.create_text_channel(name=lobby_name, overwrites=overwrites, category=None)
        await self.bot.dh.add_channel_to_lobby(lobby_id, lobby_channel.id)
        lobby = await self.bot.dh.get_lobby(channel_id=lobby_channel.id)
        await self.start_checkin(lobby, lobby_channel)
        
    async def get_lobby_channel(self, lobby):
        channel_id = lobby['channel_id']
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.channels, id=channel_id)
        return channel
    
    async def get_mentions(self, lobby):
        mentions = [f"<@{id}>" for id in lobby['players']]
        return mentions
        
    async def start_checkin(self, lobby, channel):
        view = CheckinView(self.bot, lobby)
        embed = view.generate_embed()
        mentions = await self.get_mentions(lobby)
        await channel.send(' '.join(mentions),embed=embed, view=view)
        
    async def end_checkin(self, lobby):
        tournament = await self.bot.dh.get_tournament(name=lobby['tournament'])
        if lobby['num_stage_bans'] == None:
            await self.start_reporting(lobby)
        else:
            await self.start_stage_bans(lobby)
        
    async def start_stage_bans(self, lobby):
        channel = await self.get_lobby_channel(lobby)
        view = BanStagesButton(self.bot, lobby)
        embed = view.generate_embed()
        mentions = await self.get_mentions(lobby)
        await channel.send(' '.join(mentions), embed=embed, view=view)
    
    async def end_stage_bans(self, lobby, banned_stages):
        print(banned_stages)
    
    async def start_reporting(self, lobby):
        pass
    
    