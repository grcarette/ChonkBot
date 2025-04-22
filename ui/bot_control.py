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
        self.message = None
        self.stage = 'setup'
        
        name = self.tm.tournament['name']
        self.publish_button = discord.ui.Button(
            label=f"Publish Tournament {INDICATOR_EMOJIS['eye']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-publish"
            )
        self.checkin_button = discord.ui.Button(
            label=f"Start Check-in {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_checkin"
            )
        self.start_button = discord.ui.Button(
            label=f"Start Tournament {INDICATOR_EMOJIS['game_controller']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_tournament"
            )
        self.reset_button = discord.ui.Button(
            label=f"Reset Tournament {INDICATOR_EMOJIS['rotating_arrows']}", style=discord.ButtonStyle.danger, custom_id=f"{name}-reset"
            )
        self.add_link_button = discord.ui.Button(
            label=f"Add Link{INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-link"
            )
        self.open_reg_button = discord.ui.Button(
            label=f"Open Registration{INDICATOR_EMOJIS['notepad']}", style=discord.ButtonStyle.success, custom_id=f"{name}-open_reg", disabled=True
            )
        self.close_reg_button = discord.ui.Button(
            label=f"Close Registration{INDICATOR_EMOJIS['notepad']}", style=discord.ButtonStyle.success, custom_id=f"{name}-close_reg", disabled=False
            )
        
        self.publish_button.callback = self.publish_tournament
        self.checkin_button.callback = self.start_checkin
        self.start_button.callback = self.start_tournament
        self.reset_button.callback = self.reset_tournament
        self.add_link_button.callback = self.input_link
        self.open_reg_button.callback = self.open_registration
        self.close_reg_button.callback = self.close_registration
                
    async def publish_tournament(self, interaction: discord.Interaction):
        tournament = await self.tm.get_tournament()
        if interaction.user.id != tournament['organizer']:
            await interaction.response.send_message("Only the TO is authorized to do this.", ephemeral=True)
        else:
            await interaction.response.defer()
            await self.tm.publish_tournament()
            
    async def open_registration(self, interaction: discord.Interaction):
        self.open_reg_button.disabled=True
        self.close_reg_button.disabled=False
        await interaction.response.edit_message(view=self)
        await self.tm.open_registration()
    
    async def close_registration(self, interaction: discord.Interaction):
        self.close_reg_button.disabled=True
        self.open_reg_button.disabled=False
        await interaction.response.edit_message(view=self)
        await self.tm.close_registration()
        
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
        
    async def update_tournament_state(self, state):
        if self.message == None:
            self.message = await self.get_control_message()
        self.clear_items()
        self.stage = state
        if state == 'setup':
            self.add_item(self.add_link_button)
            # self.add_item(self.add_stage_button)
            self.add_item(self.publish_button)
        elif state == 'registration':
            self.add_item(self.open_reg_button)
            self.add_item(self.close_reg_button)
            self.add_item(self.add_link_button)
            # self.add_item(self.edit_stagelist_button)
            self.add_item(self.checkin_button)
        elif state == 'checkin':
            # self.add_item(self.close_checkin_button)
            self.add_item(self.start_button)
            self.add_item(self.add_link_button)
        elif state == 'active':
            self.add_item(self.reset_button)
            self.add_item(self.add_link_button)
        elif state == 'finished':
            self.add_item(self.add_link_button)
            
        embed = await self.generate_embed()
        await self.message.edit(view=self, embed=embed)
            
    async def get_control_message(self):
        channel = await self.tm.get_channel('bot-control')
        bot_id = self.tm.bot.id
        
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id == bot_id:
                return message
            
        return None
    
    async def generate_embed(self):
        embed = discord.Embed(
            title="Tournament Controls",
            description=f"Stage: {self.stage}",
            color=discord.Color.green()
        )
        return embed
        
        
    
        

        

        