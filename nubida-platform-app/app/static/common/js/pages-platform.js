// ============================================================
// 누비다플랫폼 v2 Premium — 플랫폼관리(Platform) 페이지 스크립트
// API: system, analytics, logs
// ============================================================
// ===== 초기화: 모든 페이지 공통 =====

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

document.addEventListener('DOMContentLoaded', () => {
    requireAuth();
    renderSidebarUser();
    initPage();
});

function initPage() {
    const page = window.location.pathname.split('/').pop().replace('.html', '');
    switch(page) {
        case 'dashboard': loadDashboard(); break;
        case 'system': loadSystem(); break;
        case 'analytics': loadAnalytics(); break;
        case 'logs': loadLogs(); break;
    }
}

// ===== 대시보드 =====
async function loadDashboard() {
    try {
        const status = await apiGet('/platform/system/status');
        setText('totalUsers', formatNumber(status?.total_users || status?.totalUsers || 0));
        setText('activeSessions', formatNumber(status?.active_sessions || status?.activeSessions || 0));
        setText('todayVisits', formatNumber(status?.today_visits || status?.todayVisits || 0));
        setText('serverStatus', status?.server_status || status?.serverStatus || '-');

        // 기관 현황 테이블
        if (status?.organizations || status?.org_stats) {
            const orgs = status.organizations || status.org_stats || [];
            renderTable('orgStatsBody', orgs, [
                { key: 'type', render: v => v },
                { key: 'count', render: v => formatNumber(v) },
            ]);
        }

        // 시스템 요약
        const summaryEl = document.getElementById('systemSummary');
        if (summaryEl && status) {
            summaryEl.innerHTML = `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                    <div><strong>플랫폼</strong><br><span style="color:var(--text-tertiary)">${status.version || status.platform_version || '-'}</span></div>
                    <div><strong>가동 시간</strong><br><span style="color:var(--text-tertiary)">${status.uptime || '-'}</span></div>
                    <div><strong>CPU</strong><br><span style="color:var(--text-tertiary)">${status.cpu_usage != null ? status.cpu_usage + '%' : '-'}</span></div>
                    <div><strong>메모리</strong><br><span style="color:var(--text-tertiary)">${status.memory_usage != null ? status.memory_usage + '%' : '-'}</span></div>
                </div>
            `;
        }

        // 최근 활동
        if (status?.recent_activities || status?.activities) {
            const activities = status.recent_activities || status.activities || [];
            renderTable('activityBody', activities, [
                { key: 'time', render: v => formatDateTime(v) },
                { key: 'user', render: v => v },
                { key: 'action', render: v => v },
                { key: 'detail', render: v => v || '-' },
            ]);
        }
    } catch(e) { console.error('Dashboard error:', e); }
}

// ===== 시스템 상태 (설정 불러오기) =====
async function loadSystem() {
    try {
        const config = await apiGet('/platform/system/status');

        // 보안 설정
        const inputMapping = {
            'jwtExpiry': config?.jwt_expiry ?? config?.jwtExpiry ?? 1440,
            'maxLoginAttempts': config?.max_login_attempts ?? config?.maxLoginAttempts ?? 5,
            'require2fa': config?.require_2fa ?? config?.require2fa ?? true,
            'ipRestriction': config?.ip_restriction ?? config?.ipRestriction ?? false,
        };
        Object.entries(inputMapping).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (el.type === 'checkbox') {
                el.checked = !!val;
            } else {
                el.value = val;
            }
        });

        // 알림 설정
        const smtpMapping = {
            'smtpHost': config?.smtp_host ?? config?.smtpHost ?? 'smtp.gmail.com',
            'smtpPort': config?.smtp_port ?? config?.smtpPort ?? 587,
            'smtpEmail': config?.smtp_email ?? config?.smtpEmail ?? '',
            'emailNotification': config?.email_notification ?? config?.emailNotification ?? true,
        };
        Object.entries(smtpMapping).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (el.type === 'checkbox') {
                el.checked = !!val;
            } else {
                el.value = val;
            }
        });

        // 결제 설정
        const paymentMapping = {
            'paymentCycle': config?.payment_cycle ?? config?.paymentCycle ?? 'monthly',
            'paymentDueDay': config?.payment_due_day ?? config?.paymentDueDay ?? '15',
            'lateFee': config?.late_fee ?? config?.lateFee ?? 5,
        };
        Object.entries(paymentMapping).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        });

        // 기타 설정
        const miscMapping = {
            'systemLang': config?.system_lang ?? config?.systemLang ?? 'ko',
            'timezone': config?.timezone ?? 'Asia/Seoul',
            'backupInterval': config?.backup_interval ?? config?.backupInterval ?? '12',
        };
        Object.entries(miscMapping).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        });
    } catch(e) { console.error('System load error:', e); }
}

