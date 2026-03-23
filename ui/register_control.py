import discord

from utils.emojis import INDICATOR_EMOJIS

class RegisterControlView(discord.ui.View):
    def __init__(self, tournament_manager):
        super().__init__(timeout=None)
        self.tm = tournament_manager

        tid = str(self.tm.tournament['_id'])
        self.register_button = discord.ui.Button(
            label="Register",
            style=discord.ButtonStyle.success,
            custom_id=f"{tid}-Register"
        )
        self.unregister_button = discord.ui.Button(
            label="Unregister",
            style=discord.ButtonStyle.danger,
            custom_id=f"{tid}-Unregister"
        )

        self.register_button.callback = self.register_player
        self.unregister_button.callback = self.unregister_player

        self.add_item(self.register_button)
        self.add_item(self.unregister_button)
        
    async def register_player(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player_registered = await self.get_registration_status(interaction)
        user_id = interaction.user.id

        if player_registered:
            await interaction.followup.send("You are already registered.", ephemeral=True)
            return

        result = await self.tm.register_player(user_id)
        if result == 'pending':
            await interaction.followup.send(
                f"Your registration for {self.tm.tournament['name']} is awaiting TO approval.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"You are now registered for {self.tm.tournament['name']}.", ephemeral=True
            )
            
    async def unregister_player(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
        player_registered = await self.get_registration_status(interaction)
        message_content = (
            f"You have been unregistered from {tournament['name']}"
        )
        if player_registered:
            await self.tm.unregister_player(user_id)
        await interaction.followup.send(message_content, ephemeral=True)
        
    async def get_registration_status(self, interaction):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)
        player_registered = await self.tm.bot.dh.get_registration_status(tournament['_id'], user_id)
        
        return player_registered
