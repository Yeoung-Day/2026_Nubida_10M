// ============================================================
// 누비다플랫폼 v2 Premium — 지사운영(Branch) 페이지 스크립트
// API: dashboard, revenue, courses, employees, payments, schedule
// ============================================================

// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: 숫자 포맷 (utils.js fallback) =====
function formatNumber(n) {
    if (n == null) return '-';
    return Number(n).toLocaleString('ko-KR');
}

function formatCurrency(n) {
    if (n == null) return '-';
    return '₩' + Number(n).toLocaleString('ko-KR');
}

// ===== Helper: 날짜 포맷 (utils.js fallback) =====
function formatDate(d) {
    if (!d) return '-';
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

// ===== Helper: HTML 이스케이프 (utils.js fallback) =====
function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
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
        'scheduled': ['info', '예정'],
        'live':      ['success', '진행중'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 학년 한글 레이블 =====
function gradeLabel(grade) {
    const map = {
        'e1': '초1', 'e2': '초2', 'e3': '초3',
        'e4': '초4', 'e5': '초5', 'e6': '초6',
        'm1': '중1', 'm2': '중2', 'm3': '중3',
        'h1': '고1', 'h2': '고2', 'h3': '고3',
    };
    return map[grade] || grade || '-';
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
        case 'revenue': loadRevenue(); break;
        case 'employees': loadEmployees(); break;
        case 'courses': loadCourses(); break;
        case 'students': loadStudents(); break;
        case 'studios': loadStudios(); break;
        case 'schedule': loadSchedule(); break;
        case 'settings': loadSettings(); break;
        case 'portfolio': loadPortfolio(); break;
    }
}

// ===== Helper: branch_id from current user =====
function getBranchId() {
    try {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        return user.branch_id || null;
    } catch { return null; }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        const stats = await apiGet('/branch/dashboard/stats');
        const s = stats?.data || stats;
        setText('totalCourses', formatNumber(s?.total_courses ?? s?.totalCourses ?? 0));
        setText('totalStudents', formatNumber(s?.total_students ?? s?.totalStudents ?? 0));
        setText('totalDirectors', formatNumber(s?.total_employees ?? s?.directors ?? 0));
        setText('monthlyRevenue', formatCurrency(s?.monthly_revenue ?? s?.monthlyRevenue ?? 0));

        // 강좌별 현황
        const courses = await apiGet('/branch/courses');
        const courseList = courses?.data || courses?.items || courses || [];
        if (Array.isArray(courseList)) {
            renderTable('courseStatusBody', courseList.slice(0, 10), [
                { key: 'name', render: v => esc(v || '-') },
                { key: 'category', render: v => esc(v || '-') },
                { key: 'status', render: v => statusBadge(v) },
            ]);
        }

        // 최근 매출 (revenue API 사용 — user/course JOIN 포함)
        try {
            const rev = await apiGet('/branch/revenue?period=month&per_page=5');
            const payments = rev?.data?.payments || rev?.data || rev?.items || [];
            if (Array.isArray(payments)) {
                renderTable('revenueBody', payments, [
                    { key: 'item', label: '내역', render: v => esc(v || '-') },
                    { key: 'amount', label: '금액', render: v => formatCurrency(v) },
                    { key: 'status', render: v => statusBadge(v) },
                ]);
            }
        } catch(e) { /* revenue table optional */ }
    } catch(e) { console.error('Dashboard error:', e); }
}

// ============================================================
// 수강생 관리 (director/classes/{id}/students 집계)
// ============================================================
let allStudents = [];

async function loadStudents() {
    try {
        const res = await apiGet('/branch/students?per_page=100');
        let list = res?.data || res?.items || [];
        if (!Array.isArray(list) && res?.data?.data) list = res.data.data;
        if (!Array.isArray(list)) list = [];

        allStudents = list.map(s => ({
            id: s.id,
            name: s.name,
            phone: s.phone || '-',
            grade: s.grade || '-',
            director_name: s.director_name || '-',
            courses: Array.isArray(s.courses) ? s.courses : [],
            created_at: s.created_at || null,
            status: s.status || 'inactive',
        }));

        // 통계 업데이트
        const now = new Date();
        const thisMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
        const activeStudents = allStudents.filter(s => s.status === 'active');
        const newThisMonth = allStudents.filter(s => {
            if (!s.created_at) return false;
            const d = new Date(s.created_at);
            const ym = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
            return ym === thisMonth;
        });

        setText('totalStudents', formatNumber(allStudents.length));
        setText('activeStudents', formatNumber(activeStudents.length));
        setText('courseCount', formatNumber(new Set(allStudents.flatMap(s => s.courses || [])).size));
        setText('newStudents', formatNumber(newThisMonth.length));

        renderStudentTable(allStudents);
        setupStudentForm();
    } catch(e) { console.error('Students error:', e); }
}

function renderStudentTable(students) {
    renderTable('studentBody', students, [
        { key: 'id', render: v => v },
        { key: 'name', render: v => esc(v) },
        { key: 'phone', render: v => esc(v) },
        { key: 'director_name', render: v => esc(v || '-') },
        { key: 'grade', render: v => gradeLabel(v) },
        { key: 'courses', render: v => Array.isArray(v) ? v.map(c => esc(c)).join(', ') : esc(v || '-') },
        { key: 'created_at', render: v => formatDate(v) },
        { key: 'status', render: v => statusBadge(v) },
        { key: 'id', render: (v, row) => {
            const sid = v != null ? v : (row && row.id);
            return `
            <div class="action-buttons">
                <button class="btn btn-sm btn-outline" onclick="editStudent(${sid})">수정</button>
                <button class="btn btn-sm btn-danger" onclick="deleteStudent(${sid})">삭제</button>
            </div>
            `;
        }},
    ]);
}

