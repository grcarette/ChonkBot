// ── phases.js ─────────────────────────────────────────────────────────────────
// Phase navigation, phase content rendering for multi-phase events.

let _selectedPhase = null;  // null = overview, or phase index

function renderPhaseNav(data) {
    const section = document.getElementById('phase-nav-section');
    const wrap    = document.getElementById('phase-nav-items');

    if (!data.is_multi_phase) {
        section.hidden = true;
        return;
    }

    section.hidden = false;
    wrap.innerHTML = data.phases.map(p => {
        const isActive   = _selectedPhase === p.index;
        const stateClass = p.state === 'active'   ? 'phase-active'
                         : p.state === 'finished' ? 'phase-finished'
                         : 'phase-waiting';
        return `
            <div class="phase-group">
                <button class="nav-item ${isActive ? 'active' : ''}"
                        data-phase="${p.index}"
                        onclick="selectPhase(${p.index})">
                    <span class="phase-dot ${stateClass}"></span>
                    ${escapeHtml(p.label)}
                    <span class="phase-state-label ${stateClass}">${p.state}</span>
                </button>
            </div>`;
    }).join('');
}

async function selectPhase(index) {
    _selectedPhase = index;

    // Update active nav item
    document.querySelectorAll('#phase-nav-items .nav-item').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.phase) === index);
    });

    // Fetch phase detail data
    try {
        const phaseData = await api('GET',
            `/api/tournament/${TOURNAMENT_ID}/phase/${index}`);
        renderPhaseContent(phaseData);
    } catch (err) {
        showToast('Failed to load phase data', 'error');
    }
}

function renderPhaseContent(phaseData) {
    if (!phaseData) return;

    // Switch to the matches section and render phase-specific matches
    document.querySelectorAll('.nav-item[data-section]').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));

    const matchesSection = document.getElementById('section-matches');
    if (matchesSection) {
        matchesSection.classList.add('active');
        document.getElementById('topbar-title').textContent = phaseData.label || 'Phase';
        document.getElementById('topbar-sub').textContent   = `${phaseData.type} · ${phaseData.state}`;
    }

    // Bracket phases: show bracket link + entrant count above the match list
    if (phaseData.type === 'double elimination' || phaseData.type === 'single elimination') {
        const wrap = document.getElementById('matches-section-wrap');
        let headerHtml = '';
        if (phaseData.challonge_url) {
            const count = phaseData.entrant_count ?? 0;
            headerHtml = `<div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                <span style="font-size:13px;font-weight:600">${escapeHtml(phaseData.label)}</span>
                <span style="font-size:12px;color:var(--text-muted)">${count} player${count !== 1 ? 's' : ''}</span>
                <a href="${escapeHtml(phaseData.challonge_url)}" target="_blank" rel="noopener"
                   class="btn btn-secondary btn-sm" style="text-decoration:none">
                    View Bracket ↗
                </a>
            </div>`;
        }
        if (wrap) wrap.innerHTML = headerHtml;
        return;
    }

    // Swiss phase: render matches and swiss data
    if (phaseData.swiss) {
        renderMatches(
            phaseData.lobbies  || [],
            phaseData.pending  || [],
            false,
            phaseData.swiss,
            []
        );
    } else if (phaseData.lobbies) {
        renderMatches(phaseData.lobbies || [], phaseData.pending || [], false, null, []);
    }
}
