// ── bracket.js ────────────────────────────────────────────────────────────────
// Bracket view: renderBracket, match cards, match drawer.

let bracketData = null;
let _bracketRapidPollTimer = null;

async function loadBracket() {
    try {
        const data = await api('GET', `/api/tournament/${TOURNAMENT_ID}/bracket`);
        bracketData = data;
        if (document.getElementById('section-bracket').classList.contains('active'))
            renderBracket(data);
    } catch (err) {
        if (err.message?.includes('only available for DE/SE')) return;
        document.getElementById('bracket-wrap').innerHTML =
            `<div class="bracket-unavailable"><p>${escapeHtml(err.message)}</p></div>`;
    }
}

function renderBracket(data) {
    const wrap = document.getElementById('bracket-wrap');
    if (!data || !data.matches || !data.matches.length) {
        wrap.innerHTML = `<div class="bracket-unavailable">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
            <p>No matches yet. The bracket will appear once the tournament starts.</p>
        </div>`;
        return;
    }
    const isDE = data.format === 'double elimination';
    wrap.innerHTML = '';
    if (isDE) {
        const wEl = document.createElement('div'); wEl.className = 'bracket-half';
        const lEl = document.createElement('div'); lEl.className = 'bracket-half';
        renderHalf(wEl, data.matches.filter(m => m.bracket === 'Winners'), 'Winners Bracket', false);
        renderHalf(lEl, data.matches.filter(m => m.bracket === 'Losers'),  'Losers Bracket',  true);
        wrap.appendChild(wEl);
        wrap.appendChild(lEl);
    } else {
        const el = document.createElement('div'); el.className = 'bracket-half';
        renderHalf(el, data.matches, '', false);
        wrap.appendChild(el);
    }
}

function renderHalf(container, matches, title, isLosers) {
    if (!matches.length) return;
    if (title) {
        const t = document.createElement('div');
        t.className = 'bracket-half-title';
        t.textContent = title;
        container.appendChild(t);
    }

    const roundMap = {};
    for (const m of matches) {
        if (!roundMap[m.round]) roundMap[m.round] = [];
        roundMap[m.round].push(m);
    }
    const rounds = Object.keys(roundMap).map(Number).sort((a, b) =>
        isLosers ? Math.abs(a) - Math.abs(b) : a - b
    );

    const CARD_H = 80, CARD_W = 180, COL_GAP = 48, LABEL_H = 28;
    const posMap = {};

    roundMap[rounds[0]].forEach((m, i) => {
        const y = LABEL_H + i * (CARD_H + 16);
        posMap[m.match_id] = { x: 0, y, centerY: y + CARD_H / 2 };
    });

    for (let ri = 1; ri < rounds.length; ri++) {
        const colX = ri * (CARD_W + COL_GAP);
        for (const m of roundMap[rounds[ri]]) {
            let centerY;
            if (m.prereq_ids && m.prereq_ids.length >= 2) {
                const p1 = posMap[m.prereq_ids[0]], p2 = posMap[m.prereq_ids[1]];
                centerY = p1 && p2
                    ? (p1.centerY + p2.centerY) / 2
                    : p1 ? p1.centerY
                    : p2 ? p2.centerY
                    : LABEL_H + CARD_H / 2 + roundMap[rounds[ri]].indexOf(m) * (CARD_H + 16);
            } else if (m.prereq_ids && m.prereq_ids.length === 1) {
                const p1 = posMap[m.prereq_ids[0]];
                centerY = p1 ? p1.centerY : LABEL_H + CARD_H / 2;
            } else {
                centerY = LABEL_H + CARD_H / 2 + roundMap[rounds[ri]].indexOf(m) * (CARD_H + 16);
            }
            posMap[m.match_id] = { x: colX, y: centerY - CARD_H / 2, centerY };
        }
    }

    const allPos = Object.values(posMap);
    const totalW = rounds.length * (CARD_W + COL_GAP) - COL_GAP;
    const totalH = Math.max(...allPos.map(p => p.y + CARD_H)) + 16;

    const wrapper = document.createElement('div');
    wrapper.style.cssText = `position:relative;width:${totalW}px;height:${totalH}px;`;

    rounds.forEach((round, ri) => {
        const lbl = document.createElement('div');
        lbl.className = 'round-label';
        lbl.textContent = isLosers ? `L Round ${Math.abs(round)}` : `Round ${Math.abs(round)}`;
        lbl.style.cssText = `position:absolute;top:0;left:${ri*(CARD_W+COL_GAP)}px;width:${CARD_W}px;text-align:center;`;
        wrapper.appendChild(lbl);
    });

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', totalW);
    svg.setAttribute('height', totalH);
    svg.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;overflow:visible;';
    wrapper.appendChild(svg);

    for (const m of matches) {
        const pos = posMap[m.match_id];
        if (!pos) continue;
        const card = buildMatchCard(m);
        card.style.cssText = `position:absolute;left:${pos.x}px;top:${pos.y}px;width:${CARD_W}px;margin:0;`;
        wrapper.appendChild(card);
    }

    container.appendChild(wrapper);

    for (const m of matches) {
        if (!m.prereq_ids || !m.prereq_ids.length) continue;
        const dest = posMap[m.match_id];
        if (!dest) continue;
        for (let i = 0; i < m.prereq_ids.length; i++) {
            const src = posMap[m.prereq_ids[i]];
            if (!src) continue;
            const offsetY = m.prereq_ids.length === 2 ? (i === 0 ? -CARD_H * 0.2 : CARD_H * 0.2) : 0;
            const midX    = src.x + CARD_W + (dest.x - src.x - CARD_W) / 2;
            const path    = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d',
                `M ${src.x+CARD_W} ${src.centerY} C ${midX} ${src.centerY}, ${midX} ${dest.centerY+offsetY}, ${dest.x} ${dest.centerY+offsetY}`);
            path.setAttribute('stroke', 'rgba(255,255,255,0.1)');
            path.setAttribute('stroke-width', '1.5');
            path.setAttribute('fill', 'none');
            svg.appendChild(path);
        }
    }
}

