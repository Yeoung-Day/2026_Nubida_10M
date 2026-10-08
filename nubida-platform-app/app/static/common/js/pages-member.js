// ============================================================
// 누비다플랫폼 v2 Premium — 회원/멤버십 페이지 스크립트
// API: member links, tokens
// ============================================================

// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: HTML 설정 =====
function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html || '';
}

// ===== Helper: 로딩 표시 =====
function showLoading(containerId) {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = '<div class="loading-spinner" style="margin:40px auto"></div>';
}

// ===== Helper: 상태 배지 =====
function statusBadge(status) {
    const map = {
        'active':    ['success', '활성'],
        'inactive':  ['warning', '비활성'],
        'pending':   ['warning', '대기중'],
        'expired':   ['danger', '만료'],
        'linked':    ['success', '연결됨'],
        'unlinked':  ['info', '연결안됨'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 날짜 포맷 =====
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('ko-KR', {
        year: 'numeric', month: '2-digit', day: '2-digit'
    });
}

function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('ko-KR', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}

// ============================================================
// 내 토큰 조회
// ============================================================
async function getMyToken() {
    try {
        const res = await apiGet('/member/token/my');
        const container = document.getElementById('myTokenContainer');
        if (!container) return;

        if (!res || !res.data) {
            container.innerHTML = '<p class="empty-state" style="padding:var(--space-6)">발급된 토큰이 없습니다.</p>';
            return;
        }

        const token = res.data.token || res.data;
        const expiresAt = res.data.expires_at || res.data.expiresAt || null;

        container.innerHTML = `
            <div class="token-display" style="
                background:var(--bg-canvas);
                border:1px solid var(--border-subtle);
                border-radius:10px;
                padding:var(--space-5);
                margin-bottom:var(--space-4);
            ">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-3)">
                    <strong style="font-size:var(--text-sm);color:var(--text-secondary)">내 멤버십 토큰</strong>
                    <button onclick="copyToken('${token.replace(/'/g, "\\'")}')" class="btn btn-sm btn-outline" style="font-size:12px">📋 복사</button>
                </div>
                <div style="
                    font-family:var(--font-mono, monospace);
                    font-size:13px;
                    background:var(--bg-white);
                    border:1px solid var(--border-default);
                    border-radius:6px;
                    padding:var(--space-3) var(--space-4);
                    word-break:break-all;
                    color:var(--text-primary);
                    user-select:all;
                ">${esc(token)}</div>
                ${expiresAt ? `<div style="margin-top:var(--space-2);font-size:12px;color:var(--text-tertiary)">⏰ 만료: ${formatDateTime(expiresAt)}</div>` : ''}
            </div>
        `;
    } catch(e) {
        console.error('getMyToken error:', e);
        const container = document.getElementById('myTokenContainer');
        if (container) {
            container.innerHTML = '<p style="color:var(--danger);padding:var(--space-4)">토큰 정보를 불러올 수 없습니다.</p>';
        }
    }
}

// ===== 토큰 복사 =====
function copyToken(token) {
    if (!token) return;
    navigator.clipboard.writeText(token).then(() => {
        showAlert('토큰이 클립보드에 복사되었습니다.', 'success');
    }).catch(() => {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = token;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showAlert('토큰이 클립보드에 복사되었습니다.', 'success');
    });
}

// ============================================================
// 멤버 링크 관리
// ============================================================
let _memberLinks = [];

async function loadMemberLinks() {
    try {
        const res = await apiGet('/member/links');
        const links = res?.data || res || [];
        if (!Array.isArray(links)) {
            setHtml('memberLinksContainer', '<p class="empty-state" style="padding:var(--space-8)">연결된 멤버가 없습니다.</p>');
            _memberLinks = [];
            return;
        }
        _memberLinks = links;

        const container = document.getElementById('memberLinksContainer');
        if (!container) return;

        if (links.length === 0) {
            container.innerHTML = '<p class="empty-state" style="padding:var(--space-8)">연결된 멤버가 없습니다. 멤버십 토큰을 추가해보세요.</p>';
            return;
        }

        // Render as cards or table
        let html = '';
        links.forEach(link => {
            const id = link.id || link.link_id;
            const name = link.name || link.member_name || link.linked_name || '(이름 없음)';
            const role = link.role || link.member_role || link.relationship || '-';
            const status = link.status || 'active';
            const createdAt = link.created_at || link.createdAt || '';
            const token = link.token || '';

            html += `
                <div class="member-link-item" data-id="${id}" style="
                    display:flex;
                    align-items:center;
                    justify-content:space-between;
                    padding:var(--space-4) var(--space-5);
                    background:var(--bg-white);
                    border:1px solid var(--border-subtle);
                    border-radius:10px;
                    margin-bottom:var(--space-3);
                    transition:all 150ms ease;
                ">
                    <div style="flex:1;min-width:0">
                        <div style="display:flex;align-items:center;gap:var(--space-3)">
                            <strong style="font-size:var(--text-base)">${esc(name)}</strong>
                            ${statusBadge(status)}
                        </div>
                        <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:var(--space-1)">
                            <span style="font-size:12px;color:var(--text-tertiary)">🎭 ${esc(role)}</span>
                            ${createdAt ? `<span style="font-size:12px;color:var(--text-tertiary)">📅 ${formatDate(createdAt)}</span>` : ''}
                        </div>
                    </div>
                    <div style="display:flex;gap:var(--space-2);flex-shrink:0;margin-left:var(--space-3)">
                        ${token ? `<button onclick="copyToken('${token.replace(/'/g, "\\'")}')" class="btn btn-sm btn-outline" title="토큰 복사" style="font-size:11px;padding:4px 8px">📋</button>` : ''}
                        <button onclick="removeMemberLink('${id}')" class="btn btn-sm btn-danger" title="연결 해제" style="font-size:11px;padding:4px 8px">✕</button>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch(e) {
        console.error('loadMemberLinks error:', e);
        const container = document.getElementById('memberLinksContainer');
        if (container) {
            container.innerHTML = '<p style="color:var(--danger);padding:var(--space-4)">멤버 링크를 불러올 수 없습니다.</p>';
        }
    }
}

// ===== 멤버 링크 추가 =====
async function addMemberLink(token, relationship) {
    if (!token || !token.trim()) {
        showAlert('멤버십 토큰을 입력해주세요.', 'warning');
        return;
    }

    const btn = document.getElementById('addLinkBtn');
    if (btn) { btn.disabled = true; btn.textContent = '처리 중...'; }

    try {
        const payload = { token: token.trim() };
        if (relationship && relationship.trim()) {
            payload.relationship = relationship.trim();
        }

        const res = await apiPost('/member/link', payload);

        showAlert('멤버가 성공적으로 연결되었습니다!', 'success');

        // Reset form
        const tokenInput = document.getElementById('linkTokenInput');
        if (tokenInput) tokenInput.value = '';
        const relInput = document.getElementById('linkRelationshipInput');
        if (relInput) relInput.value = '';

        // Reload links
        await loadMemberLinks();
    } catch(e) {
        showAlert('멤버 연결 실패: ' + (e.message || '오류가 발생했습니다.'), 'danger');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '연결하기'; }
    }
}

// ===== 멤버 링크 제거 =====
async function removeMemberLink(linkId) {
    if (!linkId) return;

    if (!confirm('정말로 이 멤버 연결을 해제하시겠습니까?')) return;

    try {
        await apiDelete(`/member/link/${linkId}`);
        showAlert('멤버 연결이 해제되었습니다.', 'success');
        await loadMemberLinks();
    } catch(e) {
        showAlert('연결 해제 실패: ' + (e.message || '오류가 발생했습니다.'), 'danger');
    }
}

// ============================================================
// 페이지 초기화
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const page = window.location.pathname.split('/').pop().replace('.html', '');

    // Only run auth check on pages that need it (not register)
    if (page !== 'register') {
        requireAuth();
        renderSidebarUser();
    }

    switch(page) {
        case 'member-token':
        case 'member_token':
            getMyToken();
            break;
        case 'member-links':
        case 'member_links':
            loadMemberLinks();
            break;
        case 'member-manage':
        case 'member_manage':
            getMyToken();
            loadMemberLinks();
            break;
    }
});
