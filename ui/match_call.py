import discord

class MatchCallView(discord.ui.View):
    def __init__(self, tournament_manager, match_data, match_held=False):
        super().__init__()
        self.tm = tournament_manager
        self.match_data = match_data
        self.match_held = match_held

        self.call_match_button = discord.ui.Button(
            label='Call Match', style=discord.ButtonStyle.primary
        )
        self.hold_match_button = discord.ui.Button(
            label='Hold Match', style=discord.ButtonStyle.primary
        )
        self.start_held_match_button = discord.ui.Button(
            label='Start Held Match', style=discord.ButtonStyle.primary
        )

        self.call_match_button.callback = self.call_match
        self.hold_match_button.callback = self.hold_match
        self.start_held_match_button.callback = self.start_held_match

        self.add_items()

    def add_items(self):
        self.clear_items()
        if self.match_held:
            self.add_item(self.start_held_match_button)
        else:
            self.add_item(self.call_match_button)
            self.add_item(self.hold_match_button)

    async def add_message(self, message):
        self.message = message

    async def call_match(self, interaction: discord.Interaction):
        await self.tm.call_match(self.match_data)
        await interaction.response.defer()

    async def hold_match(self, interaction: discord.Interaction):
        await self.tm.call_match(self.match_data, hold_match=True)
        self.match_held=True
        self.add_items()
        await self.message.edit(view=self)
        await interaction.response.defer()

    async def start_held_match(self, interaction: discord.Interaction):
        await self.tm.start_held_match(self.match_data)
        