// ── Match card ────────────────────────────────────────────────────────────────

function matchCardStateClass(m) {
    if (m.state === 'complete')   return 'state-complete';
    if (m.state === 'pending')    return 'state-pending';
    if (m.lobby_state === 'held') return 'state-stuck';
    return 'state-open';
}

function lobbyTagClass(m) {
    if (m.state === 'complete')       return 'lobby-tag-complete';
    if (m.hold_when_ready)            return 'lobby-tag-hold';
    if (!m.has_lobby)                 return 'lobby-tag-pending';
    return `lobby-tag-${m.lobby_state || 'pending'}`;
}

function lobbyTagLabel(m) {
    if (m.state === 'complete') return 'Done';
    if (m.hold_when_ready)      return 'Hold ★';
    if (!m.has_lobby)           return 'Waiting';
    return (m.lobby_state || 'pending').replace(/_/g, ' ');
}

function _playerAvatar(name, avatarUrl, extraClass) {
    if (avatarUrl) {
        return `<img src="${escapeHtml(avatarUrl)}"
            class="match-player-avatar ${extraClass}"
            alt=""
            onerror="this.style.display='none'">`;
    }
    const initial = name ? escapeHtml(name[0].toUpperCase()) : '?';
    return `<div class="match-player-avatar-placeholder ${extraClass}">${initial}</div>`;
}

function buildMatchCard(m) {
    const card  = document.createElement('div');
    card.className = `match-card ${matchCardStateClass(m)}`;
    const p1Win = m.state === 'complete' && m.winner_discord_id === m.p1_discord_id;
    const p2Win = m.state === 'complete' && m.winner_discord_id === m.p2_discord_id;
    const p1Cls = m.state === 'complete' ? (p1Win ? 'winner' : 'loser') : '';
    const p2Cls = m.state === 'complete' ? (p2Win ? 'winner' : 'loser') : '';

    const p1Avatar = m.p1_name
        ? _playerAvatar(m.p1_name, m.p1_avatar_url, p1Cls)
        : '';
    const p2Avatar = m.p2_name
        ? _playerAvatar(m.p2_name, m.p2_avatar_url, p2Cls)
        : '';

    card.innerHTML = `
        <div class="match-player ${p1Cls}">
            ${p1Avatar}
            ${m.p1_name
                ? `<span class="match-player-name">${escapeHtml(m.p1_name)}</span>`
                : '<span class="match-player-tbd">TBD</span>'}
        </div>
        <div class="match-player ${p2Cls}">
            ${p2Avatar}
            ${m.p2_name
                ? `<span class="match-player-name">${escapeHtml(m.p2_name)}</span>`
                : '<span class="match-player-tbd">TBD</span>'}
        </div>
        <div class="match-card-footer">
            <span class="match-lobby-tag ${lobbyTagClass(m)}">${lobbyTagLabel(m)}</span>
            <span class="match-card-id">#${m.match_id}</span>
        </div>`;
    card.addEventListener('click', () => openDrawer(m));
    return card;
}

