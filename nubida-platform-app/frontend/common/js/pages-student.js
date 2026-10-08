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
// allCourses는 nubida-bundle.js에 선언됨

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
// portfolioItems는 nubida-bundle.js에 선언됨

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

// _enrolledCourses는 nubida-bundle.js에 선언됨

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

function renderContentBoxes(content) {
    // Parse content into [label]: value sections
    var sections = [];
    var lines = (content || '').split('\n');
    var currentLabel = '';
    var currentText = [];
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        var labelMatch = line.match(/^\[([^\]]+)\]/);
        if (labelMatch) {
            if (currentLabel) {
                sections.push({label: currentLabel, text: currentText.join('\n').trim()});
            }
            currentLabel = labelMatch[1];
            currentText = [];
        } else {
            currentText.push(line);
        }
    }
    if (currentLabel) {
        sections.push({label: currentLabel, text: currentText.join('\n').trim()});
    }
    // If no labels found, return plain text
    if (sections.length === 0) {
        var preview = (content || '').substring(0, 120);
        return '<div class="journal-card-content">' + esc(preview) + (content && content.length > 120 ? '...' : '') + '</div>';
    }
    // Build boxes
    var html = '';
    for (var j = 0; j < sections.length; j++) {
        var sec = sections[j];
        var iconMap = {'오늘 배운 내용': '📖', '새로 알게 된 점': '💡', '어려웠던 점': '🤔'};
        var icon = iconMap[sec.label] || '📌';
        var textPreview = sec.text.substring(0, 80);
        html += '<div class="content-box">';
        html += '<div class="content-box-label">' + icon + ' ' + esc(sec.label) + '</div>';
        html += '<div class="content-box-text">' + esc(textPreview) + (sec.text.length > 80 ? '...' : '') + '</div>';
        html += '</div>';
    }
    return html;
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

    container.innerHTML = `<div class=\"journal-grid\">${items.map(item => {
        const images = item.image_urls || [];
        const dateStr = item.created_at ? formatDate(item.created_at) : '';
        const contentPreview = (item.content || '').substring(0, 120);

        // Photo grid HTML
        let photosHtml = '';
        if (images.length > 0) {
            const countClass = images.length === 1 ? 'single' : images.length === 3 ? 'triple' : '';
            const countExtra = images.length === 2 ? ' journal-card-photos-count-2' : '';
            photosHtml = `<div class=\"journal-card-photos${countClass ? ' ' + countClass : ''}${countExtra}\">`;
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
                ${photosHtml ? photosHtml.replace('journal-card-photos', 'journal-card-photos journal-card-photos-section') : ''}
                <div class=\"journal-card-content-area\">
                    ${item.content ? renderContentBoxes(item.content) : '<div class=\"journal-card-content journal-card-content-empty\">내용이 없습니다</div>'}
                </div>
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