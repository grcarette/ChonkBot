import discord

from utils.emojis import INDICATOR_EMOJIS
from .config_components import TournamentColorModal

COLOR_PICKER_URL = 'https://htmlcolorcodes.com/color-picker/'

class ColorPickerView(discord.ui.View):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc
        
        self.set_color_button = discord.ui.Button(
            label=f"Set Color {INDICATOR_EMOJIS['paint']}", style=discord.ButtonStyle.primary
            )
        self.color_picker_link = discord.ui.Button(
            label=f"Color Picker Tool {INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.link, url=COLOR_PICKER_URL
            )
        
        self.set_color_button.callback = self.input_tournament_color
        
        self.add_item(self.set_color_button)
        self.add_item(self.color_picker_link)
        
    async def input_tournament_color(self, interaction: discord.Interaction):
        modal = TournamentColorModal(self.set_tournament_color)
        await interaction.response.send_modal(modal)
        
    async def set_tournament_color(self, color):
        await self.tc.edit_tournament_config(color=color)