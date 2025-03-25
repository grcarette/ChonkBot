import discord
from discord.ext import commands
from utils.reaction_utils import create_reaction_flag
from utils.errors import NoStagesFoundError

DEFAULT_RANDOM_NUMBER = 1
MAX_RANDOM_NUMBER = 5

class MessageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.content.lower() == 'register' or message.content.lower() == 'unregister':
            if message.content.lower() == 'register':
                is_register = True
            else:
                is_register = False
                
            channel_id = message.channel.id
            category_id = message.channel.category.id
            register_flag = await self.bot.dh.get_registration_flag(channel_id=channel_id)
            if register_flag:
                await self.bot.th.process_registration(message, is_register=is_register)
                
    @commands.command(name="random")
    async def random(self, ctx, *, random_number: str = None):
        if random_number is None:
            random_number = DEFAULT_RANDOM_NUMBER
        try:
            random_number = int(random_number)
            if random_number > MAX_RANDOM_NUMBER:
                random_number = MAX_RANDOM_NUMBER
        except:
            message_content = (
                "Error: Please provide a valid number of random stages"
            )
            await ctx.channel.send(message_content)
            return
        if ctx.channel.name == 'secret-bot-testing':
            try:
                stages = await self.bot.dh.get_random_stages(random_number, user=ctx.message.author)
            except NoStagesFoundError:
                message_content = (
                    "You have blocked every legal stage, are you trying to break me??"
                )
                message = await ctx.channel.send(message_content)
                return
            
            for stage in stages:
                message_content = (
                    f"# {stage['name']}\n"
                    f"Creator: {stage['creator']}\n"
                    f"Code: {stage['code']}\n"
                    f"{stage['imgur']}"
                )
                message = await ctx.channel.send(message_content)
                user_id = ctx.message.author.id
                await create_reaction_flag(self.bot, message, 'random_stage', user_filter=user_id, value=stage['code'])
                

async def setup(bot):
    await bot.add_cog(MessageCog(bot))