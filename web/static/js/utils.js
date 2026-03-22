// ── Shared utilities ──────────────────────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res  = await fetch(path, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

// Toast
let _toastTimer;
function showToast(msg, type = 'success') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className   = `show ${type}`;
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { t.className = ''; }, 3000);
}

// Confirm modal
let _confirmResolve = null;

function closeModal() {
    document.getElementById('modal-backdrop').hidden = true;
    const extra = document.getElementById('modal-extra');
    if (extra) extra.innerHTML = '';
    if (_confirmResolve) { _confirmResolve(false); _confirmResolve = null; }
}

function showConfirm(title, desc, type = 'warning', extraHtml = '') {
    return new Promise(resolve => {
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-desc').textContent  = desc;
        const extra = document.getElementById('modal-extra');
        if (extra) extra.innerHTML = extraHtml;
        document.getElementById('modal-icon').className    = `modal-icon ${type}`;
        const confirmBtn = document.getElementById('modal-confirm');
        confirmBtn.className = `modal-confirm ${type}`;
        document.getElementById('modal-backdrop').hidden = false;
        _confirmResolve = resolve;
        confirmBtn.onclick = () => {
            document.getElementById('modal-backdrop').hidden = true;
            if (extra) extra.innerHTML = '';
            resolve(true); _confirmResolve = null;
        };
    });
}

// Badge map (shared)
const BADGE_MAP = {
    active:       ['badge-active',  'Active'],
    registration: ['badge-reg',     'Registration'],
    checkin:      ['badge-checkin', 'Check-in'],
    setup:        ['badge-setup',   'Setup'],
    initialize:   ['badge-setup',   'Initializing'],
    finished:     ['badge-finished','Finished'],
    finalized:    ['badge-finished','Finalized'],
};

// Avatar setup
function initAvatar(username, avatarUrl) {
    const wrap = document.getElementById('user-avatar-wrap');
    if (!wrap) return;
    if (avatarUrl) {
        const img = document.createElement('img');
        img.src = avatarUrl; img.className = 'user-avatar'; img.alt = '';
        wrap.appendChild(img);
    } else {
        const ph = document.createElement('div');
        ph.className = 'user-avatar-placeholder';
        ph.textContent = (username || '?').charAt(0).toUpperCase();
        wrap.appendChild(ph);
    }
}

// Wire up cancel button and backdrop click for the modal
document.addEventListener('DOMContentLoaded', () => {
    const cancelBtn  = document.getElementById('modal-cancel');
    const backdrop   = document.getElementById('modal-backdrop');
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (backdrop)  backdrop.addEventListener('click', e => {
        if (e.target === backdrop) closeModal();
    });
});