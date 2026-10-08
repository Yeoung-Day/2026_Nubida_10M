// ============================================================
// 누비다플랫폼 v2 Premium — 학생학습(Student) 페이지 스크립트
// API: student/dashboard, courses, scores, schedule, attendance
// ============================================================

// ===== 내장 유틸리티 (SW/캐시 문제로 외부 의존 제거) =====
if (typeof window.esc !== 'function') {
    window.esc = function(str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    };
}
if (typeof window.formatNumber !== 'function') {
    window.formatNumber = function(n) {
        if (n == null) return '-';
        return Number(n).toLocaleString('ko-KR');
    };
}

// ===== Helper: 텍스트 설정 =====
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '-';
}

// ===== Helper: HTML 설정 =====
function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
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
        'in_progress': ['info', '진행중'],
        'not_started': ['warning', '시작전'],
    };
    const [cls, label] = map[status] || ['info', status];
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// ===== Helper: 등급 표시 =====
function gradeBadge(grade) {
    const map = {
        'A': 'success', 'A+': 'success', 'A0': 'success',
        'B': 'info', 'B+': 'info', 'B0': 'info',
        'C': 'warning',
        'D': 'danger',
        'F': 'danger',
    };
    const cls = map[grade] || 'info';
    return `<span class="badge badge-${cls}">${esc(grade)}</span>`;
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
        case 'courses': loadCourses(); break;
        case 'grades': loadGrades(); break;
        case 'portfolio': loadPortfolio(); break;
        case 'timetable': loadTimetable(); break;
        case 'classroom': loadClassroom(); break;
        case 'videos': loadVideos(); break;
        case 'learning': /* no-op, learning.html has its own JS */ break;
    }
}

// ============================================================
// 대시보드
// ============================================================
async function loadDashboard() {
    try {
        const res = await apiGet('/student/dashboard');
        const d = res?.data || {};
        setText('totalCourses', formatNumber(d?.total_courses || 0));
        setText('completedLessons', formatNumber(d?.completed_lessons || 0));
        setText('avgGrade', d?.avg_grade || '-');
        setText('attendanceRate', (d?.attendance_rate != null) ? d.attendance_rate + '%' : '-');

        // 내 강좌 목록
        const myCoursesEl = document.getElementById('myCourses');
        if (myCoursesEl && d?.recent_courses) {
            if (d.recent_courses.length === 0) {
                myCoursesEl.innerHTML = '<div class="empty-state"><div class="icon">📚</div><p>수강 중인 강좌가 없습니다.</p></div>';
            } else {
                myCoursesEl.innerHTML = d.recent_courses.map(c => `
                    <div class="list-item" style="padding:var(--space-4);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);margin-bottom:var(--space-3);transition:all 0.2s">
                        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                            <div class="list-item-title">${esc(c.name)}</div>
                            <span style="font-size:12px;font-weight:600;color:var(--text-tertiary)">${c.progress || 0}%</span>
                        </div>
                        <div class="list-item-sub" style="margin-bottom:10px">${esc(c.teacher || '')}</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width:${c.progress || 0}%"></div>
                        </div>
                    </div>
                `).join('');
            }
        }

        // 오늘 시간표
        const todayScheduleEl = document.getElementById('todaySchedule');
        if (todayScheduleEl && d?.today_schedule) {
            if (d.today_schedule.length === 0) {
                todayScheduleEl.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>오늘은 수업이 없습니다.</p></div>';
            } else {
                todayScheduleEl.innerHTML = d.today_schedule.map(s => `
                    <div class="list-item">
                        <div class="list-item-title">${esc(s.time)} — ${esc(s.course)}</div>
                        <div class="list-item-sub">${esc(s.teacher || '')} · ${esc(s.room || '')}</div>
                    </div>
                `).join('');
            }
        }

        // 최근 성적
        const gradeData = d?.recent_scores || [];
        const gradeColumns = [
            { key: 'exam_name', render: v => esc(v) },
            { key: 'course_name', render: v => esc(v) },
            { key: 'score', render: v => v != null ? v : '-' },
            { key: 'grade', render: v => v ? gradeBadge(v) : '-' },
            { key: 'date', render: v => formatDate(v) },
        ];
        renderTable('recentGradeBody', gradeData, gradeColumns);
        
        // 최근 포트폴리오
        loadRecentPortfolios();
    } catch(e) { console.error('Dashboard error:', e); }
}

async function loadRecentPortfolios() {
    try {
        const res = await apiGet('/portfolio');
        const items = Array.isArray(res) ? res : (res?.data || res?.items || []);
        const container = document.getElementById('recentPortfolios');
        if (!container) return;
        
        if (!items || items.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="icon">📖</div><p>아직 작성한 학습 노트가 없습니다.</p></div>';
            return;
        }
        
        const recent = items.slice(0, 5);
        container.innerHTML = recent.map(p => `
            <div class="list-item" style="padding:var(--space-3) 0;border-bottom:1px solid var(--border-subtle);cursor:pointer" onclick="window.location.href='portfolio.html'">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div class="list-item-title">${esc(p.title || '제목 없음')}</div>
                        <div class="list-item-sub">${esc(p.subject || '기타')} · ${formatDate(p.created_at)}</div>
                    </div>
                    <span class="badge badge-${p.status === 'published' ? 'success' : 'warning'}">${p.status === 'published' ? '발행' : '임시'}</span>
                </div>
            </div>
        `).join('');
    } catch(e) {
        console.error('Recent portfolios error:', e);
    }
}


// ============================================================
// 강좌 목록
// ============================================================
let allCourses = [];

async function loadCourses() {
    try {
        const res = await apiGet('/student/catalog');
        allCourses = Array.isArray(res) ? res : (res?.data || res?.courses || []);
        updateCourseStats();
        renderCourses(allCourses);
    } catch(e) {
        console.error('Courses load error:', e);
        setHTML('courseList', '<div class="empty-state"><div class="icon">⚠️</div><p>강좌 정보를 불러올 수 없습니다.</p></div>');
    }
}

