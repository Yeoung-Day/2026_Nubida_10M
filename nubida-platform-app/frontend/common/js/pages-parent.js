// ============================================================
// 누비다플랫폼 v2 Premium — 학부모모니터링(Parent) 페이지 스크립트
// API: children, grades, payments, consultations, portfolio
// ============================================================

// ===== Helper: apiGet wrapper — 자동으로 .data 추출 =====
async function apiGetData(path) {
    try {
        const res = await apiGet(path);
        return res && res.data !== undefined ? res.data : res;
    } catch(e) {
        throw e;
    }
}

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

// ===== Helper: 상태 배지 =====
function statusBadge(status) {
    const map = {
        'active':    ['success', '활성'],
        'inactive':  ['warning', '비활성'],
        'pending':   ['warning', '대기중'],
        'completed': ['success', '완료'],
        'failed':    ['danger', '실패'],
        'published': ['success', '발행'],
        'draft':     ['warning', '임시'],
        'paid':      ['success', '완납'],
        'unpaid':    ['danger', '미납'],
        'cancelled': ['info', '취소'],
        'refunded':  ['warning', '환불'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 모달 열기/닫기 =====
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// ===== Helper: 날짜 포맷 =====
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
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

function formatNumber(n) {
    if (n === null || n === undefined) return '0';
    return Number(n).toLocaleString();
}

function formatCurrency(n) {
    if (n === null || n === undefined) return '0원';
    return Number(n).toLocaleString() + '원';
}

// ===== Helper: 출석률 렌더 =====
function attendanceRate(value) {
    const v = Number(value) || 0;
    const color = v >= 90 ? 'var(--md-success)' : v >= 75 ? 'var(--md-warning)' : 'var(--md-danger)';
    return `<span style="color:${color};font-weight:600">${v}%</span>`;
}

// ===== Helper: 점수 렌더 =====
function scoreRender(value) {
    const v = Number(value) || 0;
    const color = v >= 90 ? 'var(--md-success)' : v >= 70 ? 'var(--md-primary)' : v >= 50 ? 'var(--md-warning)' : 'var(--md-danger)';
    return `<span style="color:${color};font-weight:600">${v}</span>`;
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
        case 'grades': loadGrades(); break;
        case 'progress': loadProgress(); break;
        case 'portfolio': loadPortfolio(); break;
        case 'children': loadChildren(); break;
        case 'counseling': loadCounseling(); break;
        case 'payments': loadPayments(); break;
        case 'pay-tuition': loadPayTuition(); break;
    }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        setText('todayDate', new Date().toLocaleDateString('ko-KR', {
            year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
        }));

        const [children, notifs, payments, portfolios] = await Promise.all([
            apiGetData('/parent/children').catch(() => []),
            apiGetData('/parent/notifications').catch(() => []),
            apiGet('/parent/payments').catch(() => ({ payments: [] })),
            apiGetData('/portfolio').catch(() => []),
        ]);

        // Stat cards
        setText('totalChildren', formatNumber(children?.length || 0));

        // 금주 포트폴리오
        const now = new Date();
        const weekStart = new Date(now);
        weekStart.setDate(now.getDate() - now.getDay());
        weekStart.setHours(0, 0, 0, 0);
        const weekPortfolioCount = Array.isArray(portfolios)
            ? portfolios.filter(p => new Date(p.created_at || p.date) >= weekStart).length
            : 0;
        setText('weeklyPortfolios', formatNumber(weekPortfolioCount));

        // 최근 결제 내역
        const paymentList = payments?.payments || payments || [];
        const recentPay = paymentList.length > 0 ? formatCurrency(paymentList[0].amount || 0) : '0원';
        setText('recentPayment', recentPay);

        // 평균 성적
        try {
            const allScores = [];
            if (children && children.length > 0) {
                for (const child of children) {
                    const scores = await apiGetData(`/parent/children/${child.id}/scores`).catch(() => []);
                    if (Array.isArray(scores)) allScores.push(...scores);
                }
            }
            const avg = allScores.length > 0
                ? Math.round(allScores.reduce((s, r) => s + (Number(r.score) || 0), 0) / allScores.length)
                : 0;
            setText('avgGrade', avg > 0 ? avg + '점' : '-');
        } catch(e) {
            setText('avgGrade', '-');
        }

        // Children list card
        if (children && children.length > 0) {
            const html = children.map(c => `
                <div class="child-item" style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-4) 0;border-bottom:1px solid var(--border-subtle)">
                    <div>
                        <div style="font-weight:600">${c.name}</div>
                        <div style="font-size:var(--text-sm);color:var(--text-tertiary)">${c.school || ''} ${c.grade ? c.grade + '학년' : ''} ${c.class_name || ''}</div>
                    </div>
                    <div style="text-align:right">
                        <div style="font-size:var(--text-sm)">출석 ${attendanceRate(c.attendance_rate)}</div>
                    </div>
                </div>
            `).join('');
            setHtml('childrenList', html);
        } else {
            setHtml('childrenList', '<p class="empty-state" style="padding:var(--space-7)">등록된 자녀가 없습니다.</p>');
        }

        // Quick actions
        setHtml('quickActions', `
            <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:var(--space-4)">
                <a href="children.html" class="btn btn-outline" style="text-align:center;padding:var(--space-5)">👶 자녀 관리</a>
                <a href="grades.html" class="btn btn-outline" style="text-align:center;padding:var(--space-5)">📈 성적 조회</a>
                <a href="payments.html" class="btn btn-outline" style="text-align:center;padding:var(--space-5)">💳 결제 내역</a>
                <a href="counseling.html" class="btn btn-outline" style="text-align:center;padding:var(--space-5)">💬 상담 신청</a>
            </div>
        `);

        // Activity feed (from portfolios)
        if (Array.isArray(portfolios) && portfolios.length > 0) {
            const recent = portfolios.slice(0, 5);
            const html = recent.map(p => `
                <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--border-subtle)">
                    <span style="font-weight:500">${p.title || p.name || '포트폴리오'}</span>
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);margin-left:var(--space-3)">${formatDate(p.created_at || p.date)}</span>
                </div>
            `).join('');
            setHtml('activityFeed', html);
        } else {
            setHtml('activityFeed', '<p class="empty-state" style="padding:var(--space-7)">최근 활동이 없습니다.</p>');
        }

        // Recent notices
        if (Array.isArray(notifs) && notifs.length > 0) {
            const recent = notifs.slice(0, 5);
            const html = recent.map(n => `
                <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--border-subtle)">
                    <span>${n.title || n.message || '알림'}</span>
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);margin-left:var(--space-3)">${formatDate(n.created_at || n.date)}</span>
                </div>
            `).join('');
            setHtml('recentNotices', html);
        } else {
            setHtml('recentNotices', '<p class="empty-state" style="padding:var(--space-7)">새 알림이 없습니다.</p>');
        }

        // Recent portfolios for dashboard — enhanced with child names
        if (Array.isArray(portfolios) && portfolios.length > 0) {
            const recent = portfolios.slice(0, 5);
            // Build a map of student_id -> child name
            const childMap = {};
            if (Array.isArray(children)) {
                children.forEach(c => { childMap[c.id] = c.name; });
            }
            const html = recent.map(p => {
                const childName = childMap[p.student_id] || p.child_name || '자녀';
                return `
                <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--border-subtle);cursor:pointer" onclick="window.location.href='portfolio.html'">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <div>
                            <span style="font-weight:500">${p.title || p.name || '포트폴리오'}</span>
                            <span style="font-size:var(--text-sm);color:var(--text-tertiary);margin-left:var(--space-3)">👶 ${childName}</span>
                            <span style="font-size:var(--text-sm);color:var(--text-tertiary);margin-left:var(--space-2)">${p.subject || ''}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <span class="badge badge-${p.status === 'approved' ? 'success' : p.status === 'published' ? 'info' : 'warning'}">${p.status === 'approved' ? '✅ 승인' : p.status === 'published' ? '📝 발행' : '📄 임시'}</span>
                            <span style="font-size:var(--text-xs);color:var(--text-tertiary)">${formatDate(p.created_at || p.date)}</span>
                        </div>
                    </div>
                </div>
            `}).join('');
            setHtml('childPortfolios', html);
        } else {
            setHtml('childPortfolios', '<p class="empty-state" style="padding:var(--space-7)">최근 포트폴리오가 없습니다.</p>');
        }

        // Recent grades table
        if (children && children.length > 0) {
            try {
                const allScores = [];
                for (const child of children) {
                    const scores = await apiGetData(`/parent/children/${child.id}/scores`).catch(() => []);
                    if (Array.isArray(scores)) {
                        scores.forEach(s => {
                            if (!s.child_name) s.child_name = child.name;
                            allScores.push(s);
                        });
                    }
                }
                const sorted = allScores.sort((a, b) => new Date(b.date || b.created_at) - new Date(a.date || a.created_at)).slice(0, 10);
                renderTable('gradeBody', sorted, [
                    { key: 'child_name', label: '자녀' },
                    { key: 'exam', label: '시험' },
                    { key: 'course', label: '과목' },
                    { key: 'score', label: '점수', render: v => scoreRender(v) },
                    { key: 'grade', label: '등급' },
                    { key: 'date', label: '일시', render: v => formatDate(v) }
                ]);
            } catch(e) {
                setHtml('gradeBody', '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-tertiary)">성적 데이터를 불러올 수 없습니다.</td></tr>');
            }
        }
    } catch(e) {
        console.error('Dashboard error:', e);
    }
}

// ============================================================
// 자녀 관리 (children.html)
// ============================================================
async function loadChildren() {
    try {
        const children = await apiGetData('/parent/children');
        if (!children) {
            setHtml('childList', '<p class="empty-state" style="padding:var(--space-8)">등록된 자녀가 없습니다.</p>');
            setHtml('childSummaryBody', '<tr><td colspan="6" class="empty-state" style="padding:var(--space-8)">데이터가 없습니다.</td></tr>');
            return;
        }

        // Card grid
        const cards = children.map(c => `
            <div class="card card-premium" style="cursor:pointer" onclick="editChild('${c.id}')">
                <div class="card-header">
                    <h2 style="font-size:var(--text-lg)">👶 ${c.name}</h2>
                </div>
                <div class="card-body">
                    <div style="display:flex;flex-direction:column;gap:var(--space-2)">
                        <div><span class="text-secondary">학교:</span> ${c.school || '-'}</div>
                        <div><span class="text-secondary">학년:</span> ${c.grade ? c.grade + '학년' : '-'}</div>
                        <div><span class="text-secondary">학급:</span> ${c.class_name || '-'}</div>
                        <div><span class="text-secondary">출석률:</span> ${attendanceRate(c.attendance_rate)}</div>
                    </div>
                </div>
            </div>
        `).join('');
        setHtml('childList', cards);

        // Summary table
        renderTable('childSummaryBody', children, [
            { key: 'name', label: '자녀' },
            { key: 'class_name', label: '학급' },
            { key: 'recent_exam', label: '최근시험', render: v => v || '-' },
            { key: 'average_score', label: '평균', render: v => v ? scoreRender(v) : '-' },
            { key: 'attendance_rate', label: '출석률', render: v => attendanceRate(v) },
            { key: 'unpaid', label: '미결제', render: v => v ? formatCurrency(v) : '0원' }
        ]);
    } catch(e) {
        console.error('loadChildren error:', e);
        setHtml('childList', '<p class="empty-state" style="padding:var(--space-8)">데이터를 불러오는 중 오류가 발생했습니다.</p>');
    }
}

// ===== 자녀 등록/수정 모달 =====
function openChildModal() {
    document.getElementById('editChildId').value = '';
    document.getElementById('childName').value = '';
    document.getElementById('childGrade').value = '1';
    document.getElementById('childSchool').value = '';
    document.getElementById('childRemark').value = '';
    document.querySelector('#childModal h2').textContent = '자녀 등록';
    openModal('childModal');
}

function editChild(id) {
    // For now, just show a simple alert since we don't have full child data stored locally
    alert(`자녀 ID: ${id} 상세정보는 곧 제공됩니다.`);
}

// Save child form handler (called from HTML onsubmit)
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('childForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                const id = document.getElementById('editChildId').value;
                const data = {
                    name: document.getElementById('childName').value,
                    grade: document.getElementById('childGrade').value,
                    school: document.getElementById('childSchool').value,
                    remark: document.getElementById('childRemark').value
                };
                if (id) {
                    await apiPut(`/parent/children/${id}`, data);
                } else {
                    await apiPost('/parent/children', data);
                }
                closeModal('childModal');
                loadChildren();
            } catch(err) {
                alert('저장 중 오류가 발생했습니다: ' + err.message);
            }
        });
    }
});

