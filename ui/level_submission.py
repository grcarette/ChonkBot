import discord
import re

class LevelConfigModal(discord.ui.Modal, title="Create Level"):
    name = discord.ui.TextInput(label="Name", placeholder="Enter the Level Name")
    level_code = discord.ui.TextInput(label="Level Code", placeholder="Enter the Level Code")
    imgur = discord.ui.TextInput(label="Imgur", placeholder="Enter the Imgur Link")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.name.value, self.level_code.value, self.imgur.value)
        
class SubmitLevelButton(discord.ui.View):
    def __init__(self, bot, timeout = None):
        self.bot = bot
        super().__init__(timeout=timeout)
        
    @discord.ui.button(label="Submit Level", style=discord.ButtonStyle.primary, custom_id="Submit_Level")
    async def submit_level(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        view = LevelSubmissionView(self.bot, user)
        await interaction.response.send_message(view=view, ephemeral=True)

class LevelSubmissionView(discord.ui.View):
    def __init__(self, bot, user):
        super().__init__()
        self.bot = bot
        self.user = user
        
        self.type = None
        self.name = None
        self.code = None
        self.imgur = None
        
        self.party_button = discord.ui.Button(label='Party', style=discord.ButtonStyle.secondary)
        self.challenge_button = discord.ui.Button(label='Challenge', style=discord.ButtonStyle.secondary)
        self.submit_button = discord.ui.Button(label='Submit', style=discord.ButtonStyle.success)
        self.modal_button = discord.ui.Button(label='Enter Level Info', style=discord.ButtonStyle.primary)
        
        self.party_button.callback = self.toggle_party_mode
        self.challenge_button.callback = self.toggle_challenge_mode
        self.submit_button.callback = self.submit_level
        self.modal_button.callback = self.enter_level_info
        
        self.add_item(self.party_button)
        self.add_item(self.challenge_button)
        self.add_item(self.modal_button)
        self.add_item(self.submit_button)
        
        self.required_responses = {
            'type': {
                'value': lambda: self.type,
                'components': [self.party_button, self.challenge_button]
            },
            'code': {
                'value': lambda: self.code,
                'components': [self.modal_button]
            },
            'imgur': {
                'value': lambda: self.imgur,
                'components': [self.modal_button]
            },
            'name': {
                'value': lambda: self.name,
                'components': [self.modal_button]
            }
        }
        
    async def toggle_party_mode(self, interaction: discord.Interaction):
        self.type = 'Party'
        self.party_button.style = discord.ButtonStyle.primary
        self.challenge_button.style = discord.ButtonStyle.secondary
        
        await interaction.response.edit_message(view=self)
    
    async def toggle_challenge_mode(self, interaction: discord.Interaction):
        self.type = 'Challenge'
        self.party_button.style = discord.ButtonStyle.secondary
        self.challenge_button.style = discord.ButtonStyle.primary
        
        await interaction.response.edit_message(view=self)
        
    async def submit_level(self, interaction: discord.Interaction):
        required_responses = [self.type, self.code, self.imgur]
        if None not in required_responses:
            user = interaction.user
            level_submitted = await self.bot.dh.add_level(self.name, self.type, user, self.code, self.imgur)
            if level_submitted == 'creator_match':
                message_content = (
                    'You have already submitted this level, would you like to replace it?'
                )
                await interaction.response.send_message(message_content, ephemeral=True)
            elif level_submitted == 'creator_mismatch':
                message_content = (
                    'Someone else has already submitted this level.'
                )
                await interaction.response.send_message(message_content, ephemeral=True)
            else:
                message_id = await self.bot.mh.submit_level(level_submitted)
                level = await self.bot.dh.add_message_to_level(self.code, message_id)
        else:
            for response in self.required_responses:
                if self.required_responses[response]['value']() == None:
                    for component in self.required_responses[response]['components']:
                        component.style=discord.ButtonStyle.danger
            await interaction.response.edit_message(view=self)
        
    async def process_modal_submission(self, interaction: discord.Interaction, name, code, imgur):
        if not self.check_code(code):
            message_content = (
                'Please enter a valid level code (Format: XXXX-XXXX)'
            )
            await interaction.response.send_message(message_content, ephemeral=True)
            return
        if not self.check_imgur(imgur):
            message_content = (
                'Please enter a valid imgur link'
            )
            await interaction.response.defer()
            await interaction.followup.send(message_content, ephemeral=True)
            return

        self.name = name
        self.code = code
        self.imgur = imgur
        self.modal_button.style=discord.ButtonStyle.success
        await interaction.response.edit_message(view=self)
        
    def check_code(self, code):
        pattern = r'^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$'
        is_valid_code = bool(re.fullmatch(pattern, code))
        return is_valid_code
    
    def check_imgur(self, imgur):
        pattern = r"^https?://(www\.)?imgur\.com/([a-zA-Z0-9-_]+)(\.[a-zA-Z0-9]+)?$"
        is_valid_imgur = bool(re.fullmatch(pattern, imgur))
        return is_valid_imgur
        
    async def enter_level_info(self, interaction: discord.Interaction):
        modal=LevelConfigModal(self.process_modal_submission)
        await interaction.response.send_modal(modal)
        

    