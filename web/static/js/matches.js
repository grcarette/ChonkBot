// ── matches.js ────────────────────────────────────────────────────────────────
// Match panel: renderMatches, per-match action buttons, force-advance modal.

const LOBBY_STATE_TAG = {
    checkin:    ['tag-state',  'Check-in'],
    stage_bans: ['tag-state',  'Stage Bans'],
    reporting:  ['tag-active', 'Reporting'],
    held:       ['tag-stuck',  'Held'],
    initialize: ['tag-done',   'Init'],
    finished:   ['tag-done',   'Finished'],
};

const FINISHED_LOBBY_STATES = new Set(['finished', 'closed']);
const ACTIVE_LOBBY_STATES   = new Set(['initialize', 'checkin', 'stage_bans', 'reporting', 'held']);

// Tracks match IDs where an action is in-flight so buttons stay disabled across re-renders.
const _matchActionInFlight = new Set();

// ── Render ────────────────────────────────────────────────────────────────────

function renderMatches(lobbies, pending, autocall, swiss) {
    const container       = document.getElementById('matches-section-wrap');
    const activeLobbies   = lobbies.filter(l => ACTIVE_LOBBY_STATES.has(l.state));
    const finishedLobbies = lobbies.filter(l => FINISHED_LOBBY_STATES.has(l.state));
    const totalCount      = (pending?.length ?? 0) + lobbies.length;
    document.getElementById('matches-count').textContent = `${totalCount} total`;

    // ── Toolbar ──
    const hasPending    = pending && pending.length > 0;
    const autocallClass = autocall ? 'btn-toggle-on' : 'btn-toggle-off';
    let html = `<div class="matches-toolbar">
        <button class="btn ${autocallClass}" id="btn-autocall">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Auto Call: ${autocall ? 'On' : 'Off'}
        </button>
        <button class="btn btn-primary" id="btn-call-all" ${!hasPending ? 'disabled' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Call All${hasPending ? ` (${pending.length})` : ''}
        </button>
    </div>`;

    // ── Pending ──
    html += `<div class="matches-group-title">Pending${hasPending ? ` · ${pending.length}` : ''}</div>`;
    if (hasPending) {
        html += pending.map(m => {
            const inFlight   = _matchActionInFlight.has(m.match_id);
            const bracketTag = m.bracket
                ? `<span class="tag tag-state" style="font-size:10px;padding:1px 5px">${escapeHtml(m.bracket)}</span>`
                : '';
            const roundLabel = `Rd ${Math.abs(m.round)}`;
            return `<div class="match-row" data-match-id="${m.match_id}">
                <div class="match-row-info">
                    ${bracketTag}
                    <span class="match-row-players">${escapeHtml(m.p1_name)} vs ${escapeHtml(m.p2_name)}</span>
                    <span class="match-row-meta">${roundLabel}</span>
                </div>
                <div class="match-row-actions">
                    <button class="btn btn-success btn-sm"
                        onclick="matchAction_call(${m.match_id}, this)"
                        ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? 'Calling...' : 'Call'}
                    </button>
                    <button class="btn btn-secondary btn-sm"
                        onclick="matchAction_hold(${m.match_id}, this)"
                        ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? '...' : 'Hold'}
                    </button>
                </div>
            </div>`;
        }).join('');
    } else {
        html += `<div class="match-row-empty">No pending matches.</div>`;
    }

    // ── Active ──
    html += `<div class="matches-group-title">Active · ${activeLobbies.length}</div>`;
    if (activeLobbies.length) {
        html += activeLobbies.map(l => {
            const inFlight           = _matchActionInFlight.has(l.match_id);
            const [tagCls, tagLabel] = LOBBY_STATE_TAG[l.state] || ['tag-done', l.state];
            const players            = l.player_names.map(escapeHtml).join(' vs ');
            const namesJson          = JSON.stringify(l.player_names);
            const idsJson            = JSON.stringify(l.player_ids);
            const heldBtn            = l.state === 'held'
                ? `<button class="btn btn-success btn-sm"
                        onclick="matchAction_startHeld(${l.match_id}, this)"
                        ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? 'Starting...' : 'Start Match'}
                   </button>`
                : '';
            const dqButtons = (l.player_ids || []).map((pid, i) =>
                `<button class="btn btn-danger btn-sm match-dq-btn"
                    data-pid="${pid}"
                    data-name="${escapeHtml(l.player_names[i] || String(pid))}"
                    ${inFlight ? 'disabled' : ''}>
                    DQ ${escapeHtml(l.player_names[i] || String(pid))}
                </button>`
            ).join('');
            return `<div class="match-row" data-match-id="${l.match_id}">
                <div class="match-row-info">
                    <span class="match-row-players">${players}</span>
                    <span class="match-row-meta">${escapeHtml(l.lobby_name || String(l.match_id))}</span>
                    <span class="tag ${tagCls}">${tagLabel}</span>
                </div>
                <div class="match-row-actions">
                    ${heldBtn}
                    <button class="btn btn-secondary btn-sm"
                        onclick='matchAction_forceAdvance(${l.match_id},${namesJson},${idsJson},this)'
                        ${inFlight ? 'disabled' : ''}>
                        Force Advance
                    </button>
                    ${dqButtons}
                </div>
            </div>`;
        }).join('');
    } else {
        html += `<div class="match-row-empty">No active lobbies.</div>`;
    }

    // ── Finished ──
    html += `<div class="matches-group-title">Finished · ${finishedLobbies.length}</div>`;
    if (finishedLobbies.length) {
        const canReopen = swiss && swiss.current_round > 0;
        html += finishedLobbies.map(l => {
            const players  = l.player_names.map(escapeHtml).join(' vs ');
            const inFlight = _matchActionInFlight.has(l.match_id);
            const reopenBtn = canReopen
                ? `<button class="btn btn-secondary btn-sm"
                        onclick="matchAction_reopen('${l.match_id}', this)"
                        ${inFlight ? 'disabled' : ''}>
                        Reopen
                   </button>`
                : '';
            return `<div class="match-row match-row-finished" data-match-id="${l.match_id}">
                <div class="match-row-info">
                    <span class="match-row-players">${players}</span>
                    <span class="match-row-meta">${escapeHtml(l.lobby_name || String(l.match_id))}</span>
                </div>
                <div class="match-row-actions">
                    ${reopenBtn}
                    <span class="tag tag-done" style="flex-shrink:0">Done</span>
                </div>
            </div>`;
        }).join('');
    } else {
        html += `<div class="match-row-empty">No finished matches yet.</div>`;
    }

    container.innerHTML = html;

    // Wire DQ buttons
    container.querySelectorAll('.match-dq-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const pid  = parseInt(btn.dataset.pid, 10);
            const name = btn.dataset.name;
            if (await showConfirm(
                'Disqualify Player?',
                `${escapeHtml(name)} will be DQ'd. If they have an active match, their opponent wins.`,
                'danger'
            )) {
                await doAction('dq_player', { discord_id: pid });
            } else {
                btn.disabled = false;
            }
        });
    });

    document.getElementById('btn-autocall').onclick = async () => {
        await doAction('set_autocall', { enabled: !autocall });
    };
    document.getElementById('btn-call-all').onclick = async () => {
        if (!hasPending) return;
        await doAction('call_all_matches');
    };
}