function filterCourses() {
    const q = (document.getElementById('courseSearch')?.value || '').trim().toLowerCase();
    const filtered = q ? allCourses.filter(c =>
        (c.name || '').toLowerCase().includes(q) ||
        (c.teacher || '').toLowerCase().includes(q)
    ) : allCourses;
    renderCourses(filtered);
}

function updateCourseStats() {
    const total = allCourses.length;
    const inProgress = allCourses.filter(c => c.status === 'active' || c.status === 'in_progress' || !c.status).length;
    const completed = allCourses.filter(c => c.status === 'completed').length;
    setText('totalCourses', total);
    setText('weekClasses', inProgress);
    setText('completionRate', total > 0 ? Math.round(completed / total * 100) + '%' : '0%');
}

function renderCourses(courses) {
    const container = document.getElementById('courseList');
    if (!container) return;

    if (!courses || courses.length === 0) {
        container.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="icon">📖</div><p>검색 결과가 없습니다.</p></div>';
        return;
    }

    container.innerHTML = courses.map(c => {
        const progress = c.progress || c.progress_pct || 0;
        const status = c.status || 'active';
        const totalMats = c.material_count || 0;
        const completedCnt = c.completed_count || 0;
        // progress_pct 기반 상태: 100% = 완료, 0% = 수강전, 그외 = 진행중
        const statusLabel = (totalMats === 0) ? '자료 없음'
            : (progress >= 100) ? '완료'
            : (completedCnt > 0) ? '진행중'
            : '수강 전';
        return `
            <div class="card course-card">
                <div class="card-body" onclick="showCourseDetail('${c.id}')" style="cursor:pointer">
                    <div class="flex-between mb-8">
                        <h3 class="course-card-title">${esc(c.name || c.title || '')}</h3>
                        ${statusBadge(status)}
                    </div>
                    <div class="small-text mb-8">📘 ${esc(c.description || '')}</div>
                    <div class="small-text mb-8">📦 자료 ${c.material_count || 0}개</div>
                    <div class="progress-bar mb-8">
                        <div class="progress-fill" style="width:${progress}%"></div>
                    </div>
                    <div class="flex-between small-text">
                        <span>진행률 ${progress}%</span>
                        <span>${statusLabel}</span>
                    </div>
                </div>
                <div class="card-footer" style="padding:12px 20px;border-top:1px solid var(--border-subtle)">
                    <a href="learning.html?course_id=${c.id}" class="btn btn-primary btn-sm" style="text-decoration:none;width:100%;text-align:center">
                        📚 학습하기
                    </a>
                </div>
            </div>
        `;
    }).join('');
}

async function showCourseDetail(courseId) {
    try {
        const res = await apiGet(`/student/courses/${courseId}/materials`);
        const course = allCourses.find(c => String(c.id) === String(courseId));
        const materials = Array.isArray(res) ? res : (res?.data || res?.materials || []);
        const assignmentsRes = await apiGet(`/student/courses/${courseId}/assignments`).catch(() => null);
        const assignments = assignmentsRes ? (Array.isArray(assignmentsRes) ? assignmentsRes : (assignmentsRes?.data || assignmentsRes?.assignments || [])) : [];

        setText('detailTitle', course ? esc(course.name || course.title || '') : '강좌 상세');

        let html = '';
        if (course) {
            html += `
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">강사</div>
                    <div>${esc(course.teacher || '-')}</div>
                </div>
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">일정</div>
                    <div>${esc(course.schedule || '-')}</div>
                </div>
                <div class="mb-16">
                    <div class="small-text" style="color:var(--text-tertiary)">진행률</div>
                    <div class="progress-bar"><div class="progress-fill" style="width:${course.progress || 0}%"></div></div>
                </div>
            `;
        }

        html += `<h3 class="mb-8">📎 학습 자료</h3>`;
        if (materials.length === 0) {
            html += `<div class="small-text mb-16" style="color:var(--text-tertiary)">등록된 자료가 없습니다.</div>`;
        } else {
            html += `<ul class="mb-16">`;
            materials.forEach(m => {
                const mt = m.material_type || 'document';
                const url = m.file_url || m.url || '#';
                const isVideo = mt === 'video' || (url.match(/\.(mp4|webm|mov)$/i));
                const isImage = mt === 'image' || (url.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i));
                const fileSize = m.file_size ? (m.file_size > 1048576 ? (m.file_size / 1048576).toFixed(1) + 'MB' : (m.file_size > 1024 ? (m.file_size / 1024).toFixed(0) + 'KB' : m.file_size + 'B')) : '';
                const typeIcon = { document: '📄', video: '🎬', image: '🖼️', link: '🔗' }[mt] || '📄';

                html += `<li class="list-item" style="padding:var(--space-2) 0;border-bottom:1px solid var(--border-subtle)">`;
                if (isVideo && url !== '#') {
                    html += `<div style="margin-bottom:4px">
                        <video controls style="width:100%;max-height:280px;border-radius:8px;background:#000" preload="metadata">
                            <source src="${esc(url)}" type="video/mp4">
                            브라우저가 영상 재생을 지원하지 않습니다.
                        </video>
                    </div>`;
                } else if (isImage && url !== '#') {
                    html += `<div style="margin-bottom:4px">
                        <img src="${esc(url)}" alt="${esc(m.title)}" style="max-width:100%;max-height:200px;border-radius:6px" loading="lazy">
                    </div>`;
                }
                html += `<div style="display:flex;justify-content:space-between;align-items:center">
                    <a href="${esc(url)}" target="_blank" class="list-item-title" style="text-decoration:none">
                        ${typeIcon} ${esc(m.title || m.name || '자료')}
                    </a>
                    <span style="font-size:11px;color:var(--text-tertiary)">${fileSize}</span>
                </div>`;
                if (url === '#') {
                    html += `<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">🔗 ${esc(m.embed_url || '')}</div>`;
                }
                html += `</li>`;
            });
            html += `</ul>`;
        }

        html += `<h3 class="mb-8">📝 과제</h3>`;
        if (assignments.length === 0) {
            html += `<div class="small-text" style="color:var(--text-tertiary)">등록된 과제가 없습니다.</div>`;
        } else {
            html += `<ul>`;
            assignments.forEach(a => {
                html += `<li class="list-item" style="padding:var(--space-2) 0">
                    <span class="list-item-title">${esc(a.title || a.name || '과제')}</span>
                    <span class="list-item-sub">${a.due_date ? '마감: ' + formatDate(a.due_date) : ''}</span>
                </li>`;
            });
            html += `</ul>`;
        }

        setHTML('detailContent', html);
        openModal('courseDetailModal');
    } catch(e) {
        console.error('Course detail error:', e);
        showAlert('강좌 상세 정보를 불러올 수 없습니다.', 'danger');
    }
}

