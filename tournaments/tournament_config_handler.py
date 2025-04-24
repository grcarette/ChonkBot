import discord

from utils.brighten_color import brighten_hex_color

class TournamentConfigHandler:
    def __init__(self, tournament_control):
        self.tc = tournament_control
        self.dh = self.tc.dh
        self.guild = self.tc.tm.guild
        
    async def set_name(self, name):
        #change name of category
        #change name in db
        #refresh info display
        #refresh control
        #
        pass
    
    async def set_color(self, color):
        hex_base = 16
        base_color = discord.Color(int(color.lstrip('#'), hex_base))
        brighter_color = brighten_hex_color(color)
        
        tournament = await self.tc.tm.get_tournament()
        tournament_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']} TO")
        
        if tournament_role:
            await tournament_role.edit(color=base_color)
        if tournament_to_role:
            await tournament_to_role.edit(color=brighter_color)
        
        await self.dh.set_tournament_color(tournament['_id'], color)
        await self.refresh_displays()
    
    async def set_time(self, time):
        #set time in db
        #refresh info display
        pass
    
    async def set_format(self, format):
        #set format in db
        #refresh info display
        pass
    
    async def refresh_displays(self):
        await self.tc.refresh_displays()