from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS

def get_tournament_creation_message(event_name, event_time):
    tournament_message = (
        f"## {event_name}\n"
        f"{event_time}\n\n"    
        "## Please select the tournament format: \n"
        f"{NUMBER_EMOJIS[1]}: Single Elimination\n"
        f"{NUMBER_EMOJIS[2]}: Double Elimination\n"
        f"{NUMBER_EMOJIS[3]}: Swiss\n"
        f"{NUMBER_EMOJIS[4]}: FFA Filter\n"
    )
    return tournament_message

    