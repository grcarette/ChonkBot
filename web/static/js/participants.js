// ── participants.js ───────────────────────────────────────────────────────────
// Participant list, drag-and-drop seeding, DQ actions.

let _participantDragState = null;
let _seedingSyncing       = false;
let _seedIdleTimer = null;
const SEED_IDLE_MS = 15000;

// ── Top-level render (called from loadTournament) ─────────────────────────────

function renderPlayers(entrants, checkedIn, dqs, state, format) {
    const wrap      = document.getElementById('participants-list-wrap');
    const countEl   = document.getElementById('players-count');
    const isBracket = format === 'single elimination' || format === 'double elimination' || format === 'swiss filter';
    const showCI    = ['checkin', 'active'].includes(state);

    if (!wrap) return;
    if (countEl) countEl.textContent = `${entrants.length} entrant${entrants.length !== 1 ? 's' : ''}`;

    document.getElementById('players-count').textContent =
        `${entrants.length} entrant${entrants.length !== 1 ? 's' : ''}`;

    if (!entrants.length) {
        wrap.innerHTML = `<div class="empty-state">No entrants yet.</div>`;
        wrap._entrants = null;
        return;
    }

    if (isBracket) {
        const alreadyRendered = Array.isArray(wrap._entrants);
        const countChanged    = alreadyRendered && wrap._entrants.length !== entrants.length;
        if (!alreadyRendered || countChanged) {
            const sorted = [...entrants].sort((a, b) => (a.seed ?? 9999) - (b.seed ?? 9999));
            renderSeedingList(wrap, sorted, checkedIn, dqs, showCI);
        }
        wrap._checkedIn = checkedIn;
        wrap._dqs       = dqs;
        wrap._showCI    = showCI;
    } else {
        renderParticipantsTable(wrap, entrants, checkedIn, dqs, showCI);
    }
}

function renderOverviewParticipants(entrants, checkedIn, dqs, state, format) {
    const wrap    = document.getElementById('overview-participants-wrap');
    const countEl = document.getElementById('overview-players-count');
    if (!wrap) return;

    countEl.textContent = `${entrants.length} entrant${entrants.length !== 1 ? 's' : ''}`;

    if (!entrants.length) {
        wrap.innerHTML = '<div class="empty-state">No entrants yet.</div>';
        wrap._entrants = null;
        return;
    }

    const isBracket = format === 'single elimination' || format === 'double elimination' || format === 'swiss filter';
    const showCI    = ['checkin', 'active'].includes(state);

    if (isBracket) {
        const alreadyRendered = Array.isArray(wrap._entrants);
        const countChanged    = alreadyRendered && wrap._entrants.length !== entrants.length;
        if (!alreadyRendered || countChanged || _forceRefreshSeeds) {
            const sorted = [...entrants].sort((a, b) => (a.seed ?? 9999) - (b.seed ?? 9999));
            renderSeedingList(wrap, sorted, checkedIn, dqs, showCI);
            _forceRefreshSeeds = false;
        }
        wrap._checkedIn = checkedIn;
        wrap._dqs       = dqs;
        wrap._showCI    = showCI;
    } else {
        wrap.innerHTML = entrants.map((e, i) => `
            <div style="display:flex;align-items:center;gap:10px;padding:9px 18px;border-bottom:1px solid var(--border)">
                <span style="width:22px;text-align:right;color:var(--text-muted);font-size:11px;font-weight:600">${i + 1}</span>
                ${e.avatar_url
                    ? `<img src="${escapeHtml(e.avatar_url)}" style="width:26px;height:26px;border-radius:50%;object-fit:cover;flex-shrink:0" alt="">`
                    : `<div style="width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">${escapeHtml((e.name||'?')[0])}</div>`
                }
                <span style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(e.name)}</span>
            </div>`
        ).join('');
    }
}

// ── Drag-and-drop seeding list (DE/SE/Swiss Filter) ───────────────────────────

