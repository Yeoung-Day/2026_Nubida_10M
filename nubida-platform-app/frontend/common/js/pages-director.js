// ============================================================
// 누비다플랫폼 v2 Premium — 원장관리(Director) 페이지 스크립트
// API: /director/classes, /director/exams, /director/scores,
//      /director/attendance, /director/reports, /portfolio,
//      /videos, /classroom
// ============================================================
// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: 숫자 포맷 =====
function formatNumber(n) {
    if (n == null) return '-';
    return Number(n).toLocaleString('ko-KR');
}

// ===== Helper: 오늘 날짜 문자열 =====
function dateStr() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    const day = String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
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
        'live':      ['warning', '진행중'],
        'cancelled': ['danger', '취소'],
        'present':   ['success', '출석'],
        'late':      ['warning', '지각'],
        'absent':    ['danger', '결석'],
        'excused':   ['info', '공결'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 성적 등급 =====
function gradeFromScore(score) {
    if (score == null) return '-';
    const s = Number(score);
    if (s >= 90) return 'A';
    if (s >= 80) return 'B';
    if (s >= 70) return 'C';
    if (s >= 60) return 'D';
    return 'F';
}

// ===== 초기화 =====
document.addEventListener('DOMContentLoaded', () => {
    requireAuth();
    renderSidebarUser();
    initPage();
});

function initPage() {
    const page = window.location.pathname.split('/').pop().replace('.html', '');
    switch(page) {
        case 'dashboard': loadDashboard(); break;
        case 'classes': loadClasses(); break;
        case 'exams': loadExams(); break;
        case 'grades': loadGrades(); break;
        case 'attendance': loadAttendance(); break;
        case 'reports': loadReports(); break;
        case 'portfolio': loadPortfolio(); break;
        case 'videos': loadVideos(); break;
        case 'classroom': loadClassroom(); break;
    }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        const [classes, scores, exams, paymentSummary] = await Promise.all([
            apiGet('/director/classes'),
            apiGet('/director/scores'),
            apiGet('/director/exams'),
            apiGet('/director/payment-summary'),
        ]);

        // ★ API 응답 구조({status, data: [...]})에서 배열 추출
        const classesData = Array.isArray(classes) ? classes : (classes?.data || []);
        const examsData = Array.isArray(exams) ? exams : (exams?.data || []);
        const paymentData = paymentSummary?.data || paymentSummary || {};

        setText('totalClasses', formatNumber(classesData.length));
        const studentCount = classesData.reduce((sum, c) => sum + (Number(c.student_count) || 0), 0);
        setText('totalStudents', formatNumber(studentCount));
        setText('todayAttendance', '-');
        setText('weekExams', formatNumber(examsData.length));

        // Payment summary
        setText('totalEnrollments', formatNumber(paymentData.total_enrollments || 0));
        setText('paidCount', formatNumber(paymentData.paid || 0));
        setText('unpaidCount', formatNumber(paymentData.unpaid || 0));
        setText('totalPaidAmount', formatNumber(paymentData.total_paid_amount || 0) + '원');

        if (classesData.length) renderTable('classStatusBody', classesData, [
            { key: 'name', label: '학급' },
            { key: 'teacher_name', label: '담임' },
            { key: 'student_count', label: '인원', render: v => formatNumber(v) },
            { key: 'status', label: '출석률', render: () => '-' },
        ]);

    } catch(e) { console.error('Dashboard error:', e); }
}

// ============================================================
// 학급 관리 (classes.html)
// ============================================================
async function loadClasses() {
    try {
        const data = await apiGet('/director/classes');
        const classesData = Array.isArray(data) ? data : (data?.data || []);
        if (!classesData) return;

        // Stats
        const total = classesData.length || 0;
        const active = classesData.filter(c => c.status === 'active').length || 0;
        const totalStudents = classesData.reduce((s, c) => s + (Number(c.student_count) || 0), 0);
        const avg = total > 0 ? Math.round(totalStudents / total) : 0;
        setText('totalClasses', formatNumber(total));
        setText('activeClasses', formatNumber(active));
        setText('avgStudents', formatNumber(avg));

        // Table
        renderTable('classBody', classesData, [
            { key: 'id', label: 'ID', render: v => `<span class="small-text">${v}</span>` },
            { key: 'name', label: '학급명' },
            { key: 'teacher_name', label: '담임' },
            { key: 'course_name', label: '강좌' },
            { key: 'student_count', label: '인원', render: v => formatNumber(v) },
            { key: 'schedule', label: '요일/시간' },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'id', label: '관리', render: (v, row) => `
                <div class="action-btns">
                    <button class="btn btn-ghost btn-xs" onclick="editClass(${v})">✏️</button>
                    <button class="btn btn-ghost btn-xs" onclick="deleteClass(${v})">🗑️</button>
                </div>
            `},
        ]);
    } catch(e) { console.error('loadClasses error:', e); }
}

function openClassModal() {
    document.getElementById('editClassId').value = '';
    document.getElementById('classModalTitle').textContent = '학급 등록';
    document.getElementById('className').value = '';
    document.getElementById('classTeacher').value = '';
    document.getElementById('classCourse').value = '';
    document.getElementById('classCapacity').value = '15';
    document.getElementById('classStatus').value = 'active';
    openModal('classModal');
}

async function editClass(id) {
    try {
        const data = await apiGet('/director/classes');
        const classes = Array.isArray(data) ? data : (data?.data || []);
        const cls = classes.find(c => c.id == id);
        if (!cls) { showAlert('학급을 찾을 수 없습니다.', 'danger'); return; }
        document.getElementById('editClassId').value = id;
        document.getElementById('classModalTitle').textContent = '학급 수정';
        document.getElementById('className').value = cls.name || '';
        document.getElementById('classTeacher').value = cls.teacher_name || '';
        document.getElementById('classCourse').value = cls.course_id || '';
        document.getElementById('classCapacity').value = cls.capacity || '15';
        document.getElementById('classStatus').value = cls.status || 'active';
        openModal('classModal');
    } catch(e) { showAlert('학급 정보를 불러오지 못했습니다.', 'danger'); }
}

