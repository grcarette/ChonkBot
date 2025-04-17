import discord
from .confirmation import ConfirmationView

class EndTournamentView(discord.ui.View):
    def __init__(self, tournament_manager, timeout=None):
        super().__init__(timeout=timeout)
        
        self.tm = tournament_manager
        
        name = self.tm.tournament['name']
        end_tournament_button = discord.ui.Button(label='End Tournament', style=discord.ButtonStyle.success, custom_id=f"{name}-end_tournament")
        end_tournament_button.callback = self.end_tournament
        
        self.add_item(end_tournament_button)
        
    async def end_tournament(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        embed = discord.Embed(
            title="Are you sure you want to end the tournament?",
            color=discord.Color.red()
        )
        view = ConfirmationView(self.tm.end_tournament, user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        