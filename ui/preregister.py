# ui/preregister.py

import discord


class PreregisterSelect(discord.ui.UserSelect):
    def __init__(self, tm):
        super().__init__(placeholder="Select a player...")
        self.tm = tm

    async def callback(self, interaction: discord.Interaction):
        user = self.values[0]
        already_registered = await self.tm.bot.dh.get_registration_status(
            self.tm.tournament['_id'], user.id
        )
        if already_registered:
            await interaction.response.send_message(
                f"{user.display_name} is already registered.", ephemeral=True
            )
            return

        success = await self.tm.register_player(user.id)
        if success:
            await interaction.response.send_message(
                f"{user.display_name} has been pre-registered.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Failed to pre-register {user.display_name}.", ephemeral=True
            )


class PreregisterView(discord.ui.View):
    def __init__(self, tm):
        super().__init__(timeout=60)
        self.add_item(PreregisterSelect(tm))