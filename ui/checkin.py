import discord
from utils.emojis import INDICATOR_EMOJIS

class CheckinView(discord.ui.View):
    def __init__(self, bot, lobby):
        super().__init__()
        self.bot = bot
        self.lobby = lobby
        self.checked_in = set()
        self.message = None
        
    @discord.ui.button(label="Check in", style=discord.ButtonStyle.success)
    async def checkin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        message = interaction.message 
        
        if user_id not in self.lobby['players']:
            await interaction.response.send_message("You're not part of this match!", ephemeral=True)
            return
        
        if user_id in self.checked_in:
            await interaction.response.send_message("You've already checked in!", ephemeral=True)
            return
        
        self.checked_in.add(user_id)
        embed = self.generate_embed()

        await interaction.response.edit_message(embed=embed, view=self)
        
        if len(self.checked_in) == len(self.lobby['players']):
            self.stop()
            await interaction.message.delete()
            await self.bot.lh.end_checkin(self.lobby)
            
    def generate_embed(self):
        remaining_ids = [pid for pid in self.lobby['players'] if pid not in self.checked_in]
        mentions = [f"<@{pid}>" for pid in remaining_ids]

        if mentions:
            checkin_message = (
                "Click the button below to check in for your match.\n\n"
                f"Players yet to check in:\n" +
                ("\n".join(mentions))
            )
        else:
            checkin_message = (
                f"{INDICATOR_EMOJIS['green_check']} All players have checked in"
            )
        embed = discord.Embed(
            title="Check in for your match",
            description=checkin_message,
            color=discord.Color.green()
        )
        return embed