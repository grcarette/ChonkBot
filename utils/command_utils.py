from utils.emojis import INDICATOR_EMOJIS
COMMAND_DICT = {
    'help': {
        'usage': (
            f'`help`\n'
            f'Description: Explains how to use ChonkBot\n'
            f'Permissions: Everyone\n'
            f'Usage: `!help`'),
        'tag': 'info'
    },
    'list_commands': {
        'usage': (
            f'`commands`\n'
            f'Description: Lists all commands the user has the permission to use\n'
            f'Permissions: Everyone\n'
            f'Usage: `!commands`'),
        'tag': 'info'
    },
    'usage': { 
        'usage': (
            f'`usage`\n'
            f'Description: Returns usage instructions for the specified command\n'
            f'Permissions: Everyone\n'
            f'Usage: `!usage <command name>`'),
        'tag': 'info'
    },
    'random_level': { 
        'usage': (
            f'`random`\n'
            f'Description: Returns a random level with "block" and "favourite" reactions\n'
            f'Permissions: Everyone\n'
            f"Usage: `!random <optional: number of random maps (up to 5)>`."
            f"Additional Usage: React with {INDICATOR_EMOJIS['red_x']} to block a map from showing again. React with {INDICATOR_EMOJIS['star']} to favorite a map"),
        'tag': 'utility'
    },
    'get_player_stats': { 
        'usage': (
            f'`stats`\n'
            f'Description: Returns the tournament stats of the specified player\n'
            f'Permissions: Everyone\n'
            f'Usage: `!stats <player name>`'),
        'tag': 'player statistics'
    },
    'get_head_to_head': { 
        'usage': (
            f'`h2h`\n'
            f'Description: Returns the head to head data for the specified matchup\n'
            f'Permissions: Everyone\n'
            f'Usage: `!h2h <# of sets/"all">` <player1 name>-<player2 name>'),
        'tag': 'player statistics'
    },
    'get_leaderboard': { 
        'usage': (
            f'`leaderboard`\n'
            f'Description: Returns the top 10 win rates of players who have at least 16 sets played during a specified timeframe\n'
            f'Permissions: Everyone\n'
            f'Usage: `!leaderboard <timeframe: all, season, year, custom> <if custom: start date (YYYY-MM-DD),> <if custom: end date (YYYY-MM-DD)>`'),
        'tag': 'player statistics'
    },
    'add_level': { 
        'usage': (
            f'`add_level`\n'
            f'Description: Adds a level to the level database\n'
            f'Permissions: Only Bojack\n'
            f'Usage: `!add_level <level name> <creator> <code> <length> <multiple paths> <includes hazards> <imgur>`'),
        'tag': 'database'
    },
    'register_player': { 
        'usage': (
            f'`register`\n'
            f'Description: Registers a user to the database, linking their discord account to an existing player\n'
            f'Permissions: Everyone\n'
            f'Usage: `!register <player name>`'),
        'tag': 'database'
    },
    'unregister_player': { 
        'usage': (
            f'`unregister`\n'
            f'Description: Unregisters a user from the database, removing the link between their discord account and their player data\n'
            f'Permissions: Everyone\n'
            f'Usage: `!unregister`'),
        'tag': 'database'
    },
    'change_name': { 
        'usage': (
            f'`change_name`\n'
            f'Description: Changes the player name associated with the user\n'
            f'Permissions: Everyone\n'
            f'Usage: `!change_name <new name>`'),
        'tag': 'database'
    },
    'get_bracket': { 
        'usage': (
            f'`bracket`\n'
            f'Description: Returns the bracket link for the specified tournament *UCH tournament naming conventions are historically bad, so this command may be difficult to use\n'
            f'Permissions: Everyone\n'
            f'Usage: `!bracket <bracket name>`'),
        'tag': 'database'
    },
    'create_tournament': {
        'usage': (
            f'`create_tournament`\n'
            f'Description: Creates a tournament, organizes the channels/roles in discord, and stores it in the database\n'
            f'Permissions: Only Bojack\n'
            f'Usage: `!create_tournament <name>-<date: discord timestamp>`'),
        'tag': 'event'
    },
    'reveal_tournament': { 
        'usage': (
            f'`reveal_tournament`\n'
            f'Description: Sets public tournament channels to be visible\n'
            f'Permissions: Event Organizer\n'
            f'Usage: `!reveal_tournament`'),
        'tag': 'event'
    },
    'reset_lobby': { 
        'usage': (
            f'`reset_lobby`\n'
            f'Description: Resets a lobby to the stage banning phase\n'
            f"Permissions: Event Organizer, Assistant TO's\n"
            f'Usage: `!reset_lobby`'),
        'tag': 'event'
    },
    'create_lobby': { 
        'usage': (
            f'`create_lobby`\n'
            f'Description: Creates a lobby for debugging purposes\n'
            f'Permissions: Only Bojack\n'
            f'Usage: `!create_lobby`'),
        'tag': 'debug'
    },
}

def get_usage_message(command):
    return COMMAND_DICT[command]['usage']