// ============================================================
// 성적 조회
// ============================================================
async function loadGrades() {
    try {
        const semester = document.getElementById('filterSemester')?.value || '';
        const path = semester ? `/student/scores?semester=${encodeURIComponent(semester)}` : '/student/scores';
        const res = await apiGet(path);
        const scores = Array.isArray(res) ? res : (res?.data || res?.scores || []);

        // Stat cards
        const totalExams = scores.length;
        const avgScore = totalExams > 0 ? Math.round(scores.reduce((s, r) => s + (r.score || 0), 0) / totalExams) : 0;
        const highestScore = totalExams > 0 ? Math.max(...scores.map(r => r.score || 0)) : 0;
        const lowestScore = totalExams > 0 ? Math.min(...scores.map(r => r.score || 0)) : 0;

        setText('totalExams', totalExams);
        setText('overallAvg', avgScore + '점');
        setText('bestScore', highestScore + '점');
        setText('recentTrend', totalExams > 0 ? scores[0]?.grade || '-' : '-');

        // Table
        const columns = [
            { key: 'exam_name', render: v => esc(v || '-') },
            { key: 'course_name', render: v => esc(v || '-') },
            { key: 'score', render: v => v != null ? v + '점' : '-' },
            { key: 'max_score', render: v => v != null ? v : '-' },
            { key: 'grade', render: v => v ? gradeBadge(v) : '-' },
            { key: 'rank', render: v => v != null ? v + '등' : '-' },
            { key: 'date', render: v => formatDate(v) },
        ];
        renderTable('gradeBody', scores, columns);
    } catch(e) {
        console.error('Grades load error:', e);
        setHTML('gradeBody', '<tr><td colspan="7" style="text-align:center;color:var(--text-tertiary);padding:24px">성적 정보를 불러올 수 없습니다.</td></tr>');
    }
}
// ============================================================
// 학습 노트 (포트폴리오) — 일기/노트 스타일, 사진 최대 4장
// ============================================================
let portfolioItems = [];

async function loadPortfolio() {
    try {
        const res = await apiGet('/portfolio');
        portfolioItems = Array.isArray(res) ? res : (res?.data || res?.items || []);
        
        // Calculate weekly count
        updateWeeklyCount();
        
        // Load enrolled courses for dropdown
        loadCourseSelector();
        
        renderJournal('all');
    } catch(e) {
        console.error('Portfolio load error:', e);
        setHTML('journalContainer', '<div class="empty-state"><div class="empty-icon">📖</div><h3>불러오기 실패</h3><p>잠시 후 다시 시도해주세요.</p></div>');
    }

    // Setup subject tab listeners
    const tabs = document.querySelectorAll('#subjectTabs .filter-tab');
    tabs.forEach(tab => {
        tab.onclick = function() {
            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            renderJournal(this.dataset.subject);
        };
    });
}

function updateWeeklyCount() {
    const el = document.getElementById('weeklyPortfolioCount');
    if (!el) return;
    const now = new Date();
    const startOfWeek = new Date(now);
    startOfWeek.setDate(now.getDate() - now.getDay());
    startOfWeek.setHours(0, 0, 0, 0);
    const count = portfolioItems.filter(p => {
        const d = p.created_at ? new Date(p.created_at) : null;
        return d && d >= startOfWeek;
    }).length;
    el.textContent = count;
}

let _enrolledCourses = [];

async function loadCourseSelector() {
    const sel = document.getElementById('courseFilter');
    const subj = document.getElementById('portSubject');
    if (!sel && !subj) return;
    try {
        const res = await apiGet('/student/courses');
        _enrolledCourses = Array.isArray(res) ? res : (res?.data || []);
        
        // Populate filter dropdown
        if (sel) {
            const currentVal = sel.value;
            sel.innerHTML = '<option value="all">전체 강좌</option>';
            _enrolledCourses.forEach(c => {
                sel.innerHTML += `<option value="${esc(c.name || c.subject || '')}">${esc(c.name || '')}</option>`;
            });
            if (currentVal) sel.value = currentVal;
        }
        
        // Populate subject/ course selector in modal
        if (subj) {
            const currentVal = subj.value;
            subj.innerHTML = '<option value="">강좌 선택</option>';
            _enrolledCourses.forEach(c => {
                subj.innerHTML += `<option value="${esc(c.name || c.subject || '')}">${esc(c.name || '')}</option>`;
            });
            if (currentVal) subj.value = currentVal;
        }
    } catch(e) {
        console.error('Load courses error:', e);
    }
}

function filterByCourse() {
    const sel = document.getElementById('courseFilter');
    const course = sel ? sel.value : 'all';
    renderJournal(course === 'all' ? 'all' : course);
}