// ===== 분석 =====
async function loadAnalytics() {
    try {
        const periodEl = document.getElementById('analyticsPeriod');
        const period = periodEl ? periodEl.value : '30d';

        const params = new URLSearchParams({ period });

        // 사용자 통계
        const users = await apiGet(`/platform/analytics/users?${params}`);
        setText('newUsers', formatNumber(users?.new_users ?? users?.newUsers ?? 0));
        setText('newBranches', formatNumber(users?.new_branches ?? users?.newBranches ?? 0));
        setText('newStudents', formatNumber(users?.new_students ?? users?.newStudents ?? 0));

        // 매출 통계
        const revenue = await apiGet(`/platform/analytics/revenue?${params}`);
        setText('totalRevenue', formatCurrency(revenue?.total_revenue ?? revenue?.totalRevenue ?? 0));

        // 일별 차트 (막대 그래프)
        const chartData = users?.daily || revenue?.daily || [];
        const chartEl = document.getElementById('dailyChart');
        if (chartEl) {
            if (chartData.length === 0) {
                chartEl.innerHTML = '<p style="color:var(--text-tertiary);text-align:center;width:100%">데이터가 없습니다.</p>';
            } else {
                const maxVal = Math.max(...chartData.map(d => d.count || d.value || 0), 1);
                chartEl.innerHTML = chartData.map(d => {
                    const val = d.count || d.value || 0;
                    const pct = (val / maxVal) * 100;
                    const label = d.date || d.label || '';
                    return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;height:180px;justify-content:flex-end">
                        <span style="font-size:0.65rem;color:var(--text-tertiary);margin-bottom:2px">${formatNumber(val)}</span>
                        <div style="width:100%;max-width:32px;height:${pct}%;min-height:4px;border-radius:3px 3px 0 0;background:var(--accent);opacity:0.8"></div>
                        <span style="font-size:0.6rem;color:var(--text-tertiary);margin-top:4px;transform:rotate(-30deg);white-space:nowrap">${label}</span>
                    </div>`;
                }).join('');
            }
        }

        // 지사별 통계
        const branches = users?.branches || revenue?.branches || [];
        renderTable('branchStatsBody', branches, [
            { key: 'name', render: v => v || '-' },
            { key: 'students', render: v => formatNumber(v || 0) },
            { key: 'revenue', render: v => formatCurrency(v || 0) },
            { key: 'growth', render: v => v != null ? `${v > 0 ? '+' : ''}${v}%` : '-' },
        ]);

        // 상세 통계
        const details = users?.details || revenue?.details || [];
        renderTable('detailStatsBody', details, [
            { key: 'metric', render: v => v || '-' },
            { key: 'current', render: v => formatNumber(v ?? 0) },
            { key: 'previous', render: v => formatNumber(v ?? 0) },
            { key: 'change', render: v => v != null ? `${v > 0 ? '+' : ''}${v}%` : '-' },
        ]);
    } catch(e) { console.error('Analytics error:', e); }
}

// ===== 로그 =====
let _cachedLogs = []; // filterLogs용 캐시

async function loadLogs() {
    try {
        const levelEl = document.getElementById('logLevel');
        const catEl = document.getElementById('logCategory');
        const searchEl = document.getElementById('logSearch');

        const params = new URLSearchParams();
        if (levelEl && levelEl.value) params.set('level', levelEl.value);
        if (catEl && catEl.value) params.set('category', catEl.value);
        if (searchEl && searchEl.value) params.set('search', searchEl.value);

        const data = await apiGet(`/audit/logs?${params}`);
        const logs = data?.logs || data?.data || data || [];

        _cachedLogs = Array.isArray(logs) ? logs : [];

        const countEl = document.getElementById('logCount');
        if (countEl) countEl.textContent = `총 ${formatNumber(_cachedLogs.length)}개`;

        renderLogTable(_cachedLogs);
    } catch(e) { console.error('Logs error:', e); }
}

function renderLogTable(logs) {
    renderTable('logBody', logs, [
        { key: 'timestamp', render: v => formatDateTime(v) },
        { key: 'level', render: v => statusBadge((v || '').toLowerCase()) },
        { key: 'category', render: v => v || '-' },
        { key: 'message', render: v => esc(v || '') },
        { key: 'user', render: v => v || '-' },
    ]);
}

function filterLogs() {
    const searchEl = document.getElementById('logSearch');
    const query = (searchEl?.value || '').toLowerCase().trim();

    if (!query) {
        renderLogTable(_cachedLogs);
        const countEl = document.getElementById('logCount');
        if (countEl) countEl.textContent = `총 ${formatNumber(_cachedLogs.length)}개`;
        return;
    }

    const filtered = _cachedLogs.filter(log =>
        (log.message || '').toLowerCase().includes(query) ||
        (log.user || '').toLowerCase().includes(query) ||
        (log.category || '').toLowerCase().includes(query)
    );

    renderLogTable(filtered);
    const countEl = document.getElementById('logCount');
    if (countEl) countEl.textContent = `검색 결과 ${formatNumber(filtered.length)}개`;
}