// ── In-flight helpers ─────────────────────────────────────────────────────────

function _disableMatchRow(matchId) {
    _matchActionInFlight.add(matchId);
    const row = document.querySelector(`.match-row[data-match-id="${matchId}"]`);
    if (row) row.querySelectorAll('button').forEach(b => b.disabled = true);
}

async function _matchActionAndRefresh(matchId, action, extra = {}) {
    _disableMatchRow(matchId);
    try {
        _timing.start(`api_post_action[${matchId}:${action}]`);
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, { action, match_id: matchId, ...extra });
        _timing.end(`api_post_action[${matchId}:${action}]`);
    } catch (err) {
        _timing.end(`api_post_action[${matchId}:${action}]`);
        showToast(err.message, 'error');
    }

    _timing.start(`loadTournament_after_action[${matchId}]`);
    const refreshPromises = [loadTournament({ force: true })];
    if (action === 'force_advance' ||
        document.getElementById('section-bracket')?.classList.contains('active')) {
        refreshPromises.push(loadBracket());
    }
    await Promise.all(refreshPromises);
    _timing.end(`loadTournament_after_action[${matchId}]`);

    // Start rapid bracket polling after hold or call actions since
    // Discord channel creation happens in the background
    if (action === 'hold_match' || action === 'call_match') {
        startBracketRapidPoll(20000, 1500);
    }

    _matchActionInFlight.delete(matchId);
}

// ── Button handlers ───────────────────────────────────────────────────────────

async function matchAction_call(matchId, btn) {
    _timing.start(`call_match_total[${matchId}]`);

    _timing.start(`disable_row[${matchId}]`);
    btn.textContent = 'Calling...';
    const row = document.querySelector(`.match-row[data-match-id="${matchId}"]`);
    if (row) {
        row.querySelectorAll('button').forEach(b => b.disabled = true);
        const meta = row.querySelector('.match-row-meta');
        if (meta) meta.textContent = 'Calling...';
    }
    _timing.end(`disable_row[${matchId}]`);

    await _matchActionAndRefresh(matchId, 'call_match');

    _timing.end(`call_match_total[${matchId}]`);
}

async function matchAction_startHeld(matchId, btn) {
    btn.textContent = 'Starting...';
    await _matchActionAndRefresh(matchId, 'start_held_match');
}

