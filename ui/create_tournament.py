import discord

from utils.emojis import INDICATOR_EMOJIS


class TournamentConfigModal(discord.ui.Modal, title="Create Tournament"):
    tournament_name = discord.ui.TextInput(
        label="Tournament Name", placeholder="Enter the event name"
    )
    tournament_date = discord.ui.TextInput(
        label="Tournament Date", placeholder="Enter the event time"
    )

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.tournament_name.value, self.tournament_date.value)


class RoundLimitModal(discord.ui.Modal, title="Swiss Round Limit"):
    round_limit = discord.ui.TextInput(
        label="Number of Rounds",
        placeholder="e.g. 8",
        max_length=3,
    )

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.round_limit.value)
            if value < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Round limit must be a positive whole number.", ephemeral=True
            )
            return
        await self.callback(interaction, value)


class TournamentSettingsView(discord.ui.View):
    def __init__(self, user, bot):
        super().__init__(timeout=None)
        self.user = user
        self.bot = bot
        self.tournament_name = ''
        self.tournament_date = ''

        self.tournament_format = None
        self.to_approved_registration = False
        self.randomized_stagelist = False
        self.display_entrants = False
        self.round_limit = 8  # default, only used for swiss

        self.config_button = None
        self.submit_button = None
        self.format_select = None

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "Submit":
                    self.submit_button = child
                elif child.label == "Set Name/Time":
                    self.config_button = child

    def toggle_label(self, state: bool) -> str:
        return INDICATOR_EMOJIS['green_check'] if state else INDICATOR_EMOJIS['red_x']

    @discord.ui.select(
        placeholder="Format",
        options=[
            discord.SelectOption(label="Single Elimination", value="single elimination"),
            discord.SelectOption(label="Double Elimination", value="double elimination"),
            discord.SelectOption(label="Swiss", value="swiss"),
            discord.SelectOption(label="FFA Filter (not currently supported)", value="FFA Filter"),
        ],
        row=1
    )
    async def tournament_format_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        self.tournament_format = select.values[0]
        select.placeholder = select.values[0]
        self.format_select = True

        if self.tournament_format == 'swiss':
            # Prompt for round limit immediately when swiss is selected
            modal = RoundLimitModal(self.set_round_limit)
            await interaction.response.send_modal(modal)
        else:
            self.round_limit = 8  # reset to default if format changed away from swiss
            self.check_submit_ready()
            await interaction.response.edit_message(view=self)

    async def set_round_limit(self, interaction: discord.Interaction, value: int):
        self.round_limit = value
        self.check_submit_ready()
        await interaction.response.edit_message(
            content=f"Round limit set to **{value}**.", view=self
        )

    @discord.ui.button(label="Set Name/Time", style=discord.ButtonStyle.primary, row=2)
    async def input_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message(
                "Only the TO is authorized to do this.", ephemeral=True
            )
            return
        modal = TournamentConfigModal(self.set_name_and_date)
        await interaction.response.send_modal(modal)

    async def set_name_and_date(self, interaction, name, date):
        self.tournament_name = name
        self.tournament_date = date
        self.check_submit_ready()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(
        label="Submit", style=discord.ButtonStyle.success, disabled=True, row=2
    )
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.tournament_name or not self.tournament_format:
            await interaction.response.send_message(
                "Please set a tournament name and format before submitting.", ephemeral=True
            )
            return
        if interaction.user != self.user:
            await interaction.response.send_message(
                "Only the TO is authorized to do this.", ephemeral=True
            )
            return

        tournament_data = {
            'name': self.tournament_name,
            'date': self.tournament_date,
            'organizer': interaction.user.id,
            'format': self.tournament_format,
            'approved_registration': self.to_approved_registration,
            'randomized_stagelist': self.randomized_stagelist,
            'display_entrants': self.display_entrants,
            'round_limit': self.round_limit,
        }
        await self.bot.th.set_up_tournament(tournament_data)
        await interaction.response.edit_message(
            content="Tournament created!", view=None
        )
        
    def check_submit_ready(self):
        if self.tournament_name and self.tournament_format:
            if self.submit_button is not None:
                self.submit_button.disabled = False