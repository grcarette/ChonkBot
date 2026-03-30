# Fix: Float Sync and Seed Actions Reading Empty Phase Entrants

## Problem

`sync_floated_players()` reads entrants from `phases[0].entrants`, but registration writes to top-level `tournament.entrants`. The phase entrants dict is empty, so the float sync finds 0 players and skips.

The same issue exists in `randomize_seeds` and `seed_by_rank` actions in `web_server.py`.

## Principle Reminder

- **Top-level `entrants`** = who registered (event-level). Used for seeding, floating, display.
- **Phase-level `entrants`** = `{discord_id: challonge_id}` mapping (gameplay). Used for match calling.

Anything that asks "who is in this event?" reads top-level. Anything that asks "what's their challonge ID?" reads phase-level.

---

## Change 1: `tournaments/event_manager.py` — `sync_floated_players()`

**Find:**
```python
            swiss_phase_0  = self.event.get('phases', [{}])[0] if self.event.get('phases') else {}
            swiss_entrants = swiss_phase_0.get('entrants') or {}
            pro_entrants   = pro_phase.get('entrants') or {}
            all_ids        = set(str(k) for k in swiss_entrants) | set(str(k) for k in pro_entrants)
```

**Replace with:**
```python
            # Top-level entrants = who's registered for the event
            event_entrants = self.event.get('entrants', {})
            # Pro phase entrants = who's already floated (has challonge mapping)
            pro_entrants   = pro_phase.get('entrants') or {}
            all_ids        = set(str(k) for k in event_entrants) | set(str(k) for k in pro_entrants)
```

Also update the debug log line right after:
```python
            print(f'[FLOAT] event_entrants count={len(event_entrants)}')
            print(f'[FLOAT] pro_entrants={list(pro_entrants.keys())[:5]}... ({len(pro_entrants)} total)')
            print(f'[FLOAT] all_ids count={len(all_ids)}')
```

---

## Change 2: `web/web_server.py` — `randomize_seeds` action

**Find:**
```python
                _t_phases = tournament.get('phases', [])
                _t_phase0 = _t_phases[0] if _t_phases else {}
                sf_pro = _t_phases[1].get('entrants') or {} if (tournament.get('format') == 'swiss filter' and len(_t_phases) > 1) else {}
                entrant_ids  = list({**_t_phase0.get('entrants', {}), **sf_pro}.keys())
```

**Replace with:**
```python
                # Read from top-level entrants (who's registered)
                entrant_ids  = list(tournament.get('entrants', {}).keys())
```

---

## Change 3: `web/web_server.py` — `seed_by_rank` action

**Find:**
```python
                _t_phases = tournament.get('phases', [])
                _t_phase0 = _t_phases[0] if _t_phases else {}
                sf_pro = _t_phases[1].get('entrants') or {} if (tournament.get('format') == 'swiss filter' and len(_t_phases) > 1) else {}
                entrant_ids  = set(int(did) for did in {**_t_phase0.get('entrants', {}), **sf_pro}.keys())
```

**Replace with:**
```python
                # Read from top-level entrants (who's registered)
                entrant_ids  = set(int(did) for did in tournament.get('entrants', {}).keys())
```

---

## Summary

| File | Location | What changed |
|------|----------|-------------|
| `event_manager.py` | `sync_floated_players()` | Read `self.event['entrants']` instead of `phases[0].entrants` |
| `web_server.py` | `randomize_seeds` action | Read `tournament['entrants']` instead of phase entrants |
| `web_server.py` | `seed_by_rank` action | Read `tournament['entrants']` instead of phase entrants |
