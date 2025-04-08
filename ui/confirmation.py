import discord
from typing import Callable, Awaitable

class ConfirmationView(discord.ui.View):
    def __init__(self, on_confirm: Callable[[discord.Interaction], Awaitable[None]], value=None):
        super().__init__()
        self.on_confirm = on_confirm
        self.value = value
    
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_confirm(True, self.value)
        await interaction.response.defer()
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_confirm(False, self.value)
        await interaction.response.defer()
    
        