import discord

from utils.emojis import INDICATOR_EMOJIS

class RegisterControlView(discord.ui.View):
    def __init__(self, tournament_manager):
        super().__init__(timeout=None)
        self.tm = tournament_manager
        
        self.register_button = discord.ui.Button(label=f"Register", style=discord.ButtonStyle.success, custom_id=f"{self.tm.tournament['name']}-Register")
        self.unregister_button = discord.ui.Button(label=f"Unregister", style=discord.ButtonStyle.danger, custom_id=f"{self.tm.tournament['name']}-Unregister")
        
        self.register_button.callback = self.register_player
        self.unregister_button.callback = self.unregister_player
        
        self.add_item(self.register_button)
        self.add_item(self.unregister_button)
        
    async def register_player(self, interaction: discord.Interaction):
        player_registered = await self.get_registration_status(interaction)
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
        
        if player_registered:
            message_content = (
                "You are already registered."
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        else:
            await self.tm.create_registration_approval(user_id, interaction)
            
    async def unregister_player(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
        player_registered = await self.get_registration_status(interaction)
        message_content = (
            f"You have been unregistered from {tournament['name']}"
        )
        if player_registered:
            await self.tm.unregister_player(user_id)
        await interaction.response.send_message(message_content, ephemeral=True)
        
    async def get_registration_status(self, interaction):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
        player_registered = await self.tm.bot.dh.get_registration_status(tournament['_id'], user_id)
        
        return player_registered
