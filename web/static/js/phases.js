// ── phases.js ─────────────────────────────────────────────────────────────────
// Phase navigation and content rendering for multi-phase events.
// All phase data is bundled in the main loadTournament response —
// selecting a phase just re-renders from cache, no API call.

let _selectedPhase = null;   // null = overview, or phase index
let _selectedPhaseTab = null; // 'matches' | 'bracket' | 'leaderboard'
let _cachedPhases = [];       // populated by loadTournament
let _phaseBracketPollTimer = null; // interval for polling phase bracket

function updatePhaseCache(data) {
    _cachedPhases = data.phases || [];
}

// ── Sidebar nav ──────────────────────────────────────────────────────────────

function renderPhaseNav(data) {
    const section = document.getElementById('phase-nav-section');
    const wrap    = document.getElementById('phase-nav-items');

    if (!data.phases || data.phases.length === 0) {
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

async function selectPhase(index) {
    // Stop any phase bracket poll from a previous phase selection
    _stopPhaseBracketPoll();
    _activePhaseBracketIndex = null;

    _selectedPhase = index;
    _selectedPhaseTab = null; // reset tab on phase change

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

    // Default to bracket tab for bracket phases, matches for swiss
    const isBracketPhase = phase.type === 'double elimination' || phase.type === 'single elimination';
    _selectedPhaseTab = isBracketPhase ? 'bracket' : 'matches';

    renderPhaseHeader(phase);
    renderPhaseTabs(phase);
    await renderPhaseTabContent(phase);
}

function deselectPhase() {
    _selectedPhase = null;
    _selectedPhaseTab = null;
    _stopPhaseBracketPoll();
    _activePhaseBracketIndex = null;
    document.getElementById('section-phase-content').classList.remove('active');
    document.querySelectorAll('#phase-nav-items .nav-item').forEach(btn => {
        btn.classList.remove('active');
    });
}

function _stopPhaseBracketPoll() {
    if (_phaseBracketPollTimer) {
        clearInterval(_phaseBracketPollTimer);
        _phaseBracketPollTimer = null;
    }
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
    if (isBracket) tabs.push({ id: 'bracket', label: 'Bracket' });
    tabs.push({ id: 'matches', label: 'Matches' });
    if (isSwiss)   tabs.push({ id: 'leaderboard', label: 'Leaderboard' });

    // Ensure selected tab is valid for this phase
    if (!tabs.find(t => t.id === _selectedPhaseTab)) {
        _selectedPhaseTab = tabs[0]?.id || 'matches';
    }

    tabBar.innerHTML = tabs.map(t =>
        `<button class="phase-tab ${t.id === _selectedPhaseTab ? 'active' : ''}"
                 onclick="selectPhaseTab('${t.id}')">
            ${t.label}
        </button>`
    ).join('');
}

async function selectPhaseTab(tabId) {
    if (tabId !== 'bracket') {
        _stopPhaseBracketPoll();
        _activePhaseBracketIndex = null;
    }
    _selectedPhaseTab = tabId;
    const phase = _cachedPhases[_selectedPhase];
    if (!phase) return;

    // Update tab highlight
    document.querySelectorAll('.phase-tab').forEach(t => {
        t.classList.toggle('active', t.textContent.trim().toLowerCase() === tabId);
    });

    await renderPhaseTabContent(phase);
}

// ── Tab content ──────────────────────────────────────────────────────────────

async function renderPhaseTabContent(phase) {
    const content = document.getElementById('phase-tab-content');

    if (_selectedPhaseTab === 'matches') {
        renderPhaseMatches(content, phase);
    } else if (_selectedPhaseTab === 'bracket') {
        await renderPhaseBracket(content, phase);
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

async function renderPhaseBracket(container, phase) {
    if (!phase.challonge_url) {
        container.innerHTML = `
            <div style="padding:40px;text-align:center;color:var(--text-muted)">
                ${phase.state === 'waiting' ? 'Bracket not yet created' : 'No bracket data available'}
            </div>`;
        return;
    }

    if (_activePhaseBracketIndex === phase.index && _phaseBracketPollTimer) {
        return;
    }

    // Stop any existing poll before starting a new one
    _stopPhaseBracketPoll();

    // Set active phase bracket index so drawer actions route to the right TM
    _activePhaseBracketIndex = phase.index;

    // Build the container structure (header + toolbar + bracket wrap)
    const autocall = phase.autocall_matches || false;
    const autocallClass = autocall ? 'btn-toggle-on' : 'btn-toggle-off';

    container.innerHTML = `
        <div style="padding:18px">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;flex-wrap:wrap">
                <div style="display:flex;align-items:center;gap:12px">
                    <span style="font-size:15px;font-weight:600">${escapeHtml(phase.label)}</span>
                    <span style="font-size:12px;color:var(--text-muted)">${phase.entrant_count || 0} players</span>
                    ${phase.challonge_url ?
                        `<a href="${escapeHtml(phase.challonge_url)}" target="_blank" rel="noopener"
                           class="btn btn-secondary btn-sm" style="text-decoration:none">
                            View on Challonge ↗
                        </a>` : ''}
                </div>
                <div style="display:flex;align-items:center;gap:8px">
                    <button class="btn ${autocallClass} btn-sm" id="phase-btn-autocall">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                        Auto Call: ${autocall ? 'On' : 'Off'}
                    </button>
                    <button class="btn btn-primary btn-sm" id="phase-btn-call-all">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        Call All
                    </button>
                </div>
            </div>
            <div id="phase-bracket-wrap" style="overflow-x:auto"></div>
        </div>`;

    // Wire up toolbar buttons
    document.getElementById('phase-btn-autocall')?.addEventListener('click', async () => {
        try {
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
                action: 'set_autocall',
                enabled: !autocall,
                ..._phasePayload(),
            });
            showToast(autocall ? 'Auto-call disabled' : 'Auto-call enabled', 'success');
            await loadTournament({ force: true });
            const updatedPhase = _cachedPhases[_selectedPhase];
            if (updatedPhase) await renderPhaseBracket(container, updatedPhase);
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    document.getElementById('phase-btn-call-all')?.addEventListener('click', async () => {
        try {
            document.getElementById('phase-btn-call-all').disabled = true;
            document.getElementById('phase-btn-call-all').textContent = 'Calling...';
            await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, {
                action: 'call_all_matches',
                ..._phasePayload(),
            });
            showToast('All matches called', 'success');
            await loadTournament({ force: true });
            startBracketRapidPoll(20000, 1500);
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    const wrap = document.getElementById('phase-bracket-wrap');
    let _lastPhaseBracketJson = null;

    async function fetchAndRender() {
        // Bail out if the user has navigated away from this phase or tab
        if (_activePhaseBracketIndex !== phase.index) return;
        try {
            const data = await api('GET', `/api/tournament/${TOURNAMENT_ID}/phase/${phase.index}/bracket`);
            const json = JSON.stringify(data.matches);
            if (json === _lastPhaseBracketJson) return; // nothing changed, skip re-render
            _lastPhaseBracketJson = json;
            bracketData = data;
            if (_activePhaseBracketIndex === phase.index && wrap.isConnected) {
                renderBracketInto(data, wrap);
            }
        } catch (err) {
            if (wrap.isConnected && _activePhaseBracketIndex === phase.index) {
                wrap.innerHTML = `<div style="padding:20px;color:var(--text-muted);font-size:13px">${escapeHtml(err.message)}</div>`;
            }
        }
    }

    await fetchAndRender();

    // Poll every 5 s while this phase bracket is open
    _phaseBracketPollTimer = setInterval(fetchAndRender, 5000);
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
