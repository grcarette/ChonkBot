import discord

from utils.emojis import INDICATOR_EMOJIS

from .link_view import LinkView

class AddStageModal(discord.ui.Modal, title="Add Stage(s)"):
    stage_list = discord.ui.TextInput(label="Stages", placeholder="Enter stage codes separated by ','")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.stage_list.value)

class AddTOSelectMenu(discord.ui.UserSelect):
    def __init__(self, bot_control):
        super().__init__()
        self.bc = bot_control
        
    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        await self.bc.tm.add_assistant(selected_user)
        await interaction.response.send_message(f"You selected user {selected_user.mention}", ephemeral=True)
        
class AddLinkModal(discord.ui.Modal, title="Add Link"):
    link_url = discord.ui.TextInput(label="URL", placeholder="Enter the URL")
    link_name = discord.ui.TextInput(label="Button Text", placeholder="Enter the name of the link")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.link_name.value, self.link_url.value)

class ConfigControlView(discord.ui.View):
    def __init__(self, tournament_control, timeout=None):
        super().__init__(timeout=timeout)
        self.tc = tournament_control
        self.tm = self.tc.tm
        self.embed_title = "Tournament Configuration"
        
        name = self.tm.tournament['name']
        self.add_assistant_button = discord.ui.Button(
            label=f"Add Assistant TO {INDICATOR_EMOJIS['clipboard']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-add_assistant"
            )
        self.add_link_button = discord.ui.Button(
            label=f"Add Link{INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-link"
            )
        self.add_stage_button = discord.ui.Button(
            label=f"Add Stage(s) {INDICATOR_EMOJIS['tools']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-add_stages"
            )
        
        self.add_assistant_button.callback = self.add_assistant
        self.add_link_button.callback = self.input_link
        self.add_stage_button.callback = self.input_stages
        
        self.add_item(self.add_assistant_button)
        self.add_item(self.add_link_button)
        self.add_item(self.add_stage_button)
        
    async def add_assistant(self, interaction: discord.Interaction):
        view = discord.ui.View()
        view.add_item(AddTOSelectMenu(self))
        await interaction.response.send_message(view=view, ephemeral=True)
        
    async def input_link(self, interaction: discord.Interaction):
        modal = AddLinkModal(self.add_link)
        await interaction.response.send_modal(modal)
        
    async def add_link(self, interaction: discord.Interaction, link_label, link_url):
        channel = await self.tm.get_channel('event-info')
        link_view = LinkView(link_label, link_url)
        await channel.send(view=link_view)
        message_content = "Link added successfully"
        await interaction.response.send_message(message_content, ephemeral=True)
        
    async def input_stages(self, interaction: discord.Interaction):
        modal = AddStageModal(self.add_stages)
        await interaction.response.send_modal(modal)
            
    async def add_stages(self, interaction, stage_list):
        result = await self.tm.add_stages(stage_list)
        if result != True:
            message_content = (
                f"Error: `{result}` is not a valid stage code\n"
                "Make sure you are sending valid stage codes separated by a comma"
            )
            await interaction.response.send_message(message_content)
        else:
            await interaction.response.send_message("Success!", ephemeral=True)
        #go through stages
        #add each stage to stagelist
        #if stage isnt in db, add stage to to do list
        
    async def generate_embed(self):
        description = await self.get_control_panel_info()
        embed = discord.Embed(
            title="Tournament Configuration",
            description=description,
            color=discord.Color.blue()
        )
        return embed
    
    async def get_control_panel_info(self):
        return "TBD"