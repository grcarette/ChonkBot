import discord
from typing import Callable, Awaitable

class ConfirmationView(discord.ui.View):
    def __init__(self, on_confirm: Callable[[discord.Interaction], Awaitable[None]], user_id,  **kwargs):
        super().__init__()
        self.user_id = user_id
        self.on_confirm = on_confirm
        self.kwargs = kwargs
    
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user.id != self.user_id:
            await self.deny_user(interaction)
            return

        await interaction.delete_original_response()
        await self.on_confirm(self.kwargs)
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.user.id != self.user_id:
            await self.deny_user(interaction)
            return

        await interaction.delete_original_response()
        self.stop()
        
    async def deny_user(self, interaction):
        message_content = (
            'You do not have permission to use this confirmation'
        )
        await interaction.response.send_message(message_content, ephemeral=True)