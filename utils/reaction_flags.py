from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from datetime import datetime, timezone
import time

TOURNAMENT_CONFIGURATION = {
    NUMBER_EMOJIS[1]: ['format', 'Single Elimination'],
    NUMBER_EMOJIS[2]: ['format', 'double elimination'],
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

MATCH_CONFIRMATION = {
    INDICATOR_EMOJIS['green_check']: True,
    INDICATOR_EMOJIS['red_x']: True
}

RANDOM_STAGE = {
    INDICATOR_EMOJIS['red_x']: True,
    INDICATOR_EMOJIS['star']: True,
}

LINK_CONFIRMATION = {
    INDICATOR_EMOJIS['green_check']: True
}

FLAG_DICTIONARY = {
    'create_tournament': {
        'dict': TOURNAMENT_CONFIGURATION,
        'timestamp': None
    },
    'confirm_registration': {
        'dict': REGISTRATION_CONFIRMATION,
        'timestamp': None
    },
    'match_checkin': {
        'dict': MATCH_CHECKIN,
        'timestamp': 600
    },
    'match_confirmation': {
        'dict': MATCH_CONFIRMATION,
        'timestamp': 3600
    },
    'random_stage': {
        'dict': RANDOM_STAGE,
        'timestamp': 3600
    },
    'link_confirmation': {
        'dict': LINK_CONFIRMATION,
        'timestamp': None
    },
    'stage_ban': {
        'dict': None,
        'timestamp': None
    },
    'match_report': {
        'dict': None,
        'timestamp': None
    }
}


     
