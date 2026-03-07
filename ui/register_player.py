import discord
from discord import app_commands
from discord.ext import commands

class RegistrationView(discord.ui.View):
    def __init__(self, tournament_api, player_doc, discord_user):
        super().__init__(timeout=60)
        self.api = tournament_api
        self.player_doc = player_doc
        self.discord_user = discord_user

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.api.link_discord(self.player_doc['_id'], str(self.discord_user.id))
        
        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(
            content=f"Linked **{self.discord_user.display_name}** to **{self.player_doc['username']}**!",
            view=self,
            embed=None
        )