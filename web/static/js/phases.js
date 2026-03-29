// ── phases.js ─────────────────────────────────────────────────────────────────
// Phase navigation and content rendering for multi-phase events.
// All phase data is bundled in the main loadTournament response —
// selecting a phase just re-renders from cache, no API call.

let _selectedPhase = null;   // null = overview, or phase index
let _selectedPhaseTab = null; // 'matches' | 'bracket' | 'leaderboard'
let _cachedPhases = [];       // populated by loadTournament

function updatePhaseCache(data) {
    _cachedPhases = data.phases || [];
}

// ── Sidebar nav ──────────────────────────────────────────────────────────────

function renderPhaseNav(data) {
    const section = document.getElementById('phase-nav-section');
    const wrap    = document.getElementById('phase-nav-items');

    if (!data.is_multi_phase) {
        section.hidden = true;
        return;
    }

    section.hidden = false;
    wrap.innerHTML = data.phases.map(p => {
        const isSelected = _selectedPhase === p.index;
        const stateClass = p.state === 'active'   ? 'phase-active'
                         : p.state === 'finished' ? 'phase-finished'
                         : 'phase-waiting';
        return `
            <button class="nav-item ${isSelected ? 'active' : ''}"
                    data-phase="${p.index}"
                    onclick="selectPhase(${p.index})">
                <span class="phase-dot ${stateClass}"></span>
                ${escapeHtml(p.label)}
                <span class="phase-state-label ${stateClass}">${p.state}</span>
            </button>`;
    }).join('');
}

// ── Phase selection (instant — no API call) ──────────────────────────────────

function selectPhase(index) {
    _selectedPhase = index;

    // Deselect sidebar nav items for event-level sections
    document.querySelectorAll('.nav-item[data-section]').forEach(b => b.classList.remove('active'));
    // Highlight the selected phase
    document.querySelectorAll('#phase-nav-items .nav-item').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.phase) === index);
    });

    // Hide all event-level sections, show phase content area
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById('section-phase-content').classList.add('active');

    const phase = _cachedPhases[index];
    if (!phase) return;

    // Pick default tab based on phase type
    const defaultTab = phase.type === 'swiss' ? 'matches' : 'matches';
    _selectedPhaseTab = _selectedPhaseTab || defaultTab;

    renderPhaseHeader(phase);
    renderPhaseTabs(phase);
    renderPhaseTabContent(phase);
}

function deselectPhase() {
    _selectedPhase = null;
    _selectedPhaseTab = null;
    document.getElementById('section-phase-content').classList.remove('active');
    document.querySelectorAll('#phase-nav-items .nav-item').forEach(btn => {
        btn.classList.remove('active');
    });
}

// ── Phase header ─────────────────────────────────────────────────────────────

function renderPhaseHeader(phase) {
    document.getElementById('topbar-title').textContent = phase.label;
    document.getElementById('topbar-sub').textContent =
        `${phase.type} · ${phase.state}`;
}

// ── Tab bar ──────────────────────────────────────────────────────────────────

function renderPhaseTabs(phase) {
    const tabBar = document.getElementById('phase-tab-bar');
    const isSwiss   = phase.type === 'swiss' || phase.type === 'swiss filter';
    const isBracket = phase.type === 'double elimination' || phase.type === 'single elimination';

    const tabs = [];
    tabs.push({ id: 'matches', label: 'Matches' });
    if (isBracket) tabs.push({ id: 'bracket', label: 'Bracket' });
    if (isSwiss)   tabs.push({ id: 'leaderboard', label: 'Leaderboard' });

    // Ensure selected tab is valid for this phase
    if (!tabs.find(t => t.id === _selectedPhaseTab)) {
        _selectedPhaseTab = 'matches';
    }

    tabBar.innerHTML = tabs.map(t =>
        `<button class="phase-tab ${t.id === _selectedPhaseTab ? 'active' : ''}"
                 onclick="selectPhaseTab('${t.id}')">
            ${t.label}
        </button>`
    ).join('');
}

function selectPhaseTab(tabId) {
    _selectedPhaseTab = tabId;
    const phase = _cachedPhases[_selectedPhase];
    if (!phase) return;

    // Update tab highlight
    document.querySelectorAll('.phase-tab').forEach(t => {
        t.classList.toggle('active', t.textContent.trim().toLowerCase() === tabId);
    });

    renderPhaseTabContent(phase);
}

// ── Tab content ──────────────────────────────────────────────────────────────

function renderPhaseTabContent(phase) {
    const content = document.getElementById('phase-tab-content');

    if (_selectedPhaseTab === 'matches') {
        renderPhaseMatches(content, phase);
    } else if (_selectedPhaseTab === 'bracket') {
        renderPhaseBracket(content, phase);
    } else if (_selectedPhaseTab === 'leaderboard') {
        renderPhaseLeaderboard(content, phase);
    }
}

function renderPhaseMatches(container, phase) {
    // For single-phase events, the main loadTournament already renders matches.
    // For multi-phase, we need phase-scoped match rendering.
    // Reuse the existing renderMatches function with phase-scoped data.
    container.innerHTML = '<div id="phase-matches-wrap"></div>';
    // TODO: fetch phase-scoped matches from the cached data or a targeted endpoint.
    // For now, if this is the active phase, show the existing match data.
    container.innerHTML = `
        <div style="padding:20px;color:var(--text-muted);font-size:13px">
            Matches for ${escapeHtml(phase.label)}
            ${phase.lobby_count ? ` · ${phase.lobby_count} active` : ' · No active lobbies'}
        </div>`;
}

function renderPhaseBracket(container, phase) {
    if (!phase.challonge_url) {
        container.innerHTML = `
            <div style="padding:40px;text-align:center;color:var(--text-muted)">
                ${phase.state === 'waiting' ? 'Bracket not yet created' : 'No bracket data available'}
            </div>`;
        return;
    }
    container.innerHTML = `
        <div style="padding:18px">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">
                <span style="font-size:15px;font-weight:600">${escapeHtml(phase.label)}</span>
                <span style="font-size:12px;color:var(--text-muted)">${phase.entrant_count || 0} players</span>
                <a href="${escapeHtml(phase.challonge_url)}" target="_blank" rel="noopener"
                   class="btn btn-secondary btn-sm" style="text-decoration:none">
                    View on Challonge ↗
                </a>
            </div>
            <iframe src="${escapeHtml(phase.challonge_url)}/module"
                    width="100%" height="500" frameborder="0"
                    style="border:1px solid var(--border);border-radius:var(--radius)">
            </iframe>
        </div>`;
}

function renderPhaseLeaderboard(container, phase) {
    if (!phase.swiss) {
        container.innerHTML = `
            <div style="padding:40px;text-align:center;color:var(--text-muted)">
                ${phase.state === 'waiting' ? 'Swiss rounds have not started' : 'No standings data available'}
            </div>`;
        return;
    }
    const s = phase.swiss;
    container.innerHTML = `
        <div style="padding:18px">
            <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
                <div class="info-card" style="min-width:100px"><div class="info-label">Round</div><div class="info-value">${s.current_round} / ${s.round_limit}</div></div>
                <div class="info-card" style="min-width:100px"><div class="info-label">Active</div><div class="info-value">${s.active_matches}</div></div>
                <div class="info-card" style="min-width:100px"><div class="info-label">Players</div><div class="info-value">${s.players_remaining}</div></div>
            </div>
            <div style="color:var(--text-muted);font-size:13px">
                Full leaderboard coming soon — standings data will be rendered here.
            </div>
        </div>`;
}
