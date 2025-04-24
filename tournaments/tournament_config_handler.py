import discord

from utils.color_utils import brighten_hex_color, discord_color_from_hex

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
        
    async def get_tournament_roles(self):
        tournament = await self.tc.tm.get_tournament()
        tournament_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']} TO")
        return tournament_role, tournament_to_role