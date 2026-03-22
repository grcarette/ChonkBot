// ── event-dashboard.js ────────────────────────────────────────────────────────

// ── Init ──────────────────────────────────────────────────────────────────────

let bracketRefreshInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    initAvatar(USERNAME, AVATAR_URL);

    const SECTION_META = {
        overview:  { title: 'Overview',      sub: 'Tournament status and controls' },
        participants:{ title: 'Participants', sub: 'Manage entrants and disqualifications' },
        matches:   { title: 'Matches',       sub: 'Active lobbies and match state' },
        results:   { title: 'Results',       sub: 'Force match results' },
        config:    { title: 'Configuration', sub: 'Tournament settings' },
        stagelist: { title: 'Stagelist',     sub: 'Manage tournament stages' },
        bracket:   { title: 'Bracket',       sub: 'Match tree and lobby controls' },
    };

    document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`section-${btn.dataset.section}`).classList.add('active');
            const m = SECTION_META[btn.dataset.section] || {};
            document.getElementById('topbar-title').textContent = m.title || '';
            document.getElementById('topbar-sub').textContent   = m.sub   || '';

            if (btn.dataset.section === 'bracket') {
                if (bracketData) renderBracket(bracketData);
                else loadBracket();
                if (!bracketRefreshInterval)
                    bracketRefreshInterval = setInterval(loadBracket, 15000);
            } else {
                if (bracketRefreshInterval) {
                    clearInterval(bracketRefreshInterval);
                    bracketRefreshInterval = null;
                }
                if (btn.dataset.section === 'stagelist') {
                    loadStagelist();
                    loadBrowser();
                }
            }
        });
    });

    // Entrant collapsible
    let entrantOpen = false;
    document.getElementById('entrant-toggle').addEventListener('click', () => {
        entrantOpen = !entrantOpen;
        document.getElementById('entrant-body').classList.toggle('open', entrantOpen);
        document.getElementById('entrant-chevron').classList.toggle('open', entrantOpen);
    });

    // Drawer close
    document.getElementById('drawer-close').addEventListener('click', closeDrawer);
    document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);

    // Escape key
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            if (!document.getElementById('match-drawer').hidden) closeDrawer();
            else if (!document.getElementById('modal-backdrop').hidden) closeModal();
        }
    });

    // Config handlers
    document.getElementById('cfg-save-details').onclick = async () => {
        const name = document.getElementById('cfg-name').value.trim();
        const date = document.getElementById('cfg-date').value.trim();
        if (!name) { showToast('Name cannot be empty', 'error'); return; }
        await doAction('update_config', { name, date });
    };
    document.getElementById('cfg-save-options').onclick = async () => {
        await doAction('update_config', {
            approved_registration: document.getElementById('cfg-approved').checked,
            randomized_stagelist:  document.getElementById('cfg-random-stage').checked,
            display_entrants:      document.getElementById('cfg-display-entrants').checked,
        });
    };

    // Stagelist add by code
    document.getElementById('stagelist-add-btn').addEventListener('click', addStageByCode);
    document.getElementById('stagelist-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') addStageByCode();
    });

    // Browser add selected
    document.getElementById('browser-add-selected').addEventListener('click', addSelectedStages);
    document.getElementById('browser-mode-filter').addEventListener('change', loadBrowser);
    document.getElementById('browser-search').addEventListener('input', renderBrowser);

    // Start polling
    const wrap = document.getElementById('participants-list-wrap');
    if (wrap) {
        wrap._checkedIn = data.checked_in || [];
        wrap._dqs       = data.dqs        || [];
        wrap._showCI    = ['checkin', 'active'].includes(data.state);
    }
    renderPlayers(data.entrants || [], data.checked_in || [], data.dqs || [], data.state, data.format);
    loadTournament();
    setInterval(loadTournament, 5000);
});

// ── Core action ───────────────────────────────────────────────────────────────

async function doAction(action, extra = {}) {
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, { action, ...extra });
        showToast('Done', 'success');
        await loadTournament();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ── Main load ─────────────────────────────────────────────────────────────────

