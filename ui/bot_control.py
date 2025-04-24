import discord

from utils.emojis import INDICATOR_EMOJIS
from .confirmation import ConfirmationView

class BotControlView(discord.ui.View):
    def __init__(self, tournament_control):
        super().__init__(timeout=None)
        self.tc = tournament_control
        self.tm = self.tc.tm
        self.channels_hidden = True
        self.message = None
        self.stage = 'setup'
        self.required_actions = []
        self.embed_title = "Tournament Controls"
        
        name = self.tm.tournament['name']
        self.publish_button = discord.ui.Button(
            label=f"Publish Tournament {INDICATOR_EMOJIS['eye']}", style=discord.ButtonStyle.primary, custom_id=f"{name}-publish"
            )
        self.checkin_button = discord.ui.Button(
            label=f"Start Check-in {INDICATOR_EMOJIS['green_check']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_checkin"
            )
        self.start_button = discord.ui.Button(
            label=f"Start Tournament {INDICATOR_EMOJIS['game_controller']}", style=discord.ButtonStyle.success, custom_id=f"{name}-start_tournament"
            )
        self.reset_button = discord.ui.Button(
            label=f"Reset Tournament {INDICATOR_EMOJIS['rotating_arrows']}", style=discord.ButtonStyle.danger, custom_id=f"{name}-reset"
            )
        self.open_reg_button = discord.ui.Button(
            label=f"Open Registration{INDICATOR_EMOJIS['notepad']}", style=discord.ButtonStyle.success, custom_id=f"{name}-open_reg", disabled=True
            )
        self.close_reg_button = discord.ui.Button(
            label=f"Close Registration{INDICATOR_EMOJIS['notepad']}", style=discord.ButtonStyle.success, custom_id=f"{name}-close_reg", disabled=False
            )


        self.publish_button.callback = self.publish_tournament
        self.checkin_button.callback = self.start_checkin
        self.start_button.callback = self.start_tournament
        self.reset_button.callback = self.reset_tournament

        self.open_reg_button.callback = self.open_registration
        self.close_reg_button.callback = self.close_registration
        
                
    async def publish_tournament(self, interaction: discord.Interaction):
        tournament = await self.tm.get_tournament()
        if interaction.user.id not in tournament['organizers']:
            await interaction.response.send_message("Only the TO is authorized to do this.", ephemeral=True)
        else:
            user_id = interaction.user.id
            embed = discord.Embed(
                title="Are you sure you want to publish the tournament?",
                color=discord.Color.yellow()
            )
            view = ConfirmationView(self.tm.progress_tournament, user_id, state='registration')
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
    async def open_registration(self, interaction: discord.Interaction):
        self.open_reg_button.disabled=True
        self.close_reg_button.disabled=False
        await interaction.response.edit_message(view=self)
        await self.tm.open_registration()
    
    async def close_registration(self, interaction: discord.Interaction):
        self.close_reg_button.disabled=True
        self.open_reg_button.disabled=False
        await interaction.response.edit_message(view=self)
        await self.tm.close_registration()
        
    async def start_checkin(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        embed = discord.Embed(
            title="Are you sure you want to start checkin?",
            color=discord.Color.yellow()
        )
        view = ConfirmationView(self.tm.progress_tournament, user_id, state='checkin')
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    async def start_tournament(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        tournament = await self.tm.get_tournament()
        
        embed = discord.Embed(
            title="Are you sure you want to start the tournament?",
            color=discord.Color.yellow()
        )
        view = ConfirmationView(self.tm.progress_tournament, user_id, state='active')
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    async def reset_tournament(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        embed = discord.Embed(
            title="**Warning**",
            description="Resetting the tournament will undo any matches that have already been reported. Are you **absolutely sure** you want to reset the tournament?",
            color=discord.Color.red()
        )
        view = ConfirmationView(self.tm.reset_tournament, user_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        

        
    async def update_tournament_state(self, state):
        if self.message == None:
            self.message = await self.get_control_message()
        self.clear_items()
        self.stage = state
        if state == 'setup':
            self.publish_button.disabled=False
            self.add_item(self.publish_button)
        elif state == 'registration':
            self.checkin_button.disabled=False
            self.add_item(self.open_reg_button)
            self.add_item(self.close_reg_button)
            # self.add_item(self.edit_stagelist_button)
            self.add_item(self.checkin_button)
        elif state == 'checkin':
            # self.add_item(self.close_checkin_button)
            self.add_item(self.open_reg_button)
            self.add_item(self.close_reg_button)
            self.add_item(self.start_button)
        elif state == 'active':
            self.add_item(self.reset_button)
        elif state == 'finished':
            pass
        
        await self.update_control()

    async def update_control(self):
        await self.update_required_actions()
        embed = await self.generate_embed()
        await self.message.edit(view=self, embed=embed)
            
    async def get_control_message(self):
        channel = await self.tm.get_channel('bot-control')
        bot_id = self.tm.bot.id
        
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id == bot_id and message.embeds:
                embed = message.embeds[0]
                if self.embed_title in embed.title:
                    return message
            
        return None
    
    async def update_required_actions(self):
        self.required_actions = []
        tournament = await self.tm.get_tournament()
        if self.stage == "setup":
            if len(tournament['stagelist']) > 0:
                pending_stages = await self.get_pending_stages(tournament)
                if len(pending_stages) > 0:
                    action = (
                        "Submit stages to database:\n" + "\n".join(f"-'{code}'" for code in pending_stages)
                    )
                    self.required_actions.append(action)
            else:
                self.required_actions.append("Add stages to stagelist")
        elif self.stage == "registration":
            #must have 2 players to open checkin
            pass
        elif self.stage == "checkin":
            #must close checkin to start tournament
            pass
        elif self.stage == "active":
            #tournament must be over to end tournament
            pass
        elif self.stage == "finished":
            #TBD
            pass
        else:
            self.required_actions.append('-Nothing')
        
    async def get_pending_stages(self, tournament):
        pending_stages = []
        for stage_code in tournament['stagelist']:
            stage_exists = await self.tm.bot.dh.get_stage(code=stage_code)
            if not stage_exists:
                pending_stages.append(stage_code)
        return pending_stages
                
    async def generate_embed(self):
        required_actions_string = "\n".join(self.required_actions)
        description = (
            f"Stage: {self.stage}\n"
            "To do:\n"
            f"{required_actions_string}"
        )
        embed = discord.Embed(
            title="Tournament Controls",
            description=description,
            color=discord.Color.green()
        )
        return embed
        
        
    
        

        

        