import discord
from utils.emojis import INDICATOR_EMOJIS

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
    def __init__(self, bot, lobby, original_button):
        super().__init__()
        self.bot = bot
        self.lobby = lobby
        self.original_button = original_button
        self.banned_stages = []
        
    async def setup(self):
        for stage_code in self.lobby['stages']:
            stage = await self.bot.dh.get_stage(code=stage_code)
            button = StageButton(self.lobby['num_stage_bans'], stage)
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
    def __init__(self, bot, lobby):
        super().__init__()
        self.bot = bot
        self.lobby = lobby
        self.banned_stages = set()
        self.finished_users = []
        self.message = None
        
    @discord.ui.button(label="Ban Stages", style=discord.ButtonStyle.primary)
    async def ban_stages(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = StageBansView(self.bot, self.lobby, self)
        await view.setup()
        self.message = interaction.message
        await interaction.response.send_message(view=view, ephemeral=True)
        
    async def submit_player_bans(self, user, banned_stages):
        for stage in banned_stages:
            self.banned_stages.add(stage)
        self.finished_users.append(user.id)
        embed = self.generate_embed()
        await self.message.edit(embed=embed, view=self)
        if set(self.finished_users) == set(self.lobby['players']):
            await self.bot.lh.end_stage_bans(self.lobby, self.banned_stages)
    
    def generate_embed(self):
        remaining_ids = [pid for pid in self.lobby['players'] if pid not in self.finished_users]
        mentions = [f"<@{pid}>" for pid in remaining_ids]

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
            
        
        
        
    
        
            
            
            

        