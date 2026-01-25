import discord
from utils.emojis import INDICATOR_EMOJIS
from utils.messages import get_mentions

class CheckinView(discord.ui.View):
    def __init__(self, lobby, timeout=None):
        super().__init__(timeout=timeout)
        self.lobby = lobby
        self.message = None
        
        self.checkin_button = discord.ui.Button(label="Check in", style=discord.ButtonStyle.success, custom_id=f"{self.lobby.match_id}-checkin")
        self.checkin_button.callback = self.check_in
        self.add_item(self.checkin_button)
        
    async def check_in(self, interaction: discord.Interaction):
        override = False
        user_id = interaction.user.id
        message = interaction.message 
        lobby = await self.lobby.get_lobby()
        
        user_is_to = await self.lobby.check_to_role(user_id)
        if user_is_to:
            override = True
        elif user_id not in self.lobby.remaining_players:
            await interaction.response.send_message("You're not part of this match!", ephemeral=True)
            return
        elif user_id in lobby['checked_in']:
            await interaction.response.send_message("You've already checked in!", ephemeral=True)
            return
        
        if not override:
            lobby = await self.lobby.checkin_player(user_id)
            embed = await self.generate_embed()
        else:
            for player in self.lobby.remaining_players:
                lobby = await self.lobby.checkin_player(player)
            embed = await self.generate_embed()

        await interaction.response.edit_message(embed=embed, view=self)

        if len(lobby['checked_in']) == len(self.lobby.remaining_players):
            self.stop()
            await interaction.message.delete()
            await self.lobby.end_checkin()
            
    async def generate_embed(self):
        lobby = await self.lobby.get_lobby()
        remaining_ids = [player_id for player_id in self.lobby.remaining_players if player_id not in lobby['checked_in']]
        mentions = get_mentions(remaining_ids)

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