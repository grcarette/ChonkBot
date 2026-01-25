import discord
from utils.emojis import INDICATOR_EMOJIS

class ToggleButton(discord.ui.Button):
    def __init__(self, *, label: str, state: bool = False, on_toggle: callable = None, emoji_map=None, state_map=None, row: int = 0, style=None, custom_id=None):
        self.state = state
        self.on_toggle = on_toggle
        self.emoji_map = emoji_map or {
            True: INDICATOR_EMOJIS['red_x'],
            False: INDICATOR_EMOJIS['green_check']
        }
        self.state_map = state_map or {
            True: "Disable",
            False: "Enable"
        }
        self.base_label = label
        style = style or discord.ButtonStyle.secondary
        label_with_emoji = f"{self.state_map[self.state]} {self.base_label} {self.emoji_map[self.state]}"

        super().__init__(label=label_with_emoji, style=style, row=row, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        self.state = not self.state
        self.label = f"{self.state_map[self.state]} {self.base_label} {self.emoji_map[self.state]}"

        if self.on_toggle is not None:
            await self.on_toggle(interaction, self.state)

        await interaction.response.edit_message(view=self.view)
