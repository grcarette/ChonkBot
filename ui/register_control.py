import discord

from utils.emojis import INDICATOR_EMOJIS

class RegisterControlView(discord.ui.View):
    def __init__(self, tournament_manager):
        super().__init__(timeout=None)
        self.tm = tournament_manager
        
        self.register_button = discord.ui.Button(label=f"Register", style=discord.ButtonStyle.success, custom_id=f"{self.tm.tournament['name']}-Register")
        self.register_button.callback = self.register_player
        self.add_item(self.register_button)
        
    async def register_player(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
    
        player_registered = await self.tm.bot.dh.get_registration_status(tournament['_id'], user_id)
        
        if player_registered:
            await self.tm.unregister_player(user_id)
            message_content = (
                f"You are no longer registered for {tournament['name']}\n"
                f"You may still choose to register again by pressing the button."
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        else:
            await self.tm.register_player(user_id)
            message_content = (
                f"You are now registered for {tournament['name']}\n"
                f"If you wish to unregister, press the button again."
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        
