import discord

from ui.bot_control import BotControlView
from ui.config_control import ConfigControlView
from ui.confirmation import ConfirmationView

class TournamentControl:
    def __init__(self, tournament_manager):
        self.tm = tournament_manager
        self.dh = self.tm.bot.dh
        self.tournament = self.tm.tournament
        
    async def initialize_controls(self):
        tournament = await self.tm.get_tournament()
        state = await self.tm.get_state()
        if state == 'initialize':
            self.cc = await self.add_config_control()
            self.bc = await self.add_bot_control()
        else:
            self.cc = ConfigControlView(self)
            self.bc = BotControlView(self)
        await self.cc.update_control()
        
        await self.tm.add_view(self.cc)
        await self.tm.add_view(self.bc)
        await self.bc.update_tournament_state(tournament['state'])
        
    async def add_bot_control(self):
        channel = await self.tm.get_channel('bot-control')
        bot_control = BotControlView(self)
        embed = await bot_control.generate_embed()
        await channel.send(embed=embed, view=bot_control)
        return bot_control
    
    async def add_config_control(self):
        channel = await self.tm.get_channel('bot-control')
        config_control = ConfigControlView(self)
        embed = await config_control.generate_embed()
        await channel.send(embed=embed, view=config_control)
        return config_control
    
    async def update_tournament_state(self, state):
        await self.bc.update_tournament_state(state)
        
    async def get_required_actions(self):
        pass
    
    async def edit_tournament_config(self, kwargs):
        pass
        