async function matchAction_forceAdvance(matchId, playerNames, playerIds, btn) {

    // ── Phase 1: pick target state ────────────────────────────────────────────
    const targetState = await new Promise(resolve => {
        document.getElementById('modal-title').textContent = 'Force Advance';
        document.getElementById('modal-desc').textContent  = 'Use only if the lobby is genuinely stuck.';
        document.getElementById('modal-extra').innerHTML   = `
            <div class="advance-state-list">
                <button class="advance-state-btn" id="fa-stage-bans">Reset to Stage Bans</button>
                <button class="advance-state-btn" id="fa-reporting">Reset to Reporting</button>
                <button class="advance-state-btn warn" id="fa-winner">Declare Winner...</button>
            </div>`;
        document.getElementById('modal-icon').className    = 'modal-icon warning';
        const confirmBtn = document.getElementById('modal-confirm');
        confirmBtn.className     = 'modal-confirm warning';
        confirmBtn.disabled      = true;
        confirmBtn.style.display = 'none';
        document.getElementById('modal-backdrop').hidden = false;

        _confirmResolve = (val) => {
            confirmBtn.style.display = '';
            confirmBtn.disabled = false;
            resolve(val ?? null);
            _confirmResolve = null;
        };

        const pick = (state) => {
            document.getElementById('modal-backdrop').hidden = true;
            document.getElementById('modal-extra').innerHTML = '';
            confirmBtn.style.display = '';
            _confirmResolve = null;
            resolve(state);
        };

        document.getElementById('fa-stage-bans').onclick = () => pick('stage_bans');
        document.getElementById('fa-reporting').onclick  = () => pick('reporting');
        document.getElementById('fa-winner').onclick     = () => pick('winner');
    });

    if (!targetState) return;

    // ── Phase 2: if winner, pick which player ─────────────────────────────────
    if (targetState === 'winner') {
        const winnerId = await new Promise(resolve => {
            const btns = playerIds.map((id, i) =>
                `<button class="player-pick-btn" id="pick-winner-${id}">
                    ${escapeHtml(playerNames[i])}
                </button>`
            ).join('');

            document.getElementById('modal-title').textContent = 'Declare Winner';
            document.getElementById('modal-desc').textContent  = 'Select the player who won.';
            document.getElementById('modal-extra').innerHTML   = `
                <div class="player-select-grid">${btns}</div>
                <div id="force-winner-selected"
                    style="margin-top:12px;font-size:13px;color:var(--text-muted);text-align:center">
                    No winner selected
                </div>`;
            document.getElementById('modal-icon').className = 'modal-icon warning';
            const confirmBtn = document.getElementById('modal-confirm');
            confirmBtn.className     = 'modal-confirm warning';
            confirmBtn.style.display = '';
            confirmBtn.disabled      = true;
            document.getElementById('modal-backdrop').hidden = false;

            _confirmResolve = () => { resolve(null); _confirmResolve = null; };

            let selected = null;

            playerIds.forEach((id, i) => {
                document.getElementById(`pick-winner-${id}`).onclick = () => {
                    selected = id;
                    document.querySelectorAll('.player-pick-btn').forEach(b => b.classList.remove('selected'));
                    document.getElementById(`pick-winner-${id}`).classList.add('selected');
                    document.getElementById('force-winner-selected').textContent = `Winner: ${playerNames[i]}`;
                    document.getElementById('force-winner-selected').style.color = 'var(--green)';
                    confirmBtn.disabled = false;
                };
            });

            confirmBtn.onclick = () => {
                document.getElementById('modal-backdrop').hidden = true;
                document.getElementById('modal-extra').innerHTML = '';
                _confirmResolve = null;
                resolve(selected);
            };
        });

        if (!winnerId) return;
        await _matchActionAndRefresh(matchId, 'force_advance', {
            target_state: 'winner',
            winner_id:    winnerId,
        });

    } else {
        await _matchActionAndRefresh(matchId, 'force_advance', { target_state: targetState });
    }
}

async function matchAction_hold(matchId, btn) {
    btn.textContent = '...';
    await _matchActionAndRefresh(matchId, 'hold_match');
    startBracketRapidPoll(20000, 1500);
}

// ── Legacy aliases (used by bracket drawer and other call sites) ──────────────

async function callMatch(matchId)       { await _matchActionAndRefresh(matchId, 'call_match'); }
async function holdMatch(matchId)       { await _matchActionAndRefresh(matchId, 'hold_match'); }
async function startHeldMatch(matchId)  { await _matchActionAndRefresh(matchId, 'start_held_match'); }
async function callMatchOnce(matchId, btn) { await matchAction_call(matchId, btn); }

async function forceAdvanceMatch(matchId, playerNames, playerIds) {
    await matchAction_forceAdvance(matchId, playerNames, playerIds, null);
}
async function submitForceWinner(matchId, winnerId) {
    closeModal();
    await _matchActionAndRefresh(matchId, 'force_advance', { target_state: 'winner', winner_id: winnerId });
}

async function matchAction_reopen(matchId, btn) {
    btn.textContent = 'Reopening...';
    await _matchActionAndRefresh(matchId, 'reopen_swiss_lobby');
}