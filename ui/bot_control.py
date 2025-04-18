import discord

from utils.emojis import INDICATOR_EMOJIS
from .confirmation import ConfirmationView
from .link_view import LinkView

class AddLinkModal(discord.ui.Modal, title="Add Link"):
    link_url = discord.ui.TextInput(label="URL", placeholder="Enter the URL")
    link_name = discord.ui.TextInput(label="Button Text", placeholder="Enter the name of the link")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.link_name.value, self.link_url.value)

class BotControlView(discord.ui.View):
    def __init__(self, tournament_manager):
        super().__init__(timeout=None)
        self.tm = tournament_manager
        self.channels_hidden = True
        
        name = self.tm.tournament['name']
        self.reveal_button = discord.ui.Button(label=f"Reveal Category {INDICATOR_EMOJIS['eye']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-reveal")
        self.checkin_button = discord.ui.Button(label=f"Start Check-in {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_checkin")
        self.start_button = discord.ui.Button(label=f"Start Tournament {INDICATOR_EMOJIS['game_controller']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_tournament")
        self.reset_button = discord.ui.Button(label=f"Reset Tournament {INDICATOR_EMOJIS['rotating_arrows']}", style=discord.ButtonStyle.danger, custom_id=f"{name}-reset")
        self.add_link_button = discord.ui.Button(label=f"Add Link{INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.danger, custom_id=f"{name}-link")
        
        
        self.reveal_button.callback = self.toggle_reveal_category
        self.checkin_button.callback = self.start_checkin
        self.start_button.callback = self.start_tournament
        self.reset_button.callback = self.reset_tournament
        self.add_link_button.callback = self.input_link
        
        self.add_item(self.reveal_button)
        self.add_item(self.checkin_button)
        self.add_item(self.start_button)
        self.add_item(self.reset_button)
        self.add_item(self.add_link_button)
        
    async def toggle_reveal_category(self, interaction: discord.Interaction):
        button = self.reveal_button
        tournament = await self.tm.get_tournament()
        if interaction.user.id != tournament['organizer']:
            await interaction.response.send_message("Only the TO is authorized to do this.", ephemeral=True)
        
        await self.tm.toggle_reveal_channels()
        self.channels_hidden = not self.channels_hidden
        if self.channels_hidden:
            button.label=f"Hide Category {INDICATOR_EMOJIS['eye']}"
        else: 
            button.label=f"Hide Category {INDICATOR_EMOJIS['lock']}"  
        await interaction.response.edit_message(view=self)
        
    async def start_checkin(self, interaction: discord.Interaction):
        await self.tm.start_checkin()
        message_content = (
            'Starting checkin...'
        )
        await interaction.response.send_message(content=message_content, ephemeral=True)
        
    async def start_tournament(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        tournament = await self.tm.get_tournament()
        
        embed = discord.Embed(
            title="Are you sure you want to start the tournament?",
            color=discord.Color.yellow()
        )
        view = ConfirmationView(self.tm.start_tournament, user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    async def reset_tournament(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        embed = discord.Embed(
            title="**Warning**",
            description="Resetting the tournament will undo any matches that have already been reported. Are you **absolutely sure** you want to reset the tournament?",
            color=discord.Color.red()
        )
        view = ConfirmationView(self.tm.reset_tournament, user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    async def input_link(self, interaction: discord.Interaction):
        modal = AddLinkModal(self.add_link)
        await interaction.response.send_modal(modal)
        
    async def add_link(self, interaction: discord.Interaction, link_label, link_url):
        channel = await self.tm.get_channel('event-info')
        link_view = LinkView(link_label, link_url)
        await channel.send(view=link_view)
        message_content = "Link added successfully"
        await interaction.response.send_message(message_content, ephemeral=True)
        

        

        