import discord
from utils.emojis import INDICATOR_EMOJIS


class SwissActiveRegisterView(discord.ui.View):
    """
    Replaces the normal registration embed once a swiss tournament goes active.
    Players can join or leave at any time during the event.
    """
    def __init__(self, tournament_manager, timeout=None):
        super().__init__(timeout=timeout)
        self.tm = tournament_manager

        tid = str(tournament_manager.tournament['_id'])
        self.join_button = discord.ui.Button(
            label=f"Join {INDICATOR_EMOJIS['green_check']}",
            style=discord.ButtonStyle.success,
            custom_id=f"{tid}-swiss_join"
        )
        self.leave_button = discord.ui.Button(
            label=f"Leave {INDICATOR_EMOJIS['red_x']}",
            style=discord.ButtonStyle.danger,
            custom_id=f"{tid}-swiss_leave"
        )

        self.join_button.callback = self.join
        self.leave_button.callback = self.leave

        self.add_item(self.join_button)
        self.add_item(self.leave_button)

    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        tournament = await self.tm.get_tournament()

        # Check already registered
        already_registered = await self.tm.bot.dh.get_registration_status(
            tournament['_id'], user_id
        )
        if already_registered:
            await interaction.followup.send(
                "You are already registered for this event.", ephemeral=True
            )
            return

        # UCH Ranked gate
        ranked_player = await self.tm.get_ranked_player(user_id)
        if not ranked_player:
            await interaction.followup.send(
                "You need a UCH Ranked account to participate in this event. "
                "You can sign up at <https://uchranked.com>.",
                ephemeral=True
            )
            return

        # Register the player
        success = await self.tm.register_player(user_id)
        if not success:
            await interaction.followup.send(
                "Something went wrong registering you. Please try again.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"You have joined **{tournament['name']}**! "
            "You will be paired in the next available round.",
            ephemeral=True
        )

    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        tournament = await self.tm.get_tournament()

        registered = await self.tm.bot.dh.get_registration_status(
            tournament['_id'], user_id
        )
        if not registered:
            await interaction.followup.send(
                "You are not registered for this event.", ephemeral=True
            )
            return

        await self.tm.drop_swiss_player(user_id)

        await interaction.followup.send(
            f"You have left **{tournament['name']}**. Your results so far stand.",
            ephemeral=True,
        )