async function saveClass() {
    const id = document.getElementById('editClassId').value;
    const payload = {
        name: document.getElementById('className').value,
        teacher_name: document.getElementById('classTeacher').value,
        description: '',
        capacity: parseInt(document.getElementById('classCapacity').value) || 15,
        schedule: document.getElementById('classSchedule')?.value || '',
        status: document.getElementById('classStatus').value,
    };
    try {
        if (id) {
            await apiPut(`/director/classes/${id}`, payload);
            showAlert('학급이 수정되었습니다.');
        } else {
            await apiPost('/director/classes', payload);
            showAlert('학급이 등록되었습니다.');
        }
        closeModal('classModal');
        loadClasses();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function deleteClass(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/director/classes/${id}`);
        showAlert('삭제되었습니다.');
        loadClasses();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 시험 관리 (exams.html)
// ============================================================
async function loadExams() {
    try {
        const data = await apiGet('/director/exams');
        const exams = Array.isArray(data) ? data : (data?.data || []);
        if (!exams) return;

        const total = exams.length;
        const scheduled = exams.filter(e => e.status === 'scheduled').length;
        const progress = exams.filter(e => e.status === 'live' || e.status === 'in_progress').length;
        const completed = exams.filter(e => e.status === 'completed').length;

        setText('totalExams', formatNumber(total));
        setText('scheduledExams', formatNumber(scheduled));
        setText('progressExams', formatNumber(progress));
        setText('completedExams', formatNumber(completed));

        renderTable('examBody', exams, [
            { key: 'id', label: 'ID', render: v => `<span class="small-text">${v}</span>` },
            { key: 'name', label: '시험명' },
            { key: 'class_name', label: '학급' },
            { key: 'subject', label: '과목' },
            { key: 'exam_date', label: '일시', render: v => formatDate(v) },
            { key: 'student_count', label: '응시생', render: v => formatNumber(v) },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'id', label: '관리', render: (v) => `
                <div class="action-btns">
                    <button class="btn btn-ghost btn-xs" onclick="editExam(${v})">✏️</button>
                    <button class="btn btn-ghost btn-xs" onclick="deleteExam(${v})">🗑️</button>
                </div>
            `},
        ]);
    } catch(e) { console.error('loadExams error:', e); }
}

function openExamModal() {
    document.getElementById('editExamId').value = '';
    document.getElementById('examModalTitle').textContent = '시험 등록';
    document.getElementById('examName').value = '';
    document.getElementById('examClass').value = '';
    document.getElementById('examSubject').value = '';
    document.getElementById('examDate').value = dateStr();
    document.getElementById('examMaxScore').value = '100';
    document.getElementById('examDesc').value = '';
    openModal('examModal');
}

async function editExam(id) {
    try {
        const data = await apiGet('/director/exams');
        const exams = Array.isArray(data) ? data : (data?.data || []);
        const exam = exams.find(e => e.id == id);
        if (!exam) { showAlert('시험을 찾을 수 없습니다.', 'danger'); return; }
        document.getElementById('editExamId').value = id;
        document.getElementById('examModalTitle').textContent = '시험 수정';
        document.getElementById('examName').value = exam.name || '';
        document.getElementById('examClass').value = exam.class_id || '';
        document.getElementById('examSubject').value = exam.subject || '';
        document.getElementById('examDate').value = exam.exam_date ? exam.exam_date.slice(0,10) : '';
        document.getElementById('examMaxScore').value = exam.max_score || '100';
        document.getElementById('examDesc').value = exam.description || '';
        openModal('examModal');
    } catch(e) { showAlert('시험 정보를 불러오지 못했습니다.', 'danger'); }
}

async function saveExam() {
    const id = document.getElementById('editExamId').value;
    const payload = {
        name: document.getElementById('examName').value,
        class_id: parseInt(document.getElementById('examClass').value) || null,
        subject: document.getElementById('examSubject').value,
        exam_date: document.getElementById('examDate').value,
        max_score: parseInt(document.getElementById('examMaxScore').value) || 100,
        description: document.getElementById('examDesc').value,
    };
    try {
        if (id) {
            await apiPut(`/director/exams/${id}`, payload);
            showAlert('시험이 수정되었습니다.');
        } else {
            await apiPost('/director/exams', payload);
            showAlert('시험이 등록되었습니다.');
        }
        closeModal('examModal');
        loadExams();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function deleteExam(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/director/exams/${id}`);
        showAlert('삭제되었습니다.');
        loadExams();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 성적 관리 (grades.html)
// ============================================================
let _allGrades = [];

async function loadGrades() {
    try {
        const data = await apiGet('/director/scores');
        _allGrades = Array.isArray(data) ? data : (data?.data || []);
        loadGradeStats();
        renderGradeTable(_allGrades);
    } catch(e) { console.error('loadGrades error:', e); }
}

function loadGradeStats() {
    const classFilter = document.getElementById('filterClass')?.value;
    const examFilter = document.getElementById('filterExam')?.value;
    let filtered = [..._allGrades];
    if (classFilter) filtered = filtered.filter(g => String(g.class_id) === classFilter || g.class_name === classFilter);
    if (examFilter) filtered = filtered.filter(g => String(g.exam_id) === examFilter || g.exam_name === examFilter);

    const scores = filtered.map(g => Number(g.score)).filter(s => !isNaN(s));
    const total = filtered.length;
    const avg = scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
    const max = scores.length > 0 ? Math.max(...scores) : 0;
    const min = scores.length > 0 ? Math.min(...scores) : 0;

    setText('totalStudents', formatNumber(total));
    setText('avgScore', avg > 0 ? avg : '-');
    setText('maxScore', max > 0 ? max : '-');
    setText('minScore', min > 0 ? min : '-');
}

function filterGrades() {
    const q = (document.getElementById('gradeSearchInput')?.value || '').toLowerCase();
    if (!q) {
        renderGradeTable(_allGrades);
        loadGradeStats();
        return;
    }
    const filtered = _allGrades.filter(g =>
        (g.student_name || '').toLowerCase().includes(q)
    );
    renderGradeTable(filtered);
}

function renderGradeTable(grades) {
    renderTable('gradeBody', grades, [
        { key: 'student_name', label: '학생' },
        { key: 'class_name', label: '학급' },
        { key: 'exam_name', label: '시험' },
        { key: 'score', label: '점수', render: v => v != null ? v : '-' },
        { key: 'score', label: '등급', render: v => gradeFromScore(v) },
        { key: 'remark', label: '비고' },
        { key: 'id', label: '관리', render: (v) => `
            <div class="action-btns">
                <button class="btn btn-ghost btn-xs" onclick="editGrade(${v})">✏️</button>
                <button class="btn btn-ghost btn-xs" onclick="deleteGrade(${v})">🗑️</button>
            </div>
        `},
    ]);
}

function openGradeModal() {
    document.getElementById('editGradeId').value = '';
    document.getElementById('gradeModalTitle').textContent = '성적 입력';
    document.getElementById('gradeStudent').value = '';
    document.getElementById('gradeExam').value = '';
    document.getElementById('gradeScore').value = '';
    document.getElementById('gradeRemark').value = '';
    openModal('gradeModal');
}

async function editGrade(id) {
    try {
        const grade = _allGrades.find(g => g.id == id);
        if (!grade) { showAlert('성적을 찾을 수 없습니다.', 'danger'); return; }
        document.getElementById('editGradeId').value = id;
        document.getElementById('gradeModalTitle').textContent = '성적 수정';
        document.getElementById('gradeStudent').value = grade.student_id || grade.student_name || '';
        document.getElementById('gradeExam').value = grade.exam_id || '';
        document.getElementById('gradeScore').value = grade.score || '';
        document.getElementById('gradeRemark').value = grade.remark || '';
        openModal('gradeModal');
    } catch(e) { showAlert('성적 정보를 불러오지 못했습니다.', 'danger'); }
}

async function saveGrade() {
    const id = document.getElementById('editGradeId').value;
    const payload = {
        student_id: parseInt(document.getElementById('gradeStudent').value) || null,
        exam_id: parseInt(document.getElementById('gradeExam').value) || null,
        score: parseInt(document.getElementById('gradeScore').value) || 0,
        remark: document.getElementById('gradeRemark').value || '',
    };
    try {
        if (id) {
            await apiPut(`/director/scores/${id}`, payload);
            showAlert('성적이 수정되었습니다.');
        } else {
            await apiPost('/director/scores', payload);
            showAlert('성적이 입력되었습니다.');
        }
        closeModal('gradeModal');
        loadGrades();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function deleteGrade(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/director/scores/${id}`);
        showAlert('삭제되었습니다.');
        loadGrades();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 출결 관리 (attendance.html)
// ============================================================
async function loadAttendance() {
    try {
        // Load class filter options if not already loaded
        const filterClass = document.getElementById('filterClass');
        if (filterClass && filterClass.options.length <= 1) {
            const classes = await apiGet('/director/classes');
            const classList = classes.data || classes || [];
            if (Array.isArray(classList)) {
                classList.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.id;
                    opt.textContent = c.name;
                    filterClass.appendChild(opt);
                });
            }
        }

        const classFilter = filterClass?.value || '';
        const dateFilter = document.getElementById('filterDate')?.value || '';
        const statusFilter = document.getElementById('filterStatus')?.value || '';

        // Set default date to today if empty
        if (!dateFilter) {
            document.getElementById('filterDate').value = dateStr();
        }

        let path = '/director/attendance';
        const params = [];
        if (classFilter) params.push(`class_id=${classFilter}`);
        if (dateFilter || !dateFilter) params.push(`date=${document.getElementById('filterDate').value || dateStr()}`);
        if (statusFilter) params.push(`status=${statusFilter}`);
        if (params.length) path += '?' + params.join('&');

        const data = await apiGet(path);
        const records = data.data || [];

        // Stats
        const present = records.filter(r => r.status === 'present').length;
        const late = records.filter(r => r.status === 'late').length;
        const absent = records.filter(r => r.status === 'absent').length;
        const excused = records.filter(r => r.status === 'excused').length;
        const total = records.length;
        const rate = total > 0 ? Math.round((present / total) * 100) : 0;

        setText('statPresent', formatNumber(present));
        setText('statLate', formatNumber(late));
        setText('statAbsent', formatNumber(absent));
        setText('statExcused', formatNumber(excused));
        setText('statRate', rate + '%');

        renderTable('attendanceBody', records, [
            { key: 'student_name', label: '학생' },
            { key: 'class_name', label: '학급' },
            { key: 'date', label: '날짜', render: v => {
                if (!v) return '-';
                try { return new Date(v).toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }); }
                catch(e) { return v; }
            }},
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'remark', label: '비고' },
            { key: 'id', label: '관리', render: (v) => `
                <button class="btn btn-ghost btn-xs" onclick="deleteAttendance(${v})">🗑️</button>
            `},
        ]);
    } catch(e) { console.error('loadAttendance error:', e); }
}

async function openAttendanceModal() {
    document.getElementById('editAttId').value = '';
    document.getElementById('attModalTitle').textContent = '출석 기록';
    document.getElementById('attStudent').value = '';
    document.getElementById('attDate').value = dateStr();
    document.getElementById('attStatus').value = 'present';
    document.getElementById('attRate').value = '';
    document.getElementById('attRemark').value = '';
    openModal('attendanceModal');

    // ★ 학생 목록 로드
    try {
        const select = document.getElementById('attStudent');
        select.innerHTML = '<option value="">로딩 중...</option>';
        const filterClass = document.getElementById('filterClass')?.value;
        let res;
        if (filterClass) {
            res = await apiGet(`/director/classes/${filterClass}/students`);
        } else {
            res = await apiGet('/director/students/available');
        }
        const students = Array.isArray(res) ? res : (res.data || []);
        select.innerHTML = '<option value="">학생 선택</option>';
        students.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id || s.student_id;
            opt.textContent = s.name || s.student_name || '-';
            select.appendChild(opt);
        });
    } catch(e) {
        console.error('load students error:', e);
        document.getElementById('attStudent').innerHTML = '<option value="">학생 로드 실패</option>';
    }
}

async function saveAttendance() {
    const id = document.getElementById('editAttId').value;
    const payload = {
        student_id: parseInt(document.getElementById('attStudent').value) || null,
        date: document.getElementById('attDate').value,
        status: document.getElementById('attStatus').value,
        remark: document.getElementById('attRemark').value || '',
    };
    try {
        if (id) {
            await apiPut(`/director/attendance/${id}`, payload);
            showAlert('출석 정보가 수정되었습니다.');
        } else {
            // POST는 배열 형식 요구 — schedule_id 없으면 null로 전송
            await apiPost('/director/attendance', [{
                student_id: payload.student_id,
                schedule_id: null,
                date: payload.date,
                status: payload.status,
            }]);
            showAlert('출석이 기록되었습니다.');
        }
        closeModal('attendanceModal');
        loadAttendance();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function deleteAttendance(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/director/attendance/${id}`);
        showAlert('삭제되었습니다.');
        loadAttendance();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 보고서 (reports.html)
// ============================================================
async function loadReports() {
    try {
        const classFilter = document.getElementById('reportClass')?.value || '';
        const period = document.getElementById('reportPeriod')?.value || 'this_week';

        // Try to get class reports
        const classes = await apiGet('/director/classes');
        const classList = Array.isArray(classes) ? classes : (classes?.data || []);

        if (classFilter) {
            const filtered = classList.filter(c => String(c.id) === classFilter);
            renderTable('classReportBody', filtered, [
                { key: 'name', label: '학급' },
                { key: 'student_count', label: '인원', render: v => formatNumber(v) },
                { key: 'status', label: '출석률', render: () => '-' },
                { key: 'avg_score', label: '성적평균', render: () => '-' },
                { key: 'status', label: '종합', render: v => statusBadge(v) },
            ]);
        } else {
            renderTable('classReportBody', classList, [
                { key: 'name', label: '학급' },
                { key: 'student_count', label: '인원', render: v => formatNumber(v) },
                { key: 'status', label: '출석률', render: () => '-' },
                { key: 'avg_score', label: '성적평균', render: () => '-' },
                { key: 'status', label: '종합', render: v => statusBadge(v) },
            ]);
        }

        // Student trends
        const scores = await apiGet('/director/scores');
        const scoreList = Array.isArray(scores) ? scores : (scores?.data || []);
        const grouped = {};
        scoreList.forEach(s => {
            const name = s.student_name || '?';
            if (!grouped[name]) grouped[name] = [];
            grouped[name].push(s);
        });
        const trendData = Object.entries(grouped).map(([name, list]) => {
            const sorted = list.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
            const latest = sorted[0];
            const prev = sorted[1];
            let change = '-';
            if (latest && prev && latest.score != null && prev.score != null) {
                const diff = Number(latest.score) - Number(prev.score);
                change = diff > 0 ? `+${diff}` : String(diff);
            }
            return {
                student_name: name,
                exam_name: latest?.exam_name || '-',
                score: latest?.score ?? '-',
                change,
                remark: latest?.remark || '',
            };
        });
        renderTable('studentTrendBody', trendData, [
            { key: 'student_name', label: '학생' },
            { key: 'exam_name', label: '최근시험' },
            { key: 'score', label: '점수' },
            { key: 'change', label: '변화' },
            { key: 'remark', label: '비고' },
        ]);

        // Warning attendance
        renderTable('warningAttendanceBody', [], [
            { key: 'student_name', label: '학생' },
            { key: 'class_name', label: '학급' },
            { key: 'attendance_rate', label: '출석률' },
            { key: 'absent_count', label: '결석' },
            { key: 'id', label: '조치', render: () => '<span class="small-text">-</span>' },
        ]);

        // Top students
        const topStudents = [...scoreList]
            .filter(s => s.score != null)
            .sort((a, b) => Number(b.score) - Number(a.score))
            .slice(0, Math.max(5, Math.ceil(scoreList.length * 0.1)));
        renderTable('topStudentBody', topStudents, [
            { key: 'student_name', label: '학생' },
            { key: 'class_name', label: '학급' },
            { key: 'score', label: '평균', render: v => v ?? '-' },
            { key: 'score', label: '최고점', render: v => v ?? '-' },
            { key: 'remark', label: '비고' },
        ]);

        document.getElementById('reportResult').textContent = '';
    } catch(e) { console.error('loadReports error:', e); }
}

function generateReport() {
    document.getElementById('reportResult').textContent = '📄 보고서가 생성되었습니다!';
    setTimeout(() => {
        const el = document.getElementById('reportResult');
        if (el) el.textContent = '';
    }, 5000);
}

// ============================================================
// 포트폴리오 (portfolio.html)
// ============================================================
let _portfolioData = [];
let _portfolioView = 'grid';
let _dpCourseFilter = '';   // 'AI로봇' | 'AI아트' | ''
let _dpWeekFilter = '';     // ISO 주차 키 'YYYY-Www' | ''
let _dpWeekOffset = 0;      // 주간현황 패널의 주 이동 오프셋(0=이번 주)

// ============================================================
// 교육과정 / 주차 파싱 헬퍼
//  교육과정은 최상위 2개(AI로봇 / AI아트)로만 분류한다.
//  (세부 과정·주차 단위로 나누지 않음 — 사용자 지침)
//  ※ 백엔드가 내려주는 category(ai_robot/ai_art…) 값을 최우선 사용하고,
//    없을 때만 과목명 자유텍스트로 추정한다.
// ============================================================
const DP_CAT_LABELS = {
    'ai_robot': 'AI로봇',
    'ai_art':   'AI아트',
    'Ocean University': '해양 메이커',
    'physical_ai_instructor_level_2': '피지컬AI 지도사',
};
function dpTopCourse(raw) {
    // 폴백: 자유텍스트에서 최상위 과정 판별
    // ⚠️ 'Start'(St-art) 오탐 방지: AI로봇 강좌명에 'Start Kit'이 흔히 포함됨
    const s = String(raw || '');
    if (/로봇|robot|코딩|피지컬|physical|start\s*kit|아두이노|arduino|키트|kit/i.test(s)) return 'AI로봇';
    if (/(^|[^a-z])art([^a-z]|$)|아트|사이언스|science|디자인|드로잉|일러스트|그래픽|회화|미술/i.test(s)) return 'AI아트';
    if (/해양|ocean/i.test(s)) return '해양 메이커';
    return '기타';
}
function dpCourseOf(item) {
    // 1순위: 백엔드 category key (신뢰할 수 있는 값)
    const cat = item && item.category;
    if (cat && DP_CAT_LABELS[cat]) return DP_CAT_LABELS[cat];
    if (cat) return String(cat);
    // 2순위: 과정명 → courses.name 매칭값
    if (item && item.student_course_name) {
        const t = dpTopCourse(item.student_course_name);
        if (t !== '기타') return t;
    }
    // 3순위: 과목 자유텍스트
    return dpTopCourse((item && (item.subject || item.course_name)) || '');
}
// 표시 라벨(백엔드 category_name) — 툴팁/부제용
function dpCategoryLabel(item) {
    if (item && item.category_name) return item.category_name;
    return dpCourseOf(item);
}

// ── ISO 주차 계산 (월요일 시작, 주 1회 제출 판정 기준) ──
function dpIsoWeek(dateObj) {
    const d = new Date(Date.UTC(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate()));
    const dayNum = d.getUTCDay() || 7;              // 일(0) → 7
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);      // 목요일 기준
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return { year: d.getUTCFullYear(), week: week };
}
function dpWeekKey(dateObj) {
    const w = dpIsoWeek(dateObj);
    return w.year + '-W' + String(w.week).padStart(2, '0');
}
function dpParseDate(item) {
    const raw = item && (item.created_at || item.submitted_at || item.updated_at);
    if (!raw) return null;
    const s = String(raw).replace(' ', 'T');
    let d = new Date(s);
    if (isNaN(d.getTime())) d = new Date(String(raw).slice(0, 10) + 'T00:00:00');
    return isNaN(d.getTime()) ? null : d;
}
function dpItemWeekKey(item) {
    const d = dpParseDate(item);
    return d ? dpWeekKey(d) : '';
}
// 해당 주(월~일)의 시작일
function dpWeekStart(ref, offsetWeeks) {
    const d = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
    const dayNum = d.getDay() || 7;                 // 월=1 ... 일=7
    d.setDate(d.getDate() - (dayNum - 1));          // 이번 주 월요일
    if (offsetWeeks) d.setDate(d.getDate() + offsetWeeks * 7);
    return d;
}
// 해당 월의 몇 번째 주인지 (월~일 기준, 1일이 포함된 주 = 1주차)
function dpMonthWeekNo(monday) {
    // 그 주의 '목요일'이 속한 달을 기준으로 주차를 센다 (주가 두 달에 걸칠 때 안정적)
    const thu = new Date(monday); thu.setDate(thu.getDate() + 3);
    const y = thu.getFullYear(), mo = thu.getMonth();
    const first = new Date(y, mo, 1);
    // 1일이 포함된 주의 월요일
    const firstMon = dpWeekStart(first, 0);
    const diffWeeks = Math.round((thu - firstMon) / (7 * 86400000));
    return { year: y, month: mo + 1, no: Math.max(1, diffWeeks + 1) };
}
// "9월 2주차" 형태 (연도는 필요할 때만)
function dpMonthWeekText(monday, withYear) {
    const w = dpMonthWeekNo(monday);
    const base = w.month + '월 ' + w.no + '주차';
    const now = new Date();
    return (withYear || w.year !== now.getFullYear()) ? (w.year + '년 ' + base) : base;
}
function dpWeekLabel(monday) {
    const sun = new Date(monday); sun.setDate(sun.getDate() + 6);
    const f = (dt) => (dt.getMonth() + 1) + '/' + dt.getDate();
    return dpMonthWeekText(monday, false) + ' (' + f(monday) + '~' + f(sun) + ')';
}
// 주차 드롭다운용 옵션 라벨 — 키(YYYY-Www)를 "N월 M주차"로 변환
function dpWeekKeyLabel(key) {
    const m = String(key).match(/^(\d{4})-W(\d{2})$/);
    if (!m) return key;
    const y = Number(m[1]), wk = Number(m[2]);
    // ISO 주차 → 해당 주 월요일 복원
    const jan4 = new Date(y, 0, 4);
    const mon = dpWeekStart(jan4, 0);
    mon.setDate(mon.getDate() + (wk - 1) * 7);
    const w = dpMonthWeekNo(mon);
    const now = new Date();
    const base = w.month + '월 ' + w.no + '주차';
    return (w.year !== now.getFullYear()) ? (w.year + '년 ' + base) : base;
}
function dpWeekSortKey(a, b) {
    const pa = String(a).match(/(\d{4})-W(\d{2})/), pb = String(b).match(/(\d{4})-W(\d{2})/);
    if (pa && pb) return (Number(pa[1]) - Number(pb[1])) || (Number(pa[2]) - Number(pb[2]));
    return String(a).localeCompare(String(b), 'ko');
}

async function loadPortfolio() {
    try {
        const data = await apiGet('/portfolio');
        // support both PaginatedResponse {data, total} and direct array
        const items = Array.isArray(data) ? data : (data && data.data ? data.data : []);
        _portfolioData = items;

        buildFilterOptions();
        renderPortfolio();
        updateStats();
        renderWeeklyPanel();
    } catch(e) { console.error('loadPortfolio error:', e); }
}

// ===== 분류 4축 드롭다운 옵션 채우기 =====
function buildFilterOptions() {
    // 1) 학생
    const studentFilter = document.getElementById('filterStudent');
    if (studentFilter) {
        const cur = studentFilter.value;
        const students = [...new Set(_portfolioData.map(p => p.student_name || '').filter(Boolean))]
            .sort((a, b) => a.localeCompare(b, 'ko'));
        studentFilter.innerHTML = '<option value="">전체 학생</option>' +
            students.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
        if (cur) studentFilter.value = cur;
    }
    // 2) 상태 (HTML 고정 옵션 유지)
    // 3) 주 (제출 기록이 있는 주차만)
    const weekFilter = document.getElementById('filterWeek');
    if (weekFilter) {
        const cur = weekFilter.value;
        const weeks = [...new Set(_portfolioData.map(dpItemWeekKey).filter(Boolean))].sort(dpWeekSortKey);
        weekFilter.innerHTML = '<option value="">전체 주차</option>' +
            weeks.map(k => `<option value="${esc(k)}">${esc(dpWeekKeyLabel(k))}</option>`).join('');
        if (cur) weekFilter.value = cur;
    }
    // 4) 과정 (AI로봇 / AI아트 최상위 2개를 항상 우선 노출, 실제 데이터 있는 것만)
    const courseFilter = document.getElementById('filterCourse');
    if (courseFilter) {
        const cur = courseFilter.value;
        const present = new Set(_portfolioData.map(dpCourseOf).filter(Boolean));
        const ordered = ['AI로봇', 'AI아트'].filter(c => present.has(c));
        // 그 외(해양 메이커 등)도 뒤에 표시
        [...present].filter(c => !ordered.includes(c) && c !== '기타')
            .sort((a, b) => a.localeCompare(b, 'ko'))
            .forEach(c => ordered.push(c));
        courseFilter.innerHTML = '<option value="">전체 과정</option>' +
            ordered.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
        if (cur) courseFilter.value = cur;
    }
}

// ===== 4축 필터 적용 =====
function dpApplyFilter() {
    const fStudent = (document.getElementById('filterStudent') || {}).value || '';
    const fStatus  = (document.getElementById('filterStatus')  || {}).value || '';
    const fWeek    = (document.getElementById('filterWeek')    || {}).value || '';
    const fCourse  = (document.getElementById('filterCourse')  || {}).value || '';

    _dpCourseFilter = fCourse;
    _dpWeekFilter = fWeek;

    let filtered = _portfolioData.filter(function(p){
        if (fStudent && (p.student_name || '') !== fStudent) return false;
        if (fStatus && (p.status || '') !== fStatus) return false;
        if (fCourse && dpCourseOf(p) !== fCourse) return false;
        if (fWeek && dpItemWeekKey(p) !== fWeek) return false;
        return true;
    });
    window._filteredPortfolioData = filtered;
    renderPortfolio();
}

function renderPortfolio() {
    if (_portfolioView === 'grid') {
        document.getElementById('portfolioGridView').style.display = '';
        document.getElementById('portfolioTableView').style.display = 'none';
        renderPortfolioGrid();
    } else {
        document.getElementById('portfolioGridView').style.display = 'none';
        document.getElementById('portfolioTableView').style.display = '';
        renderPortfolioTable();
    }
    updateStats();
}

// ===== 주간 제출 현황 (주 1회 제출이면 충족) =====
function dpWeekShift(dir) {
    _dpWeekOffset += dir;
    renderWeeklyPanel();
}
function renderWeeklyPanel() {
    const grid = document.getElementById('weeklyGrid');
    const nowEl = document.getElementById('weeklyNow');
    if (!grid) return;

    const monday = dpWeekStart(new Date(), _dpWeekOffset);
    const key = dpWeekKey(monday);
    if (nowEl) {
        nowEl.textContent = dpWeekLabel(monday) + (_dpWeekOffset === 0 ? ' · 이번 주' : '');
    }
    document.getElementById('wkNext').style.opacity = (_dpWeekOffset >= 0) ? '.4' : '1';

    // 학생 목록 (학생 축 필터가 있으면 그 학생만)
    const fStudent = (document.getElementById('filterStudent') || {}).value || '';
    let students = [...new Set(_portfolioData.map(p => p.student_name || '').filter(Boolean))];
    if (fStudent) students = students.filter(n => n === fStudent);
    students.sort((a, b) => a.localeCompare(b, 'ko'));

    if (!students.length) {
        grid.innerHTML = '<div class="dp-weekly-empty" style="grid-column:1/-1">표시할 학생이 없습니다.</div>';
        return;
    }

    // 주간 제출 여부: 같은 ISO 주차에 1건이라도 있으면 완료
    const submitted = {};
    _portfolioData.forEach(function(p){
        if (dpItemWeekKey(p) === key) {
            const n = p.student_name || '';
            if (n) submitted[n] = true;
        }
    });

    grid.innerHTML = students.map(function(name){
        const done = !!submitted[name];
        const initial = esc(name.slice(0, 1));
        return '<div class="dp-wk-card ' + (done ? 'is-done' : 'is-miss') + '">' +
            '<span class="dp-wk-av">' + initial + '</span>' +
            '<div class="dp-wk-info">' +
                '<span class="dp-wk-name">' + esc(name) + '</span>' +
                '<span class="dp-wk-sub">' + (done ? '주간 제출 완료' : '제출 기록 없음') + '</span>' +
            '</div>' +
            '<span class="dp-wk-badge ' + (done ? 'is-done' : 'is-miss') + '">' +
                (done ? '제출' : '미제출') + '</span>' +
        '</div>';
    }).join('');
}

function onFilterChange() {
    dpApplyFilter();
    renderWeeklyPanel();
}
function resetFilters() {
    ['filterStudent', 'filterStatus', 'filterWeek', 'filterCourse'].forEach(function(id){
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    _dpCourseFilter = ''; _dpWeekFilter = ''; _dpWeekOffset = 0;
    dpApplyFilter();
    renderWeeklyPanel();
}

function updateStats() {
    const data = _portfolioData;
    const total = data.length;
    const pending = data.filter(p => p.status === 'draft' || p.status === 'published').length;
    const approved = data.filter(p => p.status === 'approved').length;

    // 이번 주 제출 현황
    const thisKey = dpWeekKey(dpWeekStart(new Date(), 0));
    const students = [...new Set(data.map(p => p.student_name || '').filter(Boolean))];
    const doneSet = {};
    data.forEach(function(p){ if (dpItemWeekKey(p) === thisKey && p.student_name) doneSet[p.student_name] = true; });
    const doneCnt = students.filter(n => doneSet[n]).length;

    setText('statTotal', formatNumber(total));
    setText('statPending', formatNumber(pending));
    setText('statApproved', formatNumber(approved));
    setText('statStudents', formatNumber(students.length));
    setText('statWeekSubmitted', formatNumber(doneCnt));
    setText('statWeekTotal', formatNumber(students.length));
}


function renderPortfolioGrid() {
    const container = document.getElementById('portfolioGridView');
    if (!container) return;
    const data = window._filteredPortfolioData || _portfolioData;
    if (!data || data.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>포트폴리오 항목이 없습니다.</p></div>';
        return;
    }

    function cardHtml(item) {
        const st = item.status === 'approved' ? 'approved'
                 : (item.status === 'published' ? 'published' : 'draft');
        const stTxt = st === 'approved' ? '승인' : (st === 'published' ? '발행' : '임시');

        let coverHtml;
        if (item.thumbnail) {
            coverHtml = '<img src="' + esc(item.thumbnail) + '" alt="">';
        } else if (item.image_urls && item.image_urls.length && item.image_urls[0]) {
            coverHtml = '<img src="' + esc(item.image_urls[0]) + '" alt="">';
        } else {
            coverHtml = '<span class="dirp-cover-ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2.5"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></span>';
        }

        // 요약(전문용): 라벨 잡음을 걷어낸 첫 문단
        let ex = '';
        if (item.content) {
            ex = String(item.content)
                .replace(/^---[\s\S]*?\n---\n?/, '')   // YAML front-matter
                .replace(/\[[^\]]+\]\s*/g, ' ')          // [오늘 배운 내용] 같은 라벨
                .replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim();
        }
        if (ex.length > 118) ex = ex.slice(0, 118) + '…';

        const metaDate = item.created_at ? formatDate(item.created_at) : '';

        return `
        <article class="dirp-card thm-${pfThemeOf(item)}" tabindex="0" onclick="viewPortfolioDetail('${item.id}')" onkeydown="if(event.key==='Enter'||event.key===' ')viewPortfolioDetail('${item.id}')">
            <div class="dirp-card-head">
                <span class="dirp-type">${esc(item.type || '기록')}</span>
                <span class="dirp-state ${st}">${stTxt}</span>
            </div>
            <div class="dirp-cover">${coverHtml}</div>
            <div class="dirp-body">
                <h3 class="dirp-title" title="${esc(item.title || '')}">${esc(item.title || '제목 없음')}</h3>
                ${ex ? `<p class="dirp-ex">${esc(ex)}</p>` : ''}
            </div>
            <div class="dirp-foot">
                <span class="dirp-stu">${esc(item.student_name || '학생')}</span>
                ${item.subject ? `<span class="dirp-sub">${esc(item.subject)}</span>` : ''}
                <span class="dirp-date">${metaDate}</span>
            </div>
        </article>
    `;
    }

    // 주차별 관리: 필터가 걸린 경우 주차 그룹으로 묶어 렌더
    if (_dpCourseFilter || _dpWeekFilter) {
        const groups = {};
        data.forEach(function(item){
            const k = dpItemWeekKey(item) || '';
            const w = k ? dpWeekKeyLabel(k) + ' (' + k + ')' : '주차 미상';
            (groups[w] = groups[w] || []).push(item);
        });
        const weeks = Object.keys(groups).sort(function(a, b){
            const ka = (a.match(/\d{4}-W\d{2}/) || [''])[0];
            const kb = (b.match(/\d{4}-W\d{2}/) || [''])[0];
            return dpWeekSortKey(ka, kb);
        });
        container.innerHTML = weeks.map(function(w){
            const items = groups[w];
            return '<section class="dirp-week-sec">' +
                '<div class="dirp-week-hd">' + esc(w) +
                '<span class="dirp-week-n">' + items.length + '건</span></div>' +
                '<div class="portfolio-grid dirp-grid">' + items.map(cardHtml).join('') + '</div>' +
                '</section>';
        }).join('');
        return;
    }

    container.innerHTML = `<div class="portfolio-grid dirp-grid">${data.map(cardHtml).join('')}</div>`;
}



// ===== 포트폴리오 코멘트/학습내용 → 전문 섹션 렌더 =====
// 저장 규약: daily=[오늘 배운 내용/새로 알게 된 점/어려웠던 점],
//            weekly=[주차/이번 주 배운 내용/코드/실행 결과/알고리즘 설명/배운 점]
function pfSectionLabel(label){
    var t = label.replace(/[\[\]]/g, '').trim();
    var cfg = {
        '오늘 배운 내용': ['','today'], '새로 알게 된 점': ['','today'],
        '어려웠던 점': ['','today'], '이번 주 배운 내용': ['','today'],
        '코드': ['','code'], '실행 결과': ['','out'], '알고리즘 설명': ['','algo'],
        '배운 점': ['','feel'], '주차': ['','week']
    };
    if (cfg[t]) return { t:t, ic:cfg[t][0], kind:cfg[t][1] };
    return { t:t, ic:'', kind:'gen' };
}
function escField(v){ return esc(String(v == null ? '' : v)); }
function buildPortfolioSections(raw){
    raw = String(raw || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
    var lines = raw.split(/\r?\n/);
    var blocks = [];          // {meta, kind, lines[]}
    var cur = null;
    lines.forEach(function(ln){
        var m = ln.match(/^\[([^\]]+)\]\s*(.*)$/);
        if (m && ln.length <= 64 && !ln.indexOf('[')) {
            cur = { meta:pfSectionLabel(m[1]), text:m[2] ? [m[2]] : [] };
            if (!(m[2])) cur._open=true;
            blocks.push(cur);
        } else {
            if (!cur) { cur = { meta:pfSectionLabel(''), text:[] }; blocks.push(cur); }
            cur.text.push(ln);
        }
    });
    if (!blocks.length) return '<div class="pf-empty">작성된 내용이 없습니다.</div>';
    var out = '';
    blocks.forEach(function(b){
        var body = b.text.join('\n').trim();
        if (!body) return;
        var bodyHtml = escField(body).replace(/\n+/g, '\n').replace(/^\n+|\n+$/g, '');
        if (b.meta.kind === 'week') {
            out += '<div class="dsec dsec-week">' + bodyHtml.replace(/\n/g,' ') + '</div>';
            return;
        }
        if (b.meta.kind === 'code' || b.meta.kind === 'out') {
            out += '<section class="dsec dsec-code">'
                 + '<div class="dsec-cap">' + b.meta.ic + ' ' + escField(b.meta.t) + '</div>'
                 + '<pre class="dsec-body '+(b.meta.kind==='out'?'is-out':'')+'">' + bodyHtml + '</pre>'
                 + '</section>';
            return;
        }
        out += '<section class="dsec">'
             + '<div class="dsec-cap">' + b.meta.ic + ' ' + escField(b.meta.t) + '</div>'
             + '<div class="dsec-body p">' + bodyHtml.replace(/\n/g, '<br>') + '</div>'
             + '</section>';
    });
    return out;
}

function renderPortfolioTable() {
    const data = window._filteredPortfolioData || _portfolioData;
    renderTable('tableBody', data, [
        { key: 'title', label: '제목' },
        { key: 'student_name', label: '학생' },
        { key: 'subject', label: '과목' },
        { key: 'status', label: '상태', render: v => {
            const map = { draft: '<span class="status-badge draft">임시</span>', published: '<span class="status-badge published">발행</span>', approved: '<span class="status-badge approved">승인</span>' };
            return map[v] || v || '-';
        }},
        { key: 'created_at', label: '등록일', render: v => formatDate(v) },
        { key: 'id', label: '액션', render: v => `<button class="btn btn-ghost btn-xs" onclick="viewPortfolioDetail(${v})">보기</button>` },
    ]);
}

function setView(view) {
    _portfolioView = view;
    document.querySelectorAll('.vt-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });
    renderPortfolio();
}

async function viewPortfolioDetail(id) {
    const item = _portfolioData.find(p => p.id == id);
    if (!item) { showAlert('항목을 찾을 수 없습니다.', 'danger'); return; }
    
    // Store current item for approve/comment
    window._currentPortfolioItem = item;
    
    const content = document.getElementById('detailContent');
    if (content) {
        // Images
        const images = item.image_urls || [];
        const imageHtml = images.length > 0
            ? `<div class="portfolio-detail-images">${images.map(url => `<img src="${esc(url)}" alt="" loading="lazy">`).join('')}</div>`
            : '';
        // Content (report)
        const contentHtml = item.content
            ? `<div class="portfolio-detail-content" style="white-space:pre-wrap;line-height:1.6">${esc(item.content)}</div>`
            : '';
        
        const statusLabel = item.status === 'approved' ? '승인' : (item.status === 'published' ? '발행' : '임시');
        const statusClass = item.status === 'approved' ? 'success' : (item.status === 'published' ? 'info' : 'warning');
        
        content.innerHTML = `
            <div class="dirpd thm-${pfThemeOf(item)}">
                <div class="dirpd-labels">
                    ${item.status === 'approved'
                        ? '<span class="dirp-state approved">승인 완료</span>'
                        : (item.status === 'published'
                            ? '<span class="dirp-state published">발행 대기</span>'
                            : '<span class="dirp-state draft">임시 저장</span>')}
                    ${item.is_public === false
                        ? '<span class="dirp-lock">비공개</span>'
                        : '<span class="dirp-lock is-pub">공개</span>'}
                </div>

                <h2 class="dirpd-title">${esc(item.title || '제목 없음')}</h2>
                ${pfNoteHtml(item)}

                <dl class="dirpd-meta2">
                    <div><dt>학생</dt><dd>${esc(item.student_name || '—')}</dd></div>
                    <div><dt>과목</dt><dd>${esc(item.subject || '—')}</dd></div>
                    <div><dt>유형</dt><dd>${esc(item.type || item.file_type || '—')}</dd></div>
                    <div><dt>작성일</dt><dd>${formatDate(item.created_at)}</dd></div>
                </dl>

                ${item.file_url ? `<div class="dirpd-file"><a href="${esc(item.file_url)}" target="_blank" rel="noopener">📎 첨부파일 보기</a></div>` : ''}

                ${item.content ? `<div class="dirpd-content">${item.content ? buildPortfolioSections(item.content) : '<div class="pf-empty">작성된 내용이 없습니다.</div>'}</div>` : ''}

                ${images.length ? `
                <div class="dirpd-photos">
                    ${images.map(u => `<img src="${esc(u)}" alt="" loading="lazy" onclick="window.open('${esc(u)}','_blank')">`).join('')}
                </div>` : ''}
            </div>
        `;
    }
    
    // Update approve button state
    const approveBtn = document.getElementById('approveBtn');
    if (approveBtn) {
        if (item.status === 'approved') {
            approveBtn.textContent = '이미 승인됨';
            approveBtn.disabled = true;
        } else {
            approveBtn.textContent = '승인';
            approveBtn.disabled = false;
        }
    }
    const rejectBtn = document.getElementById('rejectBtn');
    if (rejectBtn) {
        if (item.status === 'approved') {
            rejectBtn.disabled = true; rejectBtn.style.display = 'none';
        } else if (item.status === 'revision_requested') {
            rejectBtn.disabled = true; rejectBtn.style.display = '';
            rejectBtn.textContent = '반려됨';
        } else {
            rejectBtn.disabled = false; rejectBtn.style.display = '';
            rejectBtn.textContent = '반려';
        }
    }
    
    openModal('detailModal');
}

// ===== 포트폴리오 승인 =====
async function approvePortfolio() {
    const item = window._currentPortfolioItem;
    if (!item) { showAlert('포트폴리오를 선택해주세요.', 'danger'); return; }
    if (item.status === 'approved') {
        showAlert('이미 승인된 포트폴리오입니다.', 'info');
        return;
    }
    try {
        // Use publish endpoint to change status
        await apiPost(`/portfolio/${item.id}/publish`, { status: 'approved' });
        showAlert('포트폴리오가 승인되었습니다.', 'success');
        closeModal('detailModal');
        loadPortfolio();
    } catch(e) {
        console.error('Approve error:', e);
        showAlert('승인 중 오류가 발생했습니다.', 'danger');
    }
}

// ===== 코멘트 모달 열기 =====
// 상태 테마 헬퍼 (학생·원장 공통 규칙)
function pfHasComment(item){ return !!((item.description||'').toString().trim()); }
function pfThemeOf(item){
    if (!item) return 'wip';
    const st = item.status;
    if (st === 'approved') return 'ok';
    if (st === 'revision_requested') return 'rev';
    if (pfHasComment(item)) return 'cmt';
    if (st === 'published') return 'pend';
    return 'wip'; // draft/임시
}
function pfStateTxt(item){
    const st = item.status;
    if (st === 'approved') return '승인 완료';
    if (st === 'revision_requested') return '반려 · 재작성';
    if (pfHasComment(item)) return '원장 코멘트';
    if (st === 'published') return '발행 · 확인 대기';
    return '임시';
}

function pfNoteHtml(item){
    const has = String(item.description||'').trim();
    const st = item.status;
    if (!has && st !== 'revision_requested') return '';
    if (st === 'revision_requested') {
        return '<div class="rd-note is-rej"><div class="rd-note-t">반려 사유</div>'
             + '<div class="rd-note-x">' + esc(has || '원장이 반려 처리했습니다. 수정 후 다시 발행해 주세요.') + '</div></div>';
    }
    if (st === 'approved') {
        return '<div class="rd-note is-ok"><div class="rd-note-t">승인 의견</div>'
             + '<div class="rd-note-x">' + esc(has) + '</div></div>';
    }
    return '<div class="rd-note"><div class="rd-note-t">원장 코멘트</div>'
         + '<div class="rd-note-x">' + esc(has) + '</div></div>';
}

function openCommentModal() {
    const item = window._currentPortfolioItem;
    if (!item) return;
    window._commentMode = 'comment';
    const _t1 = document.getElementById('ccModalTitle'); if (_t1) _t1.textContent = '코멘트 작성';
    document.getElementById('commentPortfolioTitle').innerHTML =
        '<span class="cc-chip cc-blue">원장 코멘트</span>' +
        '<span class="cc-sub">' + esc(item.title || '제목 없음') + '</span>';
    const ta = document.getElementById('commentText');
    ta.value = item.description ? String(item.description) : '';
    ta.placeholder = '확인한 내용이나 보완 안내를 남겨주세요. 학생에게 표시됩니다.';
    const saveBtn = document.getElementById('ccSaveBtn');
    if (saveBtn) { saveBtn.className = 'btn btn-filled cc-save-blue'; saveBtn.textContent = '코멘트 저장'; }
    openModal('commentModal');
}

function openRejectModal() {
    const item = window._currentPortfolioItem;
    if (!item) return;
    window._commentMode = 'reject';
    const _t2 = document.getElementById('ccModalTitle'); if (_t2) _t2.textContent = '반려 · 재작성 요청';
    document.getElementById('commentPortfolioTitle').innerHTML =
        '<span class="cc-chip cc-orange">반려 · 재작성 요청</span>' +
        '<span class="cc-sub">' + esc(item.title || '제목 없음') + '</span>';
    const ta = document.getElementById('commentText');
    ta.value = '';
    ta.placeholder = '반려 사유를 반드시 입력해 주세요. (보완할 내용 안내)';
    const saveBtn = document.getElementById('ccSaveBtn');
    if (saveBtn) { saveBtn.className = 'btn btn-filled cc-save-reject'; saveBtn.textContent = '반려 보내기'; }
    openModal('commentModal');
}

async function saveComment() {
    const item = window._currentPortfolioItem;
    if (!item) return;
    const mode = window._commentMode || 'comment';
    const comment = document.getElementById('commentText').value.trim();
    if (mode === 'reject') {
        if (!comment) { showAlert('반려 사유를 입력해 주세요.', 'danger'); return; }
    }
    try {
        // 상태 반영(반려) 먼저
        if (mode === 'reject') {
            await apiPost(`/portfolio/${item.id}/publish`, { status: 'revision_requested' });
        }
        // 코멘트 저장 (승인 후에도 흰 코멘트 영역으로 재표기)
        await apiPut(`/portfolio/${item.id}`, { description: comment, tags: JSON.stringify({ comment: !!comment }) });
        showAlert(mode === 'reject' ? '반려 요청이 학생에게 전달되었습니다.' : '코멘트가 저장되었습니다.', 'success');
        closeModal('commentModal');
        window._commentMode = null;
        if (mode === 'reject') window._recentReject = true;
        loadPortfolio();
    } catch(e) {
        console.error('Comment error:', e);
        showAlert('저장 중 오류가 발생했습니다.', 'danger');
    }
}

// ===== 인쇄 =====
function printPortfolioView() {
    const printArea = document.getElementById('printArea');
    if (!printArea) return;
    
    let html = '<div style="padding:40px;font-family:sans-serif">';
    html += '<h1 style="text-align:center;margin-bottom:20px">포트폴리오 관리</h1>';
    html += `<p style="text-align:center;color:#666;margin-bottom:30px">출력일: ${new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })}</p>`;
    
    if (!_portfolioData || _portfolioData.length === 0) {
        html += '<p style="text-align:center;color:#999">출력할 항목이 없습니다.</p>';
    } else {
        _portfolioData.forEach(item => {
            html += `
                <div style="border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:20px;page-break-inside:avoid;">
                    <h2 style="margin:0 0 8px 0;font-size:18px">${esc(item.title || '제목 없음')}</h2>
                    <div style="font-size:12px;color:#666;margin-bottom:12px">
                        <span>👨‍🎓 ${esc(item.student_name || '학생')}</span>
                        <span style="margin-left:12px">📚 ${esc(item.subject || '기타')}</span>
                        <span style="margin-left:12px">📅 ${formatDate(item.created_at)}</span>
                    </div>
                    <div style="white-space:pre-wrap;font-size:14px;line-height:1.6">${esc(item.content || '')}</div>
                </div>
            `;
        });
    }
    html += '</div>';
    
    printArea.innerHTML = html;
    printArea.style.display = 'block';
    window.print();
    printArea.style.display = 'none';
}

function printDetail() {
    const detailContent = document.getElementById('detailContent');
    if (!detailContent) return;
    const printArea = document.getElementById('printArea');
    if (!printArea) return;
    printArea.innerHTML = `<div style="padding:40px;font-family:sans-serif">${detailContent.innerHTML}</div>`;
    printArea.style.display = 'block';
    window.print();
    printArea.style.display = 'none';
}

// ============================================================
// 포트폴리오 CRUD (CREATE + 이미지 업로드)
// ============================================================

let portfolioTags = [];
let uploadedImages = [];

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
    uploadedImages = [];
    renderTags();
    openModal('portfolioModal');
}

function editPortfolio(id) {
    const item = _portfolioData.find(i => String(i.id) === String(id));
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

/* ============================================================
   포트폴리오 이미지 업로드 헬퍼
   ============================================================ */

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
    container.innerHTML = portfolioTags.map(t =>
        `<span class="tag">${esc(t)} <button type="button" class="tag-remove" onclick="removeTag('${esc(t)}')" style="background:none;border:none;cursor:pointer;margin-left:4px;padding:0;font-size:14px;line-height:1">&times;</button></span>`
    ).join('');
}

// ============================================================
// 영상 관리 (videos.html)
// ============================================================
async function loadVideos() {
    try {
        const search = document.getElementById('searchInput')?.value || '';
        const type = document.getElementById('typeFilter')?.value || '';
        const status = document.getElementById('statusFilter')?.value || '';
        const course = document.getElementById('courseFilter')?.value || '';

        let path = '/videos';
        const params = [];
        if (search) params.push(`search=${encodeURIComponent(search)}`);
        if (type) params.push(`type=${type}`);
        if (status) params.push(`status=${status}`);
        if (course) params.push(`course_id=${course}`);
        if (params.length) path += '?' + params.join('&');

        const data = await apiGet(path);
        const videos = Array.isArray(data) ? data : (data?.data || []);

        // Stats
        const total = videos.length;
        const youtube = videos.filter(v => v.video_type === 'youtube').length;
        const vimeo = videos.filter(v => v.video_type === 'vimeo').length;
        const upload = videos.filter(v => v.video_type === 'upload').length;

        setText('statTotal', formatNumber(total));
        setText('statYoutube', formatNumber(youtube));
        setText('statVimeo', formatNumber(vimeo));
        setText('statUpload', formatNumber(upload));
        setText('videoCount', `${total}개`);

        renderTable('videoTableBody', videos, [
            { key: 'thumbnail', label: '영상', render: v => v ? `<img src="${v}" style="width:60px;height:40px;object-fit:cover;border-radius:4px">` : '🎬' },
            { key: 'title', label: '제목' },
            { key: 'course_name', label: '강좌' },
            { key: 'video_type', label: '유형' },
            { key: 'sort_order', label: '순서', render: v => v ?? '0' },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'id', label: '관리', render: (v) => `
                <div class="action-btns">
                    <button class="btn btn-ghost btn-xs" onclick="editVideo(${v})">✏️</button>
                    <button class="btn btn-ghost btn-xs" onclick="deleteVideo(${v})">🗑️</button>
                </div>
            `},
        ]);
    } catch(e) { console.error('loadVideos error:', e); }
}

function openVideoModal() {
    document.getElementById('editVideoId').value = '';
    document.getElementById('videoModalTitle').textContent = '영상 등록';
    document.getElementById('modalTitle').value = '';
    document.getElementById('modalDescription').value = '';
    document.getElementById('modalVideoType').value = 'youtube';
    document.getElementById('modalCourse').value = '';
    document.getElementById('modalUrl').value = '';
    document.getElementById('modalSortOrder').value = '0';
    openModal('videoModal');
}

async function editVideo(id) {
    try {
        const data = await apiGet('/videos');
        const videos = Array.isArray(data) ? data : (data?.data || []);
        const video = videos.find(v => v.id == id);
        if (!video) { showAlert('영상을 찾을 수 없습니다.', 'danger'); return; }
        document.getElementById('editVideoId').value = id;
        document.getElementById('videoModalTitle').textContent = '영상 수정';
        document.getElementById('modalTitle').value = video.title || '';
        document.getElementById('modalDescription').value = video.description || '';
        document.getElementById('modalVideoType').value = video.video_type || 'youtube';
        document.getElementById('modalCourse').value = video.course_id || '';
        document.getElementById('modalUrl').value = video.url || '';
        document.getElementById('modalSortOrder').value = video.sort_order || '0';
        openModal('videoModal');
    } catch(e) { showAlert('영상 정보를 불러오지 못했습니다.', 'danger'); }
}

async function saveVideo() {
    const id = document.getElementById('editVideoId').value;
    const payload = {
        title: document.getElementById('modalTitle').value,
        description: document.getElementById('modalDescription').value || '',
        video_type: document.getElementById('modalVideoType').value,
        course_id: parseInt(document.getElementById('modalCourse').value) || null,
        url: document.getElementById('modalUrl').value || '',
        sort_order: parseInt(document.getElementById('modalSortOrder').value) || 0,
    };
    try {
        if (id) {
            await apiPut(`/videos/${id}`, payload);
            showAlert('영상이 수정되었습니다.');
        } else {
            await apiPost('/videos', payload);
            showAlert('영상이 등록되었습니다.');
        }
        closeModal('videoModal');
        loadVideos();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function deleteVideo(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/videos/${id}`);
        showAlert('삭제되었습니다.');
        loadVideos();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 원격수업 (classroom.html)
// ============================================================
let _classroomData = [];

async function loadClassroom() {
    try {
        const data = await apiGet('/classroom');
        _classroomData = Array.isArray(data) ? data : (data?.data || []);
        renderClassroom();
    } catch(e) { console.error('loadClassroom error:', e); }
}

function renderClassroom() {
    const statusFilter = document.getElementById('statusFilter')?.value || '';
    const search = document.getElementById('searchInput')?.value?.toLowerCase() || '';

    let filtered = [..._classroomData];
    if (statusFilter) filtered = filtered.filter(c => c.status === statusFilter);
    if (search) filtered = filtered.filter(c => (c.title || '').toLowerCase().includes(search));

    // Stats
    const today = dateStr();
    const todayClasses = filtered.filter(c => {
        const d = c.date ? c.date.slice(0,10) : '';
        return d === today;
    });
    const live = filtered.filter(c => c.status === 'live');

    setText('todayCount', formatNumber(todayClasses.length));
    setText('totalCount', formatNumber(filtered.length));
    setText('avgAttendance', '-');
    setText('liveCount', formatNumber(live.length));
    setText('classCount', `총 ${filtered.length}개 수업`);

    renderTable('classTableBody', filtered, [
        { key: 'date', label: '날짜', render: v => formatDate(v) },
        { key: 'title', label: '수업명' },
        { key: 'course_name', label: '강좌' },
        { key: 'status', label: '상태', render: v => statusBadge(v) },
        { key: 'attendance_count', label: '출석', render: v => v != null ? `${v}명` : '-' },
        { key: 'id', label: '관리', render: (v) => `
            <div class="action-btns">
                <button class="btn btn-ghost btn-xs" onclick="viewClassroomAttendance(${v})">📋</button>
                <button class="btn btn-ghost btn-xs" onclick="deleteClassroom(${v})">🗑️</button>
            </div>
        `},
    ]);
}

function filterClasses() {
    renderClassroom();
}

function resetCreateForm() {
    document.getElementById('classTitle').value = '';
    document.getElementById('classCourse').value = '';
    document.getElementById('classDescription').value = '';
    document.getElementById('classDate').value = dateStr();
    document.getElementById('classTime').value = '09:00';
    document.getElementById('classDuration').value = '45';
    document.getElementById('classMaxParticipants').value = '30';
}

async function createClass() {
    const payload = {
        title: document.getElementById('classTitle').value,
        course_id: parseInt(document.getElementById('classCourse').value) || null,
        description: document.getElementById('classDescription').value || '',
        date: document.getElementById('classDate').value,
        time: document.getElementById('classTime').value,
        duration: parseInt(document.getElementById('classDuration').value) || 45,
        max_participants: parseInt(document.getElementById('classMaxParticipants').value) || 30,
    };
    try {
        await apiPost('/classroom', payload);
        showAlert('수업이 생성되었습니다.');
        closeModal('createModal');
        loadClassroom();
    } catch(e) { showAlert(e.message, 'danger'); }
}

async function viewClassroomAttendance(id) {
    try {
        const cls = _classroomData.find(c => c.id == id);
        if (!cls) { showAlert('수업을 찾을 수 없습니다.', 'danger'); return; }
        document.getElementById('attendanceModalTitle').textContent = `${cls.title || ''} - 출석 현황`;

        const data = await apiGet(`/classroom/${id}/attendance`);
        const records = Array.isArray(data) ? data : [];
        renderTable('attendanceBody', records, [
            { key: 'student_name', label: '학생' },
            { key: 'status', label: '상태', render: v => statusBadge(v) },
            { key: 'time', label: '시간', render: v => v || '-' },
        ]);
        openModal('attendanceModal');
    } catch(e) {
        showAlert('출석 정보를 불러오지 못했습니다.', 'danger');
    }
}

async function deleteClassroom(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/classroom/${id}`);
        showAlert('삭제되었습니다.');
        loadClassroom();
    } catch(e) { showAlert(e.message, 'danger'); }
}

// ============================================================
// 폼 제출 바인딩 (각 페이지별)
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // Classes form
    const classForm = document.getElementById('classForm');
    if (classForm) classForm.addEventListener('submit', (e) => { e.preventDefault(); saveClass(); });

    // Exams form
    const examForm = document.getElementById('examForm');
    if (examForm) examForm.addEventListener('submit', (e) => { e.preventDefault(); saveExam(); });

    // Grades form
    const gradeForm = document.getElementById('gradeForm');
    if (gradeForm) gradeForm.addEventListener('submit', (e) => { e.preventDefault(); saveGrade(); });

    // Attendance form
    const attForm = document.getElementById('attendanceForm');
    if (attForm) attForm.addEventListener('submit', (e) => { e.preventDefault(); saveAttendance(); });

    // Videos form
    const videoForm = document.getElementById('videoForm');
    if (videoForm) videoForm.addEventListener('submit', (e) => { e.preventDefault(); saveVideo(); });
});
