"""
tests/test_bot_control_buttons.py

Tests for the format.get_active_buttons pattern and BotControlView button routing.

Covers:
- BaseFormat default get_active_buttons returns correct buttons per state
- ChallongeFormat returns seeding and match-calling buttons
- SwissFormat returns round button when active, nothing otherwise
- BotControlView.update_tournament_state adds correct fixed buttons per state
- BotControlView.update_tournament_state adds correct format-specific buttons
- DE and Swiss active states produce different button sets
- round_button is enabled and labelled correctly when added
- A future format can return a custom button set without changing BotControlView
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_tournament(format='double elimination', name='Test', tid='tid'):
    return {
        '_id': tid,
        'name': name,
        'format': format,
        'registration_open': False,
        'config': {'approved_registration': False},
        'state': 'registration',
        'stagelist': [],
        'organizers': [],
        'challonge_data': {'url': 'test-url', 'id': 'chid'},
    }


def make_tc(tournament):
    """Build a minimal TournamentControl stub for BotControlView.__init__."""
    tc = MagicMock()
    tc.tm = MagicMock()
    tc.tm.tournament = tournament
    tc.tm.format = None  # set per test
    tc.tm.bot = MagicMock()
    tc.tm.bot.dh = AsyncMock()
    tc.tm.get_tournament = AsyncMock(return_value=tournament)
    tc.tm.get_channel = AsyncMock(return_value=AsyncMock())
    return tc


def make_view(format_str='double elimination'):
    """Build a BotControlView with a mocked format."""
    from ui.bot_control import BotControlView
    tournament = make_tournament(format=format_str)
    tc = make_tc(tournament)
    view = BotControlView(tc, tournament)
    # Wire up a mock message so update_control doesn't crash
    view.message = AsyncMock()
    view.message.edit = AsyncMock()
    return view, tc


def button_ids(view) -> set[str]:
    """Return the set of custom_ids for all items currently in the view."""
    return {item.custom_id for item in view.children}


def button_labels(view) -> set[str]:
    """Return the set of labels for all items currently in the view."""
    return {item.label for item in view.children}


# ─── BaseFormat.get_active_buttons defaults ───────────────────────────────────

@pytest.mark.asyncio
async def test_base_format_registration_returns_seeding():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('registration')
    assert 'seeding' in result


@pytest.mark.asyncio
async def test_base_format_checkin_returns_autocall_and_seeding():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('checkin')
    assert 'autocall' in result
    assert 'seeding' in result


@pytest.mark.asyncio
async def test_base_format_active_returns_reset_and_match_call_buttons():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('active')
    assert 'reset' in result
    assert 'autocall' in result
    assert 'refresh_match_calls' in result


@pytest.mark.asyncio
async def test_base_format_active_does_not_return_round_button():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('active')
    assert 'round_button' not in result


@pytest.mark.asyncio
async def test_base_format_setup_returns_empty():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('setup')
    assert result == []


@pytest.mark.asyncio
async def test_base_format_finished_returns_empty():
    from formats.base import BaseFormat
    fmt = BaseFormat.__new__(BaseFormat)
    result = await fmt.get_active_buttons('finished')
    assert result == []


# ─── ChallongeFormat.get_active_buttons ──────────────────────────────────────

@pytest.mark.asyncio
async def test_challonge_format_active_includes_reset():
    from formats.challonge import ChallongeFormat
    fmt = ChallongeFormat.__new__(ChallongeFormat)
    result = await fmt.get_active_buttons('active')
    assert 'reset' in result


@pytest.mark.asyncio
async def test_challonge_format_active_does_not_include_round_button():
    from formats.challonge import ChallongeFormat
    fmt = ChallongeFormat.__new__(ChallongeFormat)
    result = await fmt.get_active_buttons('active')
    assert 'round_button' not in result


@pytest.mark.asyncio
async def test_challonge_format_registration_includes_seeding():
    from formats.challonge import ChallongeFormat
    fmt = ChallongeFormat.__new__(ChallongeFormat)
    result = await fmt.get_active_buttons('registration')
    assert 'seeding' in result


# ─── SwissFormat.get_active_buttons ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_format_active_returns_only_round_button():
    from formats.swiss import SwissFormat
    fmt = SwissFormat.__new__(SwissFormat)
    result = await fmt.get_active_buttons('active')
    assert result == ['round_button']


@pytest.mark.asyncio
async def test_swiss_format_registration_returns_empty():
    from formats.swiss import SwissFormat
    fmt = SwissFormat.__new__(SwissFormat)
    result = await fmt.get_active_buttons('registration')
    assert result == []


@pytest.mark.asyncio
async def test_swiss_format_checkin_returns_empty():
    from formats.swiss import SwissFormat
    fmt = SwissFormat.__new__(SwissFormat)
    result = await fmt.get_active_buttons('checkin')
    assert result == []


@pytest.mark.asyncio
async def test_swiss_format_active_does_not_include_reset():
    from formats.swiss import SwissFormat
    fmt = SwissFormat.__new__(SwissFormat)
    result = await fmt.get_active_buttons('active')
    assert 'reset' not in result


@pytest.mark.asyncio
async def test_swiss_format_active_does_not_include_seeding():
    from formats.swiss import SwissFormat
    fmt = SwissFormat.__new__(SwissFormat)
    result = await fmt.get_active_buttons('active')
    assert 'seeding' not in result


# ─── BotControlView button routing ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_de_active_state_has_reset_button():
    view, tc = make_view('double elimination')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['autocall', 'refresh_match_calls', 'reset'])

    await view.update_tournament_state('active')

    ids = button_ids(view)
    assert any('reset' in cid for cid in ids), f"Reset button missing from: {ids}"


@pytest.mark.asyncio
async def test_de_active_state_has_no_round_button():
    view, tc = make_view('double elimination')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['autocall', 'refresh_match_calls', 'reset'])

    await view.update_tournament_state('active')

    ids = button_ids(view)
    assert not any('next_round' in cid for cid in ids), f"Round button should not be present: {ids}"


@pytest.mark.asyncio
async def test_swiss_active_state_has_round_button():
    view, tc = make_view('swiss')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['round_button'])

    await view.update_tournament_state('active')

    ids = button_ids(view)
    assert any('next_round' in cid for cid in ids), f"Round button missing from: {ids}"


@pytest.mark.asyncio
async def test_swiss_active_state_has_no_reset_button():
    view, tc = make_view('swiss')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['round_button'])

    await view.update_tournament_state('active')

    ids = button_ids(view)
    assert not any('reset' in cid for cid in ids), f"Reset button should not be present: {ids}"


@pytest.mark.asyncio
async def test_de_registration_state_has_seeding_button():
    view, tc = make_view('double elimination')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['seeding'])

    await view.update_tournament_state('registration')

    ids = button_ids(view)
    assert any('seeding' in cid for cid in ids), f"Seeding button missing from: {ids}"


@pytest.mark.asyncio
async def test_swiss_registration_state_has_no_seeding_button():
    view, tc = make_view('swiss')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=[])

    await view.update_tournament_state('registration')

    ids = button_ids(view)
    assert not any('seeding' in cid for cid in ids), f"Seeding button should not be present: {ids}"


@pytest.mark.asyncio
async def test_round_button_enabled_when_added():
    """When round_button is in get_active_buttons, it must be enabled (not disabled)."""
    view, tc = make_view('swiss')
    tc.tm.format = AsyncMock()
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['round_button'])

    await view.update_tournament_state('active')

    round_btn = next(
        (item for item in view.children if 'next_round' in item.custom_id), None
    )
    assert round_btn is not None, "Round button not found in view"
    assert not round_btn.disabled, "Round button should be enabled when added"


@pytest.mark.asyncio
async def test_active_state_always_has_dq_buttons():
    """Disqualify and un-disqualify buttons are always present when active, regardless of format."""
    for fmt_buttons in (['round_button'], ['reset', 'autocall', 'refresh_match_calls']):
        view, tc = make_view()
        tc.tm.format = AsyncMock()
        tc.tm.format.get_active_buttons = AsyncMock(return_value=fmt_buttons)

        await view.update_tournament_state('active')

        ids = button_ids(view)
        assert any('disqualify_player' in cid and 'remove' not in cid for cid in ids), \
            f"DQ button missing for format buttons {fmt_buttons}: {ids}"
        assert any('remove_disqualify' in cid for cid in ids), \
            f"Un-DQ button missing for format buttons {fmt_buttons}: {ids}"


@pytest.mark.asyncio
async def test_no_format_does_not_crash():
    """If format is None (early init), update_tournament_state should not raise."""
    view, tc = make_view()
    tc.tm.format = None

    # Should complete without error even with no format set
    await view.update_tournament_state('active')


@pytest.mark.asyncio
async def test_custom_format_can_inject_any_buttons():
    """
    A hypothetical new format returning a custom button set works without
    any changes to BotControlView — it just won't add unrecognised keys.
    """
    view, tc = make_view()
    tc.tm.format = AsyncMock()
    # Returns known buttons plus an unknown one — unknown should be silently ignored
    tc.tm.format.get_active_buttons = AsyncMock(return_value=['reset', 'unknown_future_button'])

    await view.update_tournament_state('active')

    ids = button_ids(view)
    assert any('reset' in cid for cid in ids), "Known button 'reset' should still be added"
    # No crash from the unknown key