// ============================================================
// 누비다플랫폼 v2 Premium — 본사관리(Headquarters) 페이지 스크립트
// API 연동: 대시보드, 지사, 사용자, 결제, 통계 등
// ============================================================

// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: 테이블 렌더링 =====
function renderTable(tbodyId, data, columns) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    if (!data || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-tertiary);padding:24px">데이터가 없습니다.</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(row => {
        const cells = columns.map(col => {
            const val = col.render ? col.render(row[col.key]) : (row[col.key] ?? '-');
            return `<td>${val}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');
}

// ===== Helper: select 옵션 렌더링 =====
function renderSelectOptions(selectId, items, valueKey, labelKey, placeholder) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = '';
    if (placeholder) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = placeholder;
        sel.appendChild(opt);
    }
    items.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item[valueKey];
        opt.textContent = item[labelKey];
        sel.appendChild(opt);
    });
}

// ===== Helper: 상태 배지 =====
function statusBadge(status) {
    const map = {
        'active':    ['success', '활성'],
        'inactive':  ['warning', '비활성'],
        'pending':   ['warning', '대기'],
        'completed': ['success', '완료'],
        'failed':    ['danger', '실패'],
        'published': ['success', '발행'],
        'draft':     ['warning', '임시'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 페이지네이션 =====
function renderPaginationWidget(containerId, pagination, pageFn) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!pagination || pagination.total_pages <= 1) {
        container.innerHTML = '';
        return;
    }
    const { page, total_pages } = pagination;
    let html = '<div class="pagination">';
    if (page > 1) html += `<button class="btn btn-sm" onclick="${pageFn}(${page - 1})">‹</button>`;
    for (let i = Math.max(1, page - 2); i <= Math.min(total_pages, page + 2); i++) {
        html += `<button class="btn btn-sm ${i === page ? 'btn-primary' : 'btn-outline'}" onclick="${pageFn}(${i})">${i}</button>`;
    }
    if (page < total_pages) html += `<button class="btn btn-sm" onclick="${pageFn}(${page + 1})">›</button>`;
    html += '</div>';
    container.innerHTML = html;
}

// ===== Helper: 모달 HTML 템플릿 =====
function modalHtml(id, title, bodyContent) {
    return `
    <div class="modal-overlay" id="${id}" onclick="if(event.target===this)closeModal('${id}')">
        <div class="modal">
            <div class="modal-header">
                <h3>${title}</h3>
            </div>
            <div class="modal-body">
                ${bodyContent}
            </div>
        </div>
    </div>`;
}

// ===== Helper: 확인 대화상자 =====
function confirmDialog(message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay active';
        overlay.style.display = 'flex';
        overlay.innerHTML = `
        <div class="modal" style="max-width:400px">
            <div class="modal-header"><h3>확인</h3></div>
            <div class="modal-body">
                <p style="margin-bottom:20px">${message}</p>
                <div style="display:flex;gap:8px;justify-content:flex-end">
                    <button class="btn btn-outline" id="confirmCancel">취소</button>
                    <button class="btn btn-danger" id="confirmOk">확인</button>
                </div>
            </div>
        </div>`;
        document.body.appendChild(overlay);
        document.getElementById('confirmOk').onclick = () => { overlay.remove(); resolve(true); };
        document.getElementById('confirmCancel').onclick = () => { overlay.remove(); resolve(false); };
        overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    });
}

document.addEventListener('DOMContentLoaded', () => {
    requireAuth();
    renderSidebarUser();
    initPage();
});

function initPage() {
    const page = window.location.pathname.split('/').pop().replace('.html', '');
    switch(page) {
        case 'dashboard': loadDashboard(); break;
        case 'branches': loadBranches(); break;
        case 'users': loadUsers(); break;
        case 'payments': loadPayments(); break;
        case 'notices': loadNotices(); break;
        case 'statistics': loadStatistics(); break;
        case 'settings': loadSettings(); break;
        case 'portfolio': loadPortfolio(); break;
        case 'videos': loadVideos(); break;
        case 'classroom': loadClassroom(); break;
        case 'backups': loadBackups(); break;
    }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        const stats = await apiGet('/headquarters/dashboard/stats');
        const s = stats?.data || stats;
        setText('totalBranches', formatNumber(s.total_branches));
        setText('totalUsers', formatNumber(s.total_users));
        setText('todaySignups', formatNumber(s.today_signups));
        setText('monthlyRevenue', formatCurrency(s.monthly_revenue));

        if (s.branches) renderTable('branchStatusBody', s.branches, [
            { key: 'name', label: '지사' },
            { key: 'manager', label: '관리자' },
            { key: 'user_count', label: '사용자 수', render: v => formatNumber(v) },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
        ]);

        if (s.recent_activities) renderTable('recentActivityBody', s.recent_activities, [
            { key: 'content', label: '내용' },
            { key: 'username', label: '사용자' },
            { key: 'created_at', label: '시간', render: v => formatDateTime(v) },
        ]);
    } catch(e) {
        console.error('Dashboard load error:', e);
    }
}

// ============================================================
// 사용자 관리
// ============================================================
let currentUserPage = 1;
let userSearchQuery = '';
let userRoleFilter = '';

async function loadUsers() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    // Replace placeholder content with real UI
    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h2>사용자 관리</h2>
                <button class="btn btn-primary btn-sm" onclick="showUserCreateModal()">+ 사용자 추가</button>
            </div>
            <div class="card-body">
                <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
                    <input type="text" id="userSearch" placeholder="검색어 입력..." class="form-input" style="max-width:280px;flex:1" oninput="onUserSearchChange()">
                    <select id="userRoleFilter" class="form-select" style="max-width:160px" onchange="onUserFilterChange()">
                        <option value="">전체 역할</option>
                        <option value="admin">관리자</option>
                        <option value="branch_admin">에듀케어</option>
                        <option value="branch_manager">지사 매니저</option>
                        <option value="director">원장</option>
                        <option value="teacher">강사</option>
                        <option value="student">학생</option>
                        <option value="parent">학부모</option>
                    </select>
                </div>
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>이름</th>
                                <th>아이디</th>
                                <th>이메일</th>
                                <th>전화번호</th>
                                <th>역할</th>
                                <th>지사</th>
                                <th>상태</th>
                                <th>관리</th>
                            </tr>
                        </thead>
                        <tbody id="userTableBody"><tr><td colspan="9" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
                <div id="userPagination" style="display:flex;justify-content:center;margin-top:16px"></div>
            </div>
            ${modalHtml('userModal', '', '')}
            ${modalHtml('userDeleteModal', '사용자 삭제', '<p id="userDeleteMessage">정말 삭제하시겠습니까?</p><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn btn-outline" onclick="closeModal(\'userDeleteModal\')">취소</button><button class="btn btn-danger" id="userDeleteConfirmBtn">삭제</button></div>')}
        `;
    }

    await fetchUsers();
}

