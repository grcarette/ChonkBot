// ── stagelist.js ──────────────────────────────────────────────────────────────
// Stagelist management and stage browser panel.

let browserAllStages  = [];
let browserSelected   = new Set();
let currentStageCodes = new Set();

// ── Helpers ───────────────────────────────────────────────────────────────────

function imgurDirectUrl(imgurUrl) {
    if (!imgurUrl) return '';
    const lastSegment = imgurUrl.split('/').pop();
    const lastHyphen  = lastSegment.lastIndexOf('-');
    const imageId     = lastHyphen !== -1 ? lastSegment.slice(lastHyphen + 1) : lastSegment;
    return imageId ? `https://i.imgur.com/${imageId}.jpg` : '';
}

// ── Stagelist ─────────────────────────────────────────────────────────────────

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
            ${thumbUrl
                ? `<img class="stage-card-thumb" src="${thumbUrl}" alt="${escapeHtml(s.name)}"
                       onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
                : ''}
            <div class="stage-card-thumb-placeholder" ${thumbUrl ? 'style="display:none"' : ''}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".4">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                </svg>
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
                <button class="stage-remove-btn" title="Remove"
                    onclick="removeStageFromList('${escapeHtml(s.code)}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <line x1="18" y1="6" x2="6" y2="18"/>
                        <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
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
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function addStageByCode() {
    const raw = document.getElementById('stagelist-input').value.trim();
    if (!raw) return;
    try {
        await api('POST', `/api/tournament/${TOURNAMENT_ID}/stages`, { codes: raw });
        showToast('Stage(s) added', 'success');
        document.getElementById('stagelist-input').value = '';
        await loadStagelist();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ── Stage browser ─────────────────────────────────────────────────────────────

async function loadBrowser() {
    const mode = document.getElementById('browser-mode-filter').value;
    try {
        const url  = '/api/stages/browse' + (mode ? `?mode=${encodeURIComponent(mode)}` : '');
        const data = await api('GET', url);
        browserAllStages = data.stages || [];
        // Shuffle for variety
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
    if (!filtered.length) {
        wrap.innerHTML = `<div class="stagelist-empty">No stages found.</div>`;
        return;
    }

    const grid = document.createElement('div');
    grid.className = 'browser-grid';

    for (const s of filtered) {
        const alreadyAdded = currentStageCodes.has(s.code);
        const isSelected   = browserSelected.has(s.code);
        const thumbUrl     = imgurDirectUrl(s.imgur_url);
        const creator      = s.creators?.length ? s.creators[0].username : '';

        const card = document.createElement('div');
        card.className = `browser-card${isSelected ? ' selected' : ''}${alreadyAdded ? ' already-added' : ''}`;
        card.innerHTML = `
            ${thumbUrl
                ? `<img class="browser-card-thumb" src="${thumbUrl}" alt=""
                       onerror="this.style.display='none'">`
                : `<div class="browser-card-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted)">
                       <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".4">
                           <rect x="3" y="3" width="18" height="18" rx="2"/>
                           <circle cx="8.5" cy="8.5" r="1.5"/>
                           <polyline points="21 15 16 10 5 21"/>
                       </svg>
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
    } catch (err) {
        showToast(err.message, 'error');
    }
}