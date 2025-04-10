import discord
from discord.ext import commands
from utils.messages import get_lobby_instructions, get_stage_ban_message
from utils.reaction_utils import create_reaction_flag, create_numerical_reaction
from utils.emojis import NUMBER_EMOJIS, EMOJI_NUMBERS, INDICATOR_EMOJIS
import random

from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton

DEFAULT_STAGE_BANS = 2

class LobbyHandler:
    def __init__(self, bot):
        self.bot = bot
        self.debug = False
    
    async def create_lobby(self, tournament_name, match_id, prerequisite_matches, players=[], stage=None, num_winners=1, pool=None):
        guild = self.bot.guilds[0]
        organizer_role = discord.utils.get(guild.roles, name="Event Organizer")
        if self.debug == True:
            player1 = discord.utils.get(guild.members, id=1017833723506475069)
            player2 = discord.utils.get(guild.members, id=142798704703700992)
            # player3 = discord.utils.get(guild.members, id=486189871921364994)
            player4 = discord.utils.get(guild.members, id=659876874347872257)
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
            num_stage_bans = DEFAULT_STAGE_BANS
        else:
            stages = [stage]
            num_stage_bans = 0
            
        lobby_id = await self.bot.dh.create_lobby(tournament, match_id, prerequisite_matches, players, stages, num_stage_bans, num_winners, pool)
        lobby_name = f"Lobby {lobby_id}"
        lobby_channel = await guild.create_text_channel(name=lobby_name, overwrites=overwrites, category=None)
        await self.bot.dh.add_channel_to_lobby(lobby_id, tournament_name, lobby_channel.id)
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
        if lobby['config']['num_stage_bans'] == None:
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
        remaining_stages = [stage for stage in lobby['stages'] if stage not in banned_stages]
        final_stage = random.choice(remaining_stages)
        print(final_stage)
        
        lobby = await self.bot.dh.pick_lobby_stage(lobby['channel_id'], final_stage)
        await self.start_reporting(lobby)
        
    async def delete_lobby(self, lobby):
        channel = await self.get_lobby_channel(lobby)
        await channel.delete()
        await self.bot.dh.delete_lobby(lobby)

    async def start_reporting(self, lobby):
        stage = await self.bot.dh.get_stage(code=lobby['picked_stage'])
        channel = await self.get_lobby_channel(lobby)
        message_content = (
            f"You will be playing on **{stage['name']} - {stage['code']}**\n"
            f"Sort out among yourselves who will host the lobby. Make sure you are playing in party mode with the tournament ruleset.\n\n"
            f"When the match is over, report the winner of the match with the dropdown menu below."
        )
        view = MatchReportButton(self.bot, lobby)
        embed = discord.Embed(
            title = 'Match Ready!',
            description = message_content,
            color = discord.Color.yellow()
        )
        mentions = await self.get_mentions(lobby)
        await channel.send(' '.join(mentions), embed=embed, view=view)
        
    async def end_reporting(self, lobby, winner_id):
        channel = await self.get_lobby_channel(lobby)
        
        message_content = (
            f'Congratulations <@{winner_id}>'
        )
        await channel.send(message_content)
        
        lobby = await self.bot.dh.report_match(lobby['channel_id'], winner_id)
        if len(lobby['results']) < lobby['config']['num_winners']:
            await self.start_stage_bans(lobby)
        else:
            message_content = (
                'This lobby is now closed.'
            )
            await channel.send(message_content)
            await self.bot.th.report_match(lobby)
        

    
    
    