function onUserSearchChange() {
    userSearchQuery = document.getElementById('userSearch')?.value || '';
    currentUserPage = 1;
    fetchUsers();
}

function onUserFilterChange() {
    userRoleFilter = document.getElementById('userRoleFilter')?.value || '';
    currentUserPage = 1;
    fetchUsers();
}

async function fetchUsers() {
    const tbody = document.getElementById('userTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:24px">로딩 중...</td></tr>';

    try {
        let path = `/headquarters/users?page=${currentUserPage}`;
        if (userSearchQuery) path += `&search=${encodeURIComponent(userSearchQuery)}`;
        if (userRoleFilter) path += `&role=${encodeURIComponent(userRoleFilter)}`;

        const res = await apiGet(path);
        const users = res.items || res.data || [];
        const pagination = res.pagination || { page: currentUserPage, total_pages: 1, total: users.length };

        renderTable('userTableBody', users, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'name', render: v => esc(v || '-') },
            { key: 'username', render: v => esc(v || '-') },
            { key: 'email', render: v => esc(v || '-') },
            { key: 'phone', render: v => esc(v || '-') },
            { key: 'role', render: v => esc(v || '-') },
            { key: 'branch_name', render: v => esc(v || '-') },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'id', render: (v, row) => `
                <div style="display:flex;gap:4px">
                    <button class="btn btn-sm btn-outline" onclick="showUserEditModal(${v})">수정</button>
                    <button class="btn btn-sm btn-danger" onclick="showUserDeleteModal(${v})">삭제</button>
                </div>
            ` },
        ]);

        renderPaginationWidget('userPagination', pagination, 'goToUserPage');
    } catch(e) {
        console.error('Users fetch error:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:24px;color:var(--text-danger)">오류: ${e.message}</td></tr>`;
    }
}

