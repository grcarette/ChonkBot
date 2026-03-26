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

    async def get_pending_matches(self) -> list[dict]:
        """
        Return pending matches not yet called as lobbies.
        Challonge formats query Challonge. Swiss returns [] (matches are created by pairing cycle).
        """
        return []

    async def call_match(self, match_data: dict, hold_match: bool = False) -> None:
        """Create and initialize a lobby for a specific match. Challonge formats only."""
        pass

    async def call_matches(self) -> None:
        """Call all pending uncalled matches. Challonge formats only."""
        pass

    def toggle_hold_when_ready(self, match_id: int) -> bool:
        """Toggle hold-when-ready for a match. Returns new state. Challonge formats only."""
        return False

    async def on_match_calling_loop(self) -> None:
        """
        Called by TournamentManager.start_tournament_loop after the tournament
        goes active. Override to drive format-specific match calling.

        Default: TM calls refresh_match_calls() for DE/SE after this returns.
        Swiss overrides to no-op since SwissManager drives pairing via the button.
        """
        pass

    async def get_active_buttons(self, state: str) -> list[str]:
        """
        Return which format-specific buttons should be shown for this state.
        BotControlView calls this and adds the returned buttons alongside
        its fixed state buttons.

        Valid identifiers:
            'seeding'             — Challonge seeding tool
            'reset'               — Reset tournament
            'autocall'            — Toggle auto match-calling
            'round_button'        — Start next Swiss round

        Default implementation covers DE/SE.
        Override in formats that need different behaviour.
        """
        if state == 'registration':
            return ['seeding']
        elif state == 'checkin':
            return ['autocall', 'seeding']
        elif state == 'active':
            return ['autocall', 'reset']
        return []

    async def get_dashboard_state(self) -> dict:
        """
        Return format-specific state for the web dashboard.
        Called by the web server on every poll. The result is passed through
        as `format_state` in the tournament API response.
        Default: empty dict (no extra state needed).
        """
        return {}

    def get_action_buttons(self, tournament_state: str) -> list[dict]:
        """
        Return a list of button descriptors for the dashboard action area.
        Called client-side via the format_actions list in the API response.
        Each button is a dict with:
            id:       str   — element ID
            label:    str   — button text
            style:    str   — 'success' | 'primary' | 'danger' | 'secondary' | 'toggle-on' | 'toggle-off'
            disabled: bool
            confirm:  dict | None — { title, message, type } if confirmation required
            action:   str   — doAction() call
        Default: empty list.
        """
        return []

    async def on_lobby_reopen(self, lobby, lobby_db: dict) -> None:
        """
        Called when a finished lobby is reopened to checkin.
        Format-specific cleanup — e.g. unrecording Swiss results.
        Default: nothing.
        """
        pass

    @property
    def supports_reset(self) -> bool:
        """DE/SE: True. Swiss: False."""
        return True

    @property  
    def shows_bracket_link(self) -> bool:
        """DE/SE: True. Swiss: False."""
        return False

    @property
    def shows_seeding_button(self) -> bool:
        """Whether the seeding tool button should appear. DE/SE: True. Swiss: False."""
        return False

    @property
    def shows_round_button(self) -> bool:
        """Whether the Start Round button should appear. Swiss: True. DE/SE: False."""
        return False

    @property
    def ranked_compatible(self) -> bool:
        """Whether this format supports UCH Ranked reporting. Default: False."""
        return False

