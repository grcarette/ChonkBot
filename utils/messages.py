import discord
from discord.ext import commands
from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS

def get_tournament_creation_message(event_name, event_time):
    tournament_message = (
        f"## {event_name}\n"
        f"{event_time}\n\n"    
        "## Select the tournament format: \n"
        f"{NUMBER_EMOJIS[1]}: Single Elimination\n"
        f"{NUMBER_EMOJIS[2]}: Double Elimination\n"
        f"{NUMBER_EMOJIS[3]}: Swiss\n"
        f"{NUMBER_EMOJIS[4]}: FFA Filter\n\n"
        "## Select other configurations:\n"
        f"{INDICATOR_EMOJIS['blue_check']}: Require Check-in\n"
        f"{INDICATOR_EMOJIS['lock']}: Require TO approval for registration\n"
        f"{INDICATOR_EMOJIS['dice']}: Create randomized stagelist\n"
        f"{INDICATOR_EMOJIS['red_x']}: Require stage bans\n"
        f"{INDICATOR_EMOJIS['eye']}: Hide Channels\n"
        "\n"
        f"React with {INDICATOR_EMOJIS['green_check']}: to confirm your submission"
    )
    return tournament_message

async def get_lobby_instructions(bot, lobby, stage=False, winner=False):
    tournament = await bot.dh.get_tournament(name=lobby['tournament'])
    guild = bot.guilds[0]
    players = [discord.utils.get(guild.members, id=player) for player in lobby['players']]
    
    if lobby['stage'] == 'checkin':
        pings = " ".join([f"{player.mention}" for player in players])
        message = (
            f"# Welcome to lobby {lobby['lobby_id']}\n"
            f"{pings}"
            f"\nTo Check in for your match, react to this message with {INDICATOR_EMOJIS['green_check']}"
        )
    elif lobby['stage'] == 'reporting':
        pings = "\n".join([f"{NUMBER_EMOJIS[i+1]} {player.mention}" for i, player in enumerate(players)])
        message = (
            f"## You will be playing on {stage['name']}\n**Code: {stage['code']}**\n\n"
            f"When the match is finished, report the match by reacting to the **player who won**\n"
            f"{pings}"
        )
    elif lobby['stage'] == 'confirmation':
        message = (
            f'## You have reported {winner.mention} as the winner\n'
            'Is this correct?'
        )
    elif lobby['stage'] == 'finished':
        message = (
            '## This lobby is now closed. You will be pinged when it is time for your next match'
        )

    return message

async def get_stage_ban_message(stages_text, user):
    header = '# Stage banning\n'
    footer = f'\n\n{user.mention} Please select one stage you **do not** wish to play on' 
    message = header + stages_text + footer
    return message