function goToUserPage(page) {
    currentUserPage = page;
    fetchUsers();
}

async function showUserCreateModal() {
    const modal = document.getElementById('userModal');
    if (!modal) return;
    const body = modal.querySelector('.modal-body');
    if (!body) return;

    let branchOptions = '<option value="">선택 안함</option>';
    try {
        const branches = await apiGet('/headquarters/branches?page=1&per_page=100');
        const items = branches.items || branches.data || [];
        items.forEach(b => {
            branchOptions += `<option value="${b.id}">${esc(b.name)}</option>`;
        });
    } catch(e) { /* ignore */ }

    body.innerHTML = `
        <form id="userForm" onsubmit="return false">
            <input type="hidden" id="userId" value="">
            <div class="form-group">
                <label class="form-label">아이디 *</label>
                <input type="text" id="formUsername" class="form-input" required>
            </div>
            <div class="form-group">
                <label class="form-label">비밀번호 *</label>
                <input type="password" id="formPassword" class="form-input" required>
            </div>
            <div class="form-group">
                <label class="form-label">이름 *</label>
                <input type="text" id="formName" class="form-input" required>
            </div>
            <div class="form-group">
                <label class="form-label">이메일</label>
                <input type="email" id="formEmail" class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">전화번호</label>
                <input type="text" id="formPhone" class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">역할 *</label>
                <select id="formRole" class="form-select" required>
                    <option value="">선택하세요</option>
                    <option value="admin">관리자</option>
                        <option value="branch_admin">에듀케어</option>
                    <option value="branch_manager">지사 매니저</option>
                    <option value="director">원장</option>
                    <option value="teacher">강사</option>
                    <option value="student">학생</option>
                    <option value="parent">학부모</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">지사</label>
                <select id="formBranch" class="form-select">
                    ${branchOptions}
                </select>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
                <button type="button" class="btn btn-outline" onclick="closeModal('userModal')">취소</button>
                <button type="submit" class="btn btn-primary" id="userFormSubmit">생성</button>
            </div>
        </form>
    `;

    document.getElementById('userId').value = '';
    document.getElementById('formPassword').required = true;
    document.getElementById('userFormSubmit').textContent = '생성';

    const form = document.getElementById('userForm');
    form.onsubmit = async (e) => {
        e.preventDefault();
        await saveUser();
    };

    modal.querySelector('h3').textContent = '사용자 추가';
    openModal('userModal');
}

