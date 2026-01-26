import discord
from datetime import datetime, timezone
from discord.ext import commands
from utils.errors import PlayerNotFoundError, NameNotUniqueError, PlayerLinkExistsError
from utils.errors import UserLinkExistsError, PlayerNotRegisteredError, TournamentNotFoundError, MissingH2HParams
from utils.reaction_utils import create_reaction_flag

class DataCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="register_player", aliases=['register player', 'register'])
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
        player_exists = await self.bot.dh.lookup_player(player_name, use_alias=False)
        message_content = (
            f'Player `{player_name}` found!\n'
            f'Awaiting Approval...'
        )
        await channel.send(message_content)
        await create_reaction_flag(self.bot, ctx.message, 'link_confirmation', user_filter=self.bot.admin_id, value=player_name)
        
    @register_player.error
    async def register_player_error(self, ctx, error):
        channel = ctx.channel
        if isinstance(error, commands.MissingRequiredArgument):
            message_content = (
                f'Error: Missing argument `{error.param.name}`\n'
                f'Usage: `!register <player_name>`'
            )
            await channel.send(message_content)
        elif isinstance(error.original, PlayerNotFoundError):
            await self.send_closest_player(error.original.player_name, channel)
        elif isinstance(error.original, PlayerLinkExistsError):
            message_content = (
                f'Error: Player `{error.original.player_name}` is already linked to User: `{error.original.user_name}`'
            )
            await channel.send(message_content)
        elif isinstance(error.original, UserLinkExistsError):
            message_content = (
                f'Error: You are already linked to player `{error.original.player_name}`\n'
                f'Type `!unregister` if this is incorrect'
            )
            await channel.send(message_content)
        else:
            print(error)
            
    @commands.command(name='unregister_player', aliases=['unregister player', 'unregister'])
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
    
    @unregister_player.error
    async def unregister_player_error(self, ctx, error):
        channel = ctx.channel
        if isinstance(error.original, PlayerNotRegisteredError):
            message_content = (
                f'Error: You are not currently registered to a player'
            )
            await channel.send(message_content)
        
    # @commands.command(name='get_player_stats', aliases=['stats', 'get player stats', 'get stats'])
    # async def get_player_stats(self, ctx, *, player_name):
    #     if ctx.channel.name != "temporary-bot-testing":
    #         return
    #     channel = ctx.channel
    #     player_stats = await self.bot.dh.get_player_stats(player_name)

    #     best_placements = '\n'.join(player_stats['placements'])
    #     if player_stats['bracket_demon'] == None:
    #         bracket_demon_message = (
    #             "\n**Bracket Demon:** `Sample size too small`"
    #         )
    #     else:
    #         bracket_demon_message = (
    #             f"\n**Bracket Demon: **" 
    #             f"`{player_stats['bracket_demon']['name']}`\n"
    #             f"Wins: {player_stats['bracket_demon']['wins']} - "
    #             f"Losses: {player_stats['bracket_demon']['losses']}\n"
    #         )
    #     if player_stats['rival'] == None:
    #         rival_message = (
    #             "\n**Rival:** `Sample size too small`\n"
    #         )
    #     else:
    #         rival_message = (
    #             f"\n**Rival: **" 
    #             f"`{player_stats['rival']['name']}`\n"
    #             f"Wins: {player_stats['rival']['wins']} - "
    #             f"Losses: {player_stats['rival']['losses']}\n"
    #         )
    #     message_content = (
    #         f"## {player_name}"
    #         f"\n**Lifetime:**\n"
    #         f"Wins: {player_stats['lifetime']['wins']} - "
    #         f"Losses: {player_stats['lifetime']['losses']} - "
    #         f"Winrate: {player_stats['lifetime']['winrate']}\n"
            
    #         f"\n**This Season:**\n"
    #         f"Wins: {player_stats['season']['wins']} - "
    #         f"Losses: {player_stats['season']['losses']} - "
    #         f"Winrate: {player_stats['season']['winrate']}\n"
            
    #         f'{bracket_demon_message}'

    #         f'{rival_message}'
            
    #         f"\n**Best Placements:**\n"
    #         f'{best_placements}\n'
    #     )
    #     await channel.send(message_content)

    # @get_player_stats.error
    # async def get_player_stats_error(self, ctx, error):
    #     channel = ctx.channel
    #     if isinstance(error, commands.MissingRequiredArgument):
    #         message_content = (
    #             f'Error: Missing argument `{error.param.name}`\n'
    #             f'Usage: `!stats <player_name>`'
    #         )
    #         await channel.send(message_content)
    #     elif isinstance(error.original, PlayerNotFoundError):
    #         await self.send_closest_player(error.original.player_name, channel)
    #     else:
    #         print(error)
            
    # @commands.command(name='get_head_to_head', aliases=['h2h', 'headtohead', 'geth2h'])
    # async def get_head_to_head(self, ctx, set_limit: str="5", *, players: str):
    #     expected_length = 2
    #     players = players.split('-')
    #     if len(players) != expected_length:
    #         raise MissingH2HParams
    #     player1 = players[0]
    #     player2 = players[1]
    #     channel = ctx.channel

    #     player1_wins, player2_wins, recent_matches = await self.bot.dh.get_head_to_head(player1, player2, set_limit)
    #     message_content = (
    #         f'## {player1} {player1_wins}-{player2_wins} {player2}\n'
    #         f'{recent_matches}'
    #     )
    #     message = await channel.send(message_content)

    # @get_head_to_head.error
    # async def get_head_to_head_error(self, ctx, error):
    #     channel = ctx.channel
    #     if isinstance(error, commands.MissingRequiredArgument):
    #         message_content = (
    #             f'Error: Missing arguments\n'
    #             f'Usage: `!h2h <# of sets/"all"> <player1_name>-<player2_name>`'
    #         )
    #         await channel.send(message_content)
    #     elif isinstance(error.original, MissingH2HParams):
    #         message_content = (
    #             f'Error: Missing arguments\n'
    #             f'Usage: `!h2h <# of sets/"all"> <player1_name>-<player2_name>`'
    #         )
    #         await channel.send(message_content)
    #     elif isinstance(error.original, PlayerNotFoundError):
    #         await self.send_closest_player(error.original.player_name, channel)
    #     elif isinstance(error.original, ValueError):
    #         message_content = (
    #             f'Error: Invalid number of sets provided. Please provide a valid integer or "all"'
    #         )
    #         await channel.send(message_content)
    #     else:
    #         print(error)
            
    # @commands.command(name='get_leaderboard', aliases=['leaderboard'])
    # async def get_leaderboard(self, ctx, timeframe: str='False', start_timestamp: str=None, end_timestamp: str=None):
    #     if timeframe.lower() == 'custom':
    #         if not start_timestamp or not end_timestamp:
    #             return
    #         try: 
    #             start_timestamp = datetime.strptime(start_timestamp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    #             end_timestamp = datetime.strptime(end_timestamp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    #         except: 
    #             return
    #     channel = ctx.channel
    #     leaderboard = await self.bot.dh.get_leaderboard(timeframe, start_timestamp, end_timestamp)
    #     message_content = ''
    #     for i, player in enumerate(leaderboard):
    #         line_content = (
    #             f"**{i+1}: {player['name']}**\n"
    #             f"Wins: {player['wins']} Losses: {player['losses']} Winrate: {player['winrate']}\n"
    #         )
    #         message_content += line_content
    #     await channel.send(message_content)
            
    @commands.command(name='change_name')
    async def change_name(self, ctx, name: str):
        user_id = ctx.message.author.id
        channel = ctx.channel
        
        await self.bot.dh.change_name(user_id, name)
        message_content = (
            f"Name successfully changes to `{name}`"
        )
        await channel.send(message_content)

    @change_name.error
    async def change_name_error(self, ctx, error):
        channel = ctx.channel
        if isinstance(error, commands.MissingRequiredArgument):
            message_content = (
                f'Error: Missing argument `{error.param.name}`\n'
                f'Usage: `!change_name <new name>`'
            )
            await channel.send(message_content)
        elif isinstance(error.original, PlayerNotRegisteredError):
            message_content = (
                f"Error: You are not currently registered. Type !Register <name> to link yourself to the database"
            )
            await channel.send(message_content)
        elif isinstance(error.original, NameNotUniqueError):
            message_content = (
                f"Error: The name {error.original.name} is already taken."
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
        
    @get_bracket.error
    async def get_bracket_error(self, ctx, error):
        channel = ctx.channel
        if isinstance(error, commands.MissingRequiredArgument):
            message_content = (
                f'Error: Missing argument `{error.param.name}`\n'
                f'Usage: `!bracket <bracket name>`\n'
                f'Unfortunately UCH tournaments have historically had poor naming conventions, so this command may be frustrating to use.'
            )
            await channel.send(message_content)
        elif isinstance(error.original, TournamentNotFoundError):
            message_content = (
                f'Error: Tournament with {error.original.key}: {error.original.value} not found.'
            )
            await channel.send(message_content)
    

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