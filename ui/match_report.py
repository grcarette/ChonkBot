import asyncio
import discord

class MatchReportView(discord.ui.View):
    def __init__(self, lobby, parent, original_message):
        super().__init__(timeout=None)
        self.lobby = lobby
        self.winner = None
        self.parent = parent
        self.players = {}
        self.original_message = original_message
        
    async def setup(self):
        if self.lobby.tournament_manager.is_teams_mode:
            # Build options from team names rather than individual user lookups
            for team_id in self.lobby.remaining_players:
                tournament = await self.lobby.tournament_manager.get_tournament()
                team_name = tournament.get('entrants_meta', {}).get(str(team_id))
                if not team_name:
                    # Fall back to resolving member names
                    try:
                        p1, p2 = self.lobby.tournament_manager._parse_team_id(str(team_id))
                        u1 = await self.lobby.dh.get_user(user_id=p1)
                        u2 = await self.lobby.dh.get_user(user_id=p2)
                        n1 = u1['name'] if u1 else str(p1)
                        n2 = u2['name'] if u2 else str(p2)
                        team_name = f"{n1} / {n2}"
                    except (ValueError, AttributeError):
                        team_name = str(team_id)
                self.players[str(team_id)] = team_name
        else:
            for user_id in self.lobby.remaining_players:
                player = await self.lobby.dh.get_user(user_id=int(user_id))
                if player is None:
                    print(f"[MatchReportView] Could not find user {user_id} in DB")
                    self.players[int(user_id)] = str(user_id)
                else:
                    self.players[int(user_id)] = player['name']

        options = []
        for player_id, name in self.players.items():
            options.append(discord.SelectOption(label=name, value=str(player_id)))

        self.select_menu = discord.ui.Select(
            placeholder="Select the winner of the match",
            options=options
        )
        self.select_menu.callback = self.select_winner
        self.add_item(self.select_menu)
        
    async def select_winner(self, interaction: discord.Interaction):
        self.winner = self.select_menu.values[0]
        self.select_menu.placeholder = self.players[
            int(self.winner) if not self.lobby.tournament_manager.is_teams_mode
            else self.winner
        ]
        for child in self.children:
            if child.custom_id == 'report_submit':
                child.disabled = False
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label='Submit', style=discord.ButtonStyle.success, disabled=True, custom_id='report_submit')
    async def submit_winner(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        button.label = 'Submitted Successfully'
        button.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
        
        await self.parent.add_report(user, self.winner, self.original_message)
        
class MatchReportButton(discord.ui.View):
    def __init__(self, lobby, timeout=None):
        super().__init__(timeout=timeout)
        self.lobby = lobby
        self.reports = []
        self.user_reports = []
        self._lock = asyncio.Lock()
        
        self.report_button = discord.ui.Button(label='Report Match', style=discord.ButtonStyle.success, custom_id=f"{self.lobby.match_id}-report")
        self.report_button.callback = self.report_match
        self.add_item(self.report_button)
        
    async def report_match(self, interaction: discord.Interaction):
        user = interaction.user
        message = interaction.message
        is_to = any(role.name == self.lobby.organizer_role for role in user.roles)

        if not is_to:
            slot = await self.lobby._resolve_checkin_slot(user.id)
            if slot is None:
                await interaction.response.send_message(
                    'You are not a player in this match.', ephemeral=True
                )
                return

        view = MatchReportView(self.lobby, self, message)
        await view.setup()
        await interaction.response.send_message(view=view, ephemeral=True)
        
    async def add_report(self, user, report, original_message):
        async with self._lock:
            # Resolve the slot this user represents
            slot = await self.lobby._resolve_checkin_slot(user.id)
            is_to = any(role.name == self.lobby.organizer_role for role in user.roles)

            if not is_to:
                if slot is None:
                    return
                # Guard: one report per slot
                if slot in self.user_reports:
                    return
                self.reports.append(report)
                self.user_reports.append(slot)
            else:
                # TO override — report immediately
                await self.lobby.end_reporting(report)
                await original_message.delete()
                return

            all_reported = set(self.user_reports) == set(self.lobby.remaining_players)

        if all_reported:
            if len(set(self.reports)) > 1:
                await self.redo_report()
            else:
                await self.lobby.end_reporting(self.reports[0])
                await original_message.delete()
                
    async def redo_report(self):
        channel = self.lobby.channel
        message_content = (
            '# Error: Result was not unanimous\n'
            '## Report the match again. Make sure you select the player who **won**'
        )
        await channel.send(message_content)
        self.user_reports = []
        self.reports = []