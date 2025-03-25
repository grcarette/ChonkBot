class TournamentExistsError(Exception):
    """Raised when a tournament with the same name already exists"""
    pass

class TournamentNotFoundError(Exception):
    """Raised when a tournament is not found"""
    pass

class UserNotFoundError(Exception):
    """Raised when a user is not found"""
    pass

class NoStagesFoundError(Exception):
    """Raised when a user has blocked all stages"""
    pass

class PlayerNotFoundError(Exception):
    """Raised when a user can not be linked to a player"""
    pass

class PlayerLinkExistsError(Exception):
    """Raised when a user tries to link to a player who is already linked"""
    pass