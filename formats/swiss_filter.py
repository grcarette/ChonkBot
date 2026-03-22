# formats/swiss_filter.py

from formats.swiss import SwissFormat


class SwissFilterFormat(SwissFormat):
    """
    Swiss Filter format — uses a Swiss stage to seed players into 3 brackets.
    Registration and the Swiss stage are inherited from SwissFormat.
    Bracket splitting logic is not yet implemented.
    """
    pass