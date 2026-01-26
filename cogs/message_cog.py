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
        
async def setup(bot):
    await bot.add_cog(MessageCog(bot))