async function loadTournament() {
    try {
        const data = await api('GET', `/api/tournament/${TOURNAMENT_ID}`);
        renderBadge(data.state);
        renderStats(data);
        renderActionArea(data);
        renderEntrantsCollapsible(data.entrants || [], data.checked_in || [], data.dqs || [], data.state);
        renderPlayers(data.entrants || [], data.checked_in || [], data.dqs || [], data.state, data.format);
        renderMatches(data.lobbies || []);
        renderResults(data.lobbies || []);
        populateConfig(data);
    } catch (err) {
        document.getElementById('topbar-sub').textContent = 'Failed to load';
        console.error(err);
    }
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function renderBadge(state) {
    const [cls, label] = BADGE_MAP[state] || ['badge-setup', state];
    document.getElementById('sidebar-badge').innerHTML =
        `<span class="tournament-state-badge ${cls}"><span class="state-dot"></span>${label}</span>`;
}

// ── Overview ──────────────────────────────────────────────────────────────────

function renderStats(t) {
    const label = (BADGE_MAP[t.state] || ['', t.state])[1];
    document.getElementById('stat-state').textContent     = label;
    document.getElementById('stat-format').textContent    = t.format || '—';
    document.getElementById('stat-entrants').textContent  = t.entrant_count ?? '—';
    document.getElementById('stat-checkedin').textContent = t.checkin_count ?? '—';
    document.getElementById('stat-lobbies').textContent   = t.lobby_count ?? '—';
    document.getElementById('topbar-sub').textContent     = t.date ? escapeHtml(t.date) : `${label} · ${t.format}`;
}

function renderEntrantsCollapsible(entrants, checkedIn, dqs, state) {
    document.getElementById('entrant-badge').textContent = entrants.length;
    const body  = document.getElementById('entrant-body');
    if (!entrants.length) { body.innerHTML = '<div class="empty-state">No entrants yet.</div>'; return; }
    const showCI = ['checkin','active'].includes(state);
    body.innerHTML = entrants.map((e, i) => {
        const isDQ = dqs.includes(e.discord_id);
        const isCI = checkedIn.includes(e.discord_id);
        const tag  = isDQ ? `<span class="tag tag-dq">DQ</span>`
                   : (showCI && isCI ? `<span class="tag tag-checkin">&#10003;</span>` : '');
        return `<div style="display:flex;align-items:center;gap:10px;padding:9px 18px;border-bottom:1px solid var(--border)">
            <span style="width:22px;text-align:right;color:var(--text-muted);font-size:11px;font-weight:600">${i+1}</span>
            <span style="flex:1;font-size:13px">${escapeHtml(e.name)}</span>${tag}
        </div>`;
    }).join('');
}

function renderActionArea(t) {
    const area    = document.getElementById('action-area');
    const { state, registration_open, format } = t;
    const isSwiss = format === 'swiss' || format === 'swiss filter';

    if (state === 'initialize' || state === 'setup') {
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Setup</div>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:14px;">Publish the tournament to make channels visible and open registration.</p>
            <div class="action-row">
                <button class="btn btn-success" id="btn-publish">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    Publish Tournament
                </button>
            </div></div>`;
        document.getElementById('btn-publish').onclick = async () => {
            if (await showConfirm('Publish Tournament?', 'Makes all tournament channels visible and opens registration.'))
                await doAction('progress');
        };

    } else if (state === 'registration') {
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Registration</div>
            <div class="action-row">
                <button class="btn ${registration_open ? 'btn-toggle-on' : 'btn-toggle-off'}" id="btn-toggle-reg">
                    ${registration_open ? 'Registration Open' : 'Registration Closed'}
                </button>
                <button class="btn btn-primary" id="btn-start-checkin">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                    Start Check-in
                </button>
            </div></div>`;
        document.getElementById('btn-toggle-reg').onclick = () =>
            doAction(registration_open ? 'close_registration' : 'open_registration');
        document.getElementById('btn-start-checkin').onclick = async () => {
            if (await showConfirm('Start Check-in?', 'Registration will be locked and players asked to check in.'))
                await doAction('progress');
        };

    } else if (state === 'checkin') {
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Check-in</div>
            <div class="action-row">
                <button class="btn ${registration_open ? 'btn-toggle-on' : 'btn-toggle-off'}" id="btn-toggle-reg">
                    ${registration_open ? 'Registration Open' : 'Registration Closed'}
                </button>
                <button class="btn btn-secondary" id="btn-ping">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
                    Ping Check-in
                </button>
                <button class="btn btn-success" id="btn-start-tournament">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    Start Tournament
                </button>
            </div></div>`;
        document.getElementById('btn-toggle-reg').onclick = () =>
            doAction(registration_open ? 'close_registration' : 'open_registration');
        document.getElementById('btn-ping').onclick = () => doAction('ping_checkin');
        document.getElementById('btn-start-tournament').onclick = async () => {
            if (await showConfirm('Start Tournament?', 'Players who have not checked in will be removed. This cannot be undone.'))
                await doAction('progress');
        };

    } else if (state === 'active') {
        const roundHtml = isSwiss && t.swiss ? `<div class="round-info">
            <div class="action-panel-title">Swiss Progress</div>
            <div class="round-stat-row">
                <div class="round-stat"><span class="round-stat-val">${t.swiss.current_round}</span><span class="round-stat-lbl">Current Round</span></div>
                <div class="round-stat"><span class="round-stat-val">${t.swiss.round_limit}</span><span class="round-stat-lbl">Round Limit</span></div>
                <div class="round-stat"><span class="round-stat-val">${t.swiss.active_matches}</span><span class="round-stat-lbl">Active Matches</span></div>
                <div class="round-stat"><span class="round-stat-val">${t.swiss.players_remaining}</span><span class="round-stat-lbl">Players In</span></div>
            </div></div>` : '';
        const nextBtn = isSwiss && t.swiss?.round_ready
            ? `<button class="btn btn-success" id="btn-next-round">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Start Round ${t.swiss.current_round + 1}
               </button>` : '';
        area.innerHTML = `${roundHtml}<div class="action-panel"><div class="action-panel-title">Controls</div>
            <div class="action-row">
                ${nextBtn}
                <button class="btn btn-danger" id="btn-end">End Tournament</button>
            </div></div>`;
        if (isSwiss && t.swiss?.round_ready)
            document.getElementById('btn-next-round').onclick = () => doAction('next_round');
        document.getElementById('btn-end').onclick = async () => {
            if (await showConfirm('End Tournament?', 'All open matches will be closed and the tournament moved to finished state.', 'danger'))
                await doAction('progress');
        };

    } else if (state === 'finished') {
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Wrap Up</div>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:14px;">All matches are complete. Finalizing will post results and remove Discord channels.</p>
            <div class="action-row">
                <button class="btn btn-primary" id="btn-finalize">Finalize Tournament</button>
            </div></div>`;
        document.getElementById('btn-finalize').onclick = async () => {
            if (await showConfirm('Finalize Tournament?', 'Results will be posted and Discord channels removed.', 'danger'))
                await doAction('progress');
        };

    } else {
        area.innerHTML = `<div class="action-panel"><p style="color:var(--text-muted);font-size:13px;">No actions available in this state.</p></div>`;
    }
}

// ── Participants ──────────────────────────────────────────────────────────────

let _participantDragState = null;

function renderPlayers(entrants, checkedIn, dqs, state, format) {
    const wrap      = document.getElementById('participants-list-wrap');
    const isBracket = format === 'single elimination' || format === 'double elimination';
    const showCI    = ['checkin', 'active'].includes(state);

    document.getElementById('players-count').textContent =
        `${entrants.length} entrant${entrants.length !== 1 ? 's' : ''}`;

    if (!entrants.length) {
        wrap.innerHTML = `<div class="empty-state">No entrants yet.</div>`;
        return;
    }

    if (isBracket) {
        renderSeedingList(wrap, entrants, checkedIn, dqs, showCI);
    } else {
        renderParticipantsTable(wrap, entrants, checkedIn, dqs, showCI);
    }
}

// ── Drag-and-drop seeding list (DE/SE only) ───────────────────────────────────

function renderSeedingList(wrap, entrants, checkedIn, dqs, showCI) {
    // entrants already arrive sorted by seed from the server
    wrap._entrants = [...entrants]; // keep a mutable copy for drag ops

    wrap.innerHTML = `<ul id="seeding-list"></ul>
        <div id="seeding-save-status" style="height:24px;text-align:center;font-size:12px;padding:6px 0;color:var(--text-muted)"></div>`;

    _rebuildSeedingList(wrap, checkedIn, dqs, showCI);
}

function _rebuildSeedingList(wrap, checkedIn, dqs, showCI) {
    const list     = document.getElementById('seeding-list');
    const entrants = wrap._entrants;
    list.innerHTML = '';

    entrants.forEach((e, i) => {
        const isDQ = dqs.includes(e.discord_id);
        const isCI = checkedIn.includes(e.discord_id);
        let tag = '';
        if (isDQ)                tag = `<span class="tag tag-dq">DQ</span>`;
        else if (showCI && isCI) tag = `<span class="tag tag-checkin">✓</span>`;

        const nameEsc = escapeHtml(e.name).replace(/'/g, "\\'");
        const dqBtn   = isDQ
            ? `<button class="btn btn-secondary btn-sm" onclick="undqPlayer(${e.discord_id})">Un-DQ</button>`
            : `<button class="btn btn-danger btn-sm" onclick="dqPlayer(${e.discord_id},'${nameEsc}')">DQ</button>`;

        const li = document.createElement('li');
        li.className = 'participant-item';
        li.dataset.index = i;
        li.innerHTML = `
            <span class="participant-drag-handle" title="Drag to reseed">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                    <circle cx="5" cy="4" r="1.5"/><circle cx="11" cy="4" r="1.5"/>
                    <circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/>
                    <circle cx="5" cy="12" r="1.5"/><circle cx="11" cy="12" r="1.5"/>
                </svg>
            </span>
            <span class="participant-seed">${i + 1}</span>
            <span class="participant-name">${escapeHtml(e.name)}</span>
            <span class="participant-tags">${tag}</span>
            <span class="participant-actions">${dqBtn}</span>`;

        li.addEventListener('pointerdown', _onSeedPointerDown);
        list.appendChild(li);
    });

    // Store item height for shift transforms
    requestAnimationFrame(() => {
        const first = list.querySelector('.participant-item');
        if (first) list.style.setProperty('--pi-h', `${first.offsetHeight}px`);
    });
}

function _onSeedPointerDown(e) {
    // Only drag from the handle
    if (!e.target.closest('.participant-drag-handle')) return;
    if (e.button !== 0) return;
    e.preventDefault();

    const item     = e.currentTarget;
    const srcIndex = parseInt(item.dataset.index);
    const rect     = item.getBoundingClientRect();
    const list     = document.getElementById('seeding-list');

    const ghost = item.cloneNode(true);
    ghost.id = 'participant-drag-ghost';
    ghost.style.setProperty('--ghost-w', `${rect.width}px`);
    ghost.style.top  = `${rect.top}px`;
    ghost.style.left = `${rect.left}px`;
    document.body.appendChild(ghost);

    item.classList.add('is-dragging');

    _participantDragState = {
        srcIndex,
        currentIndex: srcIndex,
        offsetX: e.clientX - rect.left,
        offsetY: e.clientY - rect.top,
        ghost,
        item,
        list,
    };

    document.addEventListener('pointermove', _onSeedPointerMove);
    document.addEventListener('pointerup',   _onSeedPointerUp);
}

function _onSeedPointerMove(e) {
    if (!_participantDragState) return;
    const { ghost, offsetX, offsetY, srcIndex, list } = _participantDragState;

    ghost.style.left = `${e.clientX - offsetX}px`;
    ghost.style.top  = `${e.clientY - offsetY}px`;

    const items = [...list.querySelectorAll('.participant-item:not(.is-dragging)')];
    let newIndex = srcIndex;

    for (let i = 0; i < items.length; i++) {
        const r    = items[i].getBoundingClientRect();
        const midY = r.top + r.height / 2;
        const idx  = parseInt(items[i].dataset.index);
        if (e.clientY > midY) {
            newIndex = idx >= srcIndex ? idx : idx + 1;
        }
    }
    newIndex = Math.max(0, Math.min(newIndex, list.querySelectorAll('.participant-item').length - 1));

    if (newIndex !== _participantDragState.currentIndex) {
        _participantDragState.currentIndex = newIndex;
        _applyShifts(list, srcIndex, newIndex);
    }
}

function _applyShifts(list, srcIndex, targetIndex) {
    list.querySelectorAll('.participant-item').forEach(item => {
        const idx = parseInt(item.dataset.index);
        if (idx === srcIndex) return;
        item.classList.remove('shift-up', 'shift-down');
        if (srcIndex < targetIndex && idx > srcIndex && idx <= targetIndex)
            item.classList.add('shift-up');
        else if (srcIndex > targetIndex && idx >= targetIndex && idx < srcIndex)
            item.classList.add('shift-down');
    });
}

async function _onSeedPointerUp() {
    if (!_participantDragState) return;
    document.removeEventListener('pointermove', _onSeedPointerMove);
    document.removeEventListener('pointerup',   _onSeedPointerUp);

    const { srcIndex, currentIndex, ghost, item, list } = _participantDragState;
    _participantDragState = null;

    ghost.remove();
    item.classList.remove('is-dragging');
    list.querySelectorAll('.participant-item').forEach(el =>
        el.classList.remove('shift-up', 'shift-down'));

    if (srcIndex === currentIndex) return;

    const wrap = document.getElementById('participants-list-wrap');
    const moved = wrap._entrants.splice(srcIndex, 1)[0];
    wrap._entrants.splice(currentIndex, 0, moved);

    // Re-render immediately so seeds update visually
    const checkedIn = wrap._checkedIn || [];
    const dqs       = wrap._dqs       || [];
    const showCI    = wrap._showCI    || false;
    _rebuildSeedingList(wrap, checkedIn, dqs, showCI);

    await _syncAllSeeds(wrap._entrants);
}

async function _syncAllSeeds(entrants) {
    const statusEl = document.getElementById('seeding-save-status');
    if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.style.color = 'var(--text-muted)'; }
    try {
        for (let i = 0; i < entrants.length; i++) {
            const e = entrants[i];
            if (e.challonge_id == null) continue;
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/seed`, {
                challonge_id: e.challonge_id,
                seed:         i + 1,
            });
        }
        if (statusEl) { statusEl.textContent = 'Saved ✓'; statusEl.style.color = 'var(--green)'; }
        setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 2500);
    } catch (err) {
        if (statusEl) { statusEl.textContent = `Save failed: ${err.message}`; statusEl.style.color = 'var(--red)'; }
        showToast(`Seeding save failed: ${err.message}`, 'error');
    }
}

// ── Plain table (Swiss / Swiss Filter) ───────────────────────────────────────

function renderParticipantsTable(wrap, entrants, checkedIn, dqs, showCI) {
    wrap.innerHTML = `<table class="data-table">
        <thead><tr><th>#</th><th>Name</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody id="players-tbody"></tbody>
    </table>`;

    const tbody = document.getElementById('players-tbody');
    tbody.innerHTML = entrants.map((e, i) => {
        const isDQ = dqs.includes(e.discord_id);
        const isCI = checkedIn.includes(e.discord_id);
        let statusTag = `<span class="tag tag-done">Registered</span>`;
        if (isDQ)                statusTag = `<span class="tag tag-dq">DQ</span>`;
        else if (showCI && isCI) statusTag = `<span class="tag tag-checkin">Checked In</span>`;
        else if (showCI)         statusTag = `<span class="tag tag-stuck">Not Checked In</span>`;
        const nameEsc = escapeHtml(e.name).replace(/'/g, "\\'");
        const dqBtn   = isDQ
            ? `<button class="btn btn-secondary btn-sm" onclick="undqPlayer(${e.discord_id})">Un-DQ</button>`
            : `<button class="btn btn-danger btn-sm" onclick="dqPlayer(${e.discord_id},'${nameEsc}')">DQ</button>`;
        return `<tr>
            <td style="color:var(--text-muted);font-size:12px">${i + 1}</td>
            <td><strong>${escapeHtml(e.name)}</strong></td>
            <td>${statusTag}</td>
            <td>${dqBtn}</td>
        </tr>`;
    }).join('');
}

function buildSeedCell(e) {
    if (e.challonge_id == null) {
        return `<span style="color:var(--text-muted);font-size:12px">—</span>`;
    }
    const seed = e.seed ?? '';
    return `<div style="display:flex;align-items:center;gap:6px">
        <input
            type="number" min="1" value="${seed}"
            data-challonge="${e.challonge_id}" data-discord="${e.discord_id}"
            class="field-input seed-input"
            style="width:60px;padding:4px 7px;font-size:12px;text-align:center"
            onchange="setSeed(this)"
        >
    </div>`;
}

async function setSeed(input) {
    const newSeed     = parseInt(input.value, 10);
    const challongeId = parseInt(input.dataset.challonge, 10);
    if (!newSeed || newSeed < 1) { input.value = input.dataset.prev || ''; return; }
    input.dataset.prev = input.value;
    input.disabled = true;
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/seed`, {
            challonge_id: challongeId,
            seed:         newSeed,
        });
        showToast('Seed updated', 'success');
    } catch (err) {
        showToast(`Failed: ${err.message}`, 'error');
        input.value = input.dataset.prev || '';
    } finally {
        input.disabled = false;
    }
}

async function dqPlayer(discordId, name) {
    if (await showConfirm('Disqualify Player?',
        `${name} will be DQ'd. If they have an active match, their opponent wins.`, 'danger'))
        await doAction('dq_player', { discord_id: discordId });
}

async function undqPlayer(discordId) {
    await doAction('undq_player', { discord_id: discordId });
}

// ── Matches ───────────────────────────────────────────────────────────────────

const LOBBY_STATE_TAG = {
    checkin:    ['tag-state',  'Check-in'],
    stage_bans: ['tag-state',  'Stage Bans'],
    reporting:  ['tag-active', 'Reporting'],
    held:       ['tag-stuck',  'Held'],
    initialize: ['tag-done',   'Init'],
};

function renderMatches(lobbies) {
    const tbody = document.getElementById('matches-tbody');
    document.getElementById('matches-count').textContent = `${lobbies.length} active`;
    if (!lobbies.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="empty-state">No active lobbies.</td></tr>`;
        return;
    }
    tbody.innerHTML = lobbies.map(l => {
        const [tagCls, tagLabel] = LOBBY_STATE_TAG[l.state] || ['tag-done', l.state];
        const players   = l.player_names.map(escapeHtml).join(' vs ');
        const namesJson = JSON.stringify(l.player_names);
        const idsJson   = JSON.stringify(l.player_ids);
        return `<tr>
            <td style="font-size:12px;color:var(--text-muted)">${escapeHtml(l.lobby_name || String(l.match_id))}</td>
            <td>${players}</td>
            <td><span class="tag ${tagCls}">${tagLabel}</span></td>
            <td><button class="btn btn-secondary btn-sm"
                onclick="openForceAdvance(${l.match_id},${namesJson},${idsJson})">Force Advance</button></td>
        </tr>`;
    }).join('');
}

async function openForceAdvance(matchId, playerNames, playerIds) {
    const nj = JSON.stringify(playerNames), ij = JSON.stringify(playerIds);
    const extra = `<div class="advance-state-list">
        <button class="advance-state-btn" onclick="pickAdvanceState(${matchId},'stage_bans',${nj},${ij})">Reset to Stage Bans</button>
        <button class="advance-state-btn" onclick="pickAdvanceState(${matchId},'reporting',${nj},${ij})">Reset to Reporting</button>
        <button class="advance-state-btn warn" onclick="pickAdvanceState(${matchId},'winner',${nj},${ij})">Declare Winner...</button>
    </div>`;
    await showConfirm('Force Advance Lobby', 'Use only if the lobby is genuinely stuck.', 'warning', extra);
}

async function pickAdvanceState(matchId, targetState, playerNames, playerIds) {
    closeModal();
    if (targetState === 'winner') {
        const btns = playerIds.map((id, i) =>
            `<button class="player-pick-btn" onclick="submitForceWinner(${matchId},${id})">${escapeHtml(playerNames[i])}</button>`
        ).join('');
        await showConfirm('Declare Winner', 'Select the player who won.', 'warning',
            `<div class="player-select-grid">${btns}</div>`);
    } else {
        await doAction('force_advance', { match_id: matchId, target_state: targetState });
    }
}

async function submitForceWinner(matchId, winnerId) {
    closeModal();
    await doAction('force_advance', { match_id: matchId, target_state: 'winner', winner_id: winnerId });
}

// ── Results ───────────────────────────────────────────────────────────────────

function renderResults(lobbies) {
    const wrap = document.getElementById('results-list');
    if (!lobbies.length) {
        wrap.innerHTML = '<div class="empty-state">No active lobbies to force-report.</div>';
        return;
    }
    wrap.innerHTML = lobbies.map(l => {
        const players   = l.player_names.map(escapeHtml).join(' vs ');
        const namesJson = JSON.stringify(l.player_names);
        const idsJson   = JSON.stringify(l.player_ids);
        return `<div class="lobby-result-row">
            <div class="lobby-result-info">
                <div class="lobby-result-name">${escapeHtml(l.lobby_name || String(l.match_id))}</div>
                <div class="lobby-result-players">${players}</div>
            </div>
            <button class="btn btn-warning btn-sm" onclick="openForceResult(${l.match_id},${namesJson},${idsJson})">Force Result</button>
        </div>`;
    }).join('');
}

async function openForceResult(matchId, playerNames, playerIds) {
    const btns = playerIds.map((id, i) =>
        `<button class="player-pick-btn" onclick="submitForceResult(${matchId},${id})">${escapeHtml(playerNames[i])}</button>`
    ).join('');
    await showConfirm('Force Result', 'Select the player who won.', 'warning',
        `<div class="player-select-grid">${btns}</div>`);
}

async function submitForceResult(matchId, winnerId) {
    closeModal();
    await doAction('force_advance', { match_id: matchId, target_state: 'winner', winner_id: winnerId });
}

// ── Config ────────────────────────────────────────────────────────────────────

function populateConfig(t) {
    document.getElementById('cfg-name').value               = t.name  || '';
    document.getElementById('cfg-date').value               = t.date  || '';
    document.getElementById('cfg-approved').checked         = t.config?.approved_registration ?? false;
    document.getElementById('cfg-random-stage').checked     = t.config?.randomized_stagelist  ?? false;
    document.getElementById('cfg-display-entrants').checked = t.config?.display_entrants       ?? false;
}

// ── Bracket ───────────────────────────────────────────────────────────────────

let bracketData = null;

async function loadBracket() {
    try {
        const data = await api('GET', `/api/tournament/${TOURNAMENT_ID}/bracket`);
        bracketData = data;
        if (document.getElementById('section-bracket').classList.contains('active'))
            renderBracket(data);
    } catch (err) {
        document.getElementById('bracket-wrap').innerHTML =
            `<div class="bracket-unavailable"><p>${escapeHtml(err.message)}</p></div>`;
    }
}

function renderBracket(data) {
    const wrap = document.getElementById('bracket-wrap');
    if (!data || !data.matches || !data.matches.length) {
        wrap.innerHTML = `<div class="bracket-unavailable">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
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
        wrap.appendChild(wEl); wrap.appendChild(lEl);
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
        t.className = 'bracket-half-title'; t.textContent = title;
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
                centerY = p1 && p2 ? (p1.centerY + p2.centerY) / 2
                        : p1 ? p1.centerY : p2 ? p2.centerY
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
    svg.setAttribute('width', totalW); svg.setAttribute('height', totalH);
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
            const midX = src.x + CARD_W + (dest.x - src.x - CARD_W) / 2;
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', `M ${src.x+CARD_W} ${src.centerY} C ${midX} ${src.centerY}, ${midX} ${dest.centerY+offsetY}, ${dest.x} ${dest.centerY+offsetY}`);
            path.setAttribute('stroke', 'rgba(255,255,255,0.1)');
            path.setAttribute('stroke-width', '1.5');
            path.setAttribute('fill', 'none');
            svg.appendChild(path);
        }
    }
}