async function showUserEditModal(userId) {
    const modal = document.getElementById('userModal');
    if (!modal) return;

    try {
        const res = await apiGet(`/headquarters/users/${userId}`);
        const user = res.data || res.user || res;

        let branchOptions = '<option value="">선택 안함</option>';
        try {
            const branches = await apiGet('/headquarters/branches?page=1&per_page=100');
            const items = branches.items || branches.data || [];
            items.forEach(b => {
                const selected = (b.id === user.branch_id) ? ' selected' : '';
                branchOptions += `<option value="${b.id}"${selected}>${esc(b.name)}</option>`;
            });
        } catch(e) { /* ignore */ }

        const body = modal.querySelector('.modal-body');
        if (!body) return;

        body.innerHTML = `
            <form id="userForm" onsubmit="return false">
                <input type="hidden" id="userId" value="${userId}">
                <div class="form-group">
                    <label class="form-label">아이디 *</label>
                    <input type="text" id="formUsername" class="form-input" value="${esc(user.username || '')}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">비밀번호 (변경 시만 입력)</label>
                    <input type="password" id="formPassword" class="form-input">
                </div>
                <div class="form-group">
                    <label class="form-label">이름 *</label>
                    <input type="text" id="formName" class="form-input" value="${esc(user.name || '')}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">이메일</label>
                    <input type="email" id="formEmail" class="form-input" value="${esc(user.email || '')}">
                </div>
                <div class="form-group">
                    <label class="form-label">전화번호</label>
                    <input type="text" id="formPhone" class="form-input" value="${esc(user.phone || '')}">
                </div>
                <div class="form-group">
                    <label class="form-label">역할 *</label>
                    <select id="formRole" class="form-select" required>
                        <option value="">선택하세요</option>
                        ${['admin','branch_admin','branch_manager','director','teacher','student','parent'].map(r =>
                            `<option value="${r}"${user.role === r ? ' selected' : ''}>${r}</option>`
                        ).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">지사</label>
                    <select id="formBranch" class="form-select">
                        ${branchOptions}
                    </select>
                </div>
                <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
                    <button type="button" class="btn btn-outline" onclick="closeModal('userModal')">취소</button>
                    <button type="submit" class="btn btn-primary" id="userFormSubmit">저장</button>
                </div>
            </form>
        `;

        document.getElementById('formPassword').required = false;
        document.getElementById('userFormSubmit').textContent = '저장';

        const form = document.getElementById('userForm');
        form.onsubmit = async (e) => {
            e.preventDefault();
            await saveUser();
        };

        modal.querySelector('h3').textContent = '사용자 수정';
        openModal('userModal');
    } catch(e) {
        showAlert('사용자 정보를 불러오지 못했습니다: ' + e.message, 'error');
    }
}

async function saveUser() {
    const userId = document.getElementById('userId')?.value || '';
    const data = {
        username: document.getElementById('formUsername')?.value,
        name: document.getElementById('formName')?.value,
        email: document.getElementById('formEmail')?.value || '',
        phone: document.getElementById('formPhone')?.value || '',
        role: document.getElementById('formRole')?.value,
        branch_id: document.getElementById('formBranch')?.value || null,
    };

    const password = document.getElementById('formPassword')?.value;
    if (password) data.password = password;
    else if (!userId) {
        showAlert('비밀번호를 입력하세요.', 'error');
        return;
    }

    try {
        if (userId) {
            await apiPut(`/headquarters/users/${userId}`, data);
            showAlert('사용자가 수정되었습니다.', 'success');
        } else {
            if (!data.password) {
                showAlert('비밀번호를 입력하세요.', 'error');
                return;
            }
            await apiPost('/headquarters/users', data);
            showAlert('사용자가 생성되었습니다.', 'success');
        }
        closeModal('userModal');
        fetchUsers();
    } catch(e) {
        showAlert('오류: ' + e.message, 'error');
    }
}

let deleteTargetUserId = null;

async function showUserDeleteModal(userId) {
    deleteTargetUserId = userId;
    document.getElementById('userDeleteMessage').textContent = `사용자 ID ${userId}를 정말 삭제하시겠습니까?`;
    document.getElementById('userDeleteConfirmBtn').onclick = async () => {
        try {
            await apiDelete(`/headquarters/users/${deleteTargetUserId}`);
            showAlert('사용자가 삭제되었습니다.', 'success');
            closeModal('userDeleteModal');
            fetchUsers();
        } catch(e) {
            showAlert('삭제 오류: ' + e.message, 'error');
        }
    };
    openModal('userDeleteModal');
}

// ============================================================
// 지사 관리
// ============================================================
let currentBranchPage = 1;
let branchSearchQuery = '';

