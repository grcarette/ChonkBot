import discord

from ui.bot_control import BotControlView
from ui.config_control.config_control import ConfigControlView
from ui.confirmation import ConfirmationView

from handlers.ban_graphic_generator import StageBannerGenerator

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
            self.bc = BotControlView(self, tournament)
        await self.cc.update_control()
        
        await self.tm.add_view(self.cc)
        await self.tm.add_view(self.bc)
        await self.bc.update_tournament_state(tournament['state'])
        
    async def add_bot_control(self):
        channel = await self.tm.get_channel('bot-control')
        tournament = await self.tm.get_tournament()
        bot_control = BotControlView(self, tournament)
        embed = await bot_control.generate_embed()
        await channel.send(embed=embed, view=bot_control)
        return bot_control
    
    async def add_config_control(self):
        channel = await self.tm.get_channel('bot-control')
        config_control = ConfigControlView(self)
        embed = await config_control.generate_embed()
        await channel.send(embed=embed, view=config_control)
        return config_control
    
    async def check_stages(self, stagelist):
        stages, result = await self.tournament_config_handler.check_stages(stagelist)
        return stages, result
        
    async def add_stages(self, stagelist):
        await self.tournament_config_handler.add_stages(stagelist)
        
    async def add_random_stages(self, stage_count):
        random_stages = await self.tournament_config_handler.add_random_stages(stage_count)
        return random_stages
    
    async def update_tournament_state(self, state):
        await self.bc.update_tournament_state(state)
        
    async def get_required_actions(self):
        pass
    
    async def edit_tournament_config(self, **kwargs):
        await self.tournament_config_handler.edit_tournament_config(**kwargs)

    async def add_link_to_display(self, link_label, link_url):
        await self.tid.add_link(link_label, link_url)
        
    async def refresh_displays(self):
        await self.cc.update_control()
        await self.bc.update_control()
        await self.tid.update_display()
    
    async def refresh_stagelist(self):
        channel = await self.tm.get_channel('stagelist')
        await channel.purge(limit=None)
        await self.tid.post_stages()
        
    async def generate_banner(self):
        tournament = await self.tm.get_tournament()
        sbg = StageBannerGenerator()
        stage_list_data = []
        for map_code in tournament['stagelist']:
            stage = await self.dh.get_stage(code=map_code)
            stage_list_data.append(stage)
        filepath = await sbg.generate_banner(stage_list_data, tournament)
        return filepath

    async def disqualify_player(self, user_id):
        return await self.tm.disqualify_player(user_id)    

    async def undisqualify_player(self, user_id):
        return await self.tm.undisqualify_player(user_id)