function matchCardStateClass(m) {
    if (m.state === 'complete')         return 'state-complete';
    if (m.state === 'pending')          return 'state-pending';
    if (m.lobby_state === 'held')       return 'state-stuck';
    return 'state-open';
}
function lobbyTagClass(m) {
    if (m.state === 'complete') return 'lobby-tag-complete';
    if (!m.has_lobby)           return 'lobby-tag-pending';
    return `lobby-tag-${m.lobby_state || 'pending'}`;
}
function lobbyTagLabel(m) {
    if (m.state === 'complete') return 'Done';
    if (!m.has_lobby)           return 'Waiting';
    return (m.lobby_state || 'pending').replace(/_/g, ' ');
}

function buildMatchCard(m) {
    const card = document.createElement('div');
    card.className = `match-card ${matchCardStateClass(m)}`;
    const p1Win = m.state === 'complete' && m.winner_discord_id === m.p1_discord_id;
    const p2Win = m.state === 'complete' && m.winner_discord_id === m.p2_discord_id;
    const p1Cls = m.state === 'complete' ? (p1Win ? 'winner' : 'loser') : '';
    const p2Cls = m.state === 'complete' ? (p2Win ? 'winner' : 'loser') : '';
    card.innerHTML = `
        <div class="match-player ${p1Cls}">${m.p1_name ? `<span class="match-player-name">${escapeHtml(m.p1_name)}</span>` : '<span class="match-player-tbd">TBD</span>'}</div>
        <div class="match-player ${p2Cls}">${m.p2_name ? `<span class="match-player-name">${escapeHtml(m.p2_name)}</span>` : '<span class="match-player-tbd">TBD</span>'}</div>
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
    document.getElementById('match-drawer').hidden   = false;
    document.getElementById('drawer-backdrop').hidden = false;
    document.body.style.overflow = 'hidden';
}

function closeDrawer() {
    document.getElementById('match-drawer').hidden   = true;
    document.getElementById('drawer-backdrop').hidden = true;
    document.body.style.overflow = '';
}

function populateDrawer(m) {
    const roundAbs = Math.abs(m.round);
    const bl       = m.bracket === 'Winners' ? 'Winners' : m.bracket === 'Losers' ? 'Losers' : '';
    document.getElementById('drawer-title').textContent = bl ? `${bl} Round ${roundAbs}` : `Round ${roundAbs}`;
    document.getElementById('drawer-sub').textContent   = `Match #${m.match_id} · ${{open:'In Progress',pending:'Pending',complete:'Complete'}[m.state]||m.state}`;

    const p1Win = m.state==='complete' && m.winner_discord_id===m.p1_discord_id;
    const p2Win = m.state==='complete' && m.winner_discord_id===m.p2_discord_id;
    const lobbyLabel = m.lobby_state ? m.lobby_state.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()) : '—';

    let actionsHtml = '';
    if (m.state === 'open' && m.has_lobby) {
        const p1n=JSON.stringify(m.p1_name||'TBD'), p2n=JSON.stringify(m.p2_name||'TBD');
        const p1i=m.p1_discord_id??0, p2i=m.p2_discord_id??0;
        actionsHtml = `<div><div class="drawer-section-title">Actions</div><div class="drawer-action-list">
            <div class="drawer-action-row">
                <button class="btn btn-secondary btn-sm" onclick="drawerForceAdvance(${m.match_id},[${p1n},${p2n}],[${p1i},${p2i}])">Force Advance</button>
                <button class="btn btn-warning btn-sm"   onclick="drawerForceResult(${m.match_id},[${p1n},${p2n}],[${p1i},${p2i}])">Force Result</button>
            </div>
            ${p1i ? `<div class="drawer-action-row">
                <button class="btn btn-danger btn-sm" onclick="drawerDQ(${p1i},'${escapeHtml(m.p1_name||'')}')">DQ ${escapeHtml(m.p1_name||'P1')}</button>
                <button class="btn btn-danger btn-sm" onclick="drawerDQ(${p2i},'${escapeHtml(m.p2_name||'')}')">DQ ${escapeHtml(m.p2_name||'P2')}</button>
            </div>` : ''}
        </div></div>`;
    } else if (m.state === 'complete') {
        actionsHtml = `<div><div class="drawer-section-title">Actions</div>
            <div class="drawer-action-row"><button class="btn btn-secondary btn-sm" onclick="drawerResetMatch(${m.match_id})">Reset Match</button></div></div>`;
    } else if (m.state === 'pending') {
        actionsHtml = `<div><div class="drawer-section-title">Actions</div><p style="font-size:12px;color:var(--text-muted)">Waiting for prerequisite matches.</p></div>`;
    } else {
        actionsHtml = `<div><div class="drawer-section-title">Actions</div><p style="font-size:12px;color:var(--text-muted)">Match is open on Challonge but has no active lobby yet.</p></div>`;
    }

    document.getElementById('drawer-body').innerHTML = `
        <div><div class="drawer-section-title">Players</div><div class="drawer-players">
            <div class="drawer-player-card ${p1Win?'is-winner':m.state==='complete'?'is-loser':''} ${!m.p1_name?'is-tbd':''}">
                <span>${escapeHtml(m.p1_name||'TBD')}</span>${p1Win?'<span class="drawer-winner-tag">Winner</span>':''}
            </div>
            <div class="drawer-player-card ${p2Win?'is-winner':m.state==='complete'?'is-loser':''} ${!m.p2_name?'is-tbd':''}">
                <span>${escapeHtml(m.p2_name||'TBD')}</span>${p2Win?'<span class="drawer-winner-tag">Winner</span>':''}
            </div>
        </div></div>
        <div class="drawer-info-grid">
            <div class="drawer-info-cell"><div class="drawer-info-label">Challonge State</div><div class="drawer-info-value">${{open:'In Progress',pending:'Pending',complete:'Complete'}[m.state]||m.state}</div></div>
            <div class="drawer-info-cell"><div class="drawer-info-label">Lobby State</div><div class="drawer-info-value">${lobbyLabel}</div></div>
            ${m.picked_stage?`<div class="drawer-info-cell" style="grid-column:1/-1"><div class="drawer-info-label">Stage</div><div class="drawer-info-value">${escapeHtml(m.picked_stage)}</div></div>`:''}
        </div>
        ${actionsHtml}`;
}

