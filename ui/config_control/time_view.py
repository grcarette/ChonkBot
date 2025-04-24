import discord

from utils.emojis import INDICATOR_EMOJIS
from .config_components import TournamentTimeModal

TIMESTAMP_TOOL_URL = 'https://r.3v.fi/discord-timestamps/'

class TimePickerView(discord.ui.View):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc
        
        self.set_date_button = discord.ui.Button(
            label=f"Set Date {INDICATOR_EMOJIS['clock']}", style=discord.ButtonStyle.primary
            )
        self.timestamp_generator_link = discord.ui.Button(
            label=f"Timestamp Generator {INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.link, url=TIMESTAMP_TOOL_URL
            )
        
        self.set_date_button.callback = self.input_tournament_date
        
        self.add_item(self.set_date_button)
        self.add_item(self.timestamp_generator_link)
        
    async def input_tournament_date(self, interaction: discord.Interaction):
        modal = TournamentTimeModal(self.set_tournament_date)
        await interaction.response.send_modal(modal)
        
    async def set_tournament_date(self, date):
        await self.tc.edit_tournament_config(date=date)