function openStudentModal() {
    document.getElementById('studentModalTitle').textContent = '수강생 등록';
    document.getElementById('editStudentId').value = '';
    document.getElementById('studentForm').reset();
    openModal('studentModal');
}

function editStudent(id) {
    const student = allStudents.find(s => s.id === id);
    if (!student) return;
    document.getElementById('studentModalTitle').textContent = '수강생 수정';
    document.getElementById('editStudentId').value = student.id;
    document.getElementById('stName').value = student.name || '';
    document.getElementById('stGrade').value = student.grade || '';
    document.getElementById('stPhone').value = student.phone || '';
    document.getElementById('stAddress').value = student.address || '';
    document.getElementById('stNote').value = student.note || '';
    openModal('studentModal');
}

async function deleteStudent(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/branch/students/${id}`);
        showAlert('삭제되었습니다.', 'success');
        loadStudents();
    } catch(e) {
        showAlert(e.message || '삭제 실패', 'error');
    }
}

function setupStudentForm() {
    const form = document.getElementById('studentForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const editId = document.getElementById('editStudentId').value;
        const data = {
            name: document.getElementById('stName').value,
            grade: document.getElementById('stGrade').value,
            phone: document.getElementById('stPhone').value,
            address: document.getElementById('stAddress').value,
            note: document.getElementById('stNote').value,
        };
        try {
            if (editId) {
                await apiPut(`/branch/students/${editId}`, data);
                showAlert('수정되었습니다.', 'success');
            } else {
                data.branch_id = getBranchId();
                await apiPost('/branch/students', data);
                showAlert('등록되었습니다.', 'success');
            }
            closeModal('studentModal');
            loadStudents();
        } catch(e) {
            showAlert(e.message || '저장 실패', 'error');
        }
    };
}

// ============================================================
// 공부방 관리 (studios)
// ============================================================
let allStudios = [];
let studioDirectors = [];

async function loadStudios() {
    try {
        // 1. 원장/강사 계정 목록 조회 (담당자 선택용)
        try {
            const dirRes = await apiGet('/headquarters/users?role=director');
            studioDirectors = dirRes?.data || dirRes?.items || dirRes || [];
            if (!Array.isArray(studioDirectors)) {
                // try another endpoint
                const teacherRes = await apiGet('/headquarters/users?role=teacher');
                const teachers = teacherRes?.data || teacherRes?.items || teacherRes || [];
                studioDirectors = Array.isArray(teachers) ? teachers : [];
            }
        } catch(e) {
            console.warn('Could not fetch directors:', e.message);
            studioDirectors = [];
        }

        // 2. 공부방 목록 조회
        const branchId = getBranchId();
        const params = branchId ? `?branch_id=${branchId}` : '';
        const res = await apiGet(`/branch/studios${params}`);
        const studios = res?.data || res?.items || res || [];
        allStudios = Array.isArray(studios) ? studios : [];

        // 3. 통계 업데이트
        const activeStudios = allStudios.filter(s => s.status === 'active');
        const totalStudents = allStudios.reduce((sum, s) => sum + (parseInt(s.student_count) || 0), 0);
        const totalCourses = allStudios.reduce((sum, s) => sum + (parseInt(s.course_count) || 0), 0);

        setText('totalStudios', formatNumber(allStudios.length));
        setText('activeStudios', formatNumber(activeStudios.length));
        setText('totalStudents', formatNumber(totalStudents));
        setText('totalCourses', formatNumber(totalCourses));

        // 4. 테이블 렌더링
        renderStudioTable(allStudios);
        setupStudioForm();
        populateDirectorSelect();
    } catch(e) { console.error('Studios error:', e); }
}

function renderStudioTable(studios) {
    renderTable('studioBody', studios, [
        { key: 'name', render: v => esc(v || '-') },
        { key: 'director_name', render: v => esc(v || '-') },
        { key: 'phone', render: v => esc(v || '-') },
        { key: 'student_count', render: v => formatNumber(v ?? 0) },
        { key: 'course_count', render: v => formatNumber(v ?? 0) },
        { key: 'status', render: v => statusBadge(v) },
        { key: 'id', render: (v) => `
            <div class="action-buttons">
                <button class="btn btn-sm btn-outline" onclick="editStudio(${v})">수정</button>
                <button class="btn btn-sm btn-danger" onclick="deleteStudio(${v})">삭제</button>
            </div>
        `},
    ]);
}

function populateDirectorSelect() {
    const select = document.getElementById('studioDirectorId');
    if (!select) return;
    select.innerHTML = '<option value="">선택하세요</option>';
    studioDirectors.forEach(d => {
        const option = document.createElement('option');
        option.value = d.id;
        option.textContent = `${d.name || d.username || '이름없음'} (${d.email || '-'})`;
        select.appendChild(option);
    });
}

function openStudioModal() {
    document.getElementById('studioModalTitle').textContent = '공부방 등록';
    document.getElementById('editStudioId').value = '';
    document.getElementById('studioForm').reset();
    document.getElementById('studioStatus').value = 'active';
    populateDirectorSelect();
    openModal('studioModal');
}

function editStudio(id) {
    const studio = allStudios.find(s => s.id === id);
    if (!studio) return;
    document.getElementById('studioModalTitle').textContent = '공부방 수정';
    document.getElementById('editStudioId').value = studio.id;
    document.getElementById('studioName').value = studio.name || '';
    document.getElementById('studioDirectorId').value = studio.director_id || '';
    document.getElementById('studioPhone').value = studio.phone || '';
    document.getElementById('studioAddress').value = studio.address || '';
    document.getElementById('studioStatus').value = studio.status || 'active';
    populateDirectorSelect();
    if (studio.director_id) {
        document.getElementById('studioDirectorId').value = studio.director_id;
    }
    openModal('studioModal');
}

function deleteStudio(id) {
    document.getElementById('deleteStudioId').value = id;
    openModal('deleteStudioModal');
}

async function confirmDeleteStudio() {
    const id = document.getElementById('deleteStudioId').value;
    if (!id) return;
    try {
        await apiDelete(`/branch/studios/${id}`);
        showAlert('삭제되었습니다.', 'success');
        closeModal('deleteStudioModal');
        loadStudios();
    } catch(e) {
        showAlert(e.message || '삭제 실패', 'error');
    }
}

function setupStudioForm() {
    const form = document.getElementById('studioForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const editId = document.getElementById('editStudioId').value;
        const data = {
            name: document.getElementById('studioName').value,
            director_id: parseInt(document.getElementById('studioDirectorId').value) || null,
            phone: document.getElementById('studioPhone').value,
            address: document.getElementById('studioAddress').value,
            status: document.getElementById('studioStatus').value,
        };
        try {
            if (editId) {
                await apiPut(`/branch/studios/${editId}`, data);
                showAlert('수정되었습니다.', 'success');
            } else {
                data.branch_id = getBranchId();
                await apiPost('/branch/studios', data);
                showAlert('등록되었습니다.', 'success');
            }
            closeModal('studioModal');
            loadStudios();
        } catch(e) {
            showAlert(e.message || '저장 실패', 'error');
        }
    };
}

// ============================================================
// 매출 관리
// ============================================================
async function loadRevenue() {
    try {
        const branchId = getBranchId();
        let params = branchId ? `?branch_id=${branchId}` : '';
        const period = document.getElementById('revPeriod')?.value || 'month';
        if (period !== 'all') params += (params ? '&' : '?') + `period=${period}`;

        const res = await apiGet(`/branch/revenue${params}`);
        const data = res?.data || res || {};
        const payments = data?.payments || [];
        const stats = data?.stats || {};
        allPayments = payments;  // store for edit

        // 통계 (서버에서 계산된 값 사용)
        setText('todayRevenue', formatCurrency(stats.today_revenue ?? 0));
        setText('monthRevenue', formatCurrency(stats.total_revenue ?? 0));
        setText('monthCount', formatNumber(stats.total_count ?? 0));
        setText('pendingAmount', formatCurrency(stats.pending_revenue ?? 0));

        // 테이블 렌더링
        if (Array.isArray(payments)) {
            renderTable('revenueBody', payments, [
                { key: 'id', render: v => v },
                { key: 'paid_at', label: '일자', render: v => formatDate(v) },
                { key: 'item', label: '항목', render: v => esc(v || '-') },
                { key: 'member', label: '회원', render: v => esc(v || '-') },
                { key: 'amount', render: v => formatCurrency(v) },
                { key: 'method', render: v => {
                    const m = { 'card': '카드', 'transfer': '계좌이체', 'cash': '현금', 'virtual': '가상계좌' };
                    return m[v] || v || '-';
                }},
                { key: 'status', render: v => statusBadge(v) },
                { key: 'id', render: (v, row) => `
                    <div class="action-buttons">
                        <button class="btn btn-sm btn-outline" onclick="editRevenue(${v})">수정</button>
                        <button class="btn btn-sm btn-danger" onclick="deleteRevenue(${v})">삭제</button>
                    </div>
                `},
            ]);
        }

        setupRevenueForm();
    } catch(e) { console.error('Revenue error:', e); }
}

function openRevenueModal() {
    document.getElementById('revenueForm').reset();
    openModal('revenueModal');
}

function setupRevenueForm() {
    const form = document.getElementById('revenueForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const data = {
            amount: parseFloat(document.getElementById('revAmount').value) || 0,
            method: document.getElementById('revMethod').value,
            item: document.getElementById('revItem').value,
            member: document.getElementById('revMember').value,
            note: document.getElementById('revNote').value,
            branch_id: getBranchId(),
        };
        try {
            await apiPost('/branch/revenue', data);
            showAlert('매출이 등록되었습니다.', 'success');
            closeModal('revenueModal');
            loadRevenue();
        } catch(e) {
            showAlert(e.message || '등록 실패', 'error');
        }
    };
}

// ===== 매출 수정 =====
let allPayments = [];

function editRevenue(id) {
    const pay = allPayments.find(p => p.id === id);
    if (!pay) { showAlert('데이터를 찾을 수 없습니다.', 'error'); return; }
    document.getElementById('editRevenueId').value = pay.id;
    document.getElementById('editRevAmount').value = pay.amount || 0;
    document.getElementById('editRevMethod').value = pay.method || 'card';
    document.getElementById('editRevItem').value = pay.item || pay.receipt_number || '';
    document.getElementById('editRevStatus').value = pay.status || 'completed';
    openModal('editRevenueModal');
}

function setupEditRevenueForm() {
    const form = document.getElementById('editRevenueForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const id = document.getElementById('editRevenueId').value;
        if (!id) return;
        const data = {
            amount: parseFloat(document.getElementById('editRevAmount').value) || 0,
            method: document.getElementById('editRevMethod').value,
            item: document.getElementById('editRevItem').value,
            status: document.getElementById('editRevStatus').value,
        };
        try {
            await apiPut(`/branch/revenue/${id}`, data);
            showAlert('수정되었습니다.', 'success');
            closeModal('editRevenueModal');
            loadRevenue();
        } catch(e) { showAlert(e.message || '수정 실패', 'error'); }
    };
}

function deleteRevenue(id) {
    if (!confirm('정말 이 매출 내역을 삭제하시겠습니까?')) return;
    apiDelete(`/branch/revenue/${id}`).then(() => {
        showAlert('삭제되었습니다.', 'success');
        loadRevenue();
    }).catch(e => showAlert(e.message || '삭제 실패', 'error'));
}

// ============================================================
// 원장 관리
// ============================================================
async function loadEmployees() {
    try {
        const branchId = getBranchId();
        const params = branchId ? `?branch_id=${branchId}` : '';
        const res = await apiGet(`/branch/employees${params}`);
        const employees = res?.data || res || [];

        if (Array.isArray(employees)) {
            // employees.html has no table body — just log or render if container exists
            const tbody = document.getElementById('employeeBody');
            if (tbody) {
                renderTable('employeeBody', employees, [
                    { key: 'id', render: v => v },
                    { key: 'name', render: v => esc(v) },
                    { key: 'role', render: v => {
                        const labels = { 'branch_admin': '에듀케어', 'branch_manager': '에듀케어 관리자', 'director': '원장', 'teacher': '강사' };
                        return labels[v] || v || '-';
                    }},
                    { key: 'phone', render: v => esc(v || '-') },
                    { key: 'email', render: v => esc(v || '-') },
                    { key: 'is_active', render: v => {
                        return v === false ? '<span class="badge badge-warning">비활성</span>' : '<span class="badge badge-success">활성</span>';
                    }},
                    { key: 'id', render: v => `<button class="btn btn-xs btn-ghost" onclick="editEmployee(${v})">✏️</button><button class="btn btn-xs btn-danger" onclick="deleteEmployee(${v})">🗑️</button>` },
                ]);
            }
        }
    } catch(e) { console.error('Employees error:', e); }
}

// ============================================================
// 강좌 관리
// ============================================================
let allCourses = [];

async function loadCourses() {
    try {
        const branchId = getBranchId();
        const params = branchId ? `?branch_id=${branchId}&category=maker_coding` : '?category=maker_coding';
        const res = await apiGet(`/branch/courses${params}`);
        const courses = res?.data || res?.items || res || [];

        if (Array.isArray(courses)) {
            allCourses = courses;
            // courses.html is placeholder — render if table body exists
            const tbody = document.getElementById('courseBody');
            if (tbody) {
                renderTable('courseBody', courses, [
                    { key: 'id', render: v => v },
                    { key: 'name', render: v => esc(v) },
                    { key: 'subject', render: v => esc(v || '-') },
                    { key: 'teacher', render: v => esc(v || '-') },
                    { key: 'price', render: v => formatCurrency(v) },
                    { key: 'max_capacity', label: '정원', render: v => formatNumber(v) },
                    { key: 'status', render: v => statusBadge(v) },
                    { key: 'id', render: (v, row) => `
                        <div class="action-buttons">
                            <button class="btn btn-sm btn-outline" onclick="openArduinoCode(${v},'${esc(row?.name||'')}')">🤖 코딩</button>
                            <button class="btn btn-sm btn-outline" onclick="editCourse(${v})">수정</button>
                            <button class="btn btn-sm btn-danger" onclick="deleteCourse(${v})">삭제</button>
                        </div>
                    `},
                ]);
            }
            setupCourseForm();
        }
    } catch(e) { console.error('Courses error:', e); }
}

function openCourseModal() {
    document.getElementById('courseModalTitle').textContent = '강좌 등록';
    document.getElementById('editCourseId').value = '';
    document.getElementById('courseForm')?.reset();
    openModal('courseModal');
}

function editCourse(id) {
    const course = allCourses.find(c => c.id === id);
    if (!course) return;
    document.getElementById('courseModalTitle').textContent = '강좌 수정';
    document.getElementById('editCourseId').value = course.id;
    ['courseName','courseSubject','courseTeacher','coursePrice','courseCapacity'].forEach(f => {
        const el = document.getElementById(f);
        if (el) el.value = course[el.dataset?.field || f.replace('course', '').toLowerCase()] || '';
    });
    openModal('courseModal');
}

async function deleteCourse(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/branch/courses/${id}`);
        showAlert('삭제되었습니다.', 'success');
        loadCourses();
    } catch(e) { showAlert(e.message || '삭제 실패', 'error'); }
}