async function drawerForceAdvance(matchId, playerNames, playerIds) { closeDrawer(); await openForceAdvance(matchId, playerNames, playerIds); }
async function drawerForceResult(matchId, playerNames, playerIds)  { closeDrawer(); await openForceResult(matchId, playerNames, playerIds); }
async function drawerDQ(discordId, name)                           { closeDrawer(); await dqPlayer(discordId, name); }
async function drawerResetMatch(matchId) {
    closeDrawer();
    if (await showConfirm('Reset Match?', 'This will reopen the match on Challonge. Any recorded result will be undone.', 'danger')) {
        await doAction('reset_match', { match_id: matchId });
        await loadBracket();
    }
}

// ── Stagelist ─────────────────────────────────────────────────────────────────

function imgurDirectUrl(imgurUrl) {
    if (!imgurUrl) return '';
    const lastSegment = imgurUrl.split('/').pop();
    const lastHyphen  = lastSegment.lastIndexOf('-');
    const imageId     = lastHyphen !== -1 ? lastSegment.slice(lastHyphen + 1) : lastSegment;
    return imageId ? `https://i.imgur.com/${imageId}.jpg` : '';
}

async function loadStagelist() {
    try {
        const data = await api('GET', `/api/tournament/${TOURNAMENT_ID}/stagelist`);
        renderStagelist(data.stages || []);
        currentStageCodes = new Set((data.stages || []).map(s => s.code));
        renderBrowser();
    } catch (err) {
        document.getElementById('stagelist-grid').innerHTML =
            `<div class="stagelist-empty">Failed to load: ${escapeHtml(err.message)}</div>`;
    }
}