// ── Match drawer ──────────────────────────────────────────────────────────────

function openDrawer(m) {
    populateDrawer(m);
    document.getElementById('match-drawer').hidden    = false;
    document.getElementById('drawer-backdrop').hidden = false;
    document.body.style.overflow = 'hidden';
}

function closeDrawer() {
    document.getElementById('match-drawer').hidden    = true;
    document.getElementById('drawer-backdrop').hidden = true;
    document.body.style.overflow = '';
}

function _hasFinishedChild(matchId, allMatches) {
    // Returns true if any match that lists matchId as a prereq has a complete Challonge state
    // and a finished/closed lobby state
    return allMatches.some(m =>
        m.prereq_ids && m.prereq_ids.includes(matchId) &&
        (m.state === 'complete' || m.lobby_state === 'finished' || m.lobby_state === 'closed')
    );
}

// Store the match currently shown in the drawer
let _drawerMatch = null;

function populateDrawer(m) {
    _drawerMatch = m;  // store for button handlers to read directly

    const allMatches = bracketData?.matches || [];
    const roundAbs   = Math.abs(m.round);
    const bl         = m.bracket === 'Winners' ? 'Winners'
                     : m.bracket === 'Losers'  ? 'Losers' : '';
    document.getElementById('drawer-title').textContent =
        bl ? `${bl} Round ${roundAbs}` : `Round ${roundAbs}`;
    document.getElementById('drawer-sub').textContent =
        `Match #${m.match_id} · ${{ open: 'In Progress', pending: 'Pending', complete: 'Complete' }[m.state] || m.state}`;

    const p1Win      = m.state === 'complete' && m.winner_discord_id === m.p1_discord_id;
    const p2Win      = m.state === 'complete' && m.winner_discord_id === m.p2_discord_id;
    const lobbyLabel = m.lobby_state
        ? m.lobby_state.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '—';

    const p1i = m.p1_discord_id ?? 0;
    const p2i = m.p2_discord_id ?? 0;

    let actionsHtml = '';

    if (m.state === 'pending' && !m.has_lobby) {
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <p style="font-size:12px;color:var(--text-muted);margin-bottom:10px">
                Waiting for prerequisite matches.
            </p>
            <div class="drawer-action-row">
                <button class="btn ${m.hold_when_ready ? 'btn-toggle-on' : 'btn-secondary'} btn-sm"
                    id="drawer-btn-hold-when-ready">
                    ${m.hold_when_ready ? '★ Hold When Ready' : '☆ Hold When Ready'}
                </button>
            </div>
        </div>`;

    } else if (m.state === 'open' && !m.has_lobby) {
        const inFlight = _matchActionInFlight.has(m.match_id);
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <div class="drawer-action-list">
                <div class="drawer-action-row">
                    <button class="btn btn-success btn-sm" id="drawer-btn-call" ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? 'Calling...' : 'Call Match'}
                    </button>
                    <button class="btn btn-secondary btn-sm" id="drawer-btn-hold" ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? '...' : 'Hold Match'}
                    </button>
                </div>
                ${inFlight ? `<p style="font-size:12px;color:var(--text-muted);margin-top:8px">Creating lobby channel...</p>` : ''}
            </div>
        </div>`;

    } else if (m.state === 'open' && m.has_lobby && m.lobby_state === 'held') {
        const inFlight = _matchActionInFlight.has(m.match_id);
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <div class="drawer-action-list">
                <div class="drawer-action-row">
                    <button class="btn btn-success btn-sm" id="drawer-btn-start-held" ${inFlight ? 'disabled' : ''}>
                        ${inFlight ? 'Starting...' : 'Start Match'}
                    </button>
                    <button class="btn btn-secondary btn-sm" id="drawer-btn-force-advance" ${inFlight ? 'disabled' : ''}>
                        Force Advance
                    </button>
                </div>
                ${p1i ? `<div class="drawer-action-row">
                    <button class="btn btn-danger btn-sm" id="drawer-btn-dq1">DQ ${escapeHtml(m.p1_name || 'P1')}</button>
                    <button class="btn btn-danger btn-sm" id="drawer-btn-dq2">DQ ${escapeHtml(m.p2_name || 'P2')}</button>
                </div>` : ''}
            </div>
        </div>`;

    } else if (m.state === 'open' && m.has_lobby) {
        const inFlight = _matchActionInFlight.has(m.match_id);
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <div class="drawer-action-list">
                <div class="drawer-action-row">
                    <button class="btn btn-secondary btn-sm" id="drawer-btn-force-advance" ${inFlight ? 'disabled' : ''}>
                        Force Advance
                    </button>
                </div>
                ${p1i ? `<div class="drawer-action-row">
                    <button class="btn btn-danger btn-sm" id="drawer-btn-dq1">DQ ${escapeHtml(m.p1_name || 'P1')}</button>
                    <button class="btn btn-danger btn-sm" id="drawer-btn-dq2">DQ ${escapeHtml(m.p2_name || 'P2')}</button>
                </div>` : ''}
            </div>
        </div>`;

    } else if (m.state === 'complete') {
        const canReset = !_hasFinishedChild(m.match_id, allMatches);
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <div class="drawer-action-row">
                <button class="btn btn-secondary btn-sm" id="drawer-btn-reset-match">Reset Match</button>
                <button class="btn btn-warning btn-sm" id="drawer-btn-reset-lobby" ${canReset ? '' : 'disabled title="A dependent match has already finished"'}>
                    Reset Lobby
                </button>
            </div>
        </div>`;

    } else {
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <p style="font-size:12px;color:var(--text-muted)">No actions available.</p>
        </div>`;
    }

    document.getElementById('drawer-body').innerHTML = `
        <div><div class="drawer-section-title">Players</div>
            <div class="drawer-players">
                <div class="drawer-player-card ${p1Win ? 'is-winner' : m.state === 'complete' ? 'is-loser' : ''} ${!m.p1_name ? 'is-tbd' : ''}">
                    <span>${escapeHtml(m.p1_name || 'TBD')}</span>
                    ${p1Win ? '<span class="drawer-winner-tag">Winner</span>' : ''}
                </div>
                <div class="drawer-player-card ${p2Win ? 'is-winner' : m.state === 'complete' ? 'is-loser' : ''} ${!m.p2_name ? 'is-tbd' : ''}">
                    <span>${escapeHtml(m.p2_name || 'TBD')}</span>
                    ${p2Win ? '<span class="drawer-winner-tag">Winner</span>' : ''}
                </div>
            </div>
        </div>
        <div class="drawer-info-grid">
            <div class="drawer-info-cell">
                <div class="drawer-info-label">Challonge State</div>
                <div class="drawer-info-value">${{ open: 'In Progress', pending: 'Pending', complete: 'Complete' }[m.state] || m.state}</div>
            </div>
            <div class="drawer-info-cell">
                <div class="drawer-info-label">Lobby State</div>
                <div class="drawer-info-value">${lobbyLabel}</div>
            </div>
            ${m.picked_stage ? `
            <div class="drawer-info-cell" style="grid-column:1/-1">
                <div class="drawer-info-label">Stage</div>
                <div class="drawer-info-value">${escapeHtml(m.picked_stage)}</div>
            </div>` : ''}
        </div>
        ${actionsHtml}`;

    // Wire up buttons via addEventListener — no inline onclick, no JSON in attributes
    const $ = id => document.getElementById(id);

    $('drawer-btn-call')?.addEventListener('click', function() {
        drawerCallMatch(m.match_id, this);
    });
    $('drawer-btn-hold')?.addEventListener('click', function() {
        drawerHoldMatch(m.match_id, this);
    });
    $('drawer-btn-start-held')?.addEventListener('click', function() {
        drawerStartHeld(m.match_id, this);
    });
    $('drawer-btn-force-advance')?.addEventListener('click', () => {
        const playerNames = [m.p1_name || 'TBD', m.p2_name || 'TBD'];
        const playerIds   = [m.p1_discord_id ?? 0, m.p2_discord_id ?? 0];
        matchAction_forceAdvance(m.match_id, playerNames, playerIds, null);
    });
    $('drawer-btn-dq1')?.addEventListener('click', () => drawerDQ(p1i, m.p1_name || ''));
    $('drawer-btn-dq2')?.addEventListener('click', () => drawerDQ(p2i, m.p2_name || ''));
    $('drawer-btn-reset-match')?.addEventListener('click', () => drawerResetMatch(m.match_id));
    $('drawer-btn-reset-lobby')?.addEventListener('click', () => drawerResetLobby(m.match_id));
    $('drawer-btn-hold-when-ready')?.addEventListener('click', async () => {
        try {
            const res = await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
                action:   'toggle_hold_when_ready',
                match_id: m.match_id,
            });
            // Update the local bracketData so the card re-renders correctly
            // without a full bracket reload
            const match = bracketData?.matches?.find(bm => bm.match_id === m.match_id);
            if (match) match.hold_when_ready = res.flagged;
            m.hold_when_ready = res.flagged;
            // Re-render the card and repopulate the drawer to reflect new state
            renderBracket(bracketData);
            populateDrawer(m);
            showToast(res.flagged ? 'Will hold when ready' : 'Hold removed', 'success');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });
}

