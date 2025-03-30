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
        lobby_name = f"Lobby {lobby_id}"
        lobby_channel = await guild.create_text_channel(name=lobby_name, overwrites=overwrites, category=None)
        await self.bot.dh.add_channel_to_lobby(lobby_id, lobby_channel.id)
        lobby = await self.bot.dh.get_lobby(channel_id=lobby_channel.id)
        await self.advance_lobby(lobby)
        
    async def advance_lobby(self, lobby, confirmation=False):
        tournament = await self.bot.dh.get_tournament(name=lobby['tournament'])
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.channels, id=lobby['channel_id'])
        if lobby['stage'] == 'initialize':
            lobby = await self.bot.dh.advance_lobby(lobby['channel_id'], 'checkin')        
            message_content = await get_lobby_instructions(self.bot, lobby)
            message = await channel.send(message_content)
            user_filter = [player for player in lobby['players']]
            await create_reaction_flag(self.bot, message, 'match_checkin', user_filter=user_filter, require_all_to_react=True)
            
        elif lobby['stage'] == 'checkin':
            if tournament['require_stage_bans'] == True:
                await self.bot.dh.advance_lobby(lobby['channel_id'], 'stage_bans')
                
                new_channel_name = f"Lobby {lobby['lobby_id']} {INDICATOR_EMOJIS['green_check']}"
                await channel.edit(name=new_channel_name)
                
                await self.ban_stages(lobby['channel_id'])
            else:
                pass
            
        elif lobby['stage'] == 'stage_bans':
            lobby = await self.bot.dh.advance_lobby(lobby['channel_id'], 'reporting')   
            
            remaining_stages = [stage for stage in tournament['stagelist'] if stage not in lobby['stage_bans']]
            selected_stage_code = random.choice(remaining_stages)
            selected_stage = await self.bot.dh.get_stage(code=selected_stage_code)
            
            message_content = await get_lobby_instructions(self.bot, lobby, stage=selected_stage)
            message = await channel.send(message_content)
            
            num_list = [i+1 for i, player in enumerate(lobby['players'])]
            user_filter = lobby['players']
            
            await create_numerical_reaction(self.bot, message, num_list, 'match_report', user_filter=user_filter, require_all_to_react=True)
            
        elif lobby['stage'] == 'reporting':
            lobby = await self.bot.dh.advance_lobby(lobby['channel_id'], 'confirmation')   
            
            winner_id = lobby['results'][-1]
            winner = discord.utils.get(guild.members, id=winner_id)
            
            message_content = await get_lobby_instructions(self.bot, lobby, winner=winner)
            message = await channel.send(message_content)
            
            user_filter = lobby['players']
            await create_reaction_flag(self.bot, message, 'match_confirmation', user_filter=user_filter, require_all_to_react=True)
            
        elif lobby['stage'] == 'confirmation':
            if confirmation:
                lobby = await self.bot.dh.advance_lobby(lobby['channel_id'], 'finished')
                message_content = await get_lobby_instructions(self.bot, lobby)
                message = await channel.send(message_content)
                
            else:
                lobby = await self.bot.dh.reset_lobby(lobby['channel_id'], last_result_only=True)
                lobby = await self.bot.dh.advance_lobby(lobby['channel_id'], 'stage_bans')
                await self.advance_lobby(lobby)
    
    async def ban_stages(self, channel_id, payload=False):
        lobby = await self.bot.dh.get_lobby(channel_id=channel_id)
        tournament = await self.bot.dh.get_tournament(name=lobby['tournament'])
        
        if payload:
            banned_stage_number = EMOJI_NUMBERS[payload.emoji.name]-1
            banned_stage = tournament['stagelist'][banned_stage_number]
            lobby = await self.bot.dh.ban_stage(lobby['channel_id'], banned_stage)
                    
        stage_ban_number = len(lobby['stage_bans']) + 1
        player_count = len(lobby['players'])
        banning_player_id = lobby['players'][stage_ban_number % player_count] 
        
        if len(lobby['stage_bans']) % player_count == 0:
            remaining_stages = len(tournament['stagelist']) - len(lobby['stage_bans'])
            if remaining_stages < player_count:
                await self.advance_lobby(lobby)
                return
        
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.channels, id=lobby['channel_id'])
        banning_player = discord.utils.get(guild.members, id=banning_player_id)
        
        stage_codes = tournament['stagelist']
        stages = [await self.bot.dh.get_stage(code=stage_code) for stage_code in stage_codes]
        stages_text_lines = []
        num_list = []
        for i, stage in enumerate(stages):
            if stage['code'] not in lobby['stage_bans']:
                stages_text_lines.append(f"{NUMBER_EMOJIS[i+1]} {stage['name']}")
                num_list.append(i+1)
        stages_text = "\n".join(stages_text_lines)
        
        message_content = await get_stage_ban_message(stages_text, banning_player)
        message = await channel.send(message_content)
        await create_numerical_reaction(self.bot, message, num_list, 'stage_ban', user_filter=banning_player_id)

    