// ============================================================
// 성적 조회 (grades.html)
// ============================================================
let _gradeChildren = [];

async function loadGrades() {
    try {
        const children = await apiGetData('/parent/children');
        _gradeChildren = children || [];

        // Populate child selector
        const sel = document.getElementById('filterChild');
        if (sel) {
            sel.innerHTML = '<option value="">전체 자녀</option>';
            (children || []).forEach(c => {
                sel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            });
        }

        // Load stats + table
        await refreshGradeData();
    } catch(e) {
        console.error('loadGrades error:', e);
    }
}

async function refreshGradeData() {
    const sel = document.getElementById('filterChild');
    const childId = sel ? sel.value : '';

    try {
        let allScores = [];
        if (childId) {
            // Single child
            const scores = await apiGetData(`/parent/children/${childId}/scores`).catch(() => []);
            if (Array.isArray(scores)) {
                const child = _gradeChildren.find(c => c.id == childId);
                scores.forEach(s => { if (!s.child_name) s.child_name = child?.name || '-'; });
                allScores = scores;
            }
        } else {
            // All children
            for (const child of _gradeChildren) {
                const scores = await apiGetData(`/parent/children/${child.id}/scores`).catch(() => []);
                if (Array.isArray(scores)) {
                    scores.forEach(s => { if (!s.child_name) s.child_name = child.name; });
                    allScores.push(...scores);
                }
            }
        }

        // Stats
        const scores = allScores.map(s => Number(s.score)).filter(n => !isNaN(n));
        setText('totalExams', formatNumber(scores.length));
        setText('avgScore', scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) + '점' : '-');
        setText('bestScore', scores.length > 0 ? Math.max(...scores) + '점' : '-');

        const subjects = new Set(allScores.map(s => s.course).filter(Boolean));
        setText('subjectCount', subjects.size > 0 ? subjects.size + '개' : '-');

        // Subject breakdown
        const breakdownEl = document.getElementById('subjectBreakdown');
        if (breakdownEl && subjects.size > 0) {
            const bySubject = {};
            allScores.forEach(s => {
                const subj = s.course || '기타';
                if (!bySubject[subj]) bySubject[subj] = [];
                bySubject[subj].push(Number(s.score));
            });
            const chips = Object.entries(bySubject).map(([subj, arr]) => {
                const avg = Math.round(arr.reduce((a, b) => a + b, 0) / arr.length);
                return `<span class="badge badge-info" style="margin:var(--space-1);padding:var(--space-2) var(--space-4);font-size:var(--text-sm)">
                    ${subj}: 평균 ${avg}점 (${arr.length}회)
                </span>`;
            }).join('');
            breakdownEl.style.display = 'block';
            breakdownEl.innerHTML = `
                <div class="card card-premium">
                    <div class="card-header"><h2>📊 과목별 성적 현황</h2></div>
                    <div class="card-body">${chips}</div>
                </div>
            `;
        } else if (breakdownEl) {
            breakdownEl.style.display = 'none';
        }

        // Grade table (7 cols: 자녀, 시험, 과목, 점수, 등급, 석차, 일시)
        renderTable('gradeBody', allScores, [
            { key: 'child_name', label: '자녀' },
            { key: 'exam', label: '시험' },
            { key: 'course', label: '과목' },
            { key: 'score', label: '점수', render: v => scoreRender(v) },
            { key: 'grade', label: '등급' },
            { key: 'rank', label: '석차', render: v => v ? v + '등' : '-' },
            { key: 'date', label: '일시', render: v => formatDate(v) }
        ]);
    } catch(e) {
        console.error('refreshGradeData error:', e);
    }
}