function renderStagelist(stages) {
    const grid  = document.getElementById('stagelist-grid');
    const count = document.getElementById('stagelist-count');
    count.textContent = `${stages.length} stage${stages.length !== 1 ? 's' : ''}`;
    if (!stages.length) {
        grid.innerHTML = `<div class="stagelist-empty">No stages added yet.</div>`;
        return;
    }
    const gridEl = document.createElement('div');
    gridEl.className = 'stage-card-grid';
    for (const s of stages) {
        const thumbUrl    = imgurDirectUrl(s.imgur_url);
        const creatorName = s.creators?.length ? s.creators.map(c => escapeHtml(c.username)).join(', ') : '';
        const modeLabel   = s.mode ? escapeHtml(s.mode) : '';
        const illegalTag  = !s.tournament_legal ? `<span class="stage-illegal-tag">Not Legal</span>` : '';
        const card = document.createElement('div');
        card.className = 'stage-card';
        card.innerHTML = `
            ${thumbUrl ? `<img class="stage-card-thumb" src="${thumbUrl}" alt="${escapeHtml(s.name)}"
                onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">` : ''}
            <div class="stage-card-thumb-placeholder" ${thumbUrl ? 'style="display:none"' : ''}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".4"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            </div>
            <div class="stage-card-body">
                <div class="stage-card-name">${escapeHtml(s.name)}</div>
                <div class="stage-card-meta">
                    <span class="stage-card-code">${escapeHtml(s.code)}</span>
                    ${modeLabel ? `<span>·</span><span>${modeLabel}</span>` : ''}
                </div>
                ${creatorName ? `<div class="stage-card-creator">by ${creatorName}</div>` : ''}
            </div>
            <div class="stage-card-footer">
                <div>${illegalTag}</div>
                <button class="stage-remove-btn" title="Remove" onclick="removeStageFromList('${escapeHtml(s.code)}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            </div>`;
        gridEl.appendChild(card);
    }
    grid.innerHTML = '';
    grid.appendChild(gridEl);
}