function renderJournal(subject) {
    const container = document.getElementById('journalContainer');
    if (!container) return;

    let items = portfolioItems;
    
    // Filter by subject tab
    if (subject && subject !== 'all') {
        items = items.filter(item => item.subject === subject);
    }
    
    // Filter by course dropdown
    const courseFilter = document.getElementById('courseFilter');
    const selectedCourse = courseFilter ? courseFilter.value : 'all';
    if (selectedCourse && selectedCourse !== 'all') {
        items = items.filter(item => item.subject === selectedCourse);
    }

    if (!items || items.length === 0) {
        container.innerHTML = `
            <div class=\"empty-state\">
                <div class=\"empty-icon\">📖</div>
                <h3>아직 기록이 없습니다</h3>
                <p>오늘 배운 내용을 기록해 보세요!</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `<div style=\"display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;\">${items.map(item => {
        const images = item.image_urls || [];
        const dateStr = item.created_at ? formatDate(item.created_at) : '';
        const contentPreview = (item.content || '').substring(0, 120);

        // Photo grid HTML
        let photosHtml = '';
        if (images.length > 0) {
            const countClass = images.length === 1 ? ' single' : '';
            const countExtra = images.length === 2 ? ' journal-card-photos-count-2' : '';
            photosHtml = `<div class=\"journal-card-photos${countExtra}\">`;
            for (let i = 0; i < Math.min(images.length, 4); i++) {
                const cls = images.length === 1 ? 'journal-card-photo single' : 'journal-card-photo';
                photosHtml += `<img src=\"${esc(images[i])}\" alt=\"사진 ${i+1}\" class=\"${cls}\" onerror=\"this.style.display='none'\">`;
            }
            photosHtml += '</div>';
        }

        return `
            <div class=\"journal-card\" onclick=\"openDetailModal('${item.id}')\">
                <div class=\"journal-card-header\">
                    <h3 class=\"journal-card-title\">${esc(item.title || '제목 없음')}</h3>
                    <span class=\"journal-card-date\">${dateStr}</span>
                </div>
                ${item.content ? `<div class=\"journal-card-content\">${esc(contentPreview)}${item.content.length > 120 ? '...' : ''}</div>` : ''}
                ${photosHtml}
                <div class=\"journal-card-footer\">
                    <span class=\"journal-card-subject\">${esc(item.subject || '기타')}</span>
                    <div class=\"journal-card-actions\">
                        <button onclick=\"event.stopPropagation();editPortfolio('${item.id}')\" title=\"수정\">✏️</button>
                        <button onclick=\"event.stopPropagation();deletePortfolio('${item.id}')\" title=\"삭제\">🗑️</button>
                    </div>
                </div>
            </div>
        `;
    }).join('')}</div>`;
}

// ===== 상세 보기 모달 =====
function openDetailModal(id) {
    const item = portfolioItems.find(i => String(i.id) === String(id));
    if (!item) return;

    const images = item.image_urls || [];
    const dateStr = item.created_at ? formatDate(item.created_at) : '';
    const statusClass = item.is_public !== false ? 'public' : 'private';
    const statusLabel = item.is_public !== false ? '🌍 공개' : '🔒 비공개';

    let photosHtml = '';
    if (images.length > 0) {
        const cls = images.length === 1 ? 'journal-detail-photo single' : 'journal-detail-photo';
        photosHtml = `<div class=\"journal-detail-photos\">`;
        for (let i = 0; i < Math.min(images.length, 4); i++) {
            photosHtml += `<img src=\"${esc(images[i])}\" alt=\"사진 ${i+1}\" class=\"${cls}\" onclick=\"window.open('${esc(images[i])}','_blank')\" onerror=\"this.style.display='none'\">`;
        }
        photosHtml += '</div>';
    }

    document.getElementById('detailContent').innerHTML = `
        <h2 class=\"journal-detail-title\">${esc(item.title || '제목 없음')}</h2>
        <div class=\"journal-detail-meta\">
            <span>📅 ${dateStr}</span>
            <span>📚 ${esc(item.subject || '기타')}</span>
            <span class=\"journal-detail-status ${statusClass}\">${statusLabel}</span>
        </div>
        ${item.content ? `<div class=\"journal-detail-content\">${esc(item.content)}</div>` : '<p style=\"color:#9ca3af;font-style:italic;\">작성된 내용이 없습니다.</p>'}
        ${photosHtml}
    `;

    const editBtn = document.getElementById('detailEditBtn');
    const deleteBtn = document.getElementById('detailDeleteBtn');
    editBtn.onclick = function() { closeModal('detailModal'); editPortfolio(id); };
    deleteBtn.onclick = function() { closeModal('detailModal'); deletePortfolio(id); };

    openModal('detailModal');
}

function openAddModal() {
    document.getElementById('modalTitle').textContent = '✏️ 새 학습 기록';
    document.getElementById('editId').value = '';
    document.getElementById('portTitle').value = '';
    document.getElementById('portContent').value = '';
    document.getElementById('portContentToday').value = '';
    document.getElementById('portContentNew').value = '';
    document.getElementById('portContentDiff').value = '';
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    document.getElementById('portDate').value = `${yyyy}-${mm}-${dd}`;
    document.getElementById('portSubject').value = '';
    document.getElementById('portPublic').checked = true;
    document.getElementById('imageUrls').value = '[]';
    document.getElementById('imagePreviewContainer').innerHTML = '';
    updatePhotoCountLabel(0);
    openModal('portfolioModal');
}

function editPortfolio(id) {
    const item = portfolioItems.find(i => String(i.id) === String(id));
    if (!item) return;

    document.getElementById('modalTitle').textContent = '✏️ 학습 기록 수정';
    document.getElementById('editId').value = id;
    document.getElementById('portTitle').value = item.title || '';
    document.getElementById('portContent').value = item.content || '';
    
    // Parse template sections from content
    const content = item.content || '';
    const todayMatch = content.match(/\[오늘 배운 내용\]([\s\S]*?)(?=\[새로 알게 된 점\]|$)/);
    const newMatch = content.match(/\[새로 알게 된 점\]([\s\S]*?)(?=\[어려웠던 점\]|$)/);
    const diffMatch = content.match(/\[어려웠던 점\]([\s\S]*)/);
    document.getElementById('portContentToday').value = todayMatch ? todayMatch[1].trim() : '';
    document.getElementById('portContentNew').value = newMatch ? newMatch[1].trim() : '';
    document.getElementById('portContentDiff').value = diffMatch ? diffMatch[1].trim() : '';
    
    if (item.created_at) {
        const d = new Date(item.created_at);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        document.getElementById('portDate').value = `${yyyy}-${mm}-${dd}`;
    } else {
        document.getElementById('portDate').value = '';
    }
    document.getElementById('portSubject').value = item.subject || '';
    document.getElementById('portPublic').checked = item.is_public !== false;

    const images = item.image_urls || [];
    document.getElementById('imageUrls').value = JSON.stringify(images);
    renderPhotoPreviews(images);
    updatePhotoCountLabel(images.length);
    openModal('portfolioModal');
}

async function savePortfolio() {
    const id = document.getElementById('editId').value;
    let imageUrls = [];
    try { imageUrls = JSON.parse(document.getElementById('imageUrls').value || '[]'); } catch(e) {}
    
    // Combine template sections into content
    const todayContent = document.getElementById('portContentToday').value.trim();
    const newContent = document.getElementById('portContentNew').value.trim();
    const diffContent = document.getElementById('portContentDiff').value.trim();
    let combinedContent = '';
    if (todayContent || newContent || diffContent) {
        if (todayContent) combinedContent += `[오늘 배운 내용]\n${todayContent}\n\n`;
        if (newContent) combinedContent += `[새로 알게 된 점]\n${newContent}\n\n`;
        if (diffContent) combinedContent += `[어려웠던 점]\n${diffContent}`;
    }
    // Update hidden content field
    document.getElementById('portContent').value = combinedContent.trim();

    const data = {
        title: document.getElementById('portTitle').value.trim(),
        content: combinedContent.trim(),
        subject: document.getElementById('portSubject').value,
        is_public: document.getElementById('portPublic').checked,
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
    if (!data.content) {
        showAlert('배운 내용을 입력해주세요.', 'danger');
        return;
    }

    try {
        if (id) {
            await apiPut(`/portfolio/${id}`, data);
            showAlert('학습 기록이 수정되었습니다.', 'success');
        } else {
            await apiPost('/portfolio', data);
            showAlert('새 학습 기록이 저장되었습니다! 🎉', 'success');
        }
        closeModal('portfolioModal');
        loadPortfolio();
    } catch(e) {
        console.error('Save portfolio error:', e);
        showAlert('저장 중 오류가 발생했습니다.', 'danger');
    }
}

async function deletePortfolio(id) {
    if (!confirm('정말 이 기록을 삭제하시겠습니까?')) return;
    try {
        await apiDelete(`/portfolio/${id}`);
        showAlert('기록이 삭제되었습니다.', 'success');
        loadPortfolio();
    } catch(e) {
        console.error('Delete portfolio error:', e);
        showAlert('삭제 중 오류가 발생했습니다.', 'danger');
    }
}

// ===== 템플릿 기능 =====
function applyTemplate(type) {
    if (type === 'today') {
        document.getElementById('portContentToday').value = '오늘 배운 내용을 입력하세요...';
    } else if (type === 'new') {
        document.getElementById('portContentNew').value = '새로 알게 된 점을 입력하세요...';
    } else if (type === 'difficult') {
        document.getElementById('portContentDiff').value = '어려웠던 점을 입력하세요...';
    } else if (type === 'all') {
        if (!document.getElementById('portContentToday').value) document.getElementById('portContentToday').value = '오늘 배운 내용을 입력하세요...';
        if (!document.getElementById('portContentNew').value) document.getElementById('portContentNew').value = '새로 알게 된 점을 입력하세요...';
        if (!document.getElementById('portContentDiff').value) document.getElementById('portContentDiff').value = '어려웠던 점을 입력하세요...';
    }
    showAlert('템플릿이 적용되었습니다. 내용을 수정해주세요!', 'success');
}

function clearTemplate() {
    document.getElementById('portContentToday').value = '';
    document.getElementById('portContentNew').value = '';
    document.getElementById('portContentDiff').value = '';
    showAlert('내용이 초기화되었습니다.', 'info');
}

// ===== 내보내기 / 인쇄 =====
function exportPortfolio() {
    if (!portfolioItems || portfolioItems.length === 0) {
        showAlert('내보낼 포트폴리오가 없습니다.', 'warning');
        return;
    }
    let text = '=== 학습 노트 내보내기 ===\n';
    text += `내보내기 일시: ${new Date().toLocaleString('ko-KR')}\n`;
    text += `총 항목: ${portfolioItems.length}개\n\n`;
    text += '='.repeat(50) + '\n\n';
    portfolioItems.forEach((item, i) => {
        text += `[${i+1}] ${item.title || '제목 없음'}\n`;
        text += `과목: ${item.subject || '기타'}\n`;
        text += `날짜: ${item.created_at ? formatDate(item.created_at) : '-'}\n`;
        text += `내용:\n${item.content || '내용 없음'}\n\n`;
        text += '-'.repeat(30) + '\n\n';
    });
    
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `portfolio_export_${new Date().toISOString().slice(0,10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
    showAlert('내보내기가 완료되었습니다!', 'success');
}

function printPortfolio() {
    const printArea = document.getElementById('printArea');
    if (!printArea) return;
    
    let html = '<div style="padding:40px;font-family: sans-serif;">';
    html += '<h1 style="text-align:center;margin-bottom:20px">📖 학습 노트</h1>';
    html += `<p style="text-align:center;color:#666;margin-bottom:30px">출력일: ${new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })}</p>`;
    
    if (!portfolioItems || portfolioItems.length === 0) {
        html += '<p style="text-align:center;color:#999">출력할 항목이 없습니다.</p>';
    } else {
        portfolioItems.forEach(item => {
            const dateStr = item.created_at ? new Date(item.created_at).toLocaleDateString('ko-KR') : '';
            html += `
                <div style="border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:20px;page-break-inside:avoid;">
                    <h2 style="margin:0 0 8px 0;font-size:18px">${esc(item.title || '제목 없음')}</h2>
                    <div style="font-size:12px;color:#666;margin-bottom:12px">
                        <span>📚 ${esc(item.subject || '기타')}</span>
                        <span style="margin-left:12px">📅 ${dateStr}</span>
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
    
    printArea.innerHTML = `<div style="padding:40px;font-family:sans-serif;">${detailContent.innerHTML}</div>`;
    printArea.style.display = 'block';
    window.print();
    printArea.style.display = 'none';
}

// ===== 사진 업로드 (최대 4장, 2×2 그리드) =====
let uploadedImages = [];

function updatePhotoCountLabel(count) {
    const label = document.getElementById('photoCountLabel');
    if (label) label.textContent = `${count} / 4`;
}

function renderPhotoPreviews(urls) {
    uploadedImages = Array.isArray(urls) ? [...urls] : [];
    const container = document.getElementById('imagePreviewContainer');
    if (!container) return;

    const count = uploadedImages.length;
    updatePhotoCountLabel(count);

    if (count === 0) {
        container.innerHTML = `<div class=\"photo-grid-preview\"></div>`;
        return;
    }

    let html = '<div class=\"photo-grid-preview\">';
    for (let i = 0; i < Math.min(count, 4); i++) {
        html += `<div class=\"photo-grid-item\">
            <img src=\"${esc(uploadedImages[i])}\" alt=\"사진 ${i+1}\" class=\"photo-grid-thumb\"
                 onerror=\"this.parentElement.innerHTML='<span style=\\\\'padding:10px;color:#999;font-size:12px\\\'>⚠</span>'\">
            <button type=\"button\" class=\"photo-grid-remove\" onclick=\"removePhoto(${i})\" title=\"삭제\">×</button>
        </div>`;
    }
    for (let i = count; i < 4; i++) {
        html += `<div class=\"photo-grid-item empty\">➕</div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

function removePhoto(index) {
    uploadedImages.splice(index, 1);
    document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
    renderPhotoPreviews(uploadedImages);
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
    const currentCount = uploadedImages.length;
    const remaining = 4 - currentCount;

    if (remaining <= 0) {
        showAlert('사진은 최대 4장까지 첨부할 수 있습니다.', 'warning');
        return;
    }

    let uploaded = 0;
    for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        if (uploaded >= remaining) {
            showAlert('사진은 최대 4장까지 첨부할 수 있습니다. (' + (currentCount + uploaded) + '장 초과)', 'warning');
            break;
        }
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
                uploaded++;
                document.getElementById('imageUrls').value = JSON.stringify(uploadedImages);
                renderPhotoPreviews(uploadedImages);
            } else {
                showAlert('업로드 실패: ' + (json.message || ''), 'danger');
            }
        } catch(e) {
            showAlert('업로드 중 오류: ' + (e.message || ''), 'danger');
        }
    }
    if (uploaded > 0) {
        showAlert(uploaded + '장의 사진이 업로드되었습니다.', 'success');
    }
}

// ============================================================
// 시간표
// ============================================================
async function loadTimetable() {
    try {
        const res = await apiGet('/student/schedule');
        const schedule = Array.isArray(res) ? res : (res?.data || res?.schedule || []);

        const dateEl = document.getElementById('timetableDate');
        if (dateEl) {
            const now = new Date();
            const days = ['일', '월', '화', '수', '목', '금', '토'];
            dateEl.textContent = `${now.getFullYear()}년 ${now.getMonth() + 1}월 ${now.getDate()}일 (${days[now.getDay()]})`;
        }

        // Build timetable grid
        const dayNames = ['월', '화', '수', '목', '금', '토'];
        const dayMap = {0:'월',1:'화',2:'수',3:'목',4:'금',5:'토',6:'일'};
        const timeSlots = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00', '19:00', '20:00', '21:00'];

        // Group schedule by day_name and start_time slot
        const scheduleMap = {};
        schedule.forEach(s => {
            // API returns day_of_week (0=Monday), start_time like "09:00:00"
            const dayIdx = s.day_of_week;
            const dayName = dayMap[dayIdx] || '월';
            // Get the hour slot from start_time
            const timeStr = s.start_time ? s.start_time.substring(0, 5) : '';
            // Find the matching time slot
            let slot = timeStr;
            if (!timeSlots.includes(slot)) {
                // Round to nearest hour
                const parts = timeStr.split(':');
                if (parts.length === 2) {
                    slot = parts[0] + ':00';
                }
            }
            const key = `${dayName}_${slot}`;
            scheduleMap[key] = s;
        });

        // Render header
        const thead = document.getElementById('timetableHead');
        if (thead) {
            thead.innerHTML = `<tr><th>시간</th>${dayNames.map(d => `<th>${d}</th>`).join('')}</tr>`;
        }

        // Render body
        const tbody = document.getElementById('timetableBody');
        if (!tbody) return;

        if (schedule.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-tertiary)">등록된 시간표가 없습니다.</td></tr>';
            return;
        }

        tbody.innerHTML = timeSlots.map(time => {
            const cells = dayNames.map(day => {
                const s = scheduleMap[`${day}_${time}`];
                if (s) {
                    return `<td class="timetable-cell has-class" onclick="showScheduleDetail('${esc(s.course_name || s.course || '')}', '${esc(s.subject || '')}', '${esc(s.room || '')}', '${day}', '${s.start_time ? s.start_time.substring(0,5) : time}')">
                        <div class="tt-class-block">
                            <div class="tt-class-name">${esc(s.course_name || s.course || '')}</div>
                            <div class="tt-class-meta">${esc(s.room || '')}</div>
                        </div>
                    </td>`;
                }
                return '<td class="timetable-cell"></td>';
            }).join('');
            return `<tr><td class="timetable-time">${time}</td>${cells}</tr>`;
        }).join('');
    } catch(e) {
        console.error('Timetable load error:', e);
        const tbody = document.getElementById('timetableBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-tertiary)">시간표를 불러올 수 없습니다.</td></tr>';
    }
}

function showScheduleDetail(course, subject, room, day, time) {
    document.getElementById('scheduleModalTitle').textContent = '수업 상세';
    setHTML('scheduleDetail', `
        <div class="mb-12"><strong>과목</strong><br>${esc(course)}</div>
        <div class="mb-12"><strong>교과</strong><br>${esc(subject || '-')}</div>
        <div class="mb-12"><strong>장소</strong><br>${esc(room || '-')}</div>
        <div class="mb-12"><strong>요일</strong><br>${esc(day)}요일</div>
        <div class="mb-12"><strong>시간</strong><br>${esc(time)}</div>
    `);
    openModal('scheduleModal');
}

// ============================================================
// 원격수업 (Classroom)
// ============================================================
let classroomData = { upcoming: [], past: [] };
let currentSession = null;

async function loadClassroom() {
    try {
        const res = await apiGet('/classroom/my');
        const classes = Array.isArray(res) ? res : (res?.data || res?.classes || []);

        const now = new Date();
        classroomData.upcoming = classes.filter(c => new Date(c.start_time || c.date) >= now);
        classroomData.past = classes.filter(c => new Date(c.start_time || c.date) < now);

        renderUpcomingClasses();
        renderPastClasses();
    } catch(e) {
        console.error('Classroom load error:', e);
        setHTML('upcomingClasses', '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>불러오기 실패</h3></div>');
        setHTML('pastClasses', '');
    }
}

function switchClassTab(tab, btn) {
    document.querySelectorAll('.class-tab-item').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');

    document.getElementById('upcomingTab').style.display = tab === 'upcoming' ? '' : 'none';
    document.getElementById('pastTab').style.display = tab === 'past' ? '' : 'none';
}

function renderUpcomingClasses() {
    const container = document.getElementById('upcomingClasses');
    const count = document.getElementById('upcomingCount');
    if (!container) return;

    const items = classroomData.upcoming;
    if (count) count.textContent = `다가오는 수업 ${items.length}개`;

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📅</div><h3>예정된 수업이 없습니다</h3></div>';
        return;
    }

    container.innerHTML = items.map(c => `
        <div class="class-card" onclick="openJoinModal('${c.id}')">
            <div class="class-card-top">
                <span class="badge badge-info">${esc(c.course_name || c.course || '')}</span>
                <span class="small-text">${formatDate(c.start_time || c.date)}</span>
            </div>
            <h3 class="class-card-title">${esc(c.title || '수업')}</h3>
            <div class="class-card-info">
                <span>👨‍🏫 ${esc(c.teacher || '')}</span>
                <span>⏰ ${c.start_time ? formatDateTime(c.start_time) : ''}</span>
            </div>
            <button class="btn btn-filled btn-sm mt-8" onclick="event.stopPropagation(); openJoinModal('${c.id}')">🔗 참여하기</button>
        </div>
    `).join('');
}

function renderPastClasses() {
    const container = document.getElementById('pastClasses');
    const count = document.getElementById('pastCount');
    if (!container) return;

    const items = classroomData.past;
    if (count) count.textContent = `지난 수업 ${items.length}개`;

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><h3>지난 수업이 없습니다</h3></div>';
        return;
    }

    container.innerHTML = items.map(c => `
        <div class="class-card" onclick="viewRecording('${c.id}')">
            <div class="class-card-top">
                <span class="badge badge-secondary">${esc(c.course_name || c.course || '')}</span>
                <span class="small-text">${formatDate(c.start_time || c.date)}</span>
            </div>
            <h3 class="class-card-title">${esc(c.title || '수업')}</h3>
            <div class="class-card-info">
                <span>👨‍🏫 ${esc(c.teacher || '')}</span>
                <span>⏰ ${formatDateTime(c.start_time || c.date)}</span>
            </div>
            ${c.recording_url ? `<button class="btn btn-outline btn-sm mt-8" onclick="event.stopPropagation(); viewRecording('${c.id}')">🎬 녹화보기</button>` : ''}
        </div>
    `).join('');
}

function openJoinModal(classId) {
    const c = [...classroomData.upcoming, ...classroomData.past].find(x => String(x.id) === String(classId));
    if (!c) return;

    document.getElementById('joinTitle').textContent = c.title || '수업';
    document.getElementById('joinCourse').textContent = c.course_name || c.course || '-';
    document.getElementById('joinTime').textContent = formatDateTime(c.start_time || c.date);
    document.getElementById('joinModalInfo').textContent = '수업에 참여하시겠습니까?';

    currentSession = c;
    openModal('joinModal');
}

function confirmJoin() {
    closeModal('joinModal');
    if (!currentSession) return;

    // Switch to session view
    document.getElementById('listView').style.display = 'none';
    document.getElementById('sessionView').style.display = '';

    setText('sessionTitleDisplay', currentSession.title || '수업');
    document.getElementById('sessionStatusBadge').textContent = '📡 진행중';

    // Start timer
    const start = Date.now();
    const timer = document.getElementById('sessionTimer');
    const interval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - start) / 1000);
        const m = Math.floor(elapsed / 60);
        const s = elapsed % 60;
        if (timer) timer.textContent = `⏱ ${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }, 1000);
    timer && (timer.dataset.intervalId = interval);
}

function leaveSession() {
    const timer = document.getElementById('sessionTimer');
    if (timer && timer.dataset.intervalId) {
        clearInterval(Number(timer.dataset.intervalId));
    }
    document.getElementById('listView').style.display = '';
    document.getElementById('sessionView').style.display = 'none';
    currentSession = null;
}

function checkinAttendance() {
    document.getElementById('checkinStatus').textContent = '✅ 출석 완료';
    document.getElementById('checkinStatus').className = 'checkin-status completed';
    document.getElementById('checkinBtn').disabled = true;
    document.getElementById('checkinBtn').textContent = '출석 완료';
    showAlert('출석이 확인되었습니다.', 'success');
}

function viewRecording(classId) {
    const c = [...classroomData.upcoming, ...classroomData.past].find(x => String(x.id) === String(classId));
    if (!c) return;

    setHTML('recordingInfo', `
        <div class="mb-8"><strong>${esc(c.title || '수업')}</strong></div>
        <div class="small-text">${esc(c.course_name || c.course || '')} · ${formatDateTime(c.start_time || c.date)}</div>
        ${c.recording_url ? `<div class="mt-8"><a href="${esc(c.recording_url)}" target="_blank" class="btn btn-filled btn-sm">🎬 영상 보기</a></div>` : ''}
    `);
    openModal('recordingModal');
}

// ============================================================
// 강좌별 영상 (Videos)
// ============================================================
let videoData = [];
let allCoursesForVideos = [];
let selectedCourseForVideos = 'all';
let selectedVideo = null;

async function loadVideos() {
    try {
        const res = await apiGet('/videos');
        videoData = Array.isArray(res) ? res : (res?.data || res?.videos || []);

        // Get unique courses from videos
        const courseMap = {};
        videoData.forEach(v => {
            const cn = v.course_name || v.course || '일반';
            if (!courseMap[cn]) courseMap[cn] = 0;
            courseMap[cn]++;
        });

        allCoursesForVideos = Object.entries(courseMap).map(([name, count]) => ({ name, count }));

        // Update counts
        setText('totalVideoCount', `총 ${videoData.length}개 영상`);
        setText('countAll', videoData.length);

        // Render course filter list
        const filterList = document.getElementById('courseFilterList');
        if (filterList) {
            filterList.innerHTML = allCoursesForVideos.map(c => `
                <button class="course-filter-item" data-course="${esc(c.name)}" onclick="filterByCourse('${esc(c.name)}')">
                    📹 ${esc(c.name)}
                    <span class="cfi-count">${c.count}</span>
                </button>
            `).join('');
        }

        // Show course filter items
        filterByCourse('all');
    } catch(e) {
        console.error('Videos load error:', e);
        const container = document.getElementById('videoListContainer');
        if (container) container.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>영상 정보를 불러올 수 없습니다.</p></div>';
    }
}

function filterByCourse(course) {
    selectedCourseForVideos = course;

    // Update active state in sidebar
    document.querySelectorAll('.course-filter-item').forEach(el => el.classList.remove('active'));
    if (course === 'all') {
        const allBtn = document.querySelector('.course-filter-item[data-course="all"]');
        if (allBtn) allBtn.classList.add('active');
    } else {
        const btn = document.querySelector(`.course-filter-item[data-course="${CSS.escape(course)}"]`);
        if (btn) btn.classList.add('active');
    }

    const filtered = course === 'all' ? videoData : videoData.filter(v => (v.course_name || v.course) === course);

    // Render video list grouped by course
    const container = document.getElementById('videoListContainer');
    if (!container) return;

    if (filtered.length === 0) {
        container.innerHTML = '<div class="no-video-selected"><div class="no-video-icon">🎬</div><p>해당 강좌에 영상이 없습니다</p></div>';
        return;
    }

    // Group by course
    const grouped = {};
    filtered.forEach(v => {
        const key = v.course_name || v.course || '일반';
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(v);
    });

    container.innerHTML = Object.entries(grouped).map(([courseName, videos]) => `
        <div class="video-group mb-16">
            <h3 class="video-group-title">${esc(courseName)} <span class="small-text" style="color:var(--text-tertiary)">${videos.length}개</span></h3>
            <div class="video-list">
                ${videos.map(v => `
                    <div class="video-list-item ${selectedVideo && String(selectedVideo.id) === String(v.id) ? 'active' : ''}" onclick="selectVideo('${v.id}')">
                        <div class="video-list-thumb">🎬</div>
                        <div class="video-list-info">
                            <div class="video-list-title">${esc(v.title || '제목 없음')}</div>
                            <div class="video-list-meta">${formatDate(v.created_at || v.date)} · ${v.duration ? v.duration : ''}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function selectVideo(videoId) {
    const v = videoData.find(x => String(x.id) === String(videoId));
    if (!v) return;
    selectedVideo = v;

    // Update active state
    document.querySelectorAll('.video-list-item').forEach(el => el.classList.remove('active'));

    // Show video info
    setText('currentVideoTitle', v.title || '제목 없음');
    setText('currentVideoMeta', `${esc(v.course_name || v.course || '')} · ${formatDate(v.created_at || v.date)}`);
    setText('currentVideoType', v.type || 'video');

    document.getElementById('videoInfoBar').style.display = '';

    // Show embedded video or player
    const placeholder = document.getElementById('videoPlaceholder');
    const embedContainer = document.getElementById('videoEmbedContainer');

    if (v.embed_url || v.video_url) {
        const url = v.embed_url || v.video_url;
        placeholder.style.display = 'none';
        embedContainer.style.display = '';
        if (url.includes('youtube') || url.includes('youtu.be')) {
            let embedId = '';
            if (url.includes('youtube.com/watch?v=')) embedId = url.split('v=')[1]?.split('&')[0];
            else if (url.includes('youtu.be/')) embedId = url.split('youtu.be/')[1]?.split('?')[0];
            if (embedId) {
                embedContainer.innerHTML = `<iframe width="100%" height="400" src="https://www.youtube.com/embed/${embedId}" frameborder="0" allowfullscreen></iframe>`;
            } else {
                embedContainer.innerHTML = `<video controls width="100%" src="${esc(url)}"></video>`;
            }
        } else {
            embedContainer.innerHTML = `<video controls width="100%" src="${esc(url)}"></video>`;
        }
    } else {
        placeholder.style.display = '';
        embedContainer.style.display = 'none';
        placeholder.querySelector('.play-label').textContent = '영상 URL이 없습니다';
    }
}

function playSelectedVideo() {
    if (selectedVideo && (selectedVideo.embed_url || selectedVideo.video_url)) {
        selectVideo(String(selectedVideo.id));
    }
}
