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

        name = tournament_manager.tournament['name']
        self.join_button = discord.ui.Button(
            label=f"Join {INDICATOR_EMOJIS['green_check']}",
            style=discord.ButtonStyle.success,
            custom_id=f"{name}-swiss_join"
        )
        self.leave_button = discord.ui.Button(
            label=f"Leave {INDICATOR_EMOJIS['red_x']}",
            style=discord.ButtonStyle.danger,
            custom_id=f"{name}-swiss_leave"
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

        # Check registered
        registered = await self.tm.bot.dh.get_registration_status(
            tournament['_id'], user_id
        )
        if not registered:
            await interaction.followup.send(
                "You are not registered for this event.", ephemeral=True
            )
            return

        # Handle mid-match leave
        swiss_event = await self.tm.bot.dh.get_swiss_event_by_tournament(tournament['_id'])
        if swiss_event:
            player_data = swiss_event['players'].get(str(user_id))
            if player_data and player_data.get('active_match_id') is not None:
                active_match_id = player_data['active_match_id']
                # Find the opponent
                lobby_data = self.tm.lobbies.get(active_match_id)
                if lobby_data:
                    opponent_id = next(
                        (p for p in lobby_data.players if p != user_id), None
                    )
                    if opponent_id:
                        # Record win for opponent in swiss DB only, not UCH Ranked
                        await self.tm.bot.dh.swiss_record_result(
                            swiss_event['_id'],
                            active_match_id,
                            opponent_id,
                            user_id,
                        )
                        # Notify the lobby and close it
                        if lobby_data.channel:
                            opponent_mention = f"<@{opponent_id}>"
                            leaving_mention = f"<@{user_id}>"
                            embed = discord.Embed(
                                title="Player Left",
                                description=(
                                    f"{leaving_mention} has left the tournament.\n"
                                    f"{opponent_mention} wins this match by default.\n\n"
                                    "This win counts toward tournament standings but will not be reported to UCH Ranked."
                                ),
                                color=discord.Color.orange()
                            )
                            await lobby_data.channel.send(embed=embed)
                        # Trigger round complete check since a match just finished
                        if self.tm.swiss_manager:
                            await self.tm.swiss_manager.check_round_complete()

        # Drop from swiss event and unregister
        await self.tm.unregister_player(user_id)

        await interaction.followup.send(
            f"You have left **{tournament['name']}**. Your results so far stand.",
            ephemeral=True
        )