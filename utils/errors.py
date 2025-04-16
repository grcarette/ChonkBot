class TournamentExistsError(Exception):
    """Raised when a tournament with the same name already exists"""
    pass

class TournamentNotFoundError(Exception):
    """Raised when a tournament is not found"""
    def __init__(self, key, value, method):
        self.key=key
        self.value=value
        self.method=method
        super().__init__(f"Tournament with {self.key}: {self.value} not found in {method}")
    pass

class UserNotFoundError(Exception):
    """Raised when a user is not found"""
    pass

class LevelNotFoundError(Exception):
    """Raised when a level is not found"""
    pass

class NoStagesFoundError(Exception):
    """Raised when a user has blocked all stages"""
    pass

class PlayerNotFoundError(Exception):
    """Raised when a user can not be linked to a player"""
    def __init__(self, player, method):
        self.player_name=player
        self.method=method
        super().__init__(f"Player {self.player_name} not found in {method}")
    pass

class PlayerLinkExistsError(Exception):
    """Raised when a user tries to link to a player who is already linked"""
    def __init__(self, player, user, method):
        self.player_name=player
        self.user_name=user
        self.method=method
        super().__init__(f"Player: {player} already linked to User: {user}")
    pass

class UserLinkExistsError(Exception):
    """Raised when a user who is already linked tries to link to another player"""
    def __init__(self, user, player, method):
        self.user_name=user
        self.player_name=player
        self.method=method
        super().__init__(f"User: {user} already linked to Player {player}")
    pass

class PlayerNotRegisteredError(Exception):
    """Raised when a user attempts to use a command that requires registration"""
    pass

class NameNotUniqueError(Exception):
    """Raised when a user tries to register with an existing name"""
    def __init__(self, name, method):
        self.name=name
        self.method=method
        super().__init__(f'Name: {self.name} not unique in {method}')
    pass

class LevelExistsError(Exception):
    """Raised when a level already exists within the database"""
    pass

class MissingH2HParams(Exception):
    """Raised when a head to head stats command call is technically not missing parameters, but is entered incorrectly"""
    pass