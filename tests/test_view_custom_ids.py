"""
tests/test_view_custom_ids.py

Tests that persistent Discord view custom_ids are unique per tournament
and do not collide between tournaments with the same name, or between
Swiss join/leave and DE register/unregister buttons.

This guards against the bug where two tournaments named "Weekly #5"
could have their buttons route interactions to the wrong tournament.
"""

import pytest
from unittest.mock import MagicMock


def make_tournament(name='Weekly', tid='aaaaaaaaaaaaaaaaaaaaaaaa'):
    return {
        '_id': tid,
        'name': name,
        'format': 'double elimination',
        'registration_open': False,
        'config': {'approved_registration': False},
        'state': 'registration',
        'stagelist': [],
        'organizers': [],
    }


def make_swiss_tournament(name='Weekly', tid='bbbbbbbbbbbbbbbbbbbbbbbb'):
    return {
        '_id': tid,
        'name': name,
        'format': 'swiss',
        'registration_open': False,
        'config': {'approved_registration': False},
        'state': 'registration',
        'stagelist': [],
        'organizers': [],
    }


def make_tm(tournament):
    tm = MagicMock()
    tm.tournament = tournament
    tm.is_swiss = tournament['format'] == 'swiss'
    return tm


# ─── RegisterControlView ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_control_uses_tid_not_name():
    from ui.register_control import RegisterControlView

    t = make_tournament(name='Weekly', tid='aaaaaaaaaaaaaaaaaaaaaaaa')
    view = RegisterControlView(make_tm(t))

    ids = [item.custom_id for item in view.children]
    for cid in ids:
        assert 'aaaaaaaaaaaaaaaaaaaaaaaa' in cid, \
            f"custom_id should contain tournament _id, got: {cid}"
        assert 'Weekly' not in cid, \
            f"custom_id must not use tournament name (collision risk), got: {cid}"


@pytest.mark.asyncio
async def test_two_tournaments_same_name_have_different_register_custom_ids():
    from ui.register_control import RegisterControlView

    t1 = make_tournament(name='Weekly', tid='aaaa')
    t2 = make_tournament(name='Weekly', tid='bbbb')

    view1 = RegisterControlView(make_tm(t1))
    view2 = RegisterControlView(make_tm(t2))

    ids1 = {item.custom_id for item in view1.children}
    ids2 = {item.custom_id for item in view2.children}

    assert ids1.isdisjoint(ids2), \
        f"Two tournaments with the same name must not share custom_ids.\n{ids1}\n{ids2}"


# ─── SwissActiveRegisterView ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_view_uses_tid_not_name():
    from ui.swiss_register import SwissActiveRegisterView

    t = make_swiss_tournament(name='Weekly', tid='cccccccccccccccccccccccc')
    view = SwissActiveRegisterView(make_tm(t))

    ids = [item.custom_id for item in view.children]
    for cid in ids:
        assert 'cccccccccccccccccccccccc' in cid, \
            f"custom_id should contain tournament _id, got: {cid}"
        assert 'Weekly' not in cid, \
            f"custom_id must not use tournament name (collision risk), got: {cid}"


@pytest.mark.asyncio
async def test_swiss_and_de_same_name_have_different_custom_ids():
    from ui.register_control import RegisterControlView
    from ui.swiss_register import SwissActiveRegisterView

    de = make_tournament(name='Weekly', tid='dddd')
    sw = make_swiss_tournament(name='Weekly', tid='eeee')

    de_view = RegisterControlView(make_tm(de))
    sw_view = SwissActiveRegisterView(make_tm(sw))

    de_ids = {item.custom_id for item in de_view.children}
    sw_ids = {item.custom_id for item in sw_view.children}

    assert de_ids.isdisjoint(sw_ids), \
        f"DE and Swiss views with the same name must not share custom_ids.\n{de_ids}\n{sw_ids}"


@pytest.mark.asyncio
async def test_swiss_join_and_leave_have_distinct_ids():
    from ui.swiss_register import SwissActiveRegisterView

    t = make_swiss_tournament(tid='ffff')
    view = SwissActiveRegisterView(make_tm(t))
    ids = [item.custom_id for item in view.children]
    assert len(ids) == len(set(ids)), "Join and Leave buttons must have distinct custom_ids"


@pytest.mark.asyncio
async def test_register_and_unregister_have_distinct_ids():
    from ui.register_control import RegisterControlView

    t = make_tournament(tid='gggg')
    view = RegisterControlView(make_tm(t))
    ids = [item.custom_id for item in view.children]
    assert len(ids) == len(set(ids)), "Register and Unregister buttons must have distinct custom_ids"