async function removeStageFromList(code) {
    try {
        await api('DELETE', `/api/tournament/${TOURNAMENT_ID}/stages/${encodeURIComponent(code)}`);
        showToast('Stage removed', 'success');
        await loadStagelist();
    } catch (err) { showToast(err.message, 'error'); }
}

async function addStageByCode() {
    const raw = document.getElementById('stagelist-input').value.trim();
    if (!raw) return;
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/stages`, { codes: raw });
        showToast('Stage(s) added', 'success');
        document.getElementById('stagelist-input').value = '';
        await loadStagelist();
    } catch (err) { showToast(err.message, 'error'); }
}

// ── Stage browser ─────────────────────────────────────────────────────────────

let browserAllStages  = [];
let browserSelected   = new Set();
let currentStageCodes = new Set();

async function loadBrowser() {
    const mode = document.getElementById('browser-mode-filter').value;
    try {
        const url  = '/api/stages/browse' + (mode ? `?mode=${encodeURIComponent(mode)}` : '');
        const data = await api('GET', url);
        browserAllStages = data.stages || [];
        for (let i = browserAllStages.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [browserAllStages[i], browserAllStages[j]] = [browserAllStages[j], browserAllStages[i]];
        }
        renderBrowser();
    } catch (err) {
        document.getElementById('browser-grid-wrap').innerHTML =
            `<div class="stagelist-empty">Failed to load: ${escapeHtml(err.message)}</div>`;
    }
}

function renderBrowser() {
    const search   = (document.getElementById('browser-search')?.value || '').toLowerCase();
    const filtered = browserAllStages.filter(s =>
        !search || s.name.toLowerCase().includes(search) || s.code.toLowerCase().includes(search)
    );
    const countEl = document.getElementById('browser-count');
    if (countEl) countEl.textContent = `${filtered.length} stage${filtered.length !== 1 ? 's' : ''}`;

    const wrap = document.getElementById('browser-grid-wrap');
    if (!wrap) return;
    if (!filtered.length) { wrap.innerHTML = `<div class="stagelist-empty">No stages found.</div>`; return; }

    const grid = document.createElement('div');
    grid.className = 'browser-grid';
    for (const s of filtered) {
        const alreadyAdded = currentStageCodes.has(s.code);
        const isSelected   = browserSelected.has(s.code);
        const thumbUrl     = imgurDirectUrl(s.imgur_url);
        const creator      = s.creators?.length ? s.creators[0].username : '';
        const card = document.createElement('div');
        card.className = `browser-card${isSelected?' selected':''}${alreadyAdded?' already-added':''}`;
        card.innerHTML = `
            ${thumbUrl
                ? `<img class="browser-card-thumb" src="${thumbUrl}" alt="" onerror="this.style.display='none'">`
                : `<div class="browser-card-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted)">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".4"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                   </div>`}
            <div class="browser-card-body">
                <div class="browser-card-name">${escapeHtml(s.name)}</div>
                <div class="browser-card-meta">${escapeHtml(s.code)}${creator ? ` · ${escapeHtml(creator)}` : ''}</div>
            </div>`;
        if (!alreadyAdded) card.addEventListener('click', () => toggleBrowserSelect(s.code));
        grid.appendChild(card);
    }
    wrap.innerHTML = '';
    wrap.appendChild(grid);
}

function toggleBrowserSelect(code) {
    browserSelected.has(code) ? browserSelected.delete(code) : browserSelected.add(code);
    updateBrowserAddButton();
    renderBrowser();
}

function updateBrowserAddButton() {
    const btn   = document.getElementById('browser-add-selected');
    const count = browserSelected.size;
    document.getElementById('browser-selected-count').textContent = count;
    if (btn) btn.disabled = count === 0;
}

async function addSelectedStages() {
    if (!browserSelected.size) return;
    const codes = Array.from(browserSelected).join(',');
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/stages`, { codes });
        showToast(`Added ${browserSelected.size} stage${browserSelected.size !== 1 ? 's' : ''}`, 'success');
        browserSelected.clear();
        updateBrowserAddButton();
        await loadStagelist();
    } catch (err) { showToast(err.message, 'error'); }
}