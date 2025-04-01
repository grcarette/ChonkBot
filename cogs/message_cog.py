import discord
from discord.ext import commands
from utils.reaction_utils import create_reaction_flag
from utils.command_utils import get_usage_message, COMMAND_DICT
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
                
    @commands.command(name="help")
    async def help(self, ctx):
        message_content = (
            
        )
                
    @commands.command(name="command_usage", aliases=['usage'])
    async def command_usage(self, ctx, command_name):
        channel = ctx.channel
        for cmd in self.bot.commands:
            if command_name in cmd.aliases or command_name == cmd.name:
                command = cmd
                break
        message_content = get_usage_message(command.name)
        await channel.send(message_content)
        
    @commands.command(name="list_commands", aliases=['commands'])
    async def command_list(self, ctx):
        categorized_commands = {}

        for command_name, data in COMMAND_DICT.items():
            command = self.bot.get_command(command_name)

            if command:
                try:
                    if await command.can_run(ctx):
                        tag = data['tag']
                        if tag not in categorized_commands:
                            categorized_commands[tag] = []
                        categorized_commands[tag].append(command_name)
                except:
                    continue 

        embed = discord.Embed(
            title="Commands",
            color=discord.Color.blue()
        )

        for tag, commands in categorized_commands.items():
            command_list = "\n".join([f"`!{cmd}`" for cmd in commands])
            embed.add_field(name=f"{tag.title()}", value=command_list, inline=False)

        embed.set_footer(text="Use !usage <command> to learn more about a specific command.")

        await ctx.send(embed=embed)
        
                
    @commands.command(name="random_level", aliases=['random'])
    async def random(self, ctx, *, random_number: str = None):
        channel = ctx.channel
        user_id = ctx.message.author.id
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
        if channel.name == 'temporary-bot-testing':
            try:
                stages = await self.bot.dh.get_random_stages(random_number, user=ctx.message.author)
            except NoStagesFoundError:
                message_content = (
                    "You have blocked every legal stage, are you trying to break me??"
                )
                message = await ctx.channel.send(message_content)
                return
            
            for stage in stages:
                message = await self.bot.mh.send_level_message(stage, channel)
                await create_reaction_flag(self.bot, message, 'random_stage', user_filter=user_id, value=stage['code'])
    
                

async def setup(bot):
    await bot.add_cog(MessageCog(bot))