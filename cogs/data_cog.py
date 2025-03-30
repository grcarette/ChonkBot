import discord
from discord.ext import commands
from utils.errors import PlayerNotFoundError, NameNotUniqueError
from utils.reaction_utils import create_reaction_flag

class DataCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="register_player", aliases=['register player'])
    async def register_player(self, ctx, *, player_name):
        if ctx.channel.name != "temporary-bot-testing":
            return
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
                f"Error: Player: `{player['name']}` is already linked to User: `{player_link['name']}`"
            )
            await channel.send(message_content)
            return
        try:
            await self.bot.dh.lookup_player(player_name)
        except PlayerNotFoundError:
            message_content = (
                f"Error: Player with name: `{player_name}` not found. Perhaps try using another name you've entered events with"
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
        
    @commands.command(name='unregister_player', aliases=['unregister player'])
    async def unregister_player(self, ctx):
        if ctx.channel.name != "temporary-bot-testing":
            return
        user = ctx.message.author
        channel = ctx.channel
        await self.bot.dh.remove_player_link(user)
        message_content = (
            'Unregistered Successfully'
        )
        await channel.send(message_content)
        
    @commands.command(name='get_player_stats', aliases=['stats', 'get player statss', 'get stats'])
    async def get_player_stats(self, ctx, *, player_name):
        if ctx.channel.name != "temporary-bot-testing":
            return
        user = ctx.message.author
        channel = ctx.channel
        try:
            player_stats = await self.bot.dh.get_player_stats(player_name)

            best_placements = '\n'.join(player_stats['placements'])
            if player_stats['bracket_demon'] == None:
                bracket_demon_message = (
                    "\n**Bracket Demon:** `Sample size too small`"
                )
            else:
                bracket_demon_message = (
                    f"\n**Bracket Demon: **" 
                    f"`{player_stats['bracket_demon']['name']}`\n"
                    f"Wins: {player_stats['bracket_demon']['wins']} - "
                    f"Losses: {player_stats['bracket_demon']['losses']}\n"
                )
            if player_stats['rival'] == None:
                rival_message = (
                    "\n**Rival:** `Sample size too small`\n"
                )
            else:
                rival_message = (
                    f"\n**Rival: **" 
                    f"`{player_stats['rival']['name']}`\n"
                    f"Wins: {player_stats['rival']['wins']} - "
                    f"Losses: {player_stats['rival']['losses']}\n"
                )
            message_content = (
                f"## {player_name}"
                f"\n**Lifetime:**\n"
                f"Wins: {player_stats['lifetime']['wins']} - "
                f"Losses: {player_stats['lifetime']['losses']} - "
                f"Winrate: {player_stats['lifetime']['winrate']}\n"
                
                f"\n**This Season:**\n"
                f"Wins: {player_stats['season']['wins']} - "
                f"Losses: {player_stats['season']['losses']} - "
                f"Winrate: {player_stats['season']['winrate']}\n"
                
                f'{bracket_demon_message}'

                f'{rival_message}'
                
                f"\n**Best Placements:**\n"
                f'{best_placements}\n'
            )
            await channel.send(message_content)
            
        except PlayerNotFoundError:
            await self.send_closest_player(player_name, channel)
            
    @commands.command(name='get_head_to_head', aliases=['h2h', 'headtohead', 'geth2h'])
    async def get_head_to_head(self, ctx, set_limit: str="5", *, players: str):
        players = players.split('-')
        player1 = players[0]
        player2 = players[1]
        channel = ctx.channel
        try:
            player1_wins, player2_wins, recent_matches = await self.bot.dh.get_head_to_head(player1, player2, set_limit)
            message_content = (
                f'## {player1} {player1_wins}-{player2_wins} {player2}\n'
                f'{recent_matches}'
            )
            message = await channel.send(message_content)
        except PlayerNotFoundError:
            pass
        except ValueError:
            message_content = (
                f'Error: Invalid number of sets provided. Please provide a valid integer or "all"'
            )
            await channel.send(message_content)
            
    @commands.command(name='change_name')
    async def change_name(self, ctx, name: str):
        user_id = ctx.message.author.id
        channel = ctx.channel
        try:
            await self.bot.dh.change_name(user_id, name)
            message_content = (
                f"Name successfully changes to `{name}`"
            )
            await channel.send(message_content)
        except PlayerNotFoundError:
            message_content = (
                f"Error: You are not currently registered. Type !Register <name> to link yourself to the database"
            )
            await channel.send(message_content)
        except NameNotUniqueError:
            message_content = (
                f"Error: The name {name} is already taken."
            )
            await channel.send(message_content)
            
    @commands.command(name='get_bracket', aliases=['bracket'])
    async def get_bracket(self, ctx, *, tournament_name: str):
        channel = ctx.channel
        try: 
            tournament = await self.bot.dh.get_bracket(tournament_name)
            if tournament:
                message_content = (
                    f"{tournament['name']}: {tournament['link']}"
                )
                await channel.send(message_content)
            else:
                closest_tournament_name = await self.bot.dh.find_closest_tournament(tournament_name)
                message_content = (
                    f'Error: Tournament: `{tournament_name}` not found. Perhaps you meant `{closest_tournament_name}`?'
                )
                await channel.send(message_content)
        except PlayerNotFoundError:
            pass
        
    async def send_closest_player(self, player_name, channel):
        try: 
            closest_player_name = await self.bot.dh.find_closest_player_name(player_name)
            message_content = (
                f'Error: Player: `{player_name}` not found. Perhaps you meant `{closest_player_name}`?'
            )
            await channel.send(message_content)
        except PlayerNotFoundError:
            message_content = (
                f'Error: Player: `{player_name}` not found.'
            )
            await channel.send(message_content)
            

         
        
            
async def setup(bot):
    await bot.add_cog(DataCog(bot))