import discord

from ui.bot_control import BotControlView
from ui.config_control import ConfigControlView

class TournamentControls:
    def __init__(self, tournament):
        self.t = tournament
        
    async def initialize_controls(self):
        tournament = await self.t.get_tournament()
        state = await self.t.get_state()
        if state == 'initialize':
            self.cc = await self.add_config_control()
            self.bc = await self.add_bot_control()
        else:
            self.cc = ConfigControlView(self.t)
            self.bc = BotControlView(self.t)
        await self.t.add_view(self.cc)
        await self.t.add_view(self.bc)
        await self.bc.update_tournament_state(tournament['state'])
        
    async def add_bot_control(self):
        channel = await self.t.get_channel('bot-control')
        bot_control = BotControlView(self.t)
        embed = await bot_control.generate_embed()
        await channel.send(embed=embed, view=bot_control)
        return bot_control
    
    async def add_config_control(self):
        channel = await self.t.get_channel('bot-control')
        config_control = ConfigControlView(self.t)
        embed = await config_control.generate_embed()
        await channel.send(embed=embed, view=config_control)
        return config_control
    
    async def update_tournament_state(self, state):
        await self.bc.update_tournament_state(state)