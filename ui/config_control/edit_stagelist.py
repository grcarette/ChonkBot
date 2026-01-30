import discord
from utils.emojis import INDICATOR_EMOJIS
from .config_components import AddStageModal, RandomStageModal

import functools

class EditStagelistView(discord.ui.View):
    def __init__(self, tournament_control):
        super().__init__()
        self.tc = tournament_control

    async def setup(self):
        tournament = await self.tc.tm.get_tournament()
        dh = self.tc.dh
        for map_code in tournament['stagelist']:
            await self.add_stage_button(map_code)
                
        add_stage_button = discord.ui.Button(
            label=f"Add Stage {INDICATOR_EMOJIS['tools']}", 
            style=discord.ButtonStyle.primary,
            row=4
            )
        add_random_stages_button = discord.ui.Button(
            label=f"Add Random Stages {INDICATOR_EMOJIS['dice']}", 
            style=discord.ButtonStyle.primary,
            row=4
        )
        submit_changes_button = discord.ui.Button(
            label=f"Submit Changes {INDICATOR_EMOJIS['green_check']}", 
            style=discord.ButtonStyle.success,
            row=4
        )

        add_stage_button.callback = self.input_stages
        add_random_stages_button.callback = self.input_stage_count
        submit_changes_button.callback = self.submit_changes
        
        self.add_item(add_stage_button)
        self.add_item(add_random_stages_button)
        self.add_item(submit_changes_button)

    async def add_stage_button(self, stage_code):
        dh = self.tc.dh
        tournament = await self.tc.tm.get_tournament()
        stage = await dh.get_stage(code=stage_code)
        if not stage:
            return False

        button_label = stage['name']
        delete_button = discord.ui.Button(
            label=f"{INDICATOR_EMOJIS['red_x']} {button_label}",
            style=discord.ButtonStyle.secondary
        )

        async def delete_callback(interaction: discord.Interaction, map_code, pressed_button):
            await dh.remove_stage_from_tournament(tournament['_id'], map_code)
            self.remove_item(pressed_button)
            await interaction.response.edit_message(view=self)
        delete_button.callback = functools.partial(delete_callback, map_code=stage_code, pressed_button=delete_button)
        self.add_item(delete_button) 

    async def input_stages(self, interaction: discord.Interaction):
        modal = AddStageModal(self.add_stages)
        await interaction.response.send_modal(modal)

    async def add_stages(self, interaction, stage_list):
        stages = []
        stage_list = stage_list.split(',')
        await interaction.response.defer()
        invalid_stages = []
        for stage_code in stage_list:
            stage = await self.tc.dh.get_stage(code=stage_code)
            if not stage:
                invalid_stages.append(stage_code)
            else:
                stages.append(stage_code)
                await self.add_stage_button(stage_code)
        if len(invalid_stages) > 0:
            message_content = (
                f"Error: The following stage codes are invalid: `{', '.join(invalid_stages)}`\n"
                "Make sure you are sending valid stage codes separated by a comma"
            )
            await interaction.followup.send(content=message_content, ephemeral=True)
        if len(stages) > 0:
            await self.tc.add_stages(stages)
        await interaction.edit_original_response(view=self)

    async def input_stage_count(self, interaction: discord.Interaction):
        modal = RandomStageModal(self.add_random_stages)
        await interaction.response.send_modal(modal)
        
    async def add_random_stages(self, interaction: discord.Interaction, stage_count):
        await interaction.response.defer()
        random_stages = await self.tc.add_random_stages(int(stage_count))
        for stage_code in random_stages:
            await self.add_stage_button(stage_code)

        await interaction.edit_original_response(view=self)

    async def submit_changes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.delete_original_response()
        
        await self.tc.refresh_stagelist()
