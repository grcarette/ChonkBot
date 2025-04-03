import discord

from utils.emojis import INDICATOR_EMOJIS

class RegisterControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        
    @discord.ui.button(label=f"Register", style=discord.ButtonStyle.success, custom_id="register_button")
    async def register_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        
        tournament_name = tournament['name']
        player_registered = await self.bot.dh.get_registration_status(tournament_name, user_id)
        print(player_registered)
        
        if player_registered:
            await self.bot.dh.unregister_player(tournament_name, user_id)
            message_content = (
                f"You are no longer registered for {tournament['name']}\n"
                f"You may still choose to register again by pressing the button."
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        else:
            await self.bot.dh.register_player(tournament_name, user_id)
            message_content = (
                f"You are now registered for {tournament['name']}\n"
                f"If you wish to unregister, press the button again."
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        
