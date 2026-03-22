// ── dashboard.js — main tournament list page ──────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initAvatar(USERNAME, AVATAR_URL);

    // Navigation
    const SECTION_META = {
        overview: { title: 'Dashboard', sub: 'Overview of active tournaments' },
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
        });
    });

    loadTournaments();
    initCreateModal();

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && !document.getElementById('modal-backdrop').hidden) closeModal();
    });
});

// ── Tournament list ────────────────────────────────────────────────────────────

async function loadTournaments() {
    try {
        const data = await api('GET', '/api/tournaments');
        renderTournaments(data.tournaments);
        renderStats(data);
    } catch (err) {
        document.getElementById('tournament-list-wrap').innerHTML =
            `<div class="empty-state"><p>Failed to load tournaments.<br>${escapeHtml(err.message)}</p></div>`;
    }
}

function renderStats(data) {
    document.getElementById('stat-active').textContent  = data.active_count ?? '—';
    document.getElementById('stat-lobbies').textContent = data.lobby_count  ?? '—';
    document.getElementById('stat-players').textContent = data.player_count ?? '—';
}

function renderTournaments(tournaments) {
    const wrap = document.getElementById('tournament-list-wrap');
    if (!tournaments || !tournaments.length) {
        wrap.innerHTML = `<div class="empty-state">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
            <p>No active tournaments.<br>Use <strong>Create Event</strong> above to get started.</p>
        </div>`;
        return;
    }

    const BADGE = {
        active:       ['badge-active',  'Active'],
        registration: ['badge-reg',     'Registration'],
        checkin:      ['badge-checkin', 'Check-in'],
        setup:        ['badge-setup',   'Setup'],
        finished:     ['badge-finished','Finished'],
        initialize:   ['badge-setup',   'Initializing'],
    };

    const list = document.createElement('div');
    list.className = 'tournament-list';

    tournaments.forEach(t => {
        const [badgeClass, badgeLabel] = BADGE[t.state] || ['badge-setup', t.state];
        const entrantCount = t.entrant_count ?? 0;
        const date         = t.date ? `${escapeHtml(t.date)} · ` : '';
        const debugTag     = t.debug ? '<span class="t-debug">debug</span>' : '';

        const card = document.createElement('div');
        card.className = 'tournament-card clickable';
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');
        card.innerHTML = `
            <div class="t-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
            </div>
            <div class="t-info">
                <div class="t-name">${escapeHtml(t.name)}${debugTag}</div>
                <div class="t-meta">${date}${escapeHtml(t.format || '')} · ${entrantCount} entrant${entrantCount !== 1 ? 's' : ''}</div>
            </div>
            <div class="t-right">
                <span class="t-badge ${badgeClass}">${badgeLabel}</span>
                <svg class="t-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </div>`;

        const go = () => { window.location.href = `/dashboard/${t.id}`; };
        card.addEventListener('click', go);
        card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') go(); });
        list.appendChild(card);
    });

    wrap.innerHTML = '';
    wrap.appendChild(list);
}

// ── Create Event modal ─────────────────────────────────────────────────────────

function initCreateModal() {
    const backdrop   = document.getElementById('modal-backdrop');
    const btnOpen    = document.getElementById('btn-create-event');
    const btnClose   = document.getElementById('modal-close');
    const btnCancel  = document.getElementById('modal-cancel');
    const btnSubmit  = document.getElementById('modal-submit');
    const btnLabel   = btnSubmit.querySelector('.btn-label');
    const btnSpinner = btnSubmit.querySelector('.btn-spinner');
    const errBox     = document.getElementById('modal-error');
    const fieldName  = document.getElementById('field-name');
    const fieldDate  = document.getElementById('field-date');
    const fieldRounds= document.getElementById('field-rounds');
    const roundGroup = document.getElementById('round-limit-group');
    const formatBtns = document.querySelectorAll('.format-btn');

    let selectedFormat = null;

    function openModal() {
        fieldName.value  = '';
        fieldDate.value  = '';
        fieldRounds.value = 8;
        document.getElementById('opt-approved').checked       = false;
        document.getElementById('opt-random-stage').checked   = false;
        document.getElementById('opt-display-entrants').checked = false;
        document.getElementById('opt-debug').checked          = false;
        selectedFormat = null;
        formatBtns.forEach(b => b.classList.remove('selected'));
        roundGroup.hidden    = true;
        errBox.hidden        = true;
        errBox.textContent   = '';
        btnSubmit.disabled   = true;
        backdrop.hidden      = false;
        fieldName.focus();
    }

    function checkReady() {
        btnSubmit.disabled = !(fieldName.value.trim() && selectedFormat);
    }

    btnOpen.addEventListener('click', openModal);
    btnClose.addEventListener('click', closeModal);
    btnCancel.addEventListener('click', closeModal);
    backdrop.addEventListener('click', e => { if (e.target === backdrop) closeModal(); });

    formatBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            formatBtns.forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            selectedFormat = btn.dataset.value;
            roundGroup.hidden = !(selectedFormat === 'swiss' || selectedFormat === 'swiss filter');
            checkReady();
        });
    });

    fieldName.addEventListener('input', checkReady);

    document.getElementById('rounds-dec').addEventListener('click', () => {
        const v = parseInt(fieldRounds.value, 10);
        if (v > 1) fieldRounds.value = v - 1;
    });
    document.getElementById('rounds-inc').addEventListener('click', () => {
        const v = parseInt(fieldRounds.value, 10);
        if (v < 99) fieldRounds.value = v + 1;
    });

    btnSubmit.addEventListener('click', async () => {
        const name = fieldName.value.trim();
        if (!name || !selectedFormat) return;

        btnSubmit.disabled = true;
        btnLabel.hidden    = true;
        btnSpinner.hidden  = false;
        errBox.hidden      = true;

        const payload = {
            name,
            date:                  fieldDate.value.trim(),
            format:                selectedFormat,
            approved_registration: document.getElementById('opt-approved').checked,
            randomized_stagelist:  document.getElementById('opt-random-stage').checked,
            display_entrants:      document.getElementById('opt-display-entrants').checked,
            round_limit:           parseInt(fieldRounds.value, 10) || 8,
            debug:                 document.getElementById('opt-debug').checked,
        };

        try {
            const res  = await fetch('/api/tournaments', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            closeModal();
            await loadTournaments();
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden      = false;
            btnSubmit.disabled = false;
        } finally {
            btnLabel.hidden   = false;
            btnSpinner.hidden = true;
        }
    });
}