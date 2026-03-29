// ── dashboard.js — main tournament list page ──────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initAvatar(USERNAME, AVATAR_URL);

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

// ── Format capabilities ───────────────────────────────────────────────────────

const FORMAT_CONFIG = {
    'swiss':               { hasRoundLimit: true,  lockRoundLimit: false, showFloating: false, rankedCompatible: true  },
    'swiss filter':        { hasRoundLimit: true,  lockRoundLimit: true,  showFloating: true,  rankedCompatible: true  },
    'double elimination':  { hasRoundLimit: false, lockRoundLimit: false, showFloating: false, rankedCompatible: true  },
    'single elimination':  { hasRoundLimit: false, lockRoundLimit: false, showFloating: false, rankedCompatible: true  },
};

function formatConfig(fmt) {
    return FORMAT_CONFIG[fmt] || { hasRoundLimit: false, lockRoundLimit: false, showFloating: false, rankedCompatible: false };
}

// ── Tournament list ────────────────────────────────────────────────────────────

async function loadTournaments() {
    try {
        const data = await api('GET', '/api/tournaments');
        renderTournaments(data.tournaments);
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

    const grid = document.createElement('div');
    grid.className = 'tournament-gallery';

    tournaments.forEach(t => {
        const [badgeClass, badgeLabel] = BADGE[t.state] || ['badge-setup', t.state];
        const entrantCount = t.entrant_count ?? 0;
        const debugTag     = t.debug ? '<span class="t-debug">debug</span>' : '';

        const card = document.createElement('div');
        card.className = 'tournament-gallery-card clickable';
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');

        const logoHtml = t.logo_url
            ? `<img src="${escapeHtml(t.logo_url)}" class="tg-logo-img" alt="">`
            : `<div class="tg-logo-placeholder">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
               </div>`;

        card.innerHTML = `
            <div class="tg-logo">
                ${logoHtml}
            </div>
            <div class="tg-body">
                <div class="tg-name">${escapeHtml(t.name)}${debugTag}</div>
                <div class="tg-meta">${escapeHtml(t.format || '')} · ${entrantCount} entrant${entrantCount !== 1 ? 's' : ''}</div>
                ${t.date ? `<div class="tg-date">${escapeHtml(t.date)}</div>` : ''}
            </div>
            <div class="tg-footer">
                <span class="t-badge ${badgeClass}">${badgeLabel}</span>
                ${t.lobby_count ? `<span class="tg-lobbies">${t.lobby_count} active</span>` : ''}
            </div>`;

        card.addEventListener('click', () => {
            window.location.href = `/dashboard/${t.id}`;
        });
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') window.location.href = `/dashboard/${t.id}`;
        });

        grid.appendChild(card);
    });

    wrap.innerHTML = '';
    wrap.appendChild(grid);
}

// ── Create Event modal ─────────────────────────────────────────────────────────