function onChildChange() {
    // Called by both grades.html (filterChild) and portfolio.html (childSelect)
    const page = window.location.pathname.split('/').pop().replace('.html', '');
    if (page === 'grades') {
        refreshGradeData();
    } else if (page === 'portfolio') {
        refreshPortfolio();
    }
}

// ============================================================
// 수업 진행 현황 (progress.html)
// ============================================================
async function loadProgress() {
    try {
        setText('todayDate', new Date().toLocaleDateString('ko-KR', {
            year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
        }));

        // Load children
        const children = await apiGetData('/parent/children');
        if (!children || children.length === 0) {
            setHtml('progressContainer', `
                <div class="empty-progress">
                    <div class="empty-icon">👶</div>
                    <h3>등록된 자녀가 없습니다</h3>
                    <p>자녀를 먼저 등록해 주세요.</p>
                    <a href="children.html" class="btn btn-primary" style="margin-top:var(--space-4)">자녀 등록하기</a>
                </div>
            `);
            return;
        }

        // Load portfolio data (for latest portfolio items per child)
        const portfolios = await apiGetData('/portfolio').catch(() => []);
        const portfolioArr = Array.isArray(portfolios) ? portfolios : [];

        // Summary stats
        let totalCourses = 0;
        let totalCompletion = 0;
        let courseCount = 0;

        // Build each child's progress card
        let containerHtml = '';

        for (const child of children) {
            // Fetch courses/progress for this child
            let courses = [];
            try {
                // Try progress endpoint first (includes course data)
                const progResp = await apiGetData(`/parent/children/${child.id}/progress`).catch(() => null);
                if (progResp && Array.isArray(progResp.courses)) {
                    courses = progResp.courses;
                } else if (progResp && Array.isArray(progResp)) {
                    courses = progResp;
                }
            } catch(e) {
                courses = [];
            }

            // Accumulate stats
            courses.forEach(c => {
                totalCourses++;
                const pct = Number(c.completion_rate ?? c.progress ?? c.completed_percentage ?? 0);
                totalCompletion += pct;
                courseCount++;
            });

            // Filter portfolio items for this child
            const childPortfolios = portfolioArr.filter(p =>
                String(p.child_id) === String(child.id) ||
                String(p.user_id) === String(child.id) ||
                String(p.student_id) === String(child.id) ||
                (p.child_name && p.child_name === child.name)
            );
            const latestPortfolios = childPortfolios
                .sort((a, b) => new Date(b.created_at || b.date || 0) - new Date(a.created_at || a.date || 0))
                .slice(0, 5);

            // Build course progress HTML
            let coursesHtml;
            if (courses.length > 0) {
                coursesHtml = courses.map(c => {
                    const pct = Math.min(100, Math.max(0, Number(c.completion_rate ?? c.progress ?? c.completed_percentage ?? 0)));
                    const pctLabel = pct + '%';
                    let barClass = '';
                    if (pct >= 80) barClass = 'high';
                    else if (pct >= 50) barClass = 'medium';
                    else if (pct > 0) barClass = 'low';
                    return `
                        <div class="course-item">
                            <div class="progress-label">
                                <span class="course-name">${c.name || c.course_name || c.title || '과목'}</span>
                                <span class="course-pct">${pctLabel}</span>
                            </div>
                            <div class="progress-bar-track">
                                <div class="progress-bar-fill ${barClass}" style="width:${pct}%"></div>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                coursesHtml = `
                    <div class="course-item">
                        <p style="text-align:center;color:var(--text-tertiary);padding:var(--space-4)">등록된 수업이 없습니다.</p>
                    </div>
                `;
            }

            // Build latest portfolio items HTML
            let portfolioHtml = '';
            if (latestPortfolios.length > 0) {
                portfolioHtml = `
                    <div class="portfolio-mini-list">
                        <div class="mini-title">📁 최근 포트폴리오</div>
                        ${latestPortfolios.map(p => {
                            const statusLabel = p.status === 'approved' ? '승인' : (p.status === 'published' ? '발행' : '임시');
                            const statusClass = p.status === 'approved' ? 'badge-success' : (p.status === 'published' ? 'badge-info' : 'badge-warning');
                            return `
                                <div class="portfolio-mini-item">
                                    <span class="portfolio-title">${p.title || p.name || '제목 없음'}</span>
                                    <span class="portfolio-meta">
                                        <span>${p.subject || p.category || ''}</span>
                                        <span>${formatDate(p.created_at || p.date)}</span>
                                        <span class="badge ${statusClass}">${statusLabel}</span>
                                    </span>
                                </div>
                            `;
                        }).join('')}
                        <div style="margin-top:var(--space-2);text-align:right">
                            <a href="portfolio.html" class="btn btn-ghost btn-xs">더보기 →</a>
                        </div>
                    </div>
                `;
            }

            const initial = (child.name || '?').charAt(0);

            containerHtml += `
                <div class="card card-premium child-progress-card">
                    <div class="card-body">
                        <div class="child-header">
                            <div class="child-avatar">${initial}</div>
                            <div class="child-info">
                                <h2>${child.name}</h2>
                                <div class="child-meta">${child.school || ''} ${child.grade ? child.grade + '학년' : ''} ${child.class_name ? '· ' + child.class_name : ''}</div>
                            </div>
                            <div style="margin-left:auto;text-align:right">
                                <span style="font-size:var(--text-sm);color:var(--text-tertiary)">출석률 ${attendanceRate(child.attendance_rate)}</span>
                            </div>
                        </div>
                        ${coursesHtml}
                        ${portfolioHtml}
                    </div>
                </div>
            `;
        }

        setHtml('progressContainer', containerHtml);

        // Stats row
        const avgCompletion = courseCount > 0 ? Math.round(totalCompletion / courseCount) : 0;
        const statsEl = document.getElementById('statsRow');
        if (statsEl) {
            statsEl.style.display = 'flex';
            statsEl.innerHTML = `
                <div class="stat-item"><span class="stat-label">👶 자녀 수</span><span class="stat-value">${children.length}명</span></div>
                <div class="stat-item"><span class="stat-label">📚 총 수업</span><span class="stat-value">${totalCourses}개</span></div>
                <div class="stat-item"><span class="stat-label">📈 평균 진행률</span><span class="stat-value">${avgCompletion}%</span></div>
                <div class="stat-item"><span class="stat-label">📁 최근 포트폴리오</span><span class="stat-value">${portfolioArr.length}개</span></div>
            `;
        }
    } catch(e) {
        console.error('loadProgress error:', e);
        setHtml('progressContainer', `
            <div class="empty-progress">
                <div class="empty-icon">⚠️</div>
                <h3>데이터를 불러올 수 없습니다</h3>
                <p>잠시 후 다시 시도해 주세요.</p>
            </div>
        `);
    }
}

// ============================================================
// 포트폴리오 조회 (portfolio.html)
// ============================================================
let _portfolioChildren = [];
let _portfolioData = [];

async function loadPortfolio() {
    try {
        const children = await apiGetData('/parent/children');
        _portfolioChildren = children || [];

        const sel = document.getElementById('childSelect');
        if (sel) {
            sel.innerHTML = '<option value="">자녀를 선택하세요</option>';
            (children || []).forEach(c => {
                sel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            });
        }

        // Load all portfolio data
        _portfolioData = await apiGetData('/portfolio').catch(() => []);
        if (!Array.isArray(_portfolioData)) _portfolioData = [];
    } catch(e) {
        console.error('loadPortfolio error:', e);
    }
}

async function refreshPortfolio() {
    const sel = document.getElementById('childSelect');
    const childId = sel ? sel.value : '';

    const summaryEl = document.getElementById('portfolioSummary');
    const chipsEl = document.getElementById('filterChips');
    const containerEl = document.getElementById('portfolioContainer');

    if (!childId) {
        if (summaryEl) summaryEl.style.display = 'none';
        if (chipsEl) chipsEl.style.display = 'none';
        if (containerEl) {
            containerEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👶</div>
                    <h3>자녀를 선택해 주세요</h3>
                    <p>위에서 자녀를 선택하면 포트폴리오를 확인할 수 있습니다.</p>
                </div>
            `;
        }
        return;
    }

    const child = _portfolioChildren.find(c => c.id == childId);
    const portfolios = _portfolioData.filter(p => {
        return String(p.child_id) === String(childId) ||
               String(p.user_id) === String(childId) ||
               (p.child_name && child && p.child_name === child.name);
    });

    // Summary
    if (summaryEl) {
        summaryEl.style.display = 'block';
        summaryEl.innerHTML = `
            <div class="card card-premium mb-24">
                <div class="card-header"><h2>📁 ${child?.name || '자녀'} 포트폴리오 요약</h2></div>
                <div class="card-body">
                    <div style="display:flex;gap:var(--space-6);flex-wrap:wrap">
                        <div><span class="text-secondary">총 포트폴리오:</span> <strong>${portfolios.length}개</strong></div>
                        <div><span class="text-secondary">최근 업로드:</span> <strong>${portfolios.length > 0 ? formatDate(portfolios[0].created_at || portfolios[0].date) : '-'}</strong></div>
                    </div>
                </div>
            </div>
        `;
    }

    // Subject filter chips
    const subjects = [...new Set(portfolios.map(p => p.subject || p.category || '기타').filter(Boolean))];
    if (chipsEl) {
        if (subjects.length > 0) {
            chipsEl.style.display = 'block';
            chipsEl.innerHTML = subjects.map(subj => `
                <span class="filter-chip active" data-subject="${subj}" onclick="filterPortfolio(this, '${subj}')"
                      style="display:inline-block;padding:var(--space-2) var(--space-4);margin:var(--space-1);border:1px solid var(--border-subtle);border-radius:var(--radius-full);cursor:pointer;font-size:var(--text-sm);background:var(--bg-surface)">
                    ${subj}
                </span>
            `).join('');
        } else {
            chipsEl.style.display = 'none';
        }
    }

    // Portfolio grid
    if (containerEl) {
        if (portfolios.length === 0) {
            containerEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📁</div>
                    <h3>포트폴리오가 없습니다</h3>
                    <p>아직 등록된 포트폴리오가 없습니다.</p>
                </div>
            `;
        } else {
            containerEl.innerHTML = `<div class="portfolio-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:var(--space-4)">${
                portfolios.map(p => `
                    <div class="card card-premium portfolio-card" style="cursor:pointer" onclick="viewPortfolioDetail('${p.id}')">
                        <div class="card-body">
                            <div style="font-size:2rem;margin-bottom:var(--space-3)">${p.thumbnail ? `<img src="${p.thumbnail}" style="width:100%;height:140px;object-fit:cover;border-radius:var(--radius-md)" />` : '📄'}</div>
                            <h3 style="font-size:var(--text-base);margin-bottom:var(--space-2)">${p.title || p.name || '제목 없음'}</h3>
                            <div style="font-size:var(--text-sm);color:var(--text-tertiary)">${p.subject || p.category || ''} ${p.created_at ? '· ' + formatDate(p.created_at) : ''}</div>
                        </div>
                    </div>
                `).join('')
            }</div>`;
        }
    }
}

let _activeSubject = null;
function filterPortfolio(el, subject) {
    // Toggle active filter
    document.querySelectorAll('.filter-chip').forEach(chip => {
        chip.style.background = 'var(--bg-surface)';
        chip.style.borderColor = 'var(--border-subtle)';
    });
    if (_activeSubject === subject) {
        _activeSubject = null;
        // Show all
        document.querySelectorAll('.portfolio-card').forEach(card => card.style.display = '');
        return;
    }
    _activeSubject = subject;
    el.style.background = 'var(--md-primary)';
    el.style.color = 'white';
    el.style.borderColor = 'var(--md-primary)';

    document.querySelectorAll('.portfolio-card').forEach(card => {
        const text = card.textContent || '';
        card.style.display = text.includes(subject) ? '' : 'none';
    });
}

function viewPortfolioDetail(id) {
    const item = _portfolioData.find(p => String(p.id) === String(id));
    if (!item) return;
    
    // Store for approve
    window._currentChildPortfolio = item;

    const content = document.getElementById('detailContent');
    if (content) {
        const images = item.image_urls || [];
        const imageHtml = images.length > 0
            ? `<div style="display:flex;flex-wrap:wrap;gap:8px;margin:var(--space-4) 0">${images.map(url => `<img src="${url}" style="max-width:200px;max-height:200px;border-radius:8px;object-fit:cover" />`).join('')}</div>`
            : '';
        const statusLabel = item.status === 'approved' ? '✅ 승인' : (item.status === 'published' ? '📝 발행' : '📄 임시');
        const statusClass = item.status === 'approved' ? 'success' : (item.status === 'published' ? 'info' : 'warning');
        
        content.innerHTML = `
            <div style="padding:var(--space-4)">
                ${item.thumbnail ? `<img src="${item.thumbnail}" style="width:100%;max-height:300px;object-fit:cover;border-radius:var(--radius-md);margin-bottom:var(--space-4)" />` : ''}
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:var(--space-3)">
                    <h2 style="margin:0">${item.title || item.name || '제목 없음'}</h2>
                    <span class="badge badge-${statusClass}">${statusLabel}</span>
                </div>
                <div class="receipt-grid">
                    <div class="receipt-item"><div class="label">과목</div><div class="value">${item.subject || item.category || '-'}</div></div>
                    <div class="receipt-item"><div class="label">내용</div><div class="value" style="white-space:pre-wrap;line-height:1.6">${item.description || item.content || '-'}</div></div>
                    <div class="receipt-item"><div class="label">등록일</div><div class="value">${formatDate(item.created_at || item.date)}</div></div>
                </div>
                ${imageHtml}
                ${item.file_url ? `<div style="margin-top:var(--space-4)"><a href="${item.file_url}" class="btn btn-outline" target="_blank">📎 파일 다운로드</a></div>` : ''}
            </div>
        `;
    }
    
    // Update approve button
    const approveBtn = document.getElementById('parentApproveBtn');
    if (approveBtn) {
        if (item.status === 'approved') {
            approveBtn.textContent = '✅ 이미 승인됨';
            approveBtn.disabled = true;
            approveBtn.style.opacity = '0.6';
        } else {
            approveBtn.textContent = '✅ 승인';
            approveBtn.disabled = false;
            approveBtn.style.opacity = '1';
        }
    }
    
    openModal('detailModal');
}

// ===== 학부모 포트폴리오 승인 =====
async function approveChildPortfolio() {
    const item = window._currentChildPortfolio;
    if (!item) { showAlert('포트폴리오를 선택해주세요.', 'danger'); return; }
    if (item.status === 'approved') {
        showAlert('이미 승인된 포트폴리오입니다.', 'info');
        return;
    }
    try {
        await apiPost(`/portfolio/${item.id}/publish`, { status: 'published' });
        await apiPut(`/portfolio/${item.id}`, { status: 'approved' });
        showAlert('✅ 포트폴리오를 승인했습니다!', 'success');
        closeModal('detailModal');
        refreshPortfolio();
    } catch(e) {
        console.error('Approve error:', e);
        showAlert('승인 중 오류가 발생했습니다.', 'danger');
    }
}

// ===== 인쇄 =====
function printPortfolioView() {
    const printArea = document.createElement('div');
    printArea.id = 'printAreaTemp';
    printArea.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(printArea);
    
    const sel = document.getElementById('childSelect');
    const childName = sel && sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : '포트폴리오';
    
    let html = '<div style="padding:40px;font-family:sans-serif">';
    html += `<h1 style="text-align:center;margin-bottom:20px">📁 ${childName} 포트폴리오</h1>`;
    html += `<p style="text-align:center;color:#666;margin-bottom:30px">출력일: ${new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })}</p>`;
    
    const container = document.getElementById('portfolioContainer');
    if (container) {
        const cards = container.querySelectorAll('.portfolio-card');
        cards.forEach(card => {
            const title = card.querySelector('h3')?.textContent || '제목 없음';
            const info = card.querySelector('.small-text')?.textContent || '';
            html += `
                <div style="border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:20px;page-break-inside:avoid;">
                    <h2 style="margin:0 0 8px 0;font-size:18px">${esc(title)}</h2>
                    <div style="font-size:12px;color:#666">${esc(info)}</div>
                </div>
            `;
        });
    }
    html += '</div>';
    
    printArea.innerHTML = html;
    printArea.style.position = 'absolute';
    printArea.style.left = '0';
    printArea.style.top = '0';
    printArea.style.width = '100%';
    window.print();
    document.body.removeChild(printArea);
}

function printDetail() {
    const detailContent = document.getElementById('detailContent');
    if (!detailContent) return;
    const printArea = document.createElement('div');
    printArea.style.cssText = 'padding:40px;font-family:sans-serif';
    printArea.innerHTML = detailContent.innerHTML;
    const w = window.open();
    w.document.write(`<html><head><title>포트폴리오 상세</title></head><body>${printArea.outerHTML}</body></html>`);
    w.document.close();
    w.print();
}

// ============================================================
// 상담 신청 (counseling.html)
// ============================================================
let _counselChildren = [];
let _counselData = [];

async function loadCounseling() {
    try {
        const children = await apiGetData('/parent/children');
        _counselChildren = children || [];

        // Populate child selector in modal
        const counselSel = document.getElementById('counselChild');
        if (counselSel) {
            counselSel.innerHTML = '<option value="">선택</option>';
            (children || []).forEach(c => {
                counselSel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            });
        }

        // Fetch consultations
        const consultations = await apiGetData('/parent/consultations').catch(() => []);
        const list = Array.isArray(consultations) ? consultations : (consultations?.consultations || []);
        _counselData = list;

        // Stats
        setText('totalRequests', formatNumber(list.length));
        setText('pendingRequests', formatNumber(list.filter(c => c.status === 'pending' || c.status === 'waiting').length));
        setText('completedRequests', formatNumber(list.filter(c => c.status === 'completed' || c.status === 'done').length));

        // Table (7 cols: 자녀, 제목, 유형, 희망일, 상태, 답변, 관리)
        renderTable('counselBody', list, [
            {
                key: 'child_name',
                label: '자녀',
                render: v => {
                    if (v) return v;
                    // Try to find from children list
                    return '-';
                }
            },
            { key: 'title', label: '제목' },
            {
                key: 'type',
                label: '유형',
                render: v => {
                    const map = { academic: '학습 상담', career: '진로 상담', behavior: '생활 상담', other: '기타' };
                    return map[v] || v || '-';
                }
            },
            { key: 'desired_date', label: '희망일', render: v => formatDate(v) },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'reply', label: '답변', render: v => v || '-' },
            {
                key: 'id',
                label: '관리',
                render: (v, row) => {
                    if (row.status === 'pending' || row.status === 'waiting') {
                        return `<button class="btn btn-sm btn-ghost" onclick="deleteCounsel('${v}')">취소</button>`;
                    }
                    return '-';
                }
            }
        ]);
    } catch(e) {
        console.error('loadCounseling error:', e);
        setHtml('counselBody', '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-tertiary)">데이터를 불러올 수 없습니다.</td></tr>');
    }
}

function openCounselModal() {
    document.getElementById('editCounselId').value = '';
    document.getElementById('counselTitle').value = '';
    document.getElementById('counselType').value = 'academic';
    document.getElementById('counselDate').value = '';
    document.getElementById('counselContent').value = '';
    document.querySelector('#counselModal h2').textContent = '상담 신청';
    openModal('counselModal');
}

// Save counsel form
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('counselForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                const childId = document.getElementById('counselChild').value;
                if (!childId) {
                    alert('자녀를 선택해주세요.');
                    return;
                }
                const data = {
                    child_id: childId,
                    title: document.getElementById('counselTitle').value,
                    type: document.getElementById('counselType').value,
                    desired_date: document.getElementById('counselDate').value,
                    content: document.getElementById('counselContent').value
                };
                await apiPost('/parent/consultations', data);
                closeModal('counselModal');
                loadCounseling();
            } catch(err) {
                alert('상담 신청 중 오류가 발생했습니다: ' + err.message);
            }
        });
    }
});

async function deleteCounsel(id) {
    if (!confirm('정말 취소하시겠습니까?')) return;
    try {
        await apiDelete(`/parent/consultations/${id}`);
        loadCounseling();
    } catch(e) {
        alert('취소 중 오류가 발생했습니다.');
    }
}

// ============================================================
// 결제 내역 (payments.html)
// ============================================================
async function loadPayments() {
    try {
        const children = await apiGetData('/parent/children');
        const sel = document.getElementById('filterChild');
        if (sel) {
            const currentVal = sel.value;
            sel.innerHTML = '<option value="">전체 자녀</option>';
            (children || []).forEach(c => {
                sel.innerHTML += `<option value="${c.id}" ${c.id == currentVal ? 'selected' : ''}>${c.name}</option>`;
            });
        }

        // Fetch payments
        const resp = await apiGet('/parent/payments');
        const paymentsData = resp?.data || resp?.payments || [];
        const list = Array.isArray(paymentsData) ? paymentsData : [];

        // Stats
        const totalAmount = list.reduce((s, p) => s + (Number(p.amount) || 0), 0);
        setText('totalPaid', formatCurrency(totalAmount));
        setText('completedCount', formatNumber(list.filter(p => p.status === 'completed' || p.status === 'paid').length));
        setText('pendingCount', formatNumber(list.filter(p => p.status === 'pending' || p.status === 'unpaid' || p.status === 'failed').length));
        setText('unpaidAmount', formatCurrency(
            list.filter(p => p.status === 'pending' || p.status === 'unpaid' || p.status === 'failed')
                .reduce((s, p) => s + (Number(p.amount) || 0), 0)
        ));

        // Filter by child if selected
        let filtered = list;
        if (sel && sel.value) {
            filtered = list.filter(p => String(p.child_id) === sel.value || String(p.student_id) === sel.value);
        }

        // Table (8 cols: 자녀, 구분, 금액, 방법, 상태, 결제일, 만료일, 관리)
        renderTable('paymentBody', filtered, [
            { key: 'child_name', label: '자녀', render: v => v || '-' },
            { key: 'category', label: '구분', render: v => v || '-' },
            { key: 'amount', label: '금액', render: v => formatCurrency(v) },
            { key: 'method', label: '방법', render: v => {
                const map = { card: '카드', kakao: '카카오페이', toss: '토스페이', naver: '네이버페이', virtual_account: '가상계좌', transfer: '계좌이체' };
                return map[v] || v || '-';
            }},
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'paid_at', label: '결제일', render: v => formatDate(v) },
            { key: 'expires_at', label: '만료일', render: v => formatDate(v) },
            {
                key: 'id',
                label: '관리',
                render: (v, row) => {
                    return `<button class="btn btn-sm btn-outline" onclick="viewReceipt('${v}')">상세</button>`;
                }
            }
        ]);
    } catch(e) {
        console.error('loadPayments error:', e);
    }
}

async function viewReceipt(id) {
    try {
        const resp = await apiGet('/parent/payments');
        const list = resp?.data || resp?.payments || [];
        const payment = Array.isArray(list) ? list.find(p => String(p.id) === String(id)) : null;
        if (!payment) {
            alert('결제 정보를 찾을 수 없습니다.');
            return;
        }

        setText('receiptTid', payment.tid || payment.transaction_id || '-');
        setText('receiptMethod', payment.method || '-');
        setText('receiptStudent', payment.child_name || payment.student_name || '-');
        setText('receiptCategory', payment.category || '-');
        setText('receiptAmount', formatCurrency(payment.amount));
        setText('receiptStatus', statusBadge(payment.status));
        setText('receiptDate', formatDateTime(payment.paid_at || payment.created_at));
        setText('receiptDue', formatDate(payment.expires_at));
        setText('receiptUser', payment.registrant || payment.created_by || '-');
        setText('receiptNote', payment.note || payment.remark || '-');

        // Show/hide retry button based on status
        const isFailed = payment.status === 'failed' || payment.status === 'pending' || payment.status === 'unpaid';
        document.getElementById('receiptFailedAction').style.display = isFailed ? 'flex' : 'none';
        document.getElementById('receiptNormalAction').style.display = isFailed ? 'none' : 'flex';

        // Store payment id for retry
        if (isFailed) {
            document.getElementById('repayFromReceiptBtn').dataset.paymentId = id;
        }

        openModal('receiptModal');
    } catch(e) {
        console.error('viewReceipt error:', e);
    }
}

function retryPayment() {
    const btn = document.getElementById('repayFromReceiptBtn');
    const paymentId = btn?.dataset?.paymentId;
    if (paymentId) {
        // Redirect to pay-tuition page or show re-pay flow
        window.location.href = 'pay-tuition.html?retry=' + paymentId;
    }
}

// ============================================================
// 수강료 결제 (pay-tuition.html)
// ============================================================
let _tuitionChildren = [];
let _selectedMethod = null;

async function loadPayTuition() {
    try {
        const children = await apiGetData('/parent/children');
        _tuitionChildren = children || [];

        const sel = document.getElementById('childSelect');
        if (sel) {
            sel.innerHTML = '<option value="">자녀를 선택하세요</option>';
            (children || []).forEach(c => {
                sel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            });
        }

        setText('todayDate', new Date().toLocaleDateString('ko-KR', {
            year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
        }));
    } catch(e) {
        console.error('loadPayTuition error:', e);
    }
}

async function loadCourses() {
    const childId = document.getElementById('childSelect')?.value;
    const courseSel = document.getElementById('courseSelect');
    const courseInfo = document.getElementById('courseInfo');

    if (!courseSel) return;

    if (!childId) {
        courseSel.innerHTML = '<option value="">과정을 선택하세요</option>';
        if (courseInfo) courseInfo.style.display = 'none';
        document.getElementById('payButton').disabled = true;
        return;
    }

    try {
        // Try to get courses/progress for the child
        const progress = await apiGetData(`/parent/children/${childId}/progress`).catch(() => null);
        const courses = progress?.courses || progress?.subjects || [];

        courseSel.innerHTML = '<option value="">과정을 선택하세요</option>';
        if (Array.isArray(courses) && courses.length > 0) {
            courses.forEach(c => {
                courseSel.innerHTML += `<option value="${c.id}" data-amount="${c.price || c.amount || 0}" data-name="${c.name || c.title || ''}" data-period="${c.period || c.duration || ''}">${c.name || c.title || '과정'}</option>`;
            });
        } else {
            // Fallback: add a default course option
            courseSel.innerHTML += `<option value="default" data-amount="0" data-name="일반 과정" data-period="1개월">일반 과정</option>`;
        }

        if (courseInfo) courseInfo.style.display = 'none';
        document.getElementById('payButton').disabled = true;
    } catch(e) {
        console.error('loadCourses error:', e);
    }
}

function updateAmount() {
    const courseSel = document.getElementById('courseSelect');
    const courseInfo = document.getElementById('courseInfo');
    const childSel = document.getElementById('childSelect');

    if (!courseSel || !courseInfo) return;

    const opt = courseSel.options[courseSel.selectedIndex];
    if (!opt || !opt.value) {
        courseInfo.style.display = 'none';
        document.getElementById('payButton').disabled = true;
        return;
    }

    const amount = Number(opt.dataset.amount) || 0;
    const name = opt.dataset.name || '';
    const period = opt.dataset.period || '';
    const child = _tuitionChildren.find(c => c.id == childSel?.value);

    setText('courseName', name);
    setText('coursePeriod', period || '1개월');
    setText('courseStudent', child?.name || '-');
    setText('courseAmount', formatCurrency(amount));

    courseInfo.style.display = 'block';
    document.getElementById('payButton').disabled = !_selectedMethod || amount <= 0;
}

function selectMethod(el) {
    document.querySelectorAll('.pay-method-card').forEach(c => c.classList.remove('active'));
    if (el) {
        el.classList.add('active');
        _selectedMethod = el.dataset.method;
    }
    // Re-check pay button state
    const courseSel = document.getElementById('courseSelect');
    const opt = courseSel?.options[courseSel.selectedIndex];
    const amount = opt ? Number(opt.dataset.amount) || 0 : 0;
    document.getElementById('payButton').disabled = !_selectedMethod || amount <= 0;
}

function processPayment() {
    const childSel = document.getElementById('childSelect');
    const courseSel = document.getElementById('courseSelect');
    const opt = courseSel?.options[courseSel.selectedIndex];

    if (!childSel?.value || !opt?.value || !_selectedMethod) {
        alert('모든 항목을 선택해주세요.');
        return;
    }

    const child = _tuitionChildren.find(c => c.id == childSel.value);
    const amount = Number(opt.dataset.amount) || 0;

    // Show confirmation modal
    setText('confirmCourse', opt.dataset.name || '-');
    setText('confirmStudent', child?.name || '-');
    setText('confirmMethod', document.querySelector('.pay-method-card.active')?.querySelector('.method-label')?.textContent || _selectedMethod);
    setText('confirmDate', new Date().toLocaleDateString('ko-KR'));
    setText('confirmAmount', formatCurrency(amount));
    setText('confirmVat', '포함');

    // Hide success, show confirm
    document.getElementById('confirmContent').style.display = 'block';
    document.getElementById('confirmSuccess').style.display = 'none';
    document.getElementById('confirmActions').style.display = 'flex';
    document.getElementById('successActions').style.display = 'none';

    openModal('confirmModal');
}

async function executePayment() {
    const childSel = document.getElementById('childSelect');
    const courseSel = document.getElementById('courseSelect');
    const opt = courseSel?.options[courseSel.selectedIndex];

    try {
        const data = {
            child_id: childSel.value,
            course_id: opt.value,
            method: _selectedMethod,
            amount: Number(opt.dataset.amount) || 0,
            name: opt.dataset.name || ''
        };

        const result = await apiPost('/parent/payments', data);

        // Show success
        document.getElementById('confirmContent').style.display = 'none';
        document.getElementById('confirmActions').style.display = 'none';
        document.getElementById('confirmSuccess').style.display = 'block';
        document.getElementById('successActions').style.display = 'flex';

        setText('successTid', result?.tid || result?.transaction_id || 'TXN' + Date.now());
        setText('successMethod', document.querySelector('.pay-method-card.active')?.querySelector('.method-label')?.textContent || _selectedMethod);
        setText('successAmount', formatCurrency(data.amount));
        setText('successDate', formatDateTime(new Date()));
    } catch(e) {
        alert('결제 처리 중 오류가 발생했습니다: ' + e.message);
    }
}

function resetForm() {
    if (document.getElementById('childSelect')) document.getElementById('childSelect').value = '';
    if (document.getElementById('courseSelect')) {
        document.getElementById('courseSelect').innerHTML = '<option value="">과정을 선택하세요</option>';
    }
    if (document.getElementById('courseInfo')) document.getElementById('courseInfo').style.display = 'none';
    document.getElementById('payButton').disabled = true;
    _selectedMethod = null;
    document.querySelectorAll('.pay-method-card').forEach(c => c.classList.remove('active'));
}