function setupCourseForm() {
    const form = document.getElementById('courseForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const editId = document.getElementById('editCourseId')?.value;
        const data = {
            name: document.getElementById('courseName')?.value,
            subject: document.getElementById('courseSubject')?.value,
            teacher: document.getElementById('courseTeacher')?.value,
            price: parseFloat(document.getElementById('coursePrice')?.value || 0),
            max_capacity: parseInt(document.getElementById('courseCapacity')?.value || 0),
            branch_id: getBranchId(),
        };
        try {
            if (editId) {
                await apiPut(`/branch/courses/${editId}`, data);
                showAlert('수정되었습니다.', 'success');
            } else {
                await apiPost('/branch/courses', data);
                showAlert('등록되었습니다.', 'success');
            }
            closeModal('courseModal');
            loadCourses();
        } catch(e) { showAlert(e.message || '저장 실패', 'error'); }
    };
}

// ============================================================
// 일정 관리
// ============================================================
async function loadSchedule() {
    try {
        const branchId = getBranchId();
        const params = branchId ? `?branch_id=${branchId}` : '';

        // 1. 일정 데이터 조회 (GET /branch/schedule)
        const schedRes = await apiGet(`/branch/schedule${params}`);
        const schedData = schedRes?.data || schedRes?.items || [];
        const schedules = Array.isArray(schedData) ? schedData : [];

        // 2. 강좌 정보 병합 (course_name 조회용)
        const coursesRes = await apiGet(`/branch/courses${params}`);
        const courses = coursesRes?.data || coursesRes?.items || coursesRes || [];
        const courseMap = {};
        if (Array.isArray(courses)) {
            courses.forEach(c => { if (c.id) courseMap[c.id] = c; });
        }

        // 3. 원격 수업 조회
        let remoteClasses = [];
        try {
            const rcRes = await apiGet('/classroom');
            remoteClasses = rcRes?.data || rcRes?.items || [];
        } catch(e) { /* optional */ }

        // 금주 레이블
        const weekLabel = document.getElementById('weekLabel');
        if (weekLabel) {
            const now = new Date();
            const startOfWeek = new Date(now);
            startOfWeek.setDate(now.getDate() - now.getDay());
            const endOfWeek = new Date(startOfWeek);
            endOfWeek.setDate(startOfWeek.getDate() + 6);
            weekLabel.textContent = `${formatDate(startOfWeek)} ~ ${formatDate(endOfWeek)}`;
        }

        // 요일명 매핑
        const dayNames = ['일','월','화','수','목','금','토'];
        const days = ['일요일','월요일','화요일','수요일','목요일','금요일','토요일'];

        // 4. 일정 테이블 렌더링 (DB 저장된 일정 우선)
        const scheduleItems = [];

        // 4a. class_schedules에서 가져온 일정
        if (Array.isArray(schedules) && schedules.length > 0) {
            schedules.forEach(s => {
                const course = courseMap[s.course_id];
                const dow = s.day_of_week != null ? s.day_of_week : 0;
                const dayName = dayNames[dow] || '-';
                scheduleItems.push({
                    id: s.id,
                    day: dayName,
                    time: s.start_time || '-',
                    course_name: (course && course.name) || s.title || (s.course_name || '일반 일정'),
                    teacher: (course && course.instructor) || s.teacher_name || '-',
                    room: s.room || (course && course.location) || '-',
                    students: (course && (course.student_count || course.enrolled_count)) || 0,
                    title: s.title || '',
                    description: s.description || '',
                    date: s.date || '',
                });
            });
        }

        // 4b. 강좌 기반 일정 (courses.schedule)
        if (Array.isArray(courses)) {
            courses.filter(c => c.schedule).forEach(c => {
                // 중복 체크: 이미 추가된 course_id가 있는지 확인
                const exists = scheduleItems.some(item =>
                    item.course_name === c.name && item.day === (c.schedule?.day || (c.schedule || '').split(' ')[0] || '-')
                );
                if (exists) return;
                const dayStr = c.schedule?.day || (c.schedule || '').split(' ')[0] || '-';
                const timeStr = c.schedule?.time || (c.schedule || '').split(' ')[1] || '-';
                scheduleItems.push({
                    day: dayStr,
                    time: timeStr,
                    course_name: c.name,
                    teacher: c.teacher || c.instructor || '-',
                    room: c.room || '-',
                    students: c.student_count || c.enrolled_count || 0,
                    title: '',
                    description: '',
                    date: '',
                });
            });
        }

        // 4c. 원격 수업 일정도 추가
        if (Array.isArray(remoteClasses)) {
            remoteClasses.forEach(rc => {
                if (rc.scheduled_at) {
                    const d = new Date(rc.scheduled_at);
                    scheduleItems.push({
                        day: dayNames[d.getDay()],
                        time: d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }),
                        course_name: rc.title || '원격 수업',
                        teacher: rc.teacher_name || '-',
                        room: '온라인',
                        students: rc.max_participants || '-',
                        title: '',
                        description: '',
                        date: '',
                    });
                }
            });
        }

        // 요일 순 정렬
        const dayOrder = { '일':0,'월':1,'화':2,'수':3,'목':4,'금':5,'토':6 };
        scheduleItems.sort((a, b) => (dayOrder[a.day] ?? 0) - (dayOrder[b.day] ?? 0));

        renderTable('scheduleBody', scheduleItems, [
            { key: 'day', render: v => `<strong>${esc(v)}</strong>` },
            { key: 'time', render: v => esc(v) },
            { key: 'course_name', label: '강좌명', render: v => esc(v) },
            { key: 'teacher', render: v => esc(v) },
            { key: 'room', label: '강의실', render: v => esc(v) },
            { key: 'students', label: '수강생', render: v => formatNumber(v) },
            { key: 'id', render: (v, row) => {
                const sid = v;
                if (sid == null) return '-';
                return `
                <div class="action-buttons">
                    <button class="btn btn-sm btn-outline" onclick="editSchedule(${sid})">수정</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${sid})">삭제</button>
                </div>
                `;
            }},
        ]);

        // 오늘의 일정
        const todaySchedule = document.getElementById('todaySchedule');
        if (todaySchedule) {
            const today = new Date();
            const todayDayName = dayNames[today.getDay()];
            const todayItems = scheduleItems.filter(item => item.day === todayDayName);

            if (todayItems.length > 0) {
                todaySchedule.innerHTML = todayItems.map(item =>
                    `<div class="schedule-item">📚 ${esc(item.course_name)} (${esc(item.time)})</div>`
                ).join('');
                todaySchedule.className = 'card-body';
            } else {
                todaySchedule.innerHTML = '오늘은 수업이 없습니다';
                todaySchedule.className = 'card-body flex-center';
            }
        }

        setupQuickSchedule();
        setupScheduleForm();
    } catch(e) { console.error('Schedule error:', e); }
}

