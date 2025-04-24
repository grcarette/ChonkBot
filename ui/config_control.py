import discord

from utils.emojis import INDICATOR_EMOJIS
from .config_components import AddStageModal, AddTOSelectMenu, AddLinkModal, TournamentNameModal, TournamentTimeModal
from .link_view import LinkView
from .configure_tournament import TournamentConfigView

class ConfigControlView(discord.ui.View):
    def __init__(self, tournament_control, timeout=None):
        super().__init__(timeout=timeout)
        self.tc = tournament_control
        self.tm = self.tc.tm
        self.message = None
        self.embed_title = "Tournament Configuration"

        name = self.tm.tournament['name']
        self.configure_tournament_button = discord.ui.Button(
            label=f"Configure Tournament {INDICATOR_EMOJIS['gear']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-configure"
            )
        self.add_assistant_button = discord.ui.Button(
            label=f"Add Assistant TO {INDICATOR_EMOJIS['clipboard']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-add_assistant"
            )
        self.add_link_button = discord.ui.Button(
            label=f"Add Link{INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-link"
            )
        self.add_stage_button = discord.ui.Button(
            label=f"Add Stage(s) {INDICATOR_EMOJIS['tools']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-add_stages"
            )

        self.configure_tournament_button.callback = self.configure_tournament
        self.add_assistant_button.callback = self.add_assistant
        self.add_link_button.callback = self.input_link
        self.add_stage_button.callback = self.input_stages

    async def update_control(self):
        if self.message == None:
            self.message = await self.get_control_message()
        self.clear_items()
        self.add_item(self.configure_tournament_button)
        self.add_item(self.add_assistant_button)
        self.add_item(self.add_link_button)
        self.add_item(self.add_stage_button)
        
        embed = await self.generate_embed()
        await self.message.edit(view=self, embed=embed)
        
    async def configure_tournament(self, interaction: discord.Interaction):
        view = TournamentConfigView(self)
        await interaction.response.send_message(view=view, ephemeral=True)
        
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
        
    async def generate_embed(self):
        description = await self.get_control_panel_info()
        embed = discord.Embed(
            title="Tournament Configuration",
            description=description,
            color=discord.Color.blue()
        )
        return embed
    
    async def get_control_panel_info(self):
        tournament = await self.tm.get_tournament()
        if 'name' in tournament:
            tournament_name = tournament['name']
        else:
            tournament_name = 'N/A'
        if 'date' in tournament:
            tournament_date = tournament['date']
        else:
            tournament_date = 'TBD'
        if 'format' in tournament:
            tournament_format = tournament['format']
        else:
            tournament_format = 'N/A'
        if len(tournament['stagelist']) > 0:
            tournament_stagelist = "\n-".join(tournament['stagelist'])
        else:
            tournament_stagelist = "N/A"

        message_content = (
            f"**Name:** {tournament_name}\n"
            f"**Date:** {tournament_date}\n"
            f"**Format:** {tournament_format}\n"
            f"**State:** {tournament['state']}\n"
            f"**Stagelist:**\n-{tournament_stagelist}\n"
        )
        return message_content
    
    async def get_control_message(self):
        channel = await self.tm.get_channel('bot-control')
        bot_id = self.tm.bot.id
        
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id == bot_id and message.embeds:
                embed = message.embeds[0]
                if self.embed_title in embed.title:
                    return message
            
        return None
    
    