import discord
from datetime import datetime, timezone
from discord.ext import commands
from discord import app_commands
from utils.errors import PlayerNotFoundError, NameNotUniqueError, PlayerLinkExistsError
from utils.errors import UserLinkExistsError, PlayerNotRegisteredError, TournamentNotFoundError, MissingH2HParams
from utils.reaction_utils import create_reaction_flag
from ui.register_player import RegistrationView

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

    @app_commands.command(name="register_database", description="Register yourself in the database.")
    async def register_database(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        ALLOWED_CHANNEL = "temporary-data-bot"
        if interaction.channel.name != ALLOWED_CHANNEL:
            return
        
        target_user = member or interaction.user
        search_name = target_user.display_name
        
        player_data = await self.bot.dh.tournamentdata_api.lookup_player(search_name)
        
        if not player_data:
            return await interaction.followup.send(f"No profile found for `{search_name}`.", ephemeral=True)

        if player_data.get("discord_id"):
            return await interaction.followup.send(f"**{player_data['username']}** is already linked.", ephemeral=True)

        recent_tourneys = await self.bot.dh.tournamentdata_api.get_recent_results(player_data['_id'])
        
        embed = discord.Embed(
            title="Verify Tournament Profile",
            description=f"I found a match for **{target_user.mention}**. Do these recent results look correct?",
            color=discord.Color.blue()
        )
        embed.add_field(name="Username", value=player_data['username'], inline=True)

        if recent_tourneys:
            results_text = ""
            for t in recent_tourneys:
                placement = "N/A"
                for event in t.get('events', []):
                    res = next((item for item in event.get('results', []) if item['id'] == player_data['_id']), None)
                    if res:
                        placement = res.get('placement', '??')
                        break
                
                date_str = str(t.get('date'))[:10]
                results_text += f"• **{t['name']}** ({date_str}): {placement}\n"
            
            embed.add_field(name="Recent Results", value=results_text, inline=False)
        else:
            embed.add_field(name="Recent Results", value="No tournament history found.", inline=False)

        view = RegistrationView(self.bot.dh.tournamentdata_api, player_data, target_user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="player_history", description="View your detailed tournament history.")
    async def player_history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        player = await self.bot.dh.tournamentdata_api.players.find_one(
            {"discord_id": str(interaction.user.id)}
        )

        if not player:
            name_match = await self.bot.dh.tournamentdata_api.lookup_player(interaction.user.display_name)
            
            msg = "❌ Your Discord account is not linked to a tournament profile.\n"
            if name_match:
                msg += f"I found a profile for **{name_match['username']}** that looks like you! "
                msg += "Please go to `#temporary-data-bot` and use `/register_database` to link it."
            else:
                msg += "I couldn't find a profile matching your name. Please use `/register_database` in `#temporary-data-bot`."
            
            return await interaction.followup.send(msg)

        p_id = player['_id']
        username = player['username']

        match_stats = {} 
        total_w, total_l = 0, 0
        matches_cursor = self.bot.dh.tournamentdata_api.matches.find({"$or": [{"winner_id": p_id}, {"loser_id": p_id}]})
        
        async for m in matches_cursor:
            if m.get("is_dq"): continue
            t_id = m['tournament_id']
            if t_id not in match_stats: match_stats[t_id] = [0, 0]
            
            if m['winner_id'] == p_id:
                match_stats[t_id][0] += 1
                total_w += 1
            else:
                match_stats[t_id][1] += 1
                total_l += 1


        history = []
        tourneys_cursor = self.bot.dh.tournamentdata_api.tournaments.find({"events.results.id": p_id})
        
        async for t in tourneys_cursor:
            res_entry = None
            e_type = "Main"
            for event in t.get('events', []):
                res = next((item for item in event.get('results', []) if item['id'] == p_id), None)
                if res:
                    res_entry, e_type = res, event.get('event_type', 'Main')
                    break
            
            if not res_entry: continue
            w, l = match_stats.get(t['_id'], [0, 0])
            d = t.get("date", "N/A")
            d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]

            history.append({
                "date": d_str, "name": t.get("name", "Unknown"), "type": e_type,
                "place": res_entry.get("placement", "??"), "dq": res_entry.get("dq", False),
                "record": f"{w}-{l}"
            })

        if not history:
            return await interaction.followup.send(f"Found your profile (**{username}**), but no tournament history was found.")

        history.sort(key=lambda x: x['date'], reverse=True)
        out = f"**DETAILED HISTORY: {username.upper()}**\n```\n"
        out += f"{'DATE':<12} {'TYPE':<10} {'PLACE':<8} {'RECORD':<8} {'TOURNAMENT'}\n{'-'*65}\n"
        
        for e in history[:15]:
            p_str = f"{e['place']}{' [DQ]' if e['dq'] else ''}"
            t_name = (e['name'][:25] + '..') if len(e['name']) > 25 else e['name']
            out += f"{e['date']:<12} {e['type']:<10} {p_str:<8} {e['record']:<8} {t_name}\n"

        wr = (total_w / (total_w + total_l) * 100) if (total_w + total_l) > 0 else 0
        out += f"{'-'*65}\nLIFETIME: {total_w}-{total_l} ({wr:.1f}%) across {len(history)} events.```"
        
        await interaction.followup.send(out)

        
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