function openScheduleModal(schedule) {
    const titleEl = document.getElementById('scheduleModalTitle');
    const btnEl = document.getElementById('scheduleSubmitBtn');
    const editIdEl = document.getElementById('editScheduleId');
    if (schedule) {
        // Edit mode
        titleEl.textContent = '일정 수정';
        btnEl.textContent = '수정';
        editIdEl.value = schedule.id || '';
        document.getElementById('modalSchedTitle').value = schedule.title || schedule.course_name || '';
        document.getElementById('modalSchedDate').value = schedule.date || '';
        document.getElementById('modalSchedTime').value = schedule.time || '';
        document.getElementById('modalSchedDesc').value = schedule.description || '';
    } else {
        // Create mode
        titleEl.textContent = '일정 등록';
        btnEl.textContent = '등록';
        editIdEl.value = '';
        document.getElementById('scheduleForm').reset();
    }
    openModal('scheduleModal');
}

function editSchedule(id) {
    // Find the schedule from the already loaded data via API call
    apiGet(`/branch/schedule?per_page=200`).then(res => {
        const list = res?.data || res?.items || [];
        const sched = Array.isArray(list) ? list.find(s => s.id === id) : null;
        if (sched) {
            openScheduleModal(sched);
        } else {
            showAlert('일정 정보를 불러올 수 없습니다.', 'error');
        }
    }).catch(e => {
        showAlert(e.message || '조회 실패', 'error');
    });
}

