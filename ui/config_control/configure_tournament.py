import discord

from utils.emojis import INDICATOR_EMOJIS
from .config_components import TournamentNameModal, TournamentTimeModal, TournamentFormatSelect, TournamentColorModal

class TournamentConfigView(discord.ui.View):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc
        
        name = self.cc.tm.tournament['name']
        self.set_name_button = discord.ui.Button(
            label=f"Set Name {INDICATOR_EMOJIS['pencil']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-configure_name"
            )
        self.set_time_button = discord.ui.Button(
            label=f"Set Timestamp {INDICATOR_EMOJIS['clock']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-configure_time"
            )
        self.set_color_button = discord.ui.Button(
            label=f"Set Color {INDICATOR_EMOJIS['paint']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-configure_color"
        )
        self.format_select = TournamentFormatSelect(self)
        
        self.set_name_button.callback = self.input_tournament_name
        self.set_time_button.callback = self.input_tournament_time
        self.set_color_button.callback = self.input_tournament_color
        
        self.add_item(self.set_name_button)
        self.add_item(self.set_time_button)
        self.add_item(self.set_color_button)
        self.add_item(self.format_select)
        
    async def input_tournament_name(self, interaction: discord.Interaction):
        modal = TournamentNameModal(self.set_tournament_name)
        await interaction.response.send_modal(modal)

    async def input_tournament_time(self, interaction: discord.Interaction):
        modal = TournamentTimeModal(self.set_tournament_time)
        await interaction.response.send_modal(modal)
        
    async def set_tournament_name(self, name):
        await self.tc.edit_tournament_config(name=name)
    
    async def set_tournament_time(self, timestamp):
        await self.tc.edit_tournament_config(timestamp=timestamp)
        
    async def input_tournament_color(self, interaction: discord.Interaction):
        modal = TournamentColorModal(self.set_tournament_color)
        await interaction.response.send_modal(modal)
        
    async def set_tournament_color(self, color):
        await self.tc.edit_tournament_config(color=color)
        
    async def set_tournament_format(self, format):
        await self.tc.edit_tournament_config(format=format)
        

        
        
        
        
