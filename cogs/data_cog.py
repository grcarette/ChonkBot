import discord
from discord.ext import commands
from utils.errors import PlayerNotFoundError
from utils.reaction_utils import create_reaction_flag

class DataCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="register_player")
    async def register_player(self, ctx, *, player_name):
        user = ctx.message.author
        channel = ctx.channel
        user_link = await self.bot.dh.check_user_link(user)
        if user_link:
            player = await self.bot.dh.get_player_by_id(user_link['player_id'])
            message_content = (
                f"**Error:** You are already linked to player: *{player['name']}*"
            )
            await channel.send(message_content)
            return
        player_link = await self.bot.dh.check_player_link(player_name)
        if player_link:
            player = await self.bot.dh.get_player_by_id(player_link['player_id'])
            message_content = (
                f"**Error:** Player: *{player['name']}* is already linked to User: *{player_link['name']}*"
            )
            await channel.send(message_content)
            return
        try:
            await self.bot.dh.lookup_player(player_name)
        except PlayerNotFoundError:
            message_content = (
                f"Error: Player with name: '{player_name}' not found. Perhaps try using another name you've entered events with"
            )
            message = await channel.send(message_content)
            return
        message_content = (
            f"Player '{player_name}' found!\n"
            "Awaiting approval"
        )
        await channel.send(message_content)
        await create_reaction_flag(self.bot, ctx.message, 'link_confirmation', user_filter=self.bot.admin_id, value=player_name)
        
    @register_player.error
    async def register_player_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            message_content = (
                f'Error: Missing argument `{error.param.name}`\n'
                f'Usage: `!register_player <player_name>`'
            )
            await ctx.send(message_content)
        
    @commands.command(name='unregister_player')
    async def unregister_player(self, ctx):
        user = ctx.message.author
        channel = ctx.channel
        await self.bot.dh.remove_player_link(user)
        message_content = (
            'Unregistered Successfully'
        )
        await channel.send(message_content)
            
async def setup(bot):
    await bot.add_cog(DataCog(bot))