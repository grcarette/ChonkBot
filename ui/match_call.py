import discord

class MatchCallView(discord.ui.View):
    def __init__(self, tournament_manager, match_data):
        super().__init__()
        self.tm = tournament_manager
        self.match_data = match_data
        
    @discord.ui.button(label='Call Match', style=discord.ButtonStyle.primary)
    async def call_match(self, interaction: discord.Interaction, button: discord.Button):
        await self.tm.call_match(self.match_data)
        await interaction.response.send_message('match called', ephemeral=True)
        
    #add hold match button!
        