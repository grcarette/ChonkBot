import discord
from utils.emojis import INDICATOR_EMOJIS

class ToggleButton(discord.ui.Button):
    def __init__(self, *, label: str, state: bool = False, emoji_map=None, row: int = 0, style=None, custom_id=None):
        self.state = state
        self.emoji_map = emoji_map or {
            True: INDICATOR_EMOJIS['green_check'],
            False: INDICATOR_EMOJIS['red_x']
        }
        style = style or discord.ButtonStyle.secondary
        label_with_emoji = f"{label} {self.emoji_map[self.state]}"

        super().__init__(label=label_with_emoji, style=style, row=row, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        self.state = not self.state
        self.label = f"{self.label.split(' ')[0]} {self.emoji_map[self.state]}"
        await interaction.response.edit_message(view=self.view)
