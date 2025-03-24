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

async def get_lobby_instructions(datahandler, lobby_id, tournament_name):
    lobby = await datahandler.get_lobby(lobby_id, tournament_name)
    if lobby['stage'] == 'check_in':
        message = (
            f"# Welcome to lobby {lobby['lobby_id']}\n"
            f"To Check in for your match, react to this message with {INDICATOR_EMOJIS['green_check']}"
        )
        
    return message