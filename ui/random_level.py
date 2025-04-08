import discord

from utils.emojis import INDICATOR_EMOJIS
from utils.errors import NoStagesFoundError, LevelNotFoundError

LEVEL_SHARING_CHANNEL_ID = 1357434250034675895

class LevelRatingButton(discord.ui.View):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(timeout=None)
        pass
    
    @discord.ui.button(label='Rate Level', style=discord.ButtonStyle.primary, custom_id="Rate Level")
    async def create_level_rating_view(self, interaction: discord.Interaction, button: discord.Button):
        user = interaction.user
        level = await self.bot.dh.get_level(message_id=interaction.message.id)
        view = await LevelRatingView.create(user, self.bot, level['code'])
        await interaction.response.send_message(view=view, ephemeral=True)
    
class LevelRatingView(discord.ui.View):
    def __init__(self, user, bot, map_code, is_favorite, is_blocked, rating, *, _internal=False):
        if not _internal:
            raise RuntimeError("Use 'LevelRatingView.create()' to instantiate this class.")
        super().__init__()

        self.user = user
        self.bot = bot
        self.map_code = map_code
        
        if is_favorite:
            favorite_label = "Unfavorite"
        else:
            favorite_label = " Favorite "
        if is_blocked:
            block_label = "Unblock"
        else:
            block_label = " Block "
        if rating == 'upvote':
            upvote_style = discord.ButtonStyle.primary
            downvote_style = discord.ButtonStyle.secondary
        elif rating == 'downvote':
            upvote_style = discord.ButtonStyle.secondary
            downvote_style = discord.ButtonStyle.primary
        else:
            upvote_style = discord.ButtonStyle.secondary
            downvote_style = discord.ButtonStyle.secondary
        
        self.block_toggle = discord.ui.Button(label=block_label, style=discord.ButtonStyle.danger)
        self.downvote_button = discord.ui.Button(label=f"{INDICATOR_EMOJIS['thumbs_down']}", style=downvote_style)
        self.upvote_button = discord.ui.Button(label=f"{INDICATOR_EMOJIS['thumbs_up']}", style=upvote_style)
        self.favorite_toggle = discord.ui.Button(label=favorite_label, style=discord.ButtonStyle.success)
        
        self.block_toggle.callback = self.toggle_block_level
        self.downvote_button.callback = self.downvote_level
        self.upvote_button.callback = self.upvote_level
        self.favorite_toggle.callback = self.toggle_favorite_level
        
        self.add_item(self.block_toggle)
        self.add_item(self.downvote_button)
        self.add_item(self.upvote_button)
        self.add_item(self.favorite_toggle)
        
    @classmethod
    async def create(cls, user, bot, map_code):
        is_favorite, is_blocked, rating = await bot.dh.get_user_map_preference(user, map_code)
        return cls(user, bot, map_code, is_favorite, is_blocked, rating, _internal=True)
        
    async def toggle_block_level(self, interaction: discord.Interaction):
        button = self.block_toggle
        if button.label == " Block ":
            button.label = "Unblock"
            block = True
        else: 
            button.label = " Block "
            block = False
        await self.bot.dh.update_map_preference(self.user, self.map_code, 'blocked_maps', block)
        await interaction.response.edit_message(view=self)    
    
    async def downvote_level(self, interaction: discord.Interaction):
        self.downvote_button.style = discord.ButtonStyle.primary
        self.upvote_button.style = discord.ButtonStyle.secondary
        
        user_id = self.user.id
        rating_change = await self.bot.dh.update_level_rating(user_id, self.map_code, 'downvote')
        
        if rating_change != 0:
            await self.update_upvote_count(rating_change)
        
        await interaction.response.edit_message(view=self)        

    async def upvote_level(self, interaction: discord.Interaction):
        self.upvote_button.style = discord.ButtonStyle.primary
        self.downvote_button.style = discord.ButtonStyle.secondary

        user_id = self.user.id
        rating_change = await self.bot.dh.update_level_rating(user_id, self.map_code, 'upvote')
        
        if rating_change != 0:
            await self.update_upvote_count(rating_change)
        
        await interaction.response.edit_message(view=self)
        
    async def update_upvote_count(self, rating_change: int):
        guild = self.bot.guilds[0]
        level = await self.bot.dh.get_level(code=self.map_code)
        message_id = level['message_id']
        channel = discord.utils.get(guild.channels, id=LEVEL_SHARING_CHANNEL_ID)
        message = await channel.fetch_message(message_id)     
        lines = message.content.split("\n")
        
        updated_lines = []
        for line in lines:
            if "👍" in line:
                parts = line.split("👍")
                current_count = int(parts[1].strip())
                new_count = current_count + rating_change
                updated_line = f"{parts[0]}👍 {new_count}"
                updated_lines.append(updated_line)
            else:
                updated_lines.append(line)
        new_content = "\n".join(updated_lines)
        
        await message.edit(content=new_content)
                
    
    async def toggle_favorite_level(self, interaction: discord.Interaction):
        button = self.favorite_toggle
        if button.label == " Favorite ":
            button.label = "Unfavorite"
            favorite = True
        else:
            button.label = " Favorite "
            favorite = False
        await self.bot.dh.update_map_preference(self.user, self.map_code, 'favorite_maps', favorite)
        await interaction.response.edit_message(view=self)    

class RandomLevelView(discord.ui.View):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(timeout=None)
        
    @discord.ui.button(label="Get Random Party Level", style=discord.ButtonStyle.success, custom_id='random_party_level')
    async def get_random_party_level(self, interaction: discord.Interaction, button: discord.ui.button):
        await self.send_random_level(interaction, 'party')
    
    @discord.ui.button(label="Get Random Challenge Level", style=discord.ButtonStyle.danger, custom_id='random_challenge_level')
    async def get_random_challenge_level(self, interaction: discord.Interaction, button: discord.ui.button):
        message_content = (
            'Currently there are no challenge levels in the database'
        )
        await interaction.response.send_message(message_content, ephemeral=True)
        # await self.send_random_level(interaction, 'challenge')
    
    async def send_random_level(self, interaction, type):
        channel = interaction.channel
        user_id = interaction.message.author.id
        random_number = 1

        try:
            stages = await self.bot.dh.get_random_stages(random_number, user=interaction.user, type=type)
        except NoStagesFoundError:
            message_content = (
                "You have blocked every legal stage, are you trying to break me??"
            )
            message = await channel.send(message_content)
            return
        
        for stage in stages:
            message = await self.bot.mh.send_level_message(stage, interaction, add_rating=True)
        



        
    