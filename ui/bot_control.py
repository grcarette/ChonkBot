import discord

from utils.emojis import INDICATOR_EMOJIS
from .confirmation import ConfirmationView

class BotControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.channels_hidden = True
        
    @discord.ui.button(label=f"Reveal Category {INDICATOR_EMOJIS['eye']}", style=discord.ButtonStyle.primary, custom_id="control_tournament")
    async def toggle_reveal_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        category_id = interaction.channel.category_id
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        if interaction.user.id != tournament['organizer']:
            await interaction.response.send_message("Only the TO is authorized to do this.", ephemeral=True)
        
        await self.bot.th.toggle_reveal_channels(tournament['category_id'])
        self.channels_hidden = not self.channels_hidden
        if self.channels_hidden:
            button.label=f"Hide Category {INDICATOR_EMOJIS['eye']}"
        else: 
            button.label=f"Hide Category {INDICATOR_EMOJIS['lock']}"  
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label=f"Start Check-in {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success, custom_id="start_checkin")
    async def start_checkin(self, interaction: discord.Interaction, button: discord.ui.Button):
        category_id = interaction.channel.category_id
        await self.bot.th.start_checkin(category_id)
        message_content = (
            'Starting checkin...'
        )
        await interaction.response.send_message(content=message_content, ephemeral=True)
        
    @discord.ui.button(label=f"Start Tournament {INDICATOR_EMOJIS['game_controller']}", style=discord.ButtonStyle.success, custom_id="start_tournament")
    async def start_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        category_id = interaction.channel.category_id
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        
        embed = discord.Embed(
            title="Are you sure you want to start the tournament?",
            color=discord.Color.yellow()
        )
        view = ConfirmationView(self.bot.th.start_tournament, tournament['category_id'])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        

        