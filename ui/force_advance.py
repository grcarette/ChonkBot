import discord


class ForceAdvanceView(discord.ui.View):
    """
    Shown to the TO after /force_advance_lobby.
    First select: choose target state.
    If 'winner', a second select appears to pick the winning player.
    """
    def __init__(self, match_lobby, lobby_data):
        super().__init__(timeout=60)
        self.match_lobby = match_lobby
        self.lobby_data = lobby_data

        state_select = discord.ui.Select(
            placeholder="Choose target state...",
            options=[
                discord.SelectOption(
                    label="Stage Bans",
                    value="stage_bans",
                    description="Reset and re-run stage banning"
                ),
                discord.SelectOption(
                    label="Reporting",
                    value="reporting",
                    description="Skip to reporting (picks a random stage if needed)"
                ),
                discord.SelectOption(
                    label="Declare Winner",
                    value="winner",
                    description="Report a result and progress the bracket"
                ),
            ]
        )
        state_select.callback = self.on_state_select
        self.add_item(state_select)

    async def on_state_select(self, interaction: discord.Interaction):
        target_state = interaction.data['values'][0]

        if target_state == 'winner':
            winner_view = await ForceWinnerView.create(self.match_lobby)
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="⚠️ Declare Winner",
                    description="Select the player who **won** this match. This will be reported to Challonge.",
                    color=discord.Color.orange()
                ),
                view=winner_view
            )
        else:
            await interaction.response.defer()
            try:
                await self.match_lobby.force_advance(target_state)
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="✅ Lobby Advanced",
                        description=f"Lobby has been advanced to **{target_state.replace('_', ' ')}**.",
                        color=discord.Color.green()
                    ),
                    view=None
                )
            except Exception as e:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="❌ Force Advance Failed",
                        description=f"An error occurred: `{e}`",
                        color=discord.Color.red()
                    ),
                    view=None
                )


class ForceWinnerView(discord.ui.View):
    """
    Second step — shown when the TO selects 'Declare Winner'.
    Uses a setup() classmethod to resolve player names from the DB
    before building the Select options, since __init__ is synchronous.
    """
    def __init__(self, match_lobby):
        super().__init__(timeout=60)
        self.match_lobby = match_lobby

    @classmethod
    async def create(cls, match_lobby):
        self = cls(match_lobby)
        await self.setup()
        return self

    async def setup(self):
        options = []
        for player_id in self.match_lobby.remaining_players:
            user = await self.match_lobby.dh.get_user(user_id=player_id)
            name = user['name'] if user else str(player_id)
            options.append(discord.SelectOption(label=name, value=str(player_id)))

        winner_select = discord.ui.Select(
            placeholder="Select the winner...",
            options=options
        )
        winner_select.callback = self.on_winner_select
        self.add_item(winner_select)

    async def on_winner_select(self, interaction: discord.Interaction):
        winner_id = interaction.data['values'][0]
        await interaction.response.defer()
        try:
            await self.match_lobby.force_advance('winner', winner_id=winner_id)
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="✅ Winner Declared",
                    description=f"<@{winner_id}> has been declared the winner. The bracket has been updated.",
                    color=discord.Color.green()
                ),
                view=None
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="❌ Failed to Declare Winner",
                    description=f"An error occurred: `{e}`",
                    color=discord.Color.red()
                ),
                view=None
            )