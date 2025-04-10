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
        if interaction.user.id != self.user_id:
            await self.deny_user(interaction)
            return

        await self.disable_buttons()
        print(self.kwargs)
        await self.on_confirm(self.kwargs)
        await interaction.response.edit_message(view=self)
        
        await self.delete_message(interaction.message)
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await self.deny_user(interaction)
            return
            
        await self.disable_buttons()
        await interaction.response.edit_message(view=self)
        
        await self.delete_message(interaction.message)
        
    async def disable_buttons(self):
        for child in self.children:
            child.disabled = True
    
    async def delete_message(self, message):
        if not message.flags.ephemeral:
            await message.delete()
            
    async def deny_user(self, interaction):
        message_content = (
            'You do not have permission to use this confirmation'
        )
        await interaction.response.send_message(message_content, ephemeral=True)