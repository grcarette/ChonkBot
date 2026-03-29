// ── event_dashboard.js ────────────────────────────────────────────────────────
// Core: init, polling loop, badge, stats, action area, config, registration.
// Delegates to: matches.js, participants.js, bracket.js, stagelist.js

// ── Init ──────────────────────────────────────────────────────────────────────

let bracketRefreshInterval = null;
let _forceRefreshSeeds     = false;
let _seedsRendered         = false;
let _loadTournamentInFlight = false;
let _dangerZoneOpen = false;
let _nextRoundInFlight = false;

document.addEventListener('DOMContentLoaded', () => {
    initAvatar(USERNAME, AVATAR_URL);

    const SECTION_META = {
        overview:  { title: 'Overview',       sub: 'Tournament status and controls' },
        matches:   { title: 'Matches',        sub: 'Active lobbies and match state' },
        config:    { title: 'Configuration',  sub: 'Tournament settings' },
        stagelist: { title: 'Stagelist',      sub: 'Manage tournament stages' },
        bracket:   { title: 'Bracket',        sub: 'Match tree and lobby controls' },
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
                    bracketRefreshInterval = setInterval(loadBracket, 5000);
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

    // Drawer close
    document.getElementById('drawer-close').addEventListener('click', closeDrawer);
    document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);

    // Escape key closes drawer or modal
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            if (!document.getElementById('match-drawer').hidden) closeDrawer();
            else if (!document.getElementById('modal-backdrop').hidden) closeModal();
        }
    });

    // Config save handlers
    document.getElementById('cfg-save-details').onclick = async () => {
        const name = document.getElementById('cfg-name').value.trim();
        const date = document.getElementById('cfg-date').value.trim();
        if (!name) { showToast('Name cannot be empty', 'error'); return; }
        await doAction('update_config', { name, date });
    };
    document.getElementById('cfg-save-options').onclick = async () => {
        const payload = {
            approved_registration: document.getElementById('cfg-approved').checked,
            randomized_stagelist:  document.getElementById('cfg-random-stage').checked,
            display_entrants:      document.getElementById('cfg-display-entrants').checked,
            ranked_reporting:      document.getElementById('cfg-ranked').checked,
        };
        const staggeredRow = document.getElementById('cfg-staggered-row');
        if (staggeredRow && staggeredRow.style.display !== 'none') {
            payload.staggered_start = document.getElementById('cfg-staggered').checked;
            payload.staggered_start_threshold = parseInt(
                document.getElementById('cfg-staggered-threshold').value, 10
            ) || 16;
        }
        await doAction('update_config', payload);
    };
    // Image uploads — wired once, not on every populateConfig call
    document.getElementById('cfg-banner-upload').addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        await uploadImage(file, 'banner');
        e.target.value = '';
    });

    document.getElementById('cfg-logo-upload').addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        await uploadImage(file, 'logo');
        e.target.value = '';
    });

    document.getElementById('cfg-banner-delete').addEventListener('click', async () => {
        if (await showConfirm('Remove Banner?', 'The banner image will be deleted.', 'danger'))
            await deleteImage('banner');
    });

    document.getElementById('cfg-logo-delete').addEventListener('click', async () => {
        if (await showConfirm('Remove Logo?', 'The logo image will be deleted.', 'danger'))
            await deleteImage('logo');
    });

    // Delete tournament
    document.getElementById('btn-delete-tournament').onclick = async () => {
        const tournament = await api('GET', `/api/tournament/${TOURNAMENT_ID}`);
        const name = tournament.name;
        const extraHtml = `
            <div style="margin-top:12px">
                <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px">
                    Type <strong style="color:var(--text-primary)">${escapeHtml(name)}</strong> to confirm:
                </div>
                <input class="field-input" id="delete-confirm-input"
                    placeholder="${escapeHtml(name)}" autocomplete="off" style="width:100%">
                <div id="delete-confirm-error"
                    style="font-size:12px;color:var(--red);margin-top:6px;display:none">
                    Name does not match.
                </div>
            </div>`;
        document.getElementById('modal-title').textContent  = 'Delete Tournament?';
        document.getElementById('modal-desc').textContent   = 'This will permanently delete the tournament and all associated data.';
        document.getElementById('modal-extra').innerHTML    = extraHtml;
        document.getElementById('modal-icon').className     = 'modal-icon danger';
        const confirmBtn = document.getElementById('modal-confirm');
        confirmBtn.className = 'modal-confirm danger';
        document.getElementById('modal-backdrop').hidden = false;
        document.getElementById('delete-confirm-input').focus();

        await new Promise(resolve => {
            confirmBtn.onclick = () => {
                const typed = document.getElementById('delete-confirm-input').value.trim();
                if (typed !== name) {
                    document.getElementById('delete-confirm-error').style.display = '';
                    return;
                }
                document.getElementById('modal-backdrop').hidden = true;
                document.getElementById('modal-extra').innerHTML = '';
                resolve(true);
            };
            document.getElementById('modal-cancel').onclick = () => {
                closeModal();
                resolve(false);
            };
        });
        await doAction('delete_tournament');
    };

    // Stagelist controls
    document.getElementById('stagelist-add-btn').addEventListener('click', addStageByCode);
    document.getElementById('stagelist-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') addStageByCode();
    });
    document.getElementById('browser-add-selected').addEventListener('click', addSelectedStages);
    document.getElementById('browser-mode-filter').addEventListener('change', loadBrowser);
    document.getElementById('browser-search').addEventListener('input', renderBrowser);

    // Seed controls
    document.getElementById('btn-randomize-seeds').addEventListener('click', async () => {
        if (await showConfirm('Randomize Seeds?', 'This will randomly shuffle all current seeds.'))
            await doAction('randomize_seeds');
    });
    document.getElementById('btn-seed-by-rank').addEventListener('click', async () => {
        if (await showConfirm('Seed by Rank?',
            'This will overwrite all current seeds with UCH Ranked elo order, highest elo = seed 1.'))
            await doAction('seed_by_rank');
    });

    // Pause polling when tab is hidden, resume on focus
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') loadTournament();
    });

    // Start polling
    loadTournament();
    setInterval(loadTournament, 5000);
});