async function loadBranches() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h2>지사 관리</h2>
                <button class="btn btn-primary btn-sm" onclick="showBranchCreateModal()">+ 지사 추가</button>
            </div>
            <div class="card-body">
                <div style="display:flex;gap:8px;margin-bottom:16px">
                    <input type="text" id="branchSearch" placeholder="지사명 검색..." class="form-input" style="max-width:280px;flex:1" oninput="onBranchSearchChange()">
                </div>
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>지사명</th>
                                <th>코드</th>
                                <th>관리자</th>
                                <th>주소</th>
                                <th>전화번호</th>
                                <th>사용자 수</th>
                                <th>상태</th>
                                <th>생성일</th>
                                <th>관리</th>
                            </tr>
                        </thead>
                        <tbody id="branchTableBody"><tr><td colspan="10" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
                <div id="branchPagination" style="display:flex;justify-content:center;margin-top:16px"></div>
            </div>
            ${modalHtml('branchModal', '', '')}
            ${modalHtml('branchDeleteModal', '지사 삭제', '<p id="branchDeleteMessage">정말 삭제하시겠습니까?</p><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn btn-outline" onclick="closeModal(\'branchDeleteModal\')">취소</button><button class="btn btn-danger" id="branchDeleteConfirmBtn">삭제</button></div>')}
        `;
    }

    await fetchBranches();
}

function onBranchSearchChange() {
    branchSearchQuery = document.getElementById('branchSearch')?.value || '';
    currentBranchPage = 1;
    fetchBranches();
}

async function fetchBranches() {
    const tbody = document.getElementById('branchTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:24px">로딩 중...</td></tr>';

    try {
        let path = `/headquarters/branches?page=${currentBranchPage}`;
        if (branchSearchQuery) path += `&search=${encodeURIComponent(branchSearchQuery)}`;

        const res = await apiGet(path);
        const branches = res.items || res.data || [];
        const pagination = res.pagination || { page: currentBranchPage, total_pages: 1, total: branches.length };

        renderTable('branchTableBody', branches, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'name', render: v => esc(v || '-') },
            { key: 'code', render: v => esc(v || '-') },
            { key: 'manager', render: v => esc(v || '-') },
            { key: 'address', render: v => esc(v || '-') },
            { key: 'phone', render: v => esc(v || '-') },
            { key: 'user_count', render: v => formatNumber(v) },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDate(v) },
            { key: 'id', render: (v) => `
                <div style="display:flex;gap:4px">
                    <button class="btn btn-sm btn-outline" onclick="showBranchEditModal(${v})">수정</button>
                    <button class="btn btn-sm btn-danger" onclick="showBranchDeleteModal(${v})">삭제</button>
                </div>
            ` },
        ]);

        renderPaginationWidget('branchPagination', pagination, 'goToBranchPage');
    } catch(e) {
        console.error('Branches fetch error:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:24px;color:var(--text-danger)">오류: ${e.message}</td></tr>`;
    }
}

function goToBranchPage(page) {
    currentBranchPage = page;
    fetchBranches();
}

function showBranchCreateModal() {
    const modal = document.getElementById('branchModal');
    if (!modal) return;
    const body = modal.querySelector('.modal-body');
    if (!body) return;

    body.innerHTML = `
        <form id="branchForm" onsubmit="return false">
            <input type="hidden" id="branchId" value="">
            <div class="form-group">
                <label class="form-label">지사명 *</label>
                <input type="text" id="formBranchName" class="form-input" required>
            </div>
            <div class="form-group">
                <label class="form-label">지사 코드 *</label>
                <input type="text" id="formBranchCode" class="form-input" required>
            </div>
            <div class="form-group">
                <label class="form-label">관리자</label>
                <input type="text" id="formBranchManager" class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">주소</label>
                <input type="text" id="formBranchAddress" class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">전화번호</label>
                <input type="text" id="formBranchPhone" class="form-input">
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
                <button type="button" class="btn btn-outline" onclick="closeModal('branchModal')">취소</button>
                <button type="submit" class="btn btn-primary" id="branchFormSubmit">생성</button>
            </div>
        </form>
    `;

    document.getElementById('branchId').value = '';
    document.getElementById('branchFormSubmit').textContent = '생성';

    const form = document.getElementById('branchForm');
    form.onsubmit = async (e) => {
        e.preventDefault();
        await saveBranch();
    };

    modal.querySelector('h3').textContent = '지사 추가';
    openModal('branchModal');
}

