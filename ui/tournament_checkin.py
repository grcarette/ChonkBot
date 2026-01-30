import discord
from utils.emojis import INDICATOR_EMOJIS

from .confirmation import ConfirmationView

class TournamentCheckinView(discord.ui.View):
    def __init__(self, tournament_manager, tournament, timeout=None):
        super().__init__(timeout=timeout)
        self.tm = tournament_manager
        self.tournament = tournament
        self.checked_in = set()

        self.checkin_button = discord.ui.Button(label=f"Check In {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success, custom_id=f"{self.tournament['name']}-checkin")
        self.register_button = discord.ui.Button(label=f"Register", style=discord.ButtonStyle.primary, custom_id=f"{self.tournament['name']}-register")
        self.unregister_button = discord.ui.Button(label=f"Unregister", style=discord.ButtonStyle.danger, custom_id=f"{self.tournament['name']}-unregister")
        
        self.checkin_button.callback = self.tournament_checkin
        self.register_button.callback = self.register
        self.unregister_button.callback = self.unregister

        self.add_item(self.checkin_button)
        self.add_item(self.register_button)
        self.add_item(self.unregister_button)

        if self.tournament['registration_open']:
            self.register_button.disabled = False
        else:
            self.register_button.disabled = True

    async def unregister(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in self.checked_in:
            self.checked_in.remove(user_id)
        await self.tm.unregister_player(user_id)
        embed = await self.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        message_content = (
            'You have successfully unregistered.\n'
            'If you change your mind, you may still register through the register channel.'
        )
        await interaction.followup.send(message_content, ephemeral=True)
        
    async def register(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        result = await self.tm.register_player(user_id)
        if not result:
            await interaction.response.send_message("You are already registered for this event.", ephemeral=True)
            return
        embed = await self.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        message_content = "You have successfully registered for the tournament.\n"
        await interaction.followup.send(message_content, ephemeral=True)
        
    async def tournament_checkin(self, interaction: discord.Interaction):
        entrants = await self.get_entrants()
        user_id = interaction.user.id
        
        if user_id not in entrants:
            await interaction.response.send_message("You are not currently registered for this event.", ephemeral=True)
            return

        elif user_id in self.checked_in:
            await interaction.response.send_message("You've already checked in!", ephemeral=True)
            return
        
        self.checked_in.add(user_id)
        embed = await self.generate_embed()
        
        await interaction.response.edit_message(embed=embed, view=self)
        await self.tm.bot.dh.checkin_player(self.tournament['name'], user_id)
        
    async def get_entrants(self):
        tournament = await self.tm.bot.dh.get_tournament(name=self.tournament['name'])
        entrants = [int(user_id) for user_id in tournament['entrants'].keys()]
        return entrants
    
    async def generate_embed(self):
        entrants = await self.get_entrants()
        remaining_ids = [user_id for user_id in entrants if user_id not in self.checked_in]
        mentions = [f"<@{id}>" for id in remaining_ids]

        if mentions:
            checkin_message = (
                "Click the button below to check in.\n\n"
                f"Players yet to check in:\n" +
                ("\n".join(mentions))
            )
        else:
            checkin_message = (
                f"{INDICATOR_EMOJIS['green_check']} All players have checked in"
            )
        embed = discord.Embed(
            title=f"Check in for {self.tournament['name']}",
            description=checkin_message,
            color=discord.Color.green()
        )
        return embed