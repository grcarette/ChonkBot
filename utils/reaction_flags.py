from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS


TOURNAMENT_CONFIGURATION = {
    NUMBER_EMOJIS[1]: ['format', 'Single Elimination'],
    NUMBER_EMOJIS[2]: ['format', 'Double Elimination'],
    NUMBER_EMOJIS[3]: ['format', 'Swiss'],
    NUMBER_EMOJIS[4]: ['format', 'FFA Filter'],
    INDICATOR_EMOJIS['blue_check']: ['check-in', True],
    INDICATOR_EMOJIS['lock']: ['approved_registration', True],
    INDICATOR_EMOJIS['dice']: ['randomized_stagelist', True],
    INDICATOR_EMOJIS['red_x']: ['require_stage_bans', True],
    INDICATOR_EMOJIS['eye']: ['hide_channels', True]
}

REGISTRATION_CONFIRMATION = {
    INDICATOR_EMOJIS['green_check']: True
}

MATCH_CHECKIN = {
    INDICATOR_EMOJIS['green_check']: True
}

FLAG_DICTIONARY = {
    'create_tournament': TOURNAMENT_CONFIGURATION,
    'confirm_registration': REGISTRATION_CONFIRMATION,
    'match_checkin': MATCH_CHECKIN
}