async function showBranchEditModal(branchId) {
    const modal = document.getElementById('branchModal');
    if (!modal) return;

    try {
        const res = await apiGet(`/headquarters/branches/${branchId}`);
        const branch = res.data || res.branch || res;

        const body = modal.querySelector('.modal-body');
        if (!body) return;

        body.innerHTML = `
            <form id="branchForm" onsubmit="return false">
                <input type="hidden" id="branchId" value="${branchId}">
                <div class="form-group">
                    <label class="form-label">지사명 *</label>
                    <input type="text" id="formBranchName" class="form-input" value="${esc(branch.name || '')}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">지사 코드 *</label>
                    <input type="text" id="formBranchCode" class="form-input" value="${esc(branch.code || '')}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">관리자</label>
                    <input type="text" id="formBranchManager" class="form-input" value="${esc(branch.manager || '')}">
                </div>
                <div class="form-group">
                    <label class="form-label">주소</label>
                    <input type="text" id="formBranchAddress" class="form-input" value="${esc(branch.address || '')}">
                </div>
                <div class="form-group">
                    <label class="form-label">전화번호</label>
                    <input type="text" id="formBranchPhone" class="form-input" value="${esc(branch.phone || '')}">
                </div>
                <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
                    <button type="button" class="btn btn-outline" onclick="closeModal('branchModal')">취소</button>
                    <button type="submit" class="btn btn-primary" id="branchFormSubmit">저장</button>
                </div>
            </form>
        `;

        document.getElementById('branchFormSubmit').textContent = '저장';

        const form = document.getElementById('branchForm');
        form.onsubmit = async (e) => {
            e.preventDefault();
            await saveBranch();
        };

        modal.querySelector('h3').textContent = '지사 수정';
        openModal('branchModal');
    } catch(e) {
        showAlert('지사 정보를 불러오지 못했습니다: ' + e.message, 'error');
    }
}

async function saveBranch() {
    const branchId = document.getElementById('branchId')?.value || '';
    const data = {
        name: document.getElementById('formBranchName')?.value,
        code: document.getElementById('formBranchCode')?.value,
        manager: document.getElementById('formBranchManager')?.value || '',
        address: document.getElementById('formBranchAddress')?.value || '',
        phone: document.getElementById('formBranchPhone')?.value || '',
    };

    try {
        if (branchId) {
            await apiPut(`/headquarters/branches/${branchId}`, data);
            showAlert('지사가 수정되었습니다.', 'success');
        } else {
            await apiPost('/headquarters/branches', data);
            showAlert('지사가 생성되었습니다.', 'success');
        }
        closeModal('branchModal');
        fetchBranches();
    } catch(e) {
        showAlert('오류: ' + e.message, 'error');
    }
}

let deleteTargetBranchId = null;

async function showBranchDeleteModal(branchId) {
    deleteTargetBranchId = branchId;
    document.getElementById('branchDeleteMessage').textContent = `지사 ID ${branchId}를 정말 삭제하시겠습니까?`;
    document.getElementById('branchDeleteConfirmBtn').onclick = async () => {
        try {
            await apiDelete(`/headquarters/branches/${deleteTargetBranchId}`);
            showAlert('지사가 삭제되었습니다.', 'success');
            closeModal('branchDeleteModal');
            fetchBranches();
        } catch(e) {
            showAlert('삭제 오류: ' + e.message, 'error');
        }
    };
    openModal('branchDeleteModal');
}

