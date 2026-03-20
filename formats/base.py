# formats/base.py


class BaseFormat:
    """
    Abstract base class for tournament formats.

    A format owns everything that varies between rulesets:
    - How the bracket or event document is set up
    - How players are registered and unregistered
    - How matches are called
    - How results are processed
    - How the tournament ends and is cleaned up

    Everything format-agnostic — channels, Discord UX, the lobby system,
    state machine progression — lives in TournamentManager and is accessed
    via self.tm.

    To implement a new format:
    1. Create a new file in formats/
    2. Subclass BaseFormat and implement all abstract methods
    3. Add it to the factory in formats/__init__.py
    4. Add it to the format selector in ui/create_tournament.py

    TournamentManager does not need to change.
    """

    def __init__(self, tm):
        self.tm = tm
        self.dh = tm.bot.dh

    # ─── Lifecycle — must implement ───────────────────────────────────────────

    async def on_initialize(self) -> None:
        """
        Set up any external state this format needs.
        Called once during initialize_event, before controls are shown.

        Examples:
        - DE/SE: create the Challonge bracket if it doesn't exist
        - Swiss: create the swiss event document if it doesn't exist
        """
        raise NotImplementedError

    async def on_player_register(self, user_id: int, user: dict) -> None:
        """
        Add a player to the format's tracking system.
        Called after the user document has been created in the DB.
        Responsible for storing the player in entrants via dh.register_player.

        user: the user document from the users collection (may be None in debug mode).

        Examples:
        - DE/SE: register on Challonge, store participant ID
        - Swiss: add to swiss event players dict, store None as participant ID
        """
        raise NotImplementedError

    async def on_player_unregister(self, user_id: int) -> None:
        """
        Remove a player from the format's tracking system.
        Called after the player has been removed from the DB entrants dict.

        Examples:
        - DE/SE: destroy the Challonge participant
        - Swiss: mark the player as dropped in the swiss event
        """
        raise NotImplementedError

    async def on_tournament_start(self) -> None:
        """
        Called by start_tournament after channel setup is complete.
        Responsible for starting the format's match calling mechanism.

        Examples:
        - DE/SE: call ch.start_tournament() to lock in seeding
        - Swiss: enable the Start Round button via swiss_manager.start()
        """
        raise NotImplementedError

    async def on_result(self, result: dict, lobby) -> None:
        """
        Called when a match result is recorded.

        result dict contains:
            match_id: int
            winner_id: int  (Discord user ID)
            loser_id: int   (Discord user ID)
            is_dq: bool

        lobby: the MatchLobby instance for this match.

        Examples:
        - DE/SE: report result to Challonge, then call next matches
        - Swiss: record result in swiss event, report to UCH Ranked API
        """
        raise NotImplementedError

    async def on_tournament_end(self) -> None:
        """
        Called when the tournament transitions to finished state.
        TournamentManager closes all lobbies before calling this.

        Examples:
        - DE/SE: finalize the Challonge bracket
        - Swiss: post final standings to results channel
        """
        raise NotImplementedError

    async def on_tournament_delete(self) -> None:
        """
        Called when the tournament is deleted entirely.
        TournamentManager handles Discord cleanup (channels, roles, category).
        This is for format-specific external cleanup only.

        Examples:
        - DE/SE: delete the Challonge bracket
        - Swiss: nothing (no external bracket to clean up)
        """
        raise NotImplementedError

    # ─── Optional overrides ───────────────────────────────────────────────────

    async def on_registration_gate(self, user_id: int, interaction) -> bool:
        """
        Format-specific registration gate check, called before a player is registered.
        Return True to allow registration, False to block it (and send an error message).

        Default: always allow.

        Examples:
        - Swiss: require a UCH Ranked account
        - DE/SE: no additional gate
        """
        return True

    async def on_reset(self) -> None:
        """
        Called during reset_tournament for format-specific cleanup.
        TournamentManager handles lobby deletion and DB state reset.

        Default: nothing.

        Examples:
        - DE/SE: reset the Challonge bracket
        - Swiss: nothing (no bracket to reset)
        """
        pass

    async def on_reset_report(self, lobby: dict) -> None:
        """
        Called during reset_report for format-specific match reset.

        Default: nothing.

        Examples:
        - DE/SE: call ch.reset_match()
        - Swiss: nothing
        """
        pass

    async def on_match_calling_loop(self) -> None:
        """
        Called by TournamentManager.start_tournament_loop after the tournament
        goes active. Override to drive format-specific match calling.

        Default: TM calls refresh_match_calls() for DE/SE after this returns.
        Swiss overrides to no-op since SwissManager drives pairing via the button.
        """
        pass

    @property
    def needs_match_call_refresh(self) -> bool:
        """
        Whether TournamentManager should call refresh_match_calls() after
        on_match_calling_loop completes. True for DE/SE, False for Swiss.
        Default: True.
        """
        return True

    @property
    def supports_reset(self) -> bool:
        """
        Whether this format supports mid-tournament reset.
        If False, the Reset Tournament button is hidden in BotControlView.
        Default: True.
        """
        return True

    @property
    def shows_bracket_link(self) -> bool:
        """
        Whether this format has a publicly accessible bracket URL.
        If True, TournamentInfoDisplay will show a bracket link.
        Default: False.
        """
        return False