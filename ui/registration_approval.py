import discord

class RegistrationDenyModal(discord.ui.Modal, title="Deny Registration"):
    deny_reason = discord.ui.TextInput(label="Reason", placeholder="Cite your reason for denying")
    
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        
    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.deny_reason.value)

class RegistrationApprovalView(discord.ui.View):
    def __init__(self, tournament_manager, player_id, timeout=None):
        super().__init__(timeout=timeout)
        self.tm = tournament_manager
        self.player_id = player_id
        
        name = self.tm.tournament['name']
        self.approve_button = discord.ui.Button(label='Approve', style=discord.ButtonStyle.success, custom_id=f'{name}{self.player_id}-approve')
        self.deny_button = discord.ui.Button(label='Deny', style=discord.ButtonStyle.danger, custom_id=f'{name}{self.player_id}-deny')
        
        self.approve_button.callback = self.approve_registration
        self.deny_button.callback = self.deny_registration
        
        self.add_item(self.approve_button)
        self.add_item(self.deny_button)
        
    async def get_user(self):
        guild = self.tm.bot.guild
        user = discord.utils.get(guild.members, id=self.player_id)
        return user
        
    async def approve_registration(self, interaction: discord.Interaction):
        user = await self.get_user()
        tournament = self.tm.tournament['name']
        message = interaction.message
        message_content = (
            f"Your registration to {tournament} has been approved."
        )
        embed = discord.Embed(
            title="Registration Approved",
            description=message_content,
            color=discord.Color.green()
        )
        await user.send(embed=embed)
        await message.delete()
    
    async def deny_registration(self, interaction: discord.Interaction):
        modal = RegistrationDenyModal(self.send_deny_reason)
        await interaction.response.send_modal(modal)
        
    async def send_deny_reason(self, interaction: discord.Interaction, deny_reason):
        user = await self.get_user()
        tournament = self.tm.tournament['name']
        message = interaction.message
        
        message_content = (
            f'Your registration to {tournament} has been denied.\n'
            f'Reason: `{deny_reason}`'
        )
        embed = discord.Embed(
            title='Registration Denied',
            description=message_content,
            color=discord.Color.red()
        )
        try:
            await user.send(embed=embed)
            message_content = (
                "Registration denied successfully"
            )
        except discord.Forbidden:
            message_content = (
                "Error: Could not send dm to user. They likely have private DMS enabled\n"
                "The registration has been denied successfully,"
                " but you may need to manually inform the user that their registration has been denied"
            )
        await interaction.response.send_message(message_content, ephemeral=True)
        await message.delete()
            
        