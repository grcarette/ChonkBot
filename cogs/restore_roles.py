"""
Temporary cog: /restore_roles
Grants the "Distortion" role to every entrant in the tournament.
Delete this file after running the command once.
"""

import discord
from discord import app_commands
from discord.ext import commands


class RestoreRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='restore_roles', description='Grant tournament role to all entrants (one-time restore)')
    async def restore_roles(self, interaction: discord.Interaction):
        if interaction.user.id != self.bot.admin_id:
            await interaction.response.send_message('Admin only.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tournament = await self.bot.dh.get_tournament(name='Distortion')
        if not tournament:
            await interaction.followup.send('Tournament "Distortion" not found.', ephemeral=True)
            return

        role = discord.utils.get(interaction.guild.roles, name='Distortion')
        if not role:
            await interaction.followup.send('Role "Distortion" not found.', ephemeral=True)
            return

        entrant_ids = list(tournament.get('entrants', {}).keys())
        granted = 0
        skipped = 0
        failed = 0

        for discord_id in entrant_ids:
            member = interaction.guild.get_member(int(discord_id))
            if not member:
                skipped += 1
                continue
            if role in member.roles:
                skipped += 1
                continue
            try:
                await member.add_roles(role)
                granted += 1
            except Exception as e:
                print(f'[RESTORE_ROLES] Failed to add role to {discord_id}: {e}')
                failed += 1

        await interaction.followup.send(
            f'Done. **{granted}** granted, **{skipped}** skipped (not in server or already has role), **{failed}** failed.',
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(RestoreRoles(bot))