// ── Drawer action handlers ────────────────────────────────────────────────────

async function drawerCallMatch(matchId, btn) {
    _disableMatchRow(matchId);
    btn.textContent = 'Calling...';
    btn.disabled = true;
    const row = btn.closest('.drawer-action-row');
    if (row) row.querySelectorAll('button').forEach(b => b.disabled = true);
    document.getElementById('drawer-sub').textContent = 'Calling match...';
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
            action: 'call_match', match_id: matchId
        });
    } catch (err) {
        showToast(err.message, 'error');
    }
    _matchActionInFlight.delete(matchId);
    await Promise.all([loadTournament({ force: true }), loadBracket()]);
    // Re-populate drawer with updated match data
    const updated = bracketData?.matches?.find(m => m.match_id === matchId);
    if (updated) populateDrawer(updated);
}

async function drawerHoldMatch(matchId, btn) {
    _disableMatchRow(matchId);
    btn.textContent = 'Holding...';
    btn.disabled = true;
    const row = btn.closest('.drawer-action-row');
    if (row) row.querySelectorAll('button').forEach(b => b.disabled = true);
    document.getElementById('drawer-sub').textContent = 'Creating held lobby...';

    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
            action: 'hold_match', match_id: matchId
        });
    } catch (err) {
        showToast(err.message, 'error');
        _matchActionInFlight.delete(matchId);
        return;
    }

    document.getElementById('drawer-sub').textContent = 'Waiting for lobby to be held...';
    startBracketRapidPoll(20000, 1000);

    const MAX_POLLS = 20;
    let updated = null;
    for (let i = 0; i < MAX_POLLS; i++) {
        await new Promise(r => setTimeout(r, 1000));
        updated = bracketData?.matches?.find(m => m.match_id === matchId);
        if (updated?.lobby_state === 'held') break;
        if (updated?.has_lobby && updated?.lobby_state && updated?.lobby_state !== 'initialize') break;
    }

    _matchActionInFlight.delete(matchId);
    await loadTournament({ force: true });
    if (updated) populateDrawer(updated);
}

