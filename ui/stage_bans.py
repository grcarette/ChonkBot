import discord
from utils.emojis import INDICATOR_EMOJIS
from utils.messages import get_mentions

class StageButton(discord.ui.Button):
    def __init__(self, stage_bans, stage):
        self.banned = False
        self.num_stage_bans = stage_bans
        self.stage = stage
        super().__init__(label=stage['name'], style=discord.ButtonStyle.secondary)
        
    async def callback(self, interaction: discord.Interaction):
        if not self.banned:
            self.banned = True
            self.style = discord.ButtonStyle.primary
        else:
            self.banned = False
            self.style = discord.ButtonStyle.secondary
        
        banned_count = sum(1 for item in self.view.children if isinstance(item, StageButton) and item.banned)
        
        if banned_count == self.num_stage_bans:
            for button in self.view.children:
                if isinstance(button, StageButton) and not button.banned:
                    button.disabled = True
                if button.custom_id == 'confirm_button':
                    button.disabled = False

        elif banned_count < self.num_stage_bans:
            for button in self.view.children:
                if button.custom_id == 'confirm_button':
                    button.disabled = True
                else:
                    button.disabled = False
        await interaction.response.edit_message(view=self.view)
                
class StageBansView(discord.ui.View):
    def __init__(self, original_button):
        super().__init__()
        self.lobby = original_button.lobby
        self.original_button = original_button
        self.num_stage_bans = self.original_button.num_stage_bans
        self.banned_stages = []
        
    async def setup(self):
        for stage_code in self.lobby.stages:
            stage = await self.lobby.dh.get_stage(code=stage_code)
            button = StageButton(self.num_stage_bans, stage)
            self.add_item(button)
            
        confirm_button = discord.ui.Button(label='Confirm', style=discord.ButtonStyle.success, disabled=True, custom_id='confirm_button')
        confirm_button.callback = self.submit_bans
        self.add_item(confirm_button)
            
    async def submit_bans(self, interaction: discord.Interaction):
        user = interaction.user
        banned_stages = []
        for button in self.children:
            if isinstance(button, StageButton) and button.banned:
                banned_stages.append(button.stage['code'])

        await self.original_button.submit_player_bans(user, banned_stages)
        for button in self.children:
            button.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
            
class BanStagesButton(discord.ui.View):
    def __init__(self, lobby, timeout=None):
        super().__init__(timeout=timeout)
        self.lobby = lobby
        self.num_stage_bans = self.calculate_num_stage_bans()
        self.banned_stages = set()
        self.finished_users = []
        self.message = None
        
        self.stage_ban_button = discord.ui.Button(label="Ban Stages", style=discord.ButtonStyle.primary, custom_id=f"{self.lobby.match_id}-stageban")
        self.stage_ban_button.callback = self.ban_stages
        self.add_item(self.stage_ban_button)
        
    async def ban_stages(self, interaction: discord.Interaction):
        view = StageBansView(self)
        await view.setup()
        self.message = interaction.message
        await interaction.response.send_message(view=view, ephemeral=True)
        
    async def submit_player_bans(self, user, banned_stages):
        for stage in banned_stages:
            self.banned_stages.add(stage)
        self.finished_users.append(user.id)
        embed = self.generate_embed()
        await self.message.edit(embed=embed, view=self)
        if set(self.finished_users) == set(self.lobby.remaining_players):
            self.stop()
            await self.message.delete()
            await self.lobby.end_stage_bans(self.banned_stages)
    
    def generate_embed(self):
        remaining_ids = [pid for pid in self.lobby.remaining_players if pid not in self.finished_users]
        mentions = get_mentions(remaining_ids)

        if mentions:
            checkin_message = (
                "Click the button below to ban stages.\n\n"
                f"Players yet to ban stages:\n" +
                ("\n".join(mentions))
            )
        else:
            checkin_message = (
                f"{INDICATOR_EMOJIS['green_check']} All players have banned stages"
            )
        embed = discord.Embed(
            title="Stage Banning",
            description=checkin_message,
            color=discord.Color.blue()
        )
        return embed
    
    def calculate_num_stage_bans(self):
        num_stages = len(self.lobby.stages)
        num_players = len(self.lobby.remaining_players)
        num_stage_bans = (num_stages - (num_stages % num_players)) / num_players
        
        return num_stage_bans
            
        
        
        
    
        
            
            
            

        