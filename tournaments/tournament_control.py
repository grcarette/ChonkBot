import discord

from ui.bot_control import BotControlView
from ui.config_control.config_control import ConfigControlView
from ui.confirmation import ConfirmationView

from .tournament_info_display import TournamentInfoDisplay
from .tournament_config_handler import TournamentConfigHandler

class TournamentControl:
    def __init__(self, tournament_manager):
        self.tm = tournament_manager
        self.dh = self.tm.bot.dh
        self.tournament = self.tm.tournament
        
    async def initialize_controls(self):
        self.tid = TournamentInfoDisplay(self)
        await self.tid.initialize_display()
        
        self.tournament_config_handler = TournamentConfigHandler(self)
        
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
    
    async def edit_tournament_config(self, **kwargs):
        if 'color' in kwargs:
            await self.tournament_config_handler.set_color(kwargs.pop('color'))

    async def add_link_to_display(self, link_label, link_url):
        await self.tid.add_link(link_label, link_url)
        
    async def refresh_displays(self):
        await self.cc.update_control()
        await self.bc.update_control()
        await self.tid.update_display()
    
        