function renderSeedingList(wrap, entrants, checkedIn, dqs, showCI) {
    wrap._entrants = [...entrants];
    wrap.innerHTML = `<ul class="seeding-list"></ul>
        <div class="seeding-save-status" style="height:24px;text-align:center;font-size:12px;padding:6px 0;color:var(--text-muted)"></div>`;
    _rebuildSeedingList(wrap, checkedIn, dqs, showCI);
}

function _rebuildSeedingList(wrap, checkedIn, dqs, showCI) {
    const list     = wrap.querySelector('.seeding-list');
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
            ? `<button class="btn btn-secondary btn-sm" onclick="undqPlayer('${e.discord_id}')">Un-DQ</button>`
            : `<button class="btn btn-danger btn-sm" onclick="dqPlayer('${e.discord_id}','${nameEsc}')">DQ</button>`;

        const li = document.createElement('li');
        li.className    = 'participant-item';
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
            ${e.avatar_url
                ? `<img src="${escapeHtml(e.avatar_url)}" class="participant-avatar" alt="">`
                : `<div class="participant-avatar-placeholder">${escapeHtml((e.name || '?')[0])}</div>`
            }
            <span class="participant-name">${escapeHtml(e.name)}</span>
            <span class="participant-tags">${tag}</span>
            <span class="participant-actions">${dqBtn}</span>`;

        li.addEventListener('pointerdown', _onSeedPointerDown);
        list.appendChild(li);
    });

    requestAnimationFrame(() => {
        const first = list.querySelector('.participant-item');
        if (first) list.style.setProperty('--pi-h', `${first.offsetHeight}px`);
    });
}

function _onSeedPointerDown(e) {
    if (!e.target.closest('.participant-drag-handle')) return;
    if (e.button !== 0) return;
    e.preventDefault();

    const item     = e.currentTarget;
    const srcIndex = parseInt(item.dataset.index);
    const rect     = item.getBoundingClientRect();
    const list     = item.closest('.seeding-list');
    const wrap     = list.parentElement;

    const ghost = item.cloneNode(true);
    ghost.id = 'participant-drag-ghost';
    ghost.style.setProperty('--ghost-w', `${rect.width}px`);
    ghost.style.top  = `${rect.top}px`;
    ghost.style.left = `${rect.left}px`;
    document.body.appendChild(ghost);

    item.classList.add('is-dragging');

    _participantDragState = { srcIndex, currentIndex: srcIndex,
        offsetX: e.clientX - rect.left, offsetY: e.clientY - rect.top,
        ghost, item, list, wrap };

    document.addEventListener('pointermove', _onSeedPointerMove);
    document.addEventListener('pointerup',   _onSeedPointerUp);
}

function _onSeedPointerMove(e) {
    if (!_participantDragState) return;
    const { ghost, offsetX, offsetY, srcIndex, list } = _participantDragState;

    ghost.style.left = `${e.clientX - offsetX}px`;
    ghost.style.top  = `${e.clientY - offsetY}px`;

    const items = [...list.querySelectorAll('.participant-item:not(.is-dragging)')];
    let newIndex = 0;
    for (let i = 0; i < items.length; i++) {
        const r    = items[i].getBoundingClientRect();
        const midY = r.top + r.height / 2;
        const idx  = parseInt(items[i].dataset.index);
        if (e.clientY > midY) newIndex = idx >= srcIndex ? idx : idx + 1;
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

    const { srcIndex, currentIndex, ghost, item, list, wrap } = _participantDragState;
    _participantDragState = null;

    ghost.remove();
    item.classList.remove('is-dragging');
    list.querySelectorAll('.participant-item').forEach(el =>
        el.classList.remove('shift-up', 'shift-down'));

    if (srcIndex === currentIndex) return;

    const moved = wrap._entrants.splice(srcIndex, 1)[0];
    wrap._entrants.splice(currentIndex, 0, moved);

    const checkedIn = wrap._checkedIn || [];
    const dqs       = wrap._dqs       || [];
    const showCI    = wrap._showCI    || false;
    _rebuildSeedingList(wrap, checkedIn, dqs, showCI);
    await _syncAllSeeds(wrap._entrants, wrap);
}

async function _syncAllSeeds(entrants, wrap) {
    console.log('[seeding] _syncAllSeeds called, TOURNAMENT_ID:', typeof TOURNAMENT_ID !== 'undefined' ? TOURNAMENT_ID : 'UNDEFINED');
    _seedingSyncing = true;
    const statusEl = wrap.querySelector('.seeding-save-status');
    if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.style.color = 'var(--text-muted)'; }
    try {
        const seeds = entrants.map((e, i) => ({
            discord_id:   e.discord_id,
            challonge_id: e.challonge_id ?? null,
            seed:         i + 1,
        }));
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/seed`, { seeds });
        if (statusEl) { statusEl.textContent = 'Saved ✓'; statusEl.style.color = 'var(--green)'; }
        setTimeout(() => {
            if (statusEl) statusEl.textContent = '';
            _seedingSyncing = false;
        }, 2500);
    } catch (err) {
        _seedingSyncing = false;
        if (statusEl) { statusEl.textContent = `Save failed: ${err.message}`; statusEl.style.color = 'var(--red)'; }
        showToast(`Seeding save failed: ${err.message}`, 'error');
        return;
    }

    console.log('[seeding] seed save succeeded, setting idle timer for', SEED_IDLE_MS, 'ms');
    clearTimeout(_seedIdleTimer);
    _seedIdleTimer = setTimeout(async () => {
        console.log('[seeding] idle timer fired, calling refresh_event_info');
        _seedIdleTimer = null;
        const statusEl2 = document.querySelector('#participants-list-wrap .seeding-save-status');
        if (statusEl2) { statusEl2.textContent = 'Updating event info…'; statusEl2.style.color = 'var(--text-muted)'; }
        try {
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, { action: 'refresh_event_info' });
            console.log('[seeding] refresh_event_info succeeded');
            if (statusEl2) { statusEl2.textContent = 'Event info updated ✓'; statusEl2.style.color = 'var(--green)'; }
            setTimeout(() => { if (statusEl2) statusEl2.textContent = ''; }, 2500);
        } catch (err) {
            console.warn('[seeding] Failed to refresh event info:', err.message);
            if (statusEl2) statusEl2.textContent = '';
        }
    }, SEED_IDLE_MS);
}

