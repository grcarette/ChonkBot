# utils/event_logger.py

import logging
import os
from datetime import datetime


LOG_DIR = 'logs'


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _sanitize_name(name: str) -> str:
    """Make a tournament name safe for use as a filename."""
    return ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in name).strip()


class EventLogger:
    """
    Structured logger for a single tournament event.

    Usage:
        logger = EventLogger('UCH Monthly 12')
        logger.info('SWISS', 'Round 2 started — 8 players, 4 matches')
        logger.error('RANKED', 'API call failed — timeout')

    Log files are written to logs/<tournament_name>_<date>.log
    A shared bot.log captures anything not tied to a specific event.
    """

    def __init__(self, tournament_name: str):
        self.tournament_name = tournament_name
        _ensure_log_dir()

        date_str     = datetime.now().strftime('%Y-%m-%d')
        safe_name    = _sanitize_name(tournament_name)
        log_filename = os.path.join(LOG_DIR, f'{safe_name}_{date_str}.log')

        # Each tournament gets a uniquely named logger so multiple
        # simultaneous events never share handlers or mix output.
        logger_name  = f'event.{safe_name}.{date_str}'
        self._logger = logging.getLogger(logger_name)

        # Guard against duplicate handlers if the logger is re-used
        # (e.g. bot restart reloads the same tournament).
        if not self._logger.handlers:
            self._logger.setLevel(logging.DEBUG)

            formatter = logging.Formatter(
                fmt='[%(asctime)s] [%(levelname)-5s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            )

            # File handler — persists everything DEBUG and above
            fh = logging.FileHandler(log_filename, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            self._logger.addHandler(fh)

            # Console handler — INFO and above only, keeps terminal readable
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(formatter)
            self._logger.addHandler(ch)

        self.info('LOGGER', f'Log opened — {log_filename}')

    # ── Public API ────────────────────────────────────────────────────────────

    def info(self, category: str, message: str) -> None:
        self._logger.info(self._fmt(category, message))

    def warning(self, category: str, message: str) -> None:
        self._logger.warning(self._fmt(category, message))

    def error(self, category: str, message: str) -> None:
        self._logger.error(self._fmt(category, message))

    def debug(self, category: str, message: str) -> None:
        self._logger.debug(self._fmt(category, message))

    def exception(self, category: str, message: str) -> None:
        """Log an error with the current exception traceback attached."""
        self._logger.exception(self._fmt(category, message))

    # ── Convenience methods for common event milestones ───────────────────────

    def state_transition(self, from_state: str, to_state: str) -> None:
        self.info('STATE', f'{from_state} → {to_state}')

    def round_started(self, round_num: int, player_count: int, match_count: int) -> None:
        self.info('SWISS', f'Round {round_num} started — {player_count} players, {match_count} matches')

    def round_complete(self, round_num: int) -> None:
        self.info('SWISS', f'Round {round_num} complete')

    def match_created(self, match_id, player_1, player_2, round_num: int) -> None:
        self.info('SWISS', f'Match {match_id} created — {player_1} vs {player_2} (round {round_num})')

    def match_result(self, match_id, winner_id, loser_id, is_dq: bool = False) -> None:
        suffix = ' [DQ]' if is_dq else ''
        self.info('SWISS', f'Match {match_id} reported — winner: {winner_id}, loser: {loser_id}{suffix}')

    def bye_awarded(self, player_id) -> None:
        self.info('SWISS', f'Bye awarded to {player_id}')

    def ranked_reported(self, winner_id: int, loser_id: int, match_id: any):
        # This matches the regex: \[RANKED\] Reported — winner: \S+, loser: \S+
        self.info('RANKED', f"Reported — winner: {winner_id}, loser: {loser_id} (Match ID: {match_id})")

    def ranked_failed(self, winner_id, loser_id, error: str) -> None:
        self.error('RANKED', f'API failure — winner: {winner_id}, loser: {loser_id} — {error}')

    def player_registered(self, player_id, username: str) -> None:
        self.info('REGISTRATION', f'{username} ({player_id}) registered')

    def player_dropped(self, player_id, username: str) -> None:
        self.info('REGISTRATION', f'{username} ({player_id}) dropped')

    def player_dq(self, player_id, had_active_match: bool = False, opponent_id=None) -> None:
        if had_active_match:
            self.info('DQ', f'Player {player_id} disqualified — active match ended, {opponent_id} wins by default')
        else:
            self.info('DQ', f'Player {player_id} disqualified — no active match')

    def rehydrated(self, round_num: int, pending_count: int) -> None:
        self.info('RESTART', f'Rehydrated — round {round_num}, {pending_count} pending ranked results')

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fmt(self, category: str, message: str) -> str:
        return f'[{category}] {message}'


# ── Shared bot logger (not tied to any tournament) ────────────────────────────

def get_bot_logger() -> logging.Logger:
    """
    Returns the shared bot-level logger. Use for startup, Discord connection,
    and anything not tied to a specific tournament event.
    """
    _ensure_log_dir()
    logger = logging.getLogger('bot')

    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt='[%(asctime)s] [%(levelname)-5s] [BOT] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        fh = logging.FileHandler(os.path.join(LOG_DIR, 'bot.log'), encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger