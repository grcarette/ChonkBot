import discord

from utils.color_utils import brighten_hex_color, discord_color_from_hex
from utils.validate_stagecode import validate_stagecode

class TournamentConfigHandler:
    def __init__(self, tournament_control):
        self.tc = tournament_control
        self.dh = self.tc.dh
        self.guild = self.tc.tm.guild
        self.tournament = self.tc.tournament
        
    async def edit_tournament_config(self, **kwargs):
        if 'color' in kwargs:
            await self.set_color(kwargs.pop('color'))
        if 'name' in kwargs: 
            await self.set_name(kwargs.pop('name'))
        if 'assistant' in kwargs:
            await self.add_assistant(kwargs.pop('assistant'))
        if 'date' in kwargs:
            await self.set_date(kwargs.pop('date'))
        if 'format' in kwargs:
            await self.set_format(kwargs.pop('format'))
        
    async def set_name(self, name):
        tournament_role, tournament_to_role = await self.get_tournament_roles()
        await tournament_role.edit(name=name)
        await tournament_to_role.edit(name=f"{name} TO")
        
        await self.dh.edit_tournament_config(self.tournament['_id'], name=name)
        await self.refresh_displays()
    
    async def set_color(self, color):
        base_color = discord_color_from_hex(color)
        brighter_color = brighten_hex_color(color)
        
        tournament_role, tournament_to_role = await self.get_tournament_roles()
        
        if tournament_role:
            await tournament_role.edit(color=base_color)
        if tournament_to_role:
            await tournament_to_role.edit(color=brighter_color)
        
        await self.dh.set_tournament_color(self.tournament['_id'], color)
        await self.refresh_displays()
        
    async def add_assistant(self, user):
        tournament_role, tournament_to_role = await self.get_tournament_roles()
        await user.add_roles(tournament_to_role)
        await self.dh.add_assistant(self.tournament['_id'], user.id)
        await self.refresh_displays()
    
    async def set_date(self, date):
        await self.dh.edit_tournament_config(self.tournament['_id'], date=date)
        await self.refresh_displays()
    
    async def set_format(self, format):
        await self.dh.edit_tournament_config(self.tournament['_id'], format=format)
        await self.refresh_displays()
    
    async def refresh_displays(self):
        await self.tc.refresh_displays()

    async def add_stages(self, stages):
        await self.dh.add_stages_to_tournament(self.tournament['_id'], stages)
        await self.tc.refresh_stagelist()
        
    async def check_stages(self, stages):
        valid_stages = []
        stages = stages.split(',')
        for stage_code in stages:
            valid_code = validate_stagecode(stage_code)
            if not valid_code:
                return stage_code, False
            valid_stages.append(valid_code)
        return valid_stages, True
    
    async def add_random_stages(self, stage_count):
        tournament = await self.tc.tm.get_tournament()
        stages = await self.dh.get_random_stages(stage_count - len(tournament['stagelist']))
        stage_codes = [stage['code'] for stage in stages]
        await self.add_stages(stage_codes)
        
    async def get_tournament_roles(self):
        tournament = await self.tc.tm.get_tournament()
        tournament_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']} TO")
        return tournament_role, tournament_to_role