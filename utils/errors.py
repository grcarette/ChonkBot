class TournamentExistsError(Exception):
    """Raised when a tournament with the same name already exists"""
    pass

class TournamentNotFoundError(Exception):
    """Raised when a tournament is not found"""
    pass