function deleteSchedule(id) {
    document.getElementById('deleteScheduleId').value = id;
    openModal('deleteScheduleModal');
}

async function confirmDeleteSchedule() {
    const id = document.getElementById('deleteScheduleId').value;
    if (!id) return;
    try {
        await apiDelete(`/branch/schedule/${id}`);
        showAlert('일정이 삭제되었습니다.', 'success');
        closeModal('deleteScheduleModal');
        loadSchedule();
    } catch(e) {
        showAlert(e.message || '삭제 실패', 'error');
    }
}

function setupQuickSchedule() {
    const form = document.getElementById('quickScheduleForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const data = {
            title: document.getElementById('qsTitle').value,
            date: document.getElementById('qsDate').value,
            time: document.getElementById('qsTime').value,
            branch_id: getBranchId(),
        };
        try {
            await apiPost('/branch/schedule', data);
            showAlert('일정이 추가되었습니다.', 'success');
            form.reset();
            loadSchedule();
        } catch(e) { showAlert(e.message || '등록 실패', 'error'); }
    };
}

function setupScheduleForm() {
    const form = document.getElementById('scheduleForm');
    if (!form) return;
    form.onsubmit = async (e) => {
        e.preventDefault();
        const editId = document.getElementById('editScheduleId').value;
        const data = {
            title: document.getElementById('modalSchedTitle').value,
            date: document.getElementById('modalSchedDate').value,
            time: document.getElementById('modalSchedTime').value,
            description: document.getElementById('modalSchedDesc').value,
            branch_id: getBranchId(),
        };
        try {
            if (editId) {
                await apiPut(`/branch/schedule/${editId}`, data);
                showAlert('일정이 수정되었습니다.', 'success');
            } else {
                await apiPost('/branch/schedule', data);
                showAlert('일정이 등록되었습니다.', 'success');
            }
            closeModal('scheduleModal');
            loadSchedule();
        } catch(e) { showAlert(e.message || '저장 실패', 'error'); }
    };
}

