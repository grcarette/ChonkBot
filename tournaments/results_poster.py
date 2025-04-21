import discord
import random

from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import PRESET_COLORS
from utils.get_bracket_link import get_bracket_link

from ui.link_view import LinkView

from .challonge_handler import ChallongeHandler

RESULTS_CHANNEL_ID = 1346422769721544754

async def post_results(bot, challonge_link, challonge_id, tournament_name):
    ch = ChallongeHandler()
    channel = discord.utils.get(bot.guild.channels, id=RESULTS_CHANNEL_ID)
    challonge_id = challonge_id
    final_results = await ch.get_final_results(challonge_id)
    
    overall_winner = ''
    results = ''
    
    for player in final_results:
        mention = player['name']
            
        rank = player['final_rank']
            
        if rank == 1:
            emoji = RESULT_EMOJIS['1st']
            overall_winner = f"**{RESULT_EMOJIS['trophy']} Overall Winner: {mention}**\n\n"
        elif rank == 2:
            emoji = RESULT_EMOJIS['2nd']
        elif rank == 3:
            emoji = RESULT_EMOJIS['3rd']            
        elif rank > 3 and rank <= 8:
            emoji = RESULT_EMOJIS['medal']
        else:
            emoji = ''        
            
        results += f"{rank}: {player['name']} {emoji}\n"
        
    message_content = overall_winner + results
    bracket_link = await get_bracket_link(challonge_link)

    embed = discord.Embed(
        title=f"{tournament_name}",
        description=message_content,
        color=random.choice(PRESET_COLORS)
    )
    label = f"{INDICATOR_EMOJIS['link']} Bracket"
    
    view = LinkView(label, bracket_link)

    await channel.send(embed=embed, view=view)