// ── Plain table (Swiss) ───────────────────────────────────────────────────────

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
            ? `<button class="btn btn-secondary btn-sm" onclick="undqPlayer('${e.discord_id}')">Un-DQ</button>`
            : `<button class="btn btn-danger btn-sm" onclick="dqPlayer('${e.discord_id}','${nameEsc}')">DQ</button>`;
        return `<tr>
            <td style="color:var(--text-muted);font-size:12px">${i + 1}</td>
            <td><strong>${escapeHtml(e.name)}</strong></td>
            <td>${statusTag}</td>
            <td>${dqBtn}</td>
        </tr>`;
    }).join('');
}

// ── Seed input (used in bracket seeding view) ─────────────────────────────────

async function setSeed(input) {
    const newSeed     = parseInt(input.value, 10);
    const challongeId = parseInt(input.dataset.challonge, 10);
    if (!newSeed || newSeed < 1) { input.value = input.dataset.prev || ''; return; }
    input.dataset.prev = input.value;
    input.disabled = true;
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/seed`, { challonge_id: challongeId, seed: newSeed });
        showToast('Seed updated', 'success');
    } catch (err) {
        showToast(`Failed: ${err.message}`, 'error');
        input.value = input.dataset.prev || '';
    } finally {
        input.disabled = false;
    }
}

// ── DQ actions ────────────────────────────────────────────────────────────────

async function dqPlayer(discordId, name) {
    if (await showConfirm('Disqualify Player?',
        `${name} will be DQ'd. If they have an active match, their opponent wins.`, 'danger'))
        await doAction('dq_player', { discord_id: discordId });
}

async function undqPlayer(discordId) {
    await doAction('undq_player', { discord_id: discordId });
}