// ============================================================
// 설정
// ============================================================
async function loadSettings() {
    try {
        const branchId = getBranchId();
        if (!branchId) return;

        // 지사 정보를 어디서 가져올까? backend/api/v1/headquarters.py 에 branch CRUD 있음
        // 또는 settings page의 info table은 정적 정보 표시
        // branch 정보 GET이 필요 — HEADQUARTERS 엔드포인트 활용
        try {
            const res = await apiGet(`/headquarters/branches/${branchId}`);
            const branch = res?.data || res;
            if (branch) {
                setText('branchId', branch.id || '-');
                setText('branchStatus', branch.status || '-');
                setText('branchCreatedAt', formatDate(branch.created_at));
                setText('branchStudentCount', formatNumber(branch.student_count || 0));
                setText('branchEmpCount', formatNumber(branch.employee_count || 0));

                document.getElementById('branchName').value = branch.name || '';
                document.getElementById('branchHead').value = branch.head_name || branch.representative || '';
                document.getElementById('branchPhone').value = branch.phone || '';
                document.getElementById('branchHours').value = branch.hours || branch.operating_hours || '';
                document.getElementById('branchAddress').value = branch.address || '';
            }
        } catch(e) {
            // branch info not available via this endpoint — try getting from user profile
            console.warn('Could not load branch settings from API:', e.message);
        }

        // 알림 설정 로드 (로컬 스토리지 또는 API)
        try {
            const notifRes = await apiGet(`/branch/notifications?branch_id=${branchId}`);
            const notif = notifRes?.data || notifRes;
            if (notif) {
                document.getElementById('notifyPayment').checked = notif.payment !== false;
                document.getElementById('notifyAttendance').checked = notif.attendance !== false;
                document.getElementById('notifySchedule').checked = notif.schedule === true;
            }
        } catch(e) { /* use defaults */ }

    } catch(e) { console.error('Settings error:', e); }
}

async function saveBranchSettings() {
    const branchId = getBranchId();
    const data = {
        name: document.getElementById('branchName').value,
        head_name: document.getElementById('branchHead').value,
        phone: document.getElementById('branchPhone').value,
        operating_hours: document.getElementById('branchHours').value,
        address: document.getElementById('branchAddress').value,
    };

    // 알림 설정
    const notifData = {
        payment: document.getElementById('notifyPayment').checked,
        attendance: document.getElementById('notifyAttendance').checked,
        schedule: document.getElementById('notifySchedule').checked,
    };

    try {
        if (branchId) {
            await apiPut(`/headquarters/branches/${branchId}`, data);
        }
        await apiPost(`/branch/notifications`, { branch_id: branchId, ...notifData });
        showAlert('설정이 저장되었습니다.', 'success');
        loadSettings();
    } catch(e) {
        showAlert(e.message || '저장 실패', 'error');
    }
}