function initCreateModal() {
    const backdrop    = document.getElementById('modal-backdrop');
    const btnOpen     = document.getElementById('btn-create-event');
    const btnClose    = document.getElementById('modal-close');
    const btnCancel   = document.getElementById('modal-cancel');
    const btnBack     = document.getElementById('modal-back');
    const btnSubmit   = document.getElementById('modal-submit');
    const btnLabel    = btnSubmit.querySelector('.btn-label');
    const btnSpinner  = btnSubmit.querySelector('.btn-spinner');
    const errBox      = document.getElementById('modal-error');
    const fieldName   = document.getElementById('field-name');
    const fieldDate   = document.getElementById('field-date');
    const fieldRounds = document.getElementById('field-rounds');
    const roundGroup  = document.getElementById('round-limit-group');
    const formatBtns  = document.querySelectorAll('.format-btn');
    const step1        = document.getElementById('step-1');
    const step2        = document.getElementById('step-2');
    const step2Summary = document.getElementById('step2-summary');
    const modalTitle   = document.getElementById('modal-title');
    const rankedRow    = document.getElementById('opt-ranked-row');

    let selectedFormat = null;
    let currentStep    = 1;

    function openModal() {
        fieldName.value   = '';
        fieldDate.value   = '';
        fieldRounds.value = 8;
        document.getElementById('opt-approved').checked         = false;
        document.getElementById('opt-random-stage').checked     = false;
        document.getElementById('opt-display-entrants').checked = false;
        document.getElementById('opt-ranked').checked           = false;
        document.getElementById('opt-debug').checked            = false;
        if (document.getElementById('opt-floating'))       document.getElementById('opt-floating').checked = false;
        if (document.getElementById('opt-floating-count')) document.getElementById('opt-floating-count').value = 0;
        if (rankedRow) rankedRow.hidden = true;
        selectedFormat = null;
        formatBtns.forEach(b => b.classList.remove('selected'));
        errBox.hidden       = true;
        errBox.textContent  = '';
        roundGroup.hidden   = true;
        goToStep(1);
        backdrop.hidden = false;
        fieldName.focus();
    }

    function goToStep(n) {
        currentStep  = n;
        step1.hidden = n !== 1;
        step2.hidden = n !== 2;
        btnBack.hidden = n !== 2;

        if (n === 1) {
            modalTitle.textContent = 'Create Event';
            btnLabel.textContent   = 'Continue';
            checkStep1Ready();
        } else {
            const cfg = formatConfig(selectedFormat);
            roundGroup.hidden      = !cfg.hasRoundLimit;
            if (cfg.hasRoundLimit) {
                fieldRounds.disabled = cfg.lockRoundLimit;
                if (cfg.lockRoundLimit) fieldRounds.value = 3;
            }
            const staggeredRow = document.getElementById('opt-staggered-row');
            if (staggeredRow) staggeredRow.hidden = !cfg.hasRoundLimit || cfg.lockRoundLimit;
            const floatingRow = document.getElementById('opt-floating-row');
            if (floatingRow) floatingRow.hidden = !cfg.showFloating;
            const floatingCountRow = document.getElementById('opt-floating-count-row');
            if (floatingCountRow) floatingCountRow.hidden = !cfg.showFloating;
            modalTitle.textContent = 'Configuration';
            btnLabel.textContent   = 'Create Tournament';
            btnSubmit.style.opacity = '';
            btnSubmit.style.cursor  = '';
            step2Summary.textContent =
                `${fieldName.value.trim()} · ${selectedFormat}` +
                (fieldDate.value.trim() ? ` · ${fieldDate.value.trim()}` : '');
        }
    }

    function checkStep1Ready() {
        if (currentStep === 1) {
            const ready = !!(fieldName.value.trim() && selectedFormat);
            btnSubmit.style.opacity  = ready ? '' : '0.4';
            btnSubmit.style.cursor   = ready ? '' : 'not-allowed';
        }
    }

    btnOpen.addEventListener('click', openModal);
    btnClose.addEventListener('click', closeModal);
    btnCancel.addEventListener('click', closeModal);
    btnBack.addEventListener('click', () => goToStep(1));
    backdrop.addEventListener('click', e => { if (e.target === backdrop) closeModal(); });
    fieldName.addEventListener('input', checkStep1Ready);

    formatBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            formatBtns.forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
            selectedFormat = btn.dataset.value;
            if (rankedRow) rankedRow.hidden = !formatConfig(selectedFormat).rankedCompatible;
            checkStep1Ready();
        });
    });

    btnSubmit.addEventListener('click', async () => {
        if (currentStep === 1) {
            if (!fieldName.value.trim() || !selectedFormat) return;
            goToStep(2);
            return;
        }

        const cfg = formatConfig(selectedFormat);
        btnLabel.hidden    = true;
        btnSpinner.hidden  = false;
        btnSubmit.disabled = true;
        errBox.hidden      = true;

        try {
            const payload = {
                name:                  fieldName.value.trim(),
                date:                  fieldDate.value.trim(),
                format:                selectedFormat,
                approved_registration: document.getElementById('opt-approved').checked,
                randomized_stagelist:  document.getElementById('opt-random-stage').checked,
                display_entrants:      document.getElementById('opt-display-entrants').checked,
                ranked_reporting:      document.getElementById('opt-ranked').checked,
                debug:                 document.getElementById('opt-debug').checked,
                round_limit:           cfg.hasRoundLimit ? parseInt(fieldRounds.value) || 8 : 8,
                teams_mode:            document.getElementById('opt-teams').checked,
                staggered_start:       document.getElementById('opt-staggered')?.checked || false,
                staggered_start_threshold: 16,
            };
            if (cfg.showFloating) {
                payload.top_seed_floating       = document.getElementById('opt-floating')?.checked || false;
                payload.top_seed_floating_count = parseInt(document.getElementById('opt-floating-count')?.value) || 0;
            }
            await api('POST', '/api/tournaments', payload);
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