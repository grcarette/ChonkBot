import discord

from utils.emojis import INDICATOR_EMOJIS


class TeammateSelectView(discord.ui.View):
    """Ephemeral view shown after clicking Register in teams mode."""

    def __init__(self, tournament_manager):
        super().__init__(timeout=60)
        self.tm = tournament_manager

        select = discord.ui.UserSelect(placeholder="Select your teammate...")
        select.callback = self._on_teammate_selected
        self.add_item(select)

    async def _on_teammate_selected(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        teammate_id = int(interaction.data['values'][0])

        if teammate_id == user_id:
            await interaction.followup.send(
                "You cannot team with yourself.", ephemeral=True
            )
            return

        tournament = await self.tm.get_tournament()
        pending = await self.tm.bot.dh.get_pending_teams(tournament['_id'])

        # Check if the selected teammate has already sent an invite to this user
        mutual_invite = next(
            (pt for pt in pending
             if pt['player1_id'] == teammate_id and pt['player2_id'] == user_id),
            None
        )

        if mutual_invite:
            # Both sides picked each other — accept
            result = await self.tm.accept_team_invite(user_id)
            if result == 'registered':
                inviter = await self.tm.bot.dh.get_user(user_id=teammate_id)
                inviter_name = inviter['name'] if inviter else str(teammate_id)
                await interaction.followup.send(
                    f"You've joined **{inviter_name}**'s team! "
                    f"You are now registered for {self.tm.tournament['name']}.",
                    ephemeral=True
                )
            elif result == 'already_registered':
                await interaction.followup.send(
                    "You are already registered.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Something went wrong accepting the invite.", ephemeral=True
                )
        else:
            # No mutual invite — send a new invite to the selected teammate
            result = await self.tm.register_player_team(user_id, teammate_id)
            messages = {
                'pending':                    f"Team invite sent to <@{teammate_id}>! They must also click **Register** and select you as their teammate to complete registration.",
                'self_invite':                "You cannot team with yourself.",
                'already_registered':         "You are already registered for this event.",
                'partner_already_registered': "That player is already registered on another team.",
                'already_pending':            "You already have a pending team invite out. Unregister to cancel it first.",
            }
            await interaction.followup.send(
                messages.get(result, "Something went wrong."), ephemeral=True
            )


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
        user_id = interaction.user.id

        if self.tm.is_teams_mode:
            already_registered = await self.get_registration_status(interaction)
            if already_registered:
                await interaction.followup.send(
                    "You are already registered.", ephemeral=True
                )
                return
            view = TeammateSelectView(self.tm)
            await interaction.followup.send(
                "Select your teammate to register as a team:",
                view=view,
                ephemeral=True
            )
            return

        # ── Solo path (unchanged) ──────────────────────────────────────────────
        player_registered = await self.get_registration_status(interaction)
        if player_registered:
            await interaction.followup.send("You are already registered.", ephemeral=True)
            return

        result = await self.tm.register_player(user_id)
        if result == 'late_registration_closed':
            await interaction.followup.send(
                "Registration is closed — this event has already started.", ephemeral=True
            )
        elif result == 'no_ranked_account':
            await interaction.followup.send(
                "You need a UCH Ranked account to participate in this event. "
                "You can sign up at <https://uchranked.com>.",
                ephemeral=True
            )
        elif result == 'pending':
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

        if self.tm.is_teams_mode:
            # Check confirmed team
            t = await self.tm.get_tournament()
            team_id = self.tm._find_team_id_for_player(t, user_id)
            if team_id:
                await self.tm.unregister_player(user_id)
                await interaction.followup.send(
                    f"Your team has been unregistered from {tournament['name']}.",
                    ephemeral=True
                )
            else:
                # Check pending invite and cancel it
                pending = await self.tm.bot.dh.get_pending_teams(t['_id'])
                my_pending = next(
                    (pt for pt in pending
                     if pt['player1_id'] == user_id or pt['player2_id'] == user_id),
                    None
                )
                if my_pending:
                    await self.tm.bot.dh.remove_pending_team(
                        t['_id'], my_pending['player1_id'], my_pending['player2_id']
                    )
                    await interaction.followup.send(
                        "Your pending team invite has been cancelled.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "You are not registered for this event.", ephemeral=True
                    )
            return

        # ── Solo path ──────────────────────────────────────────────────────────
        player_registered = await self.get_registration_status(interaction)
        if player_registered:
            await self.tm.unregister_player(user_id)
        await interaction.followup.send(
            f"You have been unregistered from {tournament['name']}", ephemeral=True
        )

    async def get_registration_status(self, interaction):
        user_id = interaction.user.id
        category_id = interaction.channel.category_id
        tournament = await self.tm.bot.dh.get_tournament(category_id=category_id)

        if self.tm.is_teams_mode:
            t = await self.tm.get_tournament()
            return self.tm._find_team_id_for_player(t, user_id) is not None

        return await self.tm.bot.dh.get_registration_status(tournament['_id'], user_id)