// ============================================================
// 결제 관리
// ============================================================
async function loadPayments() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>결제 관리</h2></div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>사용자</th>
                                <th>금액</th>
                                <th>방법</th>
                                <th>상태</th>
                                <th>일자</th>
                            </tr>
                        </thead>
                        <tbody id="paymentTableBody"><tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
                <div id="paymentPagination" style="display:flex;justify-content:center;margin-top:16px"></div>
            </div>
        `;
    }

    try {
        const res = await apiGet('/headquarters/payments?page=1');
        const payments = res.items || res.data || [];
        const pagination = res.pagination || { page: 1, total_pages: 1 };

        renderTable('paymentTableBody', payments, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'user_name', render: v => esc(v || '-') },
            { key: 'amount', render: v => formatCurrency(v) },
            { key: 'method', render: v => esc(v || '-') },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDateTime(v) },
        ]);

        renderPaginationWidget('paymentPagination', pagination, '(p)=>loadPaymentsPage(p)');
    } catch(e) {
        console.error('Payments load error:', e);
    }
}

// ============================================================
// 공지사항
// ============================================================
async function loadNotices() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h2>공지사항</h2>
                <button class="btn btn-primary btn-sm" onclick="showAlert('공지사항 작성 기능은 준비 중입니다.', 'info')">+ 작성</button>
            </div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>제목</th>
                                <th>작성자</th>
                                <th>상태</th>
                                <th>작성일</th>
                            </tr>
                        </thead>
                        <tbody id="noticeTableBody"><tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    try {
        const res = await apiGet('/headquarters/notices?page=1');
        const items = res.items || res.data || [];
        renderTable('noticeTableBody', items, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'title', render: v => esc(v || '-') },
            { key: 'author', render: v => esc(v || '-') },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDateTime(v) },
        ]);
    } catch(e) {
        console.error('Notices load error:', e);
    }
}

// ============================================================
// 통계
// ============================================================
async function loadStatistics() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>통계</h2></div>
            <div class="card-body">
                <div class="stats-grid" style="margin-bottom:24px">
                    <div class="stat-card"><div class="stat-label">총 사용자</div><div class="stat-value" id="statTotalUsers">-</div></div>
                    <div class="stat-card"><div class="stat-label">총 매출</div><div class="stat-value" id="statTotalRevenue">-</div></div>
                    <div class="stat-card"><div class="stat-label">활성 사용자</div><div class="stat-value" id="statActiveUsers">-</div></div>
                </div>
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead><tr><th>지표</th><th>값</th></tr></thead>
                        <tbody id="statTableBody"></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    try {
        // 사용자 분석
        const userAnalytics = await apiGet('/platform/analytics/users');
        if (userAnalytics) {
            setText('statTotalUsers', formatNumber(userAnalytics.total_users || userAnalytics.total));
            setText('statActiveUsers', formatNumber(userAnalytics.active_users || userAnalytics.active));
        }

        // 매출 분석
        const revenueAnalytics = await apiGet('/platform/analytics/revenue');
        if (revenueAnalytics) {
            setText('statTotalRevenue', formatCurrency(revenueAnalytics.total_revenue || revenueAnalytics.total));
        }

        // 감사 로그 최근 항목 표시
        const auditLogs = await apiGet('/audit/logs?page=1&per_page=10');
        const logs = auditLogs.items || auditLogs.data || [];
        renderTable('statTableBody', logs, [
            { key: 'action', render: v => esc(v || '-') },
            { key: 'details', render: v => esc(v || '-') },
        ]);
    } catch(e) {
        console.error('Statistics load error:', e);
    }
}

// ============================================================
// 설정
// ============================================================
async function loadSettings() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>설정</h2></div>
            <div class="card-body">
                <div style="padding:24px 0">
                    <h3 style="margin-bottom:16px">시스템 설정</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:600px">
                        <div>
                            <label class="form-label">사이트명</label>
                            <input type="text" class="form-input" id="settingSiteName" value="누비다플랫폼">
                        </div>
                        <div>
                            <label class="form-label">언어</label>
                            <select class="form-select" id="settingLanguage">
                                <option value="ko">한국어</option>
                                <option value="en">English</option>
                            </select>
                        </div>
                    </div>
                    <div style="margin-top:24px;display:flex;gap:8px">
                        <button class="btn btn-primary" onclick="showAlert('설정이 저장되었습니다.', 'success')">저장</button>
                        <button class="btn btn-outline" onclick="showAlert('설정이 초기화되었습니다.', 'info')">초기화</button>
                    </div>
                </div>
            </div>
        `;
    }
}

