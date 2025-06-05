import discord

class DQPlayerSelectMenu(discord.ui.UserSelect):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc

    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        result = await self.tc.disqualify_player(selected_user.id)
        if result:
            message_content = (
                f"Player {selected_user.mention} has been disqualified"
            )
        else:
            message_content = (
                f"Player {selected_user.mention} could not be disqualified"
            )
        await interaction.response.send_message(message_content, ephemeral=True)

class RemoveDQPlayerSelectMenu(discord.ui.UserSelect):
    def __init__(self, config_control):
        super().__init__()
        self.cc = config_control
        self.tc = self.cc.tc

    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        result = await self.tc.undisqualify_player(selected_user.id)
        if result:
            message_content = (
                f"Player {selected_user.mention} has been disqualified"
            )
        else:
            message_content = (
                f"Player {selected_user.mention} could not be disqualified"
            )
        await interaction.response.send_message(message_content, ephemeral=True)