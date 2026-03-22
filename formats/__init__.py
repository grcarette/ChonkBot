# formats/__init__.py


def make_format(tm):
    """
    Factory: return the correct BaseFormat subclass for this tournament.

    To add a new format:
    1. Create formats/your_format.py implementing BaseFormat
    2. Add an elif branch here
    3. Add the format name to the selector in ui/create_tournament.py
    """
    fmt = tm.tournament.get('format')

    if fmt in ('double elimination', 'single elimination'):
        from formats.challonge import ChallongeFormat
        return ChallongeFormat(tm)

    if fmt == 'swiss':
        from formats.swiss import SwissFormat
        return SwissFormat(tm)
        
    if fmt == 'swiss filter':
        from formats.swiss_filter import SwissFilterFormat
        return SwissFilterFormat(tm)

    raise ValueError(f"Unknown tournament format: '{fmt}'")