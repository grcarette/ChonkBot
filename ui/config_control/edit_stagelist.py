import discord
from utils.emojis import INDICATOR_EMOJIS
from .config_components import AddStageModal

import functools

class EditStagelistView(discord.ui.View):
    def __init__(self, tournament_control):
        super().__init__()
        self.tc = tournament_control

    
    async def setup(self):
        tournament = await self.tc.tm.get_tournament()
        dh = self.tc.dh
        for map_code in tournament['stagelist']:
            stage = await dh.get_stage(code=map_code)
            if stage:
                button_label = stage['name']
            else:
                button_label = map_code
            
            delete_button = discord.ui.Button(
                label=f"{INDICATOR_EMOJIS['red_x']} {button_label}",
                style=discord.ButtonStyle.primary
            )
            
            async def delete_callback(interaction: discord.Interaction, map_code, pressed_button):
                await dh.remove_stage_from_tournament(tournament['_id'], map_code)
                pressed_button.disabled = True
                await interaction.response.edit_message(view=self)
                await self.tc.refresh_stagelist()
                
            delete_button.callback = functools.partial(delete_callback, map_code=map_code, pressed_button=delete_button)
            self.add_item(delete_button)
                
        add_stage_button = discord.ui.Button(label=f"Add Link {INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.success)
        add_random_stages_button = discord.ui.Button(label=f"Add Random Stages {INDICATOR_EMOJIS['dice']}", style=discord.ButtonStyle.danger)
        
        add_stage_button.callback = self.input_stages
        add_random_stages_button.callback = self.add_random_stages
        
        self.add_item(add_stage_button)
        self.add_item(add_random_stages_button)
        
    async def input_stages(self, interaction: discord.Interaction):
        modal = AddStageModal(self.add_stages)
        await interaction.response.send_modal(modal)

    async def add_stages(self, interaction, stage_list):
        stages, result = await self.tc.check_stages(stage_list)
        if result != True:
            message_content = (
                f"Error: `{result}` is not a valid stage code\n"
                "Make sure you are sending valid stage codes separated by a comma"
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        else:
            await interaction.response.defer()
            await self.tc.add_stages(stages)
        
