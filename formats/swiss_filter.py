# formats/swiss_filter.py

from formats.swiss import SwissFormat


class SwissFilterFormat(SwissFormat):
    """
    Swiss Filter format — uses a Swiss stage to seed players into 3 brackets.

    Differences from SwissFormat:
    - No late registration once the event is active.
    - When the Swiss phase ends, bracket phases are started by the TO rather
      than the event being finalized immediately.
    - get_dashboard_state() exposes a phase_transition prompt when the Swiss
      phase is done and bracket phases are waiting.
    """

    # ─── Registration ─────────────────────────────────────────────────────────

    @property
    def allows_late_registration(self) -> bool:
        return False

    @property
    def owns_end_transition(self) -> bool:
        """Keep the event active while bracket phases are waiting.
        _finish_event() will set state to 'finished' once all phases complete."""
        return True

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_tournament_start(self) -> None:
        """Sync floated players, mark phase 0 as active, then run normal Swiss start."""
        em = self.tm.bot.th.events.get(self.tm.tournament['_id'])
        if em:
            await em.sync_floated_players()
        await self._ensure_phase_active()
        await super().on_tournament_start()

    async def on_match_calling_loop(self) -> None:
        """On restart the tournament_start path is skipped, so repair phase state here."""
        await self._ensure_phase_active()
        await super().on_match_calling_loop()

    async def _ensure_phase_active(self) -> None:
        """Set phase 0 state to 'active' if it's still 'setup' (idempotent)."""
        em = self.tm.bot.th.events.get(self.tm.tournament['_id'])
        if not em:
            return
        phases = em.event.get('phases', [])
        if phases and phases[0].get('state') == 'setup':
            await em._update_phase_state(0, 'active')
            em.event = await self.tm.bot.dh.get_tournament_by_id(self.tm.tournament['_id'])

    async def on_tournament_end(self) -> None:
        """
        Swiss phase complete: flush any pending Ranked results and mark the
        phase as finished in the event doc. The event stays 'active' — the TO
        will start the bracket phase next via the dashboard.
        """
        await self.flush_pending_results()

        em = self.tm.bot.th.events.get(self.tm.tournament['_id'])
        if em:
            await em.on_phase_finished(0)

    # ─── Dashboard state ──────────────────────────────────────────────────────

    async def get_dashboard_state(self) -> dict:
        """
        Extends the swiss state dict with a `phase_transition` descriptor when
        the Swiss phase is done and bracket phases are awaiting the TO's signal.
        Checked by phase state, not tournament state, so it survives bot restarts.

        Any format can follow this pattern: return a `phase_transition` dict
        from get_dashboard_state() and the dashboard will render the transition
        button automatically.
        """
        state = await super().get_dashboard_state()

        event = await self.tm.bot.dh.get_tournament_by_id(self.tm.tournament['_id'])
        phases = event.get('phases', [])
        swiss_done = bool(phases) and phases[0].get('state') == 'finished'
        has_waiting = any(p.get('state') == 'waiting' for p in phases[1:])

        if swiss_done and has_waiting:
            state['phase_transition'] = {
                'label':           'Start Bracket Phase',
                'action':          'transition_phase',
                'confirm_title':   'Start Bracket Phase?',
                'confirm_message': (
                    'Players will be sorted into brackets based on their Swiss record. '
                    'This cannot be undone.'
                ),
            }

        return state
