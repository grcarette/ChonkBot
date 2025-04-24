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
        await self.callback(interaction, self.tournament_timestamp.value)
        
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
        
    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        await self.cc.tm.add_assistant(selected_user)
        await interaction.response.send_message(f"You selected user {selected_user.mention}", ephemeral=True)
        
class AddLinkModal(discord.ui.Modal, title="Add Link"):
    link_url = discord.ui.TextInput(label="URL", placeholder="Enter the URL")
    link_name = discord.ui.TextInput(label="Button Text", placeholder="Enter the name of the link")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.link_name.value, self.link_url.value)