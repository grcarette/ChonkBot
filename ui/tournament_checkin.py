import discord
from utils.emojis import INDICATOR_EMOJIS

from .confirmation import ConfirmationView

class TournamentCheckinView(discord.ui.View):
    def __init__(self, bot, tournament):
        super().__init__()
        self.bot = bot
        self.tournament = tournament
        self.checked_in = set()
        
    @discord.ui.button(label=f"Unregister {INDICATOR_EMOJIS['red_x']}", style=discord.ButtonStyle.danger)
    async def unregister_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in self.checked_in:
            self.checked_in.remove(user_id)
        await self.bot.th.unregister_player(self.tournament['name'], user_id)
        message_content = (
            'You have successfully unregistered.\n'
            'If you change your mind, you may still register through the register channel.'
        )
        await interaction.response.send_message(message_content, ephemeral=True)
        
        embed = await self.generate_embed()
        await interaction.message.edit(embed=embed, view=self)
        
    @discord.ui.button(label=f"Check In {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success)
    async def tournament_checkin(self, interaction: discord.Interaction, button: discord.ui.Button):
        entrants = await self.get_entrants()
        user_id = interaction.user.id
        
        if user_id not in entrants:
            await interaction.response.send_message("You are not currently registered for this event.", ephemeral=True)
            return

        if user_id in self.checked_in:
            await interaction.response.send_message("You've already checked in!", ephemeral=True)
            return
        
        self.checked_in.add(user_id)
        embed = await self.generate_embed()
        
        await interaction.response.edit_message(embed=embed, view=self)
        await self.bot.dh.checkin_player(self.tournament['name'], user_id)
        
    async def get_entrants(self):
        tournament = await self.bot.dh.get_tournament(name=self.tournament['name'])
        entrants = [int(user_id) for user_id in tournament['entrants'].keys()]
        return entrants
    
    async def generate_embed(self):
        entrants = await self.get_entrants()
        remaining_ids = [user_id for user_id in entrants if user_id not in self.checked_in]
        mentions = [f"<@{id}>" for id in remaining_ids]

        if mentions:
            checkin_message = (
                "Click the button below to check in.\n\n"
                f"Players yet to check in:\n" +
                ("\n".join(mentions))
            )
        else:
            checkin_message = (
                f"{INDICATOR_EMOJIS['green_check']} All players have checked in"
            )
        embed = discord.Embed(
            title=f"Check in for {self.tournament['name']}",
            description=checkin_message,
            color=discord.Color.green()
        )
        return embed