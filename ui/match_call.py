import discord

class MatchCallView(discord.ui.View):
    def __init__(self, bot, match_data):
        super().__init__()
        self.bot = bot
        self.match_data = match_data
        
    @discord.ui.button(label='Call Match', style=discord.ButtonStyle.primary)
    async def call_match(self, interaction: discord.Interaction, button: discord.Button):
        await self.bot.th.call_match(self.match_data)
        await interaction.response.send_message('match called', ephemeral=True)
        