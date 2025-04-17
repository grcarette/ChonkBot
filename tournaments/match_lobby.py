import discord
import asyncio
import random

from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton

from utils.messages import get_mentions

class MatchLobby:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("Use 'await MatchLobby.create() instead of direct initialization.")
            
    @classmethod
    async def create(
        cls, 
        tournament_id,
        match_id, 
        lobby_name, 
        players, 
        prereq_matches, 
        stages, 
        num_winners, 
        tournament_manager, 
        datahandler, 
        guild, 
        ):
        
        self=object.__new__(cls)
        
        self.tournament_id = tournament_id #_id
        self.match_id = match_id
        self.lobby_name = lobby_name 
        self.players = players
        self.prereq_matches = prereq_matches
        self.stages = stages
        self.num_winners = num_winners
        self.tournament_manager = tournament_manager
        self.dh = datahandler
        self.guild = guild
        
        self.tournament = await self.dh.get_tournament_by_id(self.tournament_id)
        self.override_role = f"{self.tournament['name']} TO"
        
        lobby_exists = await self.get_lobby()
        if lobby_exists:
            await self.add_channel()
        else:
            await self.setup_lobby()
        lobby = await self.get_lobby()
        self.remaining_players = [player for player in self.players if player not in lobby['results']]
    
            
        return self

    async def setup_lobby(self):
        await self.dh.create_lobby(
            tournament=self.tournament,
            match_id=self.match_id,
            lobby_name=self.lobby_name,
            prereq_matches=self.prereq_matches,
            players=self.players,
            stages=self.stages,
            num_winners=self.num_winners
            )
        
    async def add_channel(self):
        lobby = await self.get_lobby()
        if lobby['state'] == 'initialize' or lobby['state'] == 'closed':
            return False
        
        channel_id = lobby['channel_id']
        channel = discord.utils.get(self.guild.channels, id=channel_id)
        self.channel = channel
        await self.channel.send('confirm')
        
    async def initialize_match(self):
        await self.create_channel()
        await self.start_match()
        
    async def start_match(self):
        lobby = await self.get_lobby()
        self.remaining_players = [player for player in self.players if player not in lobby['results']]
        await self.start_checkin()
        
    async def create_channel(self):
        organizer_role = discord.utils.get(self.guild.roles, name=f"{self.tournament['name']} TO")
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            organizer_role: discord.PermissionOverwrite(read_messages=True)
        }
        for player in self.players:
            member = discord.utils.get(self.guild.members, id=player)
            overwrites[member] = discord.PermissionOverwrite(read_messages=True)
            
        self.channel = await self.guild.create_text_channel(name=self.lobby_name, overwrites=overwrites, category=None)
        await self.dh.add_channel_to_lobby(self.match_id, self.channel, )
        
    async def start_checkin(self):
        await self.dh.update_lobby_state(self.match_id, 'checkin')
        view = CheckinView(self)
        embed = await view.generate_embed()
        mentions = get_mentions(self.remaining_players)
        await self.channel.send(' '.join(mentions),embed=embed, view=view)
        
    async def checkin_player(self, player_id):
        lobby = await self.dh.lobby_checkin_player(self.match_id, player_id)
        return lobby
    
    async def end_checkin(self):
        await self.start_stage_bans()
        
    async def start_stage_bans(self):
        await self.dh.update_lobby_state(self.match_id, 'stage_bans')
        view = BanStagesButton(self)
        num_stage_bans = view.calculate_num_stage_bans()
        
        if num_stage_bans == 0:
            await self.end_stage_bans(banned_stages=[])
        else:    
            embed = view.generate_embed()
            mentions = get_mentions(self.remaining_players)
            await self.channel.send(' '.join(mentions), embed=embed, view=view)
            
    async def end_stage_bans(self, banned_stages):
        remaining_stages = [stage for stage in self.stages if stage not in banned_stages]
        picked_stage = random.choice(remaining_stages)
        await self.dh.pick_lobby_stage(self.match_id, picked_stage)
        await self.start_reporting()
    
    async def start_reporting(self):
        lobby = await self.get_lobby()
        picked_stage = lobby['picked_stage']
        await self.dh.update_lobby_state(self.match_id, 'reporting')
        stage = await self.dh.get_stage(code=picked_stage)
        message_content = (
            f"You will be playing on **{stage['name']} - {stage['code']}**\n"
            f"Sort out among yourselves who will host the lobby. Make sure you are playing in party mode with the tournament ruleset.\n\n"
            f"When the match is over, report the winner of the match with the dropdown menu below."
        )
        view = MatchReportButton(self)
        embed = discord.Embed(
            title = 'Match Ready!',
            description = message_content,
            color = discord.Color.yellow()
        )
        mentions = get_mentions(self.remaining_players)
        await self.channel.send(' '.join(mentions), embed=embed, view=view)
    
    async def end_reporting(self, winner_id):
        lobby = await self.dh.report_match(self.match_id, winner_id)
        if self.num_winners == len(lobby['results']):
            await self.dh.update_lobby_state(self.match_id, 'finished')
            await self.dh.end_match(self.match_id)
            await self.tournament_manager.report_match(self)
            await self.send_player_instructions()
        else:
            await self.start_match()
            
    async def send_player_instructions(self):
        lobby = await self.get_lobby()
        winner_mention = f"<@{lobby['results'][0]}>"
        loser_mention = f"<@{lobby['results'][1]}>"
        
        winner_message = (
            f"Congratulations {winner_mention}!\n"
            "You will be pinged when your next match is ready. You might need to wait to play to allow the losers bracket to catch up.\n\n"
        )
        if self.lobby_name[0] == 'w':
            loser_message = (
                f"{loser_mention} You've lost this set, but you are not out of the tournament yet.\n"
                "You will be pinged when it's time to play your next set."
            )
        elif self.lobby_name[0] == 'l':
            loser_message = (
                f"{loser_mention} Unfortunately you've been eliminated from the tournament. Thank you for playing!"
            )
        player_instructions = discord.Embed(
            title='Lobby Closed',
            description=winner_message + loser_message,
            color=discord.Color.blue()
        )
        await self.channel.send(embed=player_instructions)
        
    async def close_lobby(self):
        await self.dh.update_lobby_state(self.match_id, 'closed')
        if self.channel != None:
            await self.channel.delete()
            self.channel = None
    
    async def reset_report(self):
        await self.dh.reset_lobby(self.match_id, 'report')
        self.remaining_players = self.players
        await self.start_reporting()
        
    async def delete_lobby(self):
        await self.channel.delete()
        await self.dh.delete_lobby(self.match_id)
        
    async def get_lobby(self):
        lobby = await self.dh.get_lobby(self.match_id)
        return lobby
    
    
