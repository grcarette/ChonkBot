import discord

from utils.emojis import INDICATOR_EMOJIS

class TournamentConfigModal(discord.ui.Modal, title="Create Tournament"):
    tournament_name = discord.ui.TextInput(label="Tournament Name", placeholder="Enter the event name")
    tournament_date = discord.ui.TextInput(label="Tournament Date", placeholder="Enter the event time")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.tournament_name.value, self.tournament_date.value)
        
class TournamentSettingsView(discord.ui.View):
    def __init__(self, user, bot):
        super().__init__()
        self.user = user
        self.bot = bot
        self.tournament_name = ''
        self.tournament_date = ''
        
        self.tournament_format = None
        self.require_check_in = False
        self.to_approved_registration = False
        self.randomized_stagelist = False
        self.stage_bans = False
        
        self.config_button = None
        self.submit_button = None

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                print(child)
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
            discord.SelectOption(label="FFA Filter", value="FFA Filter"),
        ],
        row=1
    )
    async def tournament_format_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.tournament_format = select.values[0]
        select.placeholder = select.values[0]
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label="Set Name/Time", style=discord.ButtonStyle.primary, row=2)
    async def input_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("Only the TO is authorized to do this.", ephemeral=True)
            return
        
        modal = TournamentConfigModal(self.process_modal_submission)
        await interaction.response.send_modal(modal)
    
    async def process_modal_submission(self, interaction: discord.Interaction, name, time):
        self.tournament_name = name
        self.tournament_date = time
        if not self.config_button == None:
            self.config_button.label = f"{name} - {time}"
        if not self.submit_button == None:
            self.submit_button.disabled = False
        print(self.config_button, self.submit_button)
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label=f"Require Check-in {INDICATOR_EMOJIS['red_x']}", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.require_check_in = not self.require_check_in
        button.label = f"Require Check-in {self.toggle_label(self.require_check_in)}"
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label=f"Require Stage Bans {INDICATOR_EMOJIS['red_x']}", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_stage_bans(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stage_bans = not self.stage_bans
        button.label = f"Require Stage Bans {self.toggle_label(self.stage_bans)}"
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label=f"TO Approved Registrations {INDICATOR_EMOJIS['red_x']}", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_to_approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.to_approved_registration = not self.to_approved_registration
        button.label = f"TO Approved Registration {self.toggle_label(self.to_approved_registration)}"
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label=f"Randomized Stagelist {INDICATOR_EMOJIS['red_x']}", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_random_stagelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.randomized_stagelist = not self.randomized_stagelist
        button.label = f"Randomized Stagelist {self.toggle_label(self.randomized_stagelist)}"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label=f"Submit", style=discord.ButtonStyle.success, disabled=True, row=3)
    async def submit_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"Tournament `{self.tournament_name}` created.")
        await interaction.message.delete()
        tournament_data = {
            'name': self.tournament_name,
            'date': self.tournament_date,
            'organizer': self.user.id,
            'format': self.tournament_format,
            'check-in': self.require_check_in,
            'stage_bans': self.stage_bans,
            'approved_registration': self.to_approved_registration,
            'randomized_stagelist': self.randomized_stagelist,
        }
        await self.bot.th.set_up_tournament(tournament_data)
        self.stop()
        