// ============================================================
// 포트폴리오
// ============================================================
async function loadPortfolio() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>포트폴리오</h2></div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>제목</th>
                                <th>작성자</th>
                                <th>상태</th>
                                <th>등록일</th>
                            </tr>
                        </thead>
                        <tbody id="portfolioTableBody"><tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    try {
        const res = await apiGet('/portfolio?page=1');
        const items = res.items || res.data || [];
        renderTable('portfolioTableBody', items, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'title', render: v => esc(v || '-') },
            { key: 'author', render: v => esc(v || '-') },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDateTime(v) },
        ]);
    } catch(e) {
        console.error('Portfolio load error:', e);
    }
}

// ============================================================
// 비디오
// ============================================================
async function loadVideos() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>비디오 관리</h2></div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>제목</th>
                                <th>URL</th>
                                <th>상태</th>
                                <th>등록일</th>
                            </tr>
                        </thead>
                        <tbody id="videoTableBody"><tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    try {
        const res = await apiGet('/videos?page=1');
        const items = res.items || res.data || [];
        renderTable('videoTableBody', items, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'title', render: v => esc(v || '-') },
            { key: 'url', render: v => `<a href="${esc(v)}" target="_blank">${esc(v ? v.substring(0, 40) + '...' : '-')}</a>` },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDateTime(v) },
        ]);
    } catch(e) {
        console.error('Videos load error:', e);
    }
}

// ============================================================
// 원격수업
// ============================================================
async function loadClassroom() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header"><h2>원격수업</h2></div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>수업명</th>
                                <th>강사</th>
                                <th>시작</th>
                                <th>종료</th>
                                <th>상태</th>
                            </tr>
                        </thead>
                        <tbody id="classroomTableBody"><tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    try {
        const res = await apiGet('/classroom?page=1');
        const items = res.items || res.data || [];
        renderTable('classroomTableBody', items, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'title', render: v => esc(v || '-') },
            { key: 'instructor', render: v => esc(v || '-') },
            { key: 'start_time', render: v => formatDateTime(v) },
            { key: 'end_time', render: v => formatDateTime(v) },
            { key: 'status', render: v => statusBadge(v) },
        ]);
    } catch(e) {
        console.error('Classroom load error:', e);
    }
}

// ============================================================
// 백업
// ============================================================
async function loadBackups() {
    const mainContent = document.querySelector('.main-content');
    if (!mainContent) return;

    const card = mainContent.querySelector('.card');
    if (card) {
        card.innerHTML = `
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <h2>백업 관리</h2>
                <button class="btn btn-primary btn-sm" onclick="runBackup()">+ 백업 실행</button>
            </div>
            <div class="card-body">
                <div class="table-wrapper">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>파일명</th>
                                <th>크기</th>
                                <th>상태</th>
                                <th>생성일</th>
                            </tr>
                        </thead>
                        <tbody id="backupTableBody"><tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-tertiary)">로딩 중...</td></tr></tbody>
                    </table>
                </div>
            </div>
        `;
    }

    await fetchBackups();
}

async function fetchBackups() {
    const tbody = document.getElementById('backupTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px">로딩 중...</td></tr>';

    try {
        const res = await apiGet('/backups/list');
        const items = res.items || res.data || res.backups || [];

        renderTable('backupTableBody', items, [
            { key: 'id', render: v => esc(String(v)) },
            { key: 'filename', render: v => esc(v || '-') },
            { key: 'size', render: v => v ? formatNumber(v) + ' bytes' : '-' },
            { key: 'status', render: v => statusBadge(v) },
            { key: 'created_at', render: v => formatDateTime(v) },
        ]);
    } catch(e) {
        console.error('Backups fetch error:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-danger)">오류: ${e.message}</td></tr>`;
    }
}

async function runBackup() {
    try {
        showAlert('백업을 시작합니다...', 'info');
        await apiPost('/backups/run');
        showAlert('백업이 완료되었습니다.', 'success');
        fetchBackups();
    } catch(e) {
        showAlert('백업 오류: ' + e.message, 'error');
    }
}
