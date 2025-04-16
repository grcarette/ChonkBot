import discord

class MatchReportView(discord.ui.View):
    def __init__(self, lobby, parent):
        super().__init__()
        self.lobby = lobby
        self.winner = None
        self.parent = parent
        self.players = {}
        
    async def setup(self):
        for user_id in self.lobby.remaining_players:
            player = await self.lobby.dh.get_user(user_id=user_id)
            self.players[user_id] = player['name']
        
        options = []
        for player_id in self.players.keys():
            select_option = discord.SelectOption(label=f"{self.players[player_id]}", value=player_id)
            options.append(select_option)
            
        self.select_menu = discord.ui.Select(
            placeholder = "Select the winner of the match",
            options = options
        )
        self.select_menu.callback = self.select_winner
        self.add_item(self.select_menu)
        
    async def select_winner(self, interaction: discord.Interaction):
        self.winner = self.select_menu.values[0]
        self.select_menu.placeholder = self.players[int(self.select_menu.values[0])]
        for child in self.children:
            if child.custom_id == 'report_submit':
                child.disabled = False
        await interaction.response.edit_message(view=self)
        
    @discord.ui.button(label='Submit', style=discord.ButtonStyle.success, disabled=True, custom_id='report_submit')
    async def submit_winner(self, interaction: discord.Interaction,button: discord.ui.Button):
        user = interaction.user
        button.label = 'Submitted Successfully'
        button.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
        
        await self.parent.add_report(user, self.winner)
        
class MatchReportButton(discord.ui.View):
    def __init__(self, lobby, timeout=None):
        super().__init__(timeout=timeout)
        self.lobby = lobby
        self.reports = []
        self.user_reports = []
        
        self.report_button = discord.ui.Button(label='Report Match', style=discord.ButtonStyle.success, custom_id=f"{self.lobby.match_id}-report")
        self.report_button.callback = self.report_match
        self.add_item(self.report_button)
        
    async def report_match(self, interaction: discord.Interaction):
        user = interaction.user
        if any(role.name == self.lobby.override_role for role in user.roles) or user.id in self.lobby.remaining_players:
            view = MatchReportView(self.lobby, self)
            await view.setup()
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            message_content = (
                'You are not a player in this match.'
            )
            await interaction.response.send_message(message_content, ephemeral=True)
        
    async def add_report(self, user, report):
        self.reports.append(int(report))
        self.user_reports.append(int(user.id))
        
        if any(role.name == self.lobby.override_role for role in user.roles):
            await self.lobby.end_reporting(report)
        elif set(self.user_reports) == set(self.lobby.remaining_players):
            if len(set(self.reports)) > 1:
                await self.redo_report()
            else:
                await self.lobby.end_reporting(int(self.reports[0]))
                
    async def redo_report(self):
        channel = self.lobby.channel
        message_content = (
            '# Error: Result was not unanimous\n'
            '## Report the match again. Make sure you select the player who **won**'
        )
        await channel.send(message_content)
        self.user_reports = []
        self.reports = []
        
        
        
    
