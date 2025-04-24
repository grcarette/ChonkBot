import discord

class TournamentNameModal(discord.ui.Modal, title="Create Tournament"):
    tournament_name = discord.ui.TextInput(label="Tournament Name", placeholder="Enter the event name")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.tournament_name.value)
        
class TournamentTimeModal(discord.ui.Modal, title="Set Tournament Timestamp"):
    tournament_timestamp = discord.ui.TextInput(label="Tournament Timestamp", placeholder="Enter the tournament timestamp")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.callback(self.tournament_timestamp.value)
        
class TournamentColorModal(discord.ui.Modal, title="Set Tournament Color"):
    tournament_color = discord.ui.TextInput(label="Tournament Color", placeholder="Enter the hexcode for the tournament color")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.callback(self.tournament_color.value)
        
class AddStageModal(discord.ui.Modal, title="Add Stage(s)"):
    stage_list = discord.ui.TextInput(label="Stages", placeholder="Enter stage codes separated by ','")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.stage_list.value)
        
class AddTOSelectMenu(discord.ui.UserSelect):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc
        
    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        await self.tc.edit_tournament_config(assistant=selected_user)
        await interaction.response.send_message(f"You selected user {selected_user.mention}", ephemeral=True)
        
class AddLinkModal(discord.ui.Modal, title="Add Link"):
    link_url = discord.ui.TextInput(label="URL", placeholder="Enter the URL")
    link_name = discord.ui.TextInput(label="Button Text", placeholder="Enter the name of the link")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.link_name.value, self.link_url.value)
        
class TournamentFormatSelect(discord.ui.Select):
    def __init__(self, config_control):
        self.cc = config_control
        self.tc = self.cc.tc
        super().__init__(
            placeholder="Format",
            options=[
                discord.SelectOption(label="single elimination", value="single elimination"),
                discord.SelectOption(label="double elimination", value="double elimination"),
                discord.SelectOption(label="swiss", value="swiss"),
                discord.SelectOption(label="FFA Filter", value="FFA Filter"),
            ],
            row=1
        )
        
    async def callback(self, interaction: discord.Interaction):
        selected_format = self.values[0]
        await self.tc.edit_tournament_config(format=selected_format)
        await interaction.response.defer()
        