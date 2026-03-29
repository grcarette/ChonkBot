// ── participants.js ───────────────────────────────────────────────────────────
// Participant list, drag-and-drop seeding, DQ actions.

let _participantDragState = null;
let _seedingSyncing       = false;
let _seedIdleTimer = null;
const SEED_IDLE_MS = 15000;

const _lockedSeeds = new Set(); // discord_ids whose seeds are locked
let _lockedSeedsLoaded = false;

function _ensureLockedSeeds() {
    if (_lockedSeedsLoaded) return;
    _lockedSeedsLoaded = true;
    try {
        const stored = localStorage.getItem(`lockedSeeds_${TOURNAMENT_ID}`);
        if (stored) JSON.parse(stored).forEach(id => _lockedSeeds.add(id));
    } catch {}
}

function _persistLockedSeeds() {
    try {
        localStorage.setItem(`lockedSeeds_${TOURNAMENT_ID}`, JSON.stringify([..._lockedSeeds]));
    } catch {}
}

const _SVG_LOCK = `<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
    <path d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2m3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"/>
</svg>`;
const _SVG_UNLOCK = `<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
    <path d="M11 1a2 2 0 0 0-2 2v4a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h5V3a3 3 0 0 1 6 0v4a.5.5 0 0 1-1 0V3a2 2 0 0 0-2-2z"/>
</svg>`;

// ── Top-level render (called from loadTournament) ─────────────────────────────

function renderPlayers(entrants, checkedIn, dqs, state, format) {
    const wrap    = document.getElementById('participants-list-wrap');
    const countEl = document.getElementById('players-count');
    const showCI  = ['checkin', 'active'].includes(state);

    if (!wrap) return;
    if (countEl) countEl.textContent = `${entrants.length} entrant${entrants.length !== 1 ? 's' : ''}`;

    if (!entrants.length) {
        wrap.innerHTML = `<div class="empty-state">No entrants yet.</div>`;
        wrap._entrants = null;
        return;
    }

    const alreadyRendered = Array.isArray(wrap._entrants);
    const countChanged    = alreadyRendered && wrap._entrants.length !== entrants.length;
    if (!alreadyRendered || countChanged) {
        const sorted = [...entrants].sort((a, b) => (a.seed ?? 9999) - (b.seed ?? 9999));
        renderSeedingList(wrap, sorted, checkedIn, dqs, showCI);
    }
    wrap._checkedIn = checkedIn;
    wrap._dqs       = dqs;
    wrap._showCI    = showCI;
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

    const showCI = ['checkin', 'active'].includes(state);

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
}

// ── Drag-and-drop seeding list ────────────────────────────────────────────────

function renderSeedingList(wrap, entrants, checkedIn, dqs, showCI) {
    _ensureLockedSeeds();
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

        const nameEsc  = escapeHtml(e.name).replace(/'/g, "\\'");
        const dqBtn    = `<button class="btn btn-danger btn-sm" onclick="removePlayer('${e.discord_id}','${nameEsc}')">Remove</button>`;
        const isLocked = _lockedSeeds.has(e.discord_id);
        const lockBtn  = `<button class="seed-lock-btn${isLocked ? ' is-locked' : ''}" onclick="toggleSeedLock('${e.discord_id}')" title="${isLocked ? 'Unlock seed' : 'Lock seed'}">${isLocked ? _SVG_LOCK : _SVG_UNLOCK}</button>`;

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
            ${lockBtn}
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

    clearTimeout(_seedIdleTimer);
    _seedIdleTimer = setTimeout(async () => {
        _seedIdleTimer = null;
        const statusEl2 = document.querySelector('#participants-list-wrap .seeding-save-status');
        if (statusEl2) { statusEl2.textContent = 'Updating event info…'; statusEl2.style.color = 'var(--text-muted)'; }
        try {
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, { action: 'refresh_event_info' });
            if (statusEl2) { statusEl2.textContent = 'Event info updated ✓'; statusEl2.style.color = 'var(--green)'; }
            setTimeout(() => { if (statusEl2) statusEl2.textContent = ''; }, 2500);
        } catch (err) {
            if (statusEl2) statusEl2.textContent = '';
        }
    }, SEED_IDLE_MS);
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

// ── Seed locking ─────────────────────────────────────────────────────────────

function toggleSeedLock(discordId) {
    if (_lockedSeeds.has(discordId)) _lockedSeeds.delete(discordId);
    else _lockedSeeds.add(discordId);
    _persistLockedSeeds();

    for (const id of ['overview-participants-wrap', 'participants-list-wrap']) {
        const wrap = document.getElementById(id);
        if (wrap?._entrants) _rebuildSeedingList(wrap, wrap._checkedIn || [], wrap._dqs || [], wrap._showCI || false);
    }
}

function getLockedSeedsPayload() {
    const wrap = document.getElementById('overview-participants-wrap')
               || document.getElementById('participants-list-wrap');
    if (!wrap?._entrants) return [];
    return wrap._entrants
        .map((e, i) => ({ discord_id: e.discord_id, seed: i + 1 }))
        .filter(({ discord_id }) => _lockedSeeds.has(discord_id));
}

// ── Remove action ─────────────────────────────────────────────────────────────

async function removePlayer(discordId, name) {
    if (await showConfirm('Remove Player?',
        `${name} will be unregistered from the event.`, 'danger'))
        await doAction('unregister_player', { discord_id: discordId });
}