let portfolioItems = [];
let portfolioTags = [];
let uploadedImages = [];

// ============================================================
// 포트폴리오 조회 (지사 → 소속 공부방/학생 포트폴리오 확인)
// ============================================================
async function loadPortfolio() {
    try {
        const res = await apiGet('/portfolio');
        const items = res?.data || res?.items || (Array.isArray(res) ? res : []);
        portfolioItems = Array.isArray(items) ? items : [];
        if (!Array.isArray(items)) return;
        
        // Render table view
        const columns = [
            { key: 'title', label: '제목' },
            { key: 'student_name', label: '학생', render: v => v || '-' },
            { key: 'subject', label: '과목', render: v => v || '-' },
            { key: 'file_type', label: '유형', render: v => v || '-' },
            { key: 'is_published', label: '공개', render: v => v ? '✅' : '🔒' },
            { key: 'created_at', label: '등록일', render: v => formatDate(v) },
            { key: 'id', label: '액션', render: (v, row) => `<button class="btn btn-text btn-sm" onclick="viewPortfolioDetail(${v})">보기</button>` },
        ];
        renderTable('tableBody', items, columns);
        
        // Grid view
        renderPortfolioGrid(items);
        
        // Update filters
        populateFilters(items);
    } catch(e) { console.error('Portfolio load error:', e); }
}

function renderPortfolioGrid(items) {
    const grid = document.getElementById('portfolioGridView');
    if (!grid) return;
    if (!items || items.length === 0) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><p>포트폴리오가 없습니다.</p></div>';
        return;
    }
    grid.innerHTML = items.map(item => `
        <div class="portfolio-card" onclick="viewPortfolioDetail(${item.id})">
            ${item.image_urls && item.image_urls.length
                ? `<div class="portfolio-thumb"><img src="${esc(item.image_urls[0])}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-lg)"></div>`
                : `<div class="portfolio-thumb">${item.file_type === 'image' ? '🖼️' : item.file_type === 'video' ? '🎬' : '📄'}</div>`}
            <div class="portfolio-info">
                <div class="portfolio-title">${esc(item.title)}</div>
                <div class="portfolio-meta">${esc(item.student_name || '')} · ${esc(item.subject || '')}</div>
                <div class="portfolio-date">${formatDate(item.created_at)}</div>
            </div>
            <div style="display:flex;gap:4px;flex-shrink:0" onclick="event.stopPropagation()">
                <button class="btn btn-text btn-sm" onclick="editPortfolio(${item.id})">✏️</button>
                <button class="btn btn-text btn-sm" onclick="deletePortfolio(${item.id})">🗑️</button>
            </div>
        </div>
    `).join('');
}

function populateFilters(items) {
    const courseFilter = document.getElementById('filterCourse');
    const studentFilter = document.getElementById('filterStudent');
    if (!courseFilter && !studentFilter) return;
    
    const courses = [...new Set(items.map(i => i.course_name).filter(Boolean))];
    const students = [...new Set(items.map(i => i.student_name).filter(Boolean))];
    
    if (courseFilter) {
        courseFilter.innerHTML = '<option value="">전체 클래스</option>' + 
            courses.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    }
    if (studentFilter) {
        studentFilter.innerHTML = '<option value="">전체 학생</option>' + 
            students.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    }
}

function setView(view) {
    const grid = document.getElementById('portfolioGridView');
    const table = document.getElementById('portfolioTableView');
    if (!grid || !table) return;
    
    if (view === 'grid') {
        grid.style.display = '';
        table.style.display = 'none';
    } else {
        grid.style.display = 'none';
        table.style.display = '';
    }
    
    document.querySelectorAll('.vt-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.view === view);
    });
}

function onFilterChange() {
    // Client-side filtering
    const course = document.getElementById('filterCourse')?.value || '';
    // Re-fetch and filter
    loadPortfolio();
}

function resetFilters() {
    const course = document.getElementById('filterCourse');
    const student = document.getElementById('filterStudent');
    if (course) course.value = '';
    if (student) student.value = '';
    loadPortfolio();
}

async function viewPortfolioDetail(id) {
    try {
        const res = await apiGet(`/portfolio/${id}`);
        const item = res?.data || res;
        if (!item) return;
        
        const content = document.getElementById('detailContent');
        if (content) {
            content.innerHTML = `
                <h2>${esc(item.title)}</h2>
                ${item.content ? `<div class="portfolio-detail-content">${esc(item.content)}</div>` : ''}
                ${item.description ? `<p>${esc(item.description || '')}</p>` : ''}
                <div class="detail-meta">
                    <span>👤 ${esc(item.student_name || '')}</span>
                    <span>📂 ${esc(item.subject || '')}</span>
                    <span>📅 ${formatDate(item.created_at)}</span>
                </div>
                ${item.image_urls && item.image_urls.length ? `
                <div class="portfolio-detail-images">
                    ${item.image_urls.map(u => `<img src="${esc(u)}" alt="첨부 이미지">`).join('')}
                </div>` : ''}
                ${item.tags && item.tags.length ? `
                <div style="margin-top:12px;display:flex;gap:4px;flex-wrap:wrap">
                    ${item.tags.map(t => `<span class="badge badge-info">${esc(t)}</span>`).join('')}
                </div>` : ''}
            `;
        }
        openModal('detailModal');
    } catch(e) {
        console.error('Detail load error:', e);
    }
}

// ============================================================
// 포트폴리오 CRUD (Create/Update/Delete)
// ============================================================

function openAddModal() {
    document.getElementById('modalTitle').textContent = '새 포트폴리오 항목';
    document.getElementById('editId').value = '';
    document.getElementById('portTitle').value = '';
    document.getElementById('portContent').value = '';
    document.getElementById('portSubject').value = '';
    document.getElementById('portFileType').value = 'image';
    document.getElementById('portFileUrl').value = '';
    document.getElementById('portDescription').value = '';
    document.getElementById('portPublic').checked = true;
    document.getElementById('imageUrls').value = '[]';
    document.getElementById('imagePreviewContainer').innerHTML = '';
    portfolioTags = [];
    renderTags();
    openModal('portfolioModal');
}

function editPortfolio(id) {
    const item = portfolioItems.find(i => String(i.id) === String(id));
    if (!item) return;

    document.getElementById('modalTitle').textContent = '포트폴리오 수정';
    document.getElementById('editId').value = id;
    document.getElementById('portTitle').value = item.title || '';
    document.getElementById('portContent').value = item.content || '';
    document.getElementById('portSubject').value = item.subject || '';
    document.getElementById('portFileType').value = item.file_type || 'image';
    document.getElementById('portFileUrl').value = item.file_url || '';
    document.getElementById('portDescription').value = item.description || '';
    document.getElementById('portPublic').checked = item.is_public !== false;
    portfolioTags = Array.isArray(item.tags) ? [...item.tags] : [];
    renderTags();
    // Load images
    const images = item.image_urls || [];
    document.getElementById('imageUrls').value = JSON.stringify(images);
    renderImagePreviews(images);
    openModal('portfolioModal');
}

async function savePortfolio() {
    const id = document.getElementById('editId').value;
    let imageUrls = [];
    try { imageUrls = JSON.parse(document.getElementById('imageUrls').value || '[]'); } catch(e) {}
    const data = {
        title: document.getElementById('portTitle').value.trim(),
        content: document.getElementById('portContent').value.trim(),
        subject: document.getElementById('portSubject').value,
        file_type: document.getElementById('portFileType').value,
        file_url: document.getElementById('portFileUrl').value.trim(),
        description: document.getElementById('portDescription').value.trim(),
        is_public: document.getElementById('portPublic').checked,
        tags: portfolioTags,
        image_urls: imageUrls,
    };

    if (!data.title) {
        showAlert('제목을 입력해주세요.', 'danger');
        return;
    }
    if (!data.subject) {
        showAlert('과목을 선택해주세요.', 'danger');
        return;
    }

    try {
        if (id) {
            await apiPut(`/portfolio/${id}`, data);
            showAlert('포트폴리오가 수정되었습니다.', 'success');
        } else {
            await apiPost('/portfolio', data);
            showAlert('포트폴리오가 추가되었습니다.', 'success');
        }
        closeModal('portfolioModal');
        loadPortfolio();
    } catch(e) {
        console.error('Save portfolio error:', e);
        showAlert('저장 중 오류가 발생했습니다.', 'danger');
    }
}

async function deletePortfolio(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/portfolio/${id}`);
        showAlert('삭제되었습니다.', 'success');
        loadPortfolio();
    } catch(e) {
        console.error('Delete portfolio error:', e);
        showAlert('삭제 중 오류가 발생했습니다.', 'danger');
    }
}

// ============================================================
// 포트폴리오 이미지 업로드 헬퍼
// ============================================================

function renderImagePreviews(urls) {
    uploadedImages = Array.isArray(urls) ? [...urls] : [];
    const container = document.getElementById('imagePreviewContainer');
    if (!container) return;
    if (uploadedImages.length === 0) { container.innerHTML = ''; return; }
    container.innerHTML = uploadedImages.map((url, i) =>
        `<div class="image-preview-item">
            <img src="${esc(url)}" alt="첨부 이미지 ${i+1}" class="image-preview-thumb"
                 onerror="this.parentElement.innerHTML='<span style=\\'padding:10px;color:#999\\'>⚠ 로드 실패</span>'">
            <button type="button" class="image-preview-remove" onclick="removePortfolioImage(${i})" title="삭제">×</button>
        </div>`
    ).join('');
}

function removePortfolioImage(index) {
    uploadedImages.splice(index, 1);
    document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
    renderImagePreviews(uploadedImages);
}

async function handleDrop(event) {
    const files = event.dataTransfer.files;
    if (files.length > 0) await uploadFiles(files);
}

async function handleFileSelect(event) {
    const files = event.target.files;
    if (files.length > 0) await uploadFiles(files);
    event.target.value = '';
}

async function uploadFiles(files) {
    for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        try {
            const formData = new FormData();
            formData.append('file', file);
            const token = localStorage.getItem('token') || localStorage.getItem('access_token');
            const res = await fetch('/api/v1/portfolio/upload', {
                method: 'POST',
                headers: token ? { 'Authorization': 'Bearer ' + token } : {},
                body: formData
            });
            const json = await res.json();
            if (json && json.status === 'success' && json.data && json.data.url) {
                uploadedImages.push(json.data.url);
                document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
                renderImagePreviews(uploadedImages);
            } else {
                showAlert('업로드 실패: ' + (json.message || ''), 'danger');
            }
        } catch(e) {
            showAlert('업로드 중 오류: ' + (e.message || ''), 'danger');
        }
    }
}

function handleTagKey(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        const input = document.getElementById('tagInput');
        const tag = input.value.trim();
        if (tag && !portfolioTags.includes(tag)) {
            portfolioTags.push(tag);
            renderTags();
        }
        input.value = '';
    }
}

function removeTag(tag) {
    portfolioTags = portfolioTags.filter(t => t !== tag);
    renderTags();
}

function renderTags() {
    const container = document.getElementById('tagList');
    if (!container) return;
    container.innerHTML = portfolioTags.map(t => `
        <span class="tag">
            ${esc(t)}
            <button type="button" class="tag-remove" onclick="removeTag('${esc(t)}')">&times;</button>
        </span>
    `).join('');
}