async function drawerStartHeld(matchId, btn) {
    _disableMatchRow(matchId);
    btn.textContent = 'Starting...';
    btn.disabled = true;
    const row = btn.closest('.drawer-action-row');
    if (row) row.querySelectorAll('button').forEach(b => b.disabled = true);
    document.getElementById('drawer-sub').textContent = 'Starting match...';
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
            action: 'start_held_match', match_id: matchId
        });
    } catch (err) {
        showToast(err.message, 'error');
    }
    _matchActionInFlight.delete(matchId);
    await Promise.all([loadTournament({ force: true }), loadBracket()]);
    const updated = bracketData?.matches?.find(m => m.match_id === matchId);
    if (updated) populateDrawer(updated);
}
async function drawerDQ(discordId, name) {
    await dqPlayer(discordId, name);
}

async function drawerResetMatch(matchId) {
    if (await showConfirm('Reset Match?',
        'This will reopen the match on Challonge. Any recorded result will be undone.', 'danger')) {
        await doAction('reset_match', { match_id: matchId });
        await loadBracket();
    }
}

async function drawerResetLobby(matchId) {
    closeDrawer();
    if (await showConfirm(
        'Reset Lobby?',
        'This will reopen the match on Challonge, delete the finished lobby, and allow it to be re-called. Any dependent lobbies that have not yet finished will also be removed.',
        'danger'
    )) {
        try {
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
                action:   'reset_lobby',
                match_id: matchId,
            });
            showToast('Lobby reset', 'success');
        } catch (err) {
            showToast(err.message, 'error');
        }
        await loadBracket();
        await loadTournament({ force: true });
    }
}
function startBracketRapidPoll(durationMs = 15000, intervalMs = 1500) {
    // Already polling rapidly
    if (_bracketRapidPollTimer) return;

    const end = Date.now() + durationMs;
    _bracketRapidPollTimer = setInterval(async () => {
        await loadBracket();
        if (Date.now() >= end) {
            clearInterval(_bracketRapidPollTimer);
            _bracketRapidPollTimer = null;
        }
    }, intervalMs);
}