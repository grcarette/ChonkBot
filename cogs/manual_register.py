import discord
from discord import app_commands
from discord.ext import commands


class ManualRegisterSelect(discord.ui.UserSelect):
    def __init__(self, tm, tournament):
        super().__init__(
            placeholder='Select players to register...',
            min_values=1,
            max_values=10,
        )
        self.tm = tm
        self.tournament = tournament

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        results = []
        for user in self.values:
            result = await self.tm.register_player(user.id)
            if result is True:
                results.append(f'✅ {user.mention} registered')
            elif result == 'pending':
                results.append(f'⏳ {user.mention} added to pending (approval required)')
            elif result == 'late_registration_closed':
                results.append(f'❌ {user.mention} — late registration is closed')
            elif result == 'no_ranked_account':
                results.append(f'❌ {user.mention} — no ranked account linked')
            else:
                results.append(f'❌ {user.mention} — already registered or failed')

        await interaction.followup.send('\n'.join(results), ephemeral=True)


class ManualRegisterView(discord.ui.View):
    def __init__(self, tm, tournament):
        super().__init__(timeout=120)
        self.add_item(ManualRegisterSelect(tm, tournament))


class ManualRegisterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='manual_register', description='Manually register players for the active tournament')
    async def manual_register(self, interaction: discord.Interaction):
        category_id = interaction.channel.category_id
        if not category_id:
            await interaction.response.send_message('This command must be run inside a tournament category.', ephemeral=True)
            return

        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        if not tournament:
            await interaction.response.send_message('No tournament found for this category.', ephemeral=True)
            return

        is_organizer = interaction.user.id in tournament.get('organizers', [])
        is_admin = interaction.user.id == self.bot.admin_id
        if not is_organizer and not is_admin:
            await interaction.response.send_message('You must be a tournament organizer to use this command.', ephemeral=True)
            return

        tm = self.bot.th.tournaments.get(tournament['_id'])
        if not tm:
            await interaction.response.send_message('Tournament manager not loaded.', ephemeral=True)
            return

        view = ManualRegisterView(tm, tournament)
        await interaction.response.send_message('Select players to register:', view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ManualRegisterCog(bot))
