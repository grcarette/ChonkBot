import discord
from utils.emojis import INDICATOR_EMOJIS
from .config_components import AddLinkModal

import functools

class EditLinksView(discord.ui.View):
    def __init__(self, tournament_info_display):
        super().__init__()
        self.tid = tournament_info_display
        self.info_display_view = self.tid.info_display_view
        
        for child in self.info_display_view.children:
            if isinstance(child, discord.ui.Button):
                delete_button = discord.ui.Button(
                    label=f"{INDICATOR_EMOJIS['red_x']} {child.label}",
                    style=discord.ButtonStyle.primary
                )
                
                async def delete_callback(interaction: discord.Interaction, target_button, pressed_button):
                    self.info_display_view.remove_item(target_button)
                    await self.tid.update_display()
                    pressed_button.disabled = True
                    await interaction.response.edit_message(view=self)
                    
                delete_button.callback = functools.partial(delete_callback, target_button=child, pressed_button=delete_button)
                self.add_item(delete_button)
                
        add_link_button = discord.ui.Button(label=f"Add Link {INDICATOR_EMOJIS['link']}", style=discord.ButtonStyle.success)
        add_link_button.callback = self.input_link
        self.add_item(add_link_button)
        
    async def input_link(self, interaction: discord.Interaction):
        modal = AddLinkModal(self.add_link)
        await interaction.response.send_modal(modal)
        
    async def add_link(self, interaction: discord.Interaction, link_label, link_url):
        await self.tid.add_link(link_label, link_url)
        await interaction.response.send_message(F"Link added successfully {INDICATOR_EMOJIS['green_check']}", ephemeral=True)