// ── Core action ───────────────────────────────────────────────────────────────

async function doAction(action, extra = {}) {
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/action`, { action, ...extra });
        if (action === 'delete_tournament') {
            window.location.href = '/dashboard';
            return;
        }
        showToast('Done', 'success');
        if (['seed_by_rank', 'randomize_seeds'].includes(action)) {
            _forceRefreshSeeds = true;
        }
        await loadTournament({ force: true });
    } catch (err) {
        showToast(err.message, 'error');
        await loadTournament({ force: true });
    }
}

// ── Main poll ─────────────────────────────────────────────────────────────────

async function loadTournament({ force = false } = {}) {
    if (_loadTournamentInFlight && !force) return;
    _loadTournamentInFlight = true;
    try {
        _timing.start('loadTournament_total');

        _timing.start('fetch_tournament');
        _timing.start('fetch_pending');

        const [data, pmResult] = await Promise.all([
            api('GET', `/api/tournament/${TOURNAMENT_ID}`).then(r => {
                _timing.end('fetch_tournament');
                return r;
            }).catch(err => {
                _timing.end('fetch_tournament');
                throw err; // still propagate — but see below
            }),
            api('GET', `/api/tournament/${TOURNAMENT_ID}/pending_matches`)
                .catch(() => ({ pending: [] }))
                .then(r => { _timing.end('fetch_pending'); return r; }),
        ]);

        _timing.start('loadTournament_render');
        renderBadge(data.state);
        renderLogo(data.logo_url);
        renderStats(data);
        renderActionArea(data);
        populateConfig(data);
        renderOverviewParticipants(
            data.entrants || [], data.checked_in || [], data.dqs || [], data.state, data.format);
        renderRegistrationRequests(data.registration_requests || [], data.config);

        const pending = pmResult.pending || [];
        renderMatches(data.lobbies || [], pending, data.autocall_matches ?? false, data.swiss ?? null, data.dqs || []);

        if (_forceRefreshSeeds || !_seedsRendered) {
            renderPlayers(
                data.entrants || [], data.checked_in || [], data.dqs || [], data.state, data.format);
            _seedsRendered     = true;
            _forceRefreshSeeds = false;
        }
        _timing.end('loadTournament_render');
        _timing.end('loadTournament_total');
    } catch (err) {
        console.error('[loadTournament]', err);
    } finally {
        _loadTournamentInFlight = false;
    }
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function renderBadge(state) {
    const [cls, label] = BADGE_MAP[state] || ['badge-setup', state];
    document.getElementById('sidebar-badge').innerHTML =
        `<span class="tournament-state-badge ${cls}"><span class="state-dot"></span>${label}</span>`;
}

// ── Stats ─────────────────────────────────────────────────────────────────────

function renderStats(t) {
    const label = (BADGE_MAP[t.state] || ['', t.state])[1];
    document.getElementById('stat-state').textContent     = label;
    document.getElementById('stat-format').textContent    = t.format || '—';
    document.getElementById('stat-entrants').textContent  = t.entrant_count ?? '—';
    document.getElementById('stat-checkedin').textContent = t.checkin_count ?? '—';
    document.getElementById('stat-lobbies').textContent   = t.lobby_count ?? '—';
    document.getElementById('topbar-sub').textContent     = t.date
        ? escapeHtml(t.date) : `${label} · ${t.format}`;
}

// ── Action area ───────────────────────────────────────────────────────────────

function renderActionArea(t) {
    const area    = document.getElementById('action-area');
    const { state, registration_open, format } = t;
    const isSwiss = format === 'swiss' || format === 'swiss filter';

    if (state === 'initialize' || state === 'setup') {
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Setup</div>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:14px;">
                Publish the tournament to make channels visible and open registration.
            </p>
            <div class="action-row">
                <button class="btn btn-success" id="btn-publish">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                        <circle cx="12" cy="12" r="3"/>
                    </svg>
                    Publish Tournament
                </button>
            </div></div>`;
        document.getElementById('btn-publish').onclick = async () => {
            if (await showConfirm('Publish Tournament?',
                'Makes all tournament channels visible and opens registration.'))
                await doAction('progress');
        };

    } else if (state === 'registration') {
        const stagelistReady = t.stagelist_ready ?? t.stagelist_published;
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Registration</div>
            <div class="action-row">
                <button class="btn ${registration_open ? 'btn-toggle-on' : 'btn-toggle-off'}" id="btn-toggle-reg">
                    ${registration_open ? 'Close Registration' : 'Open Registration'}
                </button>
                ${(!isSwiss || !t.config?.randomized_stagelist) ? `
                <button class="btn btn-primary" id="btn-publish-stagelist">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="17 8 12 3 7 8"/>
                        <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                    ${stagelistReady ? '✓ Stagelist Published' : 'Publish Stagelist'}
                </button>` : ''}
                <button class="btn btn-primary" id="btn-start-checkin">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    Start Check-in
                </button>
                <button class="btn btn-danger" id="btn-unpublish">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polyline points="1 4 1 10 7 10"/>
                        <path d="M3.51 15a9 9 0 1 0 .49-3.45"/>
                    </svg>
                    Unpublish
                </button>
            </div></div>`;
        document.getElementById('btn-toggle-reg').onclick = () =>
            doAction(registration_open ? 'close_registration' : 'open_registration');
        document.getElementById('btn-start-checkin').onclick = async () => {
            if (await showConfirm('Start Check-in?',
                'Registration will be locked and players asked to check in.'))
                await doAction('progress');
        };
        const publishBtn = document.getElementById('btn-publish-stagelist');
        if (publishBtn) publishBtn.onclick = async () => {
            if (await showConfirm('Publish Stagelist?',
                'This will post stage embeds to the event-info channel. Any previously published stages will be replaced.'))
                await doAction('publish_stagelist');
        };
        document.getElementById('btn-unpublish').onclick = async () => {
            if (await showConfirm(
                'Unpublish Tournament?',
                'All tournament channels and roles will be permanently removed from Discord. The tournament record will remain so you can republish.',
                'danger'
            ))
                await doAction('unpublish_tournament');
        };

    } else if (state === 'checkin') {
        const stagelistReady = t.stagelist_ready ?? t.stagelist_published;
        area.innerHTML = `<div class="action-panel"><div class="action-panel-title">Check-in</div>
            <div class="action-row">
                <button class="btn ${registration_open ? 'btn-toggle-on' : 'btn-toggle-off'}" id="btn-toggle-reg">
                    ${registration_open ? 'Close Registration' : 'Open Registration'}
                </button>
                <button class="btn btn-secondary" id="btn-ping">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                    </svg>
                    Ping Check-in
                </button>
                ${(!isSwiss || !t.config?.randomized_stagelist) ? `
                <button class="btn btn-primary" id="btn-publish-stagelist">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="17 8 12 3 7 8"/>
                        <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                    ${stagelistReady ? '✓ Stagelist Published' : 'Publish Stagelist'}
                </button>` : ''}
                <button class="btn btn-success" id="btn-start-tournament"
                    ${!stagelistReady ? 'disabled title="Publish the stagelist first"' : ''}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polygon points="5 3 19 12 5 21 5 3"/>
                    </svg>
                    Start Tournament
                </button>
                <button class="btn btn-danger" id="btn-revert-checkin">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polyline points="1 4 1 10 7 10"/>
                        <path d="M3.51 15a9 9 0 1 0 .49-3.45"/>
                    </svg>
                    Revert to Registration
                </button>
            </div>
            ${!stagelistReady
                ? `<p style="font-size:12px;color:var(--yellow);margin-top:8px">
                       ⚠ Stagelist must be published before starting the tournament.
                   </p>`
                : ''}
        </div>`;
        document.getElementById('btn-toggle-reg').onclick = () =>
            doAction(registration_open ? 'close_registration' : 'open_registration');
        document.getElementById('btn-ping').onclick = () => doAction('ping_checkin');
        document.getElementById('btn-start-tournament').onclick = async () => {
            if (!stagelistReady) return;
            if (await showConfirm('Start Tournament?',
                'Players who have not checked in will be removed. This cannot be undone.')) {
                const btn = document.getElementById('btn-start-tournament');
                btn.disabled = true;
                btn.textContent = 'Starting Tournament...';
                await doAction('progress');
            }
        };
        const publishBtn = document.getElementById('btn-publish-stagelist');
        if (publishBtn) publishBtn.onclick = async () => {
            if (await showConfirm('Publish Stagelist?',
                'This will post stage embeds to the event-info channel. Any previously published stages will be replaced.'))
                await doAction('publish_stagelist');
        };
        document.getElementById('btn-revert-checkin').onclick = async () => {
            if (await showConfirm('Revert to Registration?',
                'The check-in channel will be removed and all check-in progress will be lost.', 'danger'))
                await doAction('revert_tournament');
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
        const finalRoundActive = isSwiss && t.swiss?.final_round_active;
        const nextBtn = isSwiss && t.swiss && !finalRoundActive
            ? `<button class="btn btn-success" id="btn-next-round">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                Start Round ${t.swiss.current_round + 1}
               </button>`
            : '';
        if (finalRoundActive) {
            _nextRoundInFlight = false;
        }
        const wrapUpHtml = finalRoundActive ? `
            <div class="action-panel" style="margin-top:8px">
                <div class="action-panel-title">Wrap Up</div>
                <p style="color:var(--text-secondary);font-size:13px;margin-bottom:14px;">
                    Final round is underway. Once all matches complete the event will end automatically.
                </p>
                <div class="action-row">
                    <button class="btn btn-primary" id="btn-post-results" ${t.swiss.active_matches > 0 ? 'disabled title="Waiting for all matches to finish"' : ''}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="17 8 12 3 7 8"/>
                            <line x1="12" y1="3" x2="12" y2="15"/>
                        </svg>
                        Post Results
                    </button>
                    <button class="btn btn-danger" id="btn-finalize" ${t.swiss.active_matches > 0 ? 'disabled title="Waiting for all matches to finish"' : ''}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                            <path d="M10 11v6M14 11v6"/>
                        </svg>
                        Finalize &amp; Remove Channels
                    </button>
                </div>
            </div>` : '';

        area.innerHTML = `
            ${roundHtml}
            <div class="action-panel">
                <div class="action-panel-title">Controls</div>
                <div class="action-row">
                    ${nextBtn}
                    ${(!isSwiss || !t.config?.randomized_stagelist) ? `<button class="btn btn-primary btn-sm" id="btn-publish-stagelist">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="17 8 12 3 7 8"/>
                            <line x1="12" y1="3" x2="12" y2="15"/>
                        </svg>
                        Publish Stagelist to Discord
                    </button>` : ''}
                </div>
            </div>
            ${wrapUpHtml}
            <div class="action-panel danger-zone-panel">
                <div class="danger-zone-header" id="danger-zone-toggle">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                        <line x1="12" y1="9" x2="12" y2="13"/>
                        <line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    <span>Danger Zone</span>
                    <svg class="danger-zone-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </div>
                <div class="danger-zone-body" id="danger-zone-body" ${_dangerZoneOpen ? '' : 'hidden'}>
                    <div class="action-row" style="padding:14px 18px">
                        <button class="btn btn-danger" id="btn-revert-active">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <polyline points="1 4 1 10 7 10"/>
                                <path d="M3.51 15a9 9 0 1 0 .49-3.45"/>
                            </svg>
                            Revert to Check-in
                        </button>
                    </div>
                </div>
            </div>`;

        if (finalRoundActive) {
            const postBtn = document.getElementById('btn-post-results');
            if (postBtn) postBtn.onclick = async () => {
                if (await showConfirm('Post Results?', 'This will post the final standings to the results channel.', 'warning'))
                    await doAction('post_results');
            };
            const finalizeBtn = document.getElementById('btn-finalize');
            if (finalizeBtn) finalizeBtn.onclick = async () => {
                if (await showConfirm('Finalize Tournament?', 'All lobby channels and tournament roles will be permanently removed from Discord.', 'danger'))
                    await doAction('progress');
            };
        }
        

        const chevron = document.querySelector('.danger-zone-chevron');
        if (chevron) chevron.style.transform = _dangerZoneOpen ? 'rotate(180deg)' : '';
        const nextRoundBtn = document.getElementById('btn-next-round');
        if (nextRoundBtn) {
            if (_nextRoundInFlight) nextRoundBtn.disabled = true;
            nextRoundBtn.onclick = async () => {
                _nextRoundInFlight = true;
                nextRoundBtn.disabled = true;
                nextRoundBtn.textContent = 'Starting...';
                await doAction('next_round');
                _nextRoundInFlight = false;
            };
        }

        document.getElementById('danger-zone-toggle').onclick = () => {
            const body    = document.getElementById('danger-zone-body');
            const chevron = document.querySelector('.danger-zone-chevron');
            _dangerZoneOpen = !_dangerZoneOpen;
            body.hidden   = !_dangerZoneOpen;
            chevron.style.transform = _dangerZoneOpen ? 'rotate(180deg)' : '';
        };
        const activePublishBtn = document.getElementById('btn-publish-stagelist');
        if (activePublishBtn) activePublishBtn.onclick = async () => {
            if (await showConfirm('Publish Stagelist?',
                'This will post stage embeds to the event-info channel. Any previously published stages will be replaced.'))
                await doAction('publish_stagelist');
        };
        document.getElementById('btn-revert-active').onclick = async () => {
            const extraHtml = `
                <div style="margin-top:12px">
                    <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px">
                        This will close all lobby channels and return the tournament to check-in.<br>
                        Type <strong style="color:var(--text-primary)">revert</strong> to confirm:
                    </div>
                    <input class="field-input" id="revert-confirm-input"
                        placeholder="revert" autocomplete="off" style="width:100%">
                    <div id="revert-confirm-error"
                        style="font-size:12px;color:var(--red);margin-top:6px;display:none">
                        Text does not match.
                    </div>
                </div>`;
            document.getElementById('modal-title').textContent  = 'Revert to Check-in?';
            document.getElementById('modal-desc').textContent   = 'All active lobby channels will be deleted. This cannot be undone.';
            document.getElementById('modal-extra').innerHTML    = extraHtml;
            document.getElementById('modal-icon').className     = 'modal-icon danger';
            const confirmBtn = document.getElementById('modal-confirm');
            confirmBtn.className = 'modal-confirm danger';
            document.getElementById('modal-backdrop').hidden = false;
            document.getElementById('revert-confirm-input').focus();

            const confirmed = await new Promise(resolve => {
                confirmBtn.onclick = () => {
                    const typed = document.getElementById('revert-confirm-input').value.trim().toLowerCase();
                    if (typed !== 'revert') {
                        document.getElementById('revert-confirm-error').style.display = '';
                        return;
                    }
                    document.getElementById('modal-backdrop').hidden = true;
                    document.getElementById('modal-extra').innerHTML = '';
                    resolve(true);
                };
                document.getElementById('modal-cancel').onclick = () => {
                    closeModal();
                    resolve(false);
                };
            });
            if (confirmed) await doAction('revert_tournament');
        };

    } else if (state === 'finished') {
        area.innerHTML = `<div class="action-panel">
            <div class="action-panel-title">Wrap Up</div>
            <p style="color:var(--text-secondary);font-size:13px;margin-bottom:14px;">
                All matches are complete. Post results to the results channel, then finalize when ready to tear down Discord channels.
            </p>
            <div class="action-row">
                <button class="btn btn-primary" id="btn-post-results">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="17 8 12 3 7 8"/>
                        <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                    Post Results
                </button>
                <button class="btn btn-danger" id="btn-finalize">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                        <path d="M10 11v6M14 11v6"/>
                    </svg>
                    Finalize &amp; Remove Channels
                </button>
            </div>
        </div>`;
        document.getElementById('btn-post-results').onclick = async () => {
            if (await showConfirm('Post Results?', 'This will post the final standings to the results channel.', 'warning'))
                await doAction('post_results');
        };
        document.getElementById('btn-finalize').onclick = async () => {
            if (await showConfirm('Finalize Tournament?', 'All lobby channels and tournament roles will be permanently removed from Discord.', 'danger'))
                await doAction('progress');
        };

    } else {
        area.innerHTML = `<div class="action-panel">
            <p style="color:var(--text-muted);font-size:13px;">No actions available in this state.</p>
        </div>`;
    }
}

// ── Config ────────────────────────────────────────────────────────────────────

function populateConfig(t) {
    document.getElementById('cfg-name').value               = t.name  || '';
    document.getElementById('cfg-date').value               = t.date  || '';
    document.getElementById('cfg-approved').checked         = t.config?.approved_registration ?? false;
    document.getElementById('cfg-random-stage').checked     = t.config?.randomized_stagelist  ?? false;
    document.getElementById('cfg-display-entrants').checked = t.config?.display_entrants       ?? false;

    // Image previews
    const bannerPreview = document.getElementById('cfg-banner-preview');
    if (bannerPreview) {
        bannerPreview.innerHTML = t.banner_url
            ? `<img src="${escapeHtml(t.banner_url)}" style="width:100%;max-height:120px;object-fit:cover;border-radius:6px;display:block">`
            : `<div style="font-size:12px;color:var(--text-muted);font-style:italic">No banner uploaded</div>`;
    }
    const logoPreview = document.getElementById('cfg-logo-preview');
    if (logoPreview) {
        logoPreview.innerHTML = t.logo_url
            ? `<img src="${escapeHtml(t.logo_url)}" style="width:64px;height:64px;object-fit:cover;border-radius:6px;display:block">`
            : `<div style="font-size:12px;color:var(--text-muted);font-style:italic">No logo uploaded</div>`;
    }
    const rankedRow = document.getElementById('cfg-ranked-row');
    if (rankedRow) {
        rankedRow.hidden = !t.ranked_compatible;
        document.getElementById('cfg-ranked').checked = t.ranked_reporting ?? false;
    }

    // Staggered start — only show for Swiss formats
    const isSwissFmt = (t.format === 'swiss' || t.format === 'swiss filter');
    const staggeredRow     = document.getElementById('cfg-staggered-row');
    const staggeredThRow   = document.getElementById('cfg-staggered-threshold-row');
    const staggeredCheck   = document.getElementById('cfg-staggered');
    const staggeredThInput = document.getElementById('cfg-staggered-threshold');

    if (staggeredRow) staggeredRow.style.display     = isSwissFmt ? '' : 'none';
    if (staggeredThRow) staggeredThRow.style.display  = isSwissFmt && t.config?.staggered_start ? '' : 'none';
    if (staggeredCheck) staggeredCheck.checked         = t.config?.staggered_start ?? false;
    if (staggeredThInput) staggeredThInput.value       = t.config?.staggered_start_threshold ?? 16;

    if (staggeredCheck) {
        staggeredCheck.onchange = () => {
            if (staggeredThRow) staggeredThRow.style.display = staggeredCheck.checked ? '' : 'none';
        };
    }
}

// ── Registration requests ─────────────────────────────────────────────────────

function renderRegistrationRequests(requests, config) {
    const section = document.getElementById('registration-requests-section');
    if (!section) return;
    if (!config?.approved_registration || !requests?.length) {
        section.hidden = true;
        return;
    }
    section.hidden = false;
    document.getElementById('requests-count').textContent = requests.length;
    const list = document.getElementById('requests-list');
    list.innerHTML = requests.map(r => `
        <div class="request-row">
            <div class="request-player">
                ${r.avatar_url
                    ? `<img src="${escapeHtml(r.avatar_url)}" class="request-avatar" alt="">`
                    : `<div class="request-avatar-placeholder">${escapeHtml(r.name[0] || '?')}</div>`}
                <span class="request-name">${escapeHtml(r.name)}</span>
            </div>
            <div class="request-actions">
                <button class="btn btn-success btn-sm"
                    onclick="approveRegistration('${escapeHtml(r.discord_id)}')">Approve</button>
                <button class="btn btn-danger btn-sm"
                    onclick="denyRegistration('${escapeHtml(r.discord_id)}','${escapeHtml(r.name)}')">Deny</button>
            </div>
        </div>`).join('');
}

async function approveRegistration(discordId) {
    await doAction('approve_registration', { discord_id: discordId });
}

async function denyRegistration(discordId, name) {
    const extra = `
        <div style="margin-top:12px">
            <label style="font-size:12px;color:var(--text-muted)">Reason (optional)</label>
            <input class="field-input" id="deny-reason" placeholder="e.g. Not eligible"
                style="width:100%;margin-top:4px">
        </div>`;
    if (await showConfirm('Deny Registration?',
        `Deny registration for <strong>${escapeHtml(name)}</strong>?`, 'danger', extra)) {
        const reason = document.getElementById('deny-reason')?.value?.trim() || '';
        await doAction('deny_registration', { discord_id: discordId, reason });
    }
}

function renderLogo(logoUrl) {
    const el = document.getElementById('sidebar-logo');
    if (!el) return;
    if (logoUrl) {
        el.innerHTML = `<img src="${escapeHtml(logoUrl)}?v=${Date.now()}"
            style="height:100%;width:auto;border-radius:10px;display:block;object-fit:contain;max-height:100px"
            alt="">`;
    } else {
        el.innerHTML = '';
    }
}

async function uploadImage(file, type) {
    const statusEl = document.getElementById(`cfg-${type}-status`);
    if (statusEl) { statusEl.textContent = 'Uploading...'; statusEl.style.color = 'var(--text-muted)'; }
    try {
        const form = new FormData();
        form.append('image', file);
        const resp = await fetch(`/api/tournament/${TOURNAMENT_ID}/upload/${type}`, {
            method: 'POST',
            body:   form,
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Upload failed');
        }
        if (statusEl) { statusEl.textContent = 'Uploaded ✓'; statusEl.style.color = 'var(--green)'; }
        setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
        await loadTournament({ force: true });
    } catch (err) {
        if (statusEl) { statusEl.textContent = `Failed: ${err.message}`; statusEl.style.color = 'var(--red)'; }
        showToast(`Upload failed: ${err.message}`, 'error');
    }
}

async function deleteImage(type) {
    try {
        await fetch(`/api/tournament/${TOURNAMENT_ID}/upload/${type}`, { method: 'DELETE' });
        showToast(`${type} removed`, 'success');
        await loadTournament({ force: true });
    } catch (err) {
        showToast(`Failed: ${err.message}`, 'error');
    }
}