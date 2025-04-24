import discord

class ConfigControlView(discord.ui.View):
    def __init__(self, tournament_controls, timeout = None):
        super().__init__(timeout=timeout)
        self.tc = tournament_controls
        self.embed_title = "Tournament Configuration"
        
    async def generate_embed(self):
        description = await self.get_control_panel_info()
        embed = discord.Embed(
            title="Tournament Configuration",
            description=description,
            color=discord.Color.blue()
        )
        return embed
    
    async def get_control_panel_info(self):
        return "TBD"