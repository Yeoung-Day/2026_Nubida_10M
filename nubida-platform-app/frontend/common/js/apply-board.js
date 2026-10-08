/* ============================================================
 * 교육 신청 게시판 — 공개 페이지 (2026-09-21)
 * 본사가 올린 공고를 게시판 형태로 보여주고, [신청] 버튼으로 접수.
 * 소속 강사 신청은 팝업(모달)에서 처리.
 * ============================================================ */
(function () {
    'use strict';

    var API = '/api/v1/edu-apply';

    var listBox = document.getElementById('ebList');
    var emptyBox = document.getElementById('ebEmpty');

    var PROGRAMS = [];

    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function val(id) {
        var el = document.getElementById(id);
        return el && el.value ? el.value.trim() : '';
    }
    function fmtDate(s) {
        if (!s) return '';
        return String(s).slice(0, 10);
    }

    /* ---------- 공고 목록 로드 ---------- */
    function loadPrograms() {
        listBox.innerHTML = '<div class="eb-empty"><p>불러오는 중…</p></div>';
        fetch(API + '/programs?include_closed=1')
            .then(function (r) { return r.json(); })
            .then(function (j) {
                PROGRAMS = (j && j.data) ? j.data : [];
                render();
            })
            .catch(function () {
                listBox.innerHTML = '';
                emptyBox.style.display = 'block';
            });
    }

    function render() {
        var items = PROGRAMS;
        var cntEl = document.getElementById('ebCount');
        if (cntEl) {
            var openN = 0;
            items.forEach(function (p) { if (p.status === 'open' && !p.is_full) openN++; });
            cntEl.textContent = items.length ? ('모집중 ' + openN + '건 / 전체 ' + items.length + '건') : '';
        }
        if (!items.length) {
            listBox.innerHTML = '';
            emptyBox.style.display = 'block';
            return;
        }
        emptyBox.style.display = 'none';

        var html = '';
        items.forEach(function (p) {
            var badges = '';
            if (p.is_pinned) badges += '<span class="eb-pin">📌 공지</span>';
            if (p.category) badges += '<span class="eb-cat">' + esc(p.category) + '</span>';
            if (p.status === 'closed') {
                badges += '<span class="eb-badge closed">마감</span>';
            } else if (p.is_full) {
                badges += '<span class="eb-badge full">정원마감</span>';
            } else {
                badges += '<span class="eb-badge open">모집중</span>';
            }

            var meta = '';
            if (p.recruit_start || p.recruit_end) {
                meta += '<span>📅 ' + esc(fmtDate(p.recruit_start) || '—') +
                        ' ~ ' + esc(fmtDate(p.recruit_end) || '—') + '</span>';
            }
            if (p.location) meta += '<span>📍 ' + esc(p.location) + '</span>';
            if (p.fee) meta += '<span>💰 ' + esc(p.fee) + '</span>';
            meta += '<span>👥 <b>' + (p.applicant_count || 0) + '명</b>' +
                    (p.capacity ? ' / 정원 ' + p.capacity + '명' : '') + '</span>';

            var info = '';
            if (p.recruit_start || p.recruit_end) {
                info += '<div><span>모집기간</span>' + esc(fmtDate(p.recruit_start) || '—') +
                        ' ~ ' + esc(fmtDate(p.recruit_end) || '—') + '</div>';
            }
            if (p.location) info += '<div><span>교육 장소</span>' + esc(p.location) + '</div>';
            if (p.fee) info += '<div><span>교육비</span>' + esc(p.fee) + '</div>';
            if (p.contact) info += '<div><span>문의처</span>' + esc(p.contact) + '</div>';

            var closed = (p.status === 'closed') || p.is_full;
            var btn = closed
                ? '<button type="button" class="eb-apply" disabled>' +
                  (p.status === 'closed' ? '모집이 마감되었습니다' : '정원이 마감되었습니다') + '</button>'
                : '<button type="button" class="eb-apply" onclick="ebOpenApply(' + p.id + ')">신청하기</button>';

            html +=
                '<div class="eb-item" id="ebItem' + p.id + '">' +
                    '<div class="eb-head" onclick="ebToggle(' + p.id + ')">' +
                        '<div class="eb-main">' +
                            '<div class="eb-top">' + badges + '</div>' +
                            '<h3 class="eb-title">' + esc(p.title) + '</h3>' +
                            (p.summary ? '<p class="eb-sum">' + esc(p.summary) + '</p>' : '') +
                            '<div class="eb-meta">' + meta + '</div>' +
                        '</div>' +
                        '<svg class="eb-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
                    '</div>' +
                    '<div class="eb-body">' +
                        (p.content ? '<div class="eb-content">' + esc(p.content) + '</div>' : '') +
                        (info ? '<div class="eb-info">' + info + '</div>' : '') +
                        btn +
                    '</div>' +
                '</div>';
        });
        listBox.innerHTML = html;
    }

    window.ebToggle = function (id) {
        var el = document.getElementById('ebItem' + id);
        if (el) el.classList.toggle('open');
    };

    /* ---------- 신청 모달 ---------- */
    function openModal(id) {
        var m = document.getElementById(id);
        if (!m) return;
        m.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
    function closeModal(id) {
        var m = document.getElementById(id);
        if (!m) return;
        m.classList.remove('show');
        document.body.style.overflow = '';
    }

    window.ebOpenApply = function (pid) {
        var p = null;
        for (var i = 0; i < PROGRAMS.length; i++) {
            if (PROGRAMS[i].id === pid) { p = PROGRAMS[i]; break; }
        }
        document.getElementById('ebProgramId').value = pid;
        document.getElementById('ebApplyTitle').textContent = p ? p.title : '교육 신청';
        document.getElementById('ebApplyFormWrap').style.display = 'block';
        document.getElementById('ebApplyOk').style.display = 'none';
        document.getElementById('ebApplyErr').style.display = 'none';
        document.getElementById('ebApplyForm').reset();
        document.getElementById('ebProgramId').value = pid;
        openModal('ebApplyModal');
    };
    window.ebCloseApply = function () { closeModal('ebApplyModal'); };

    window.ebOpenInstructor = function () {
        document.getElementById('ebInstFormWrap').style.display = 'block';
        document.getElementById('ebInstOk').style.display = 'none';
        document.getElementById('ebInstErr').style.display = 'none';
        document.getElementById('ebInstForm').reset();
        openModal('ebInstModal');
    };
    window.ebCloseInstructor = function () { closeModal('ebInstModal'); };

    // 모달 배경 클릭 / ESC 닫기
    ['ebApplyModal', 'ebInstModal'].forEach(function (mid) {
        var m = document.getElementById(mid);
        if (!m) return;
        m.addEventListener('click', function (e) {
            if (e.target === m) closeModal(mid);
        });
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeModal('ebApplyModal');
            closeModal('ebInstModal');
        }
    });

    function showErr(boxId, msg) {
        var b = document.getElementById(boxId);
        b.textContent = msg;
        b.style.display = 'block';
        b.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    /* ---------- 교육 신청 제출 ---------- */
    var applyForm = document.getElementById('ebApplyForm');
    applyForm.addEventListener('submit', function (e) {
        e.preventDefault();
        document.getElementById('ebApplyErr').style.display = 'none';

        var pid = val('ebProgramId');
        var name = val('ebAName');
        var phone = val('ebAPhone');

        if (!name) { showErr('ebApplyErr', '이름을 입력해 주세요.'); return; }
        if (!phone) { showErr('ebApplyErr', '연락처를 입력해 주세요.'); return; }
        var digits = phone.replace(/[^0-9]/g, '');
        if (digits.length < 9 || digits.length > 11) {
            showErr('ebApplyErr', '연락처 형식이 올바르지 않습니다. (예: 010-1234-5678)');
            return;
        }

        var btn = document.getElementById('ebApplyBtn');
        btn.disabled = true;
        btn.textContent = '접수 중…';

        var qs = new URLSearchParams({
            program_id: pid,
            name: name,
            phone: phone,
            email: val('ebAEmail'),
            region: val('ebARegion'),
            organization: val('ebAOrg'),
            memo: val('ebAMemo')
        });

        fetch(API + '/submit?' + qs.toString(), { method: 'POST' })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
            .then(function (res) {
                if (!res.ok) throw new Error((res.body && res.body.detail) || '접수에 실패했습니다.');
                document.getElementById('ebApplyFormWrap').style.display = 'none';
                document.getElementById('ebApplyOk').style.display = 'block';
                if (res.body && res.body.message) {
                    document.getElementById('ebApplyOkMsg').innerHTML =
                        esc(res.body.message) + '<br>감사합니다.';
                }
                loadPrograms();
            })
            .catch(function (err) {
                showErr('ebApplyErr', err.message || '네트워크 오류가 발생했습니다.');
            })
            .then(function () {
                btn.disabled = false;
                btn.textContent = '신청하기';
            });
    });

    /* ---------- 소속 강사 신청 제출 ---------- */
    var instForm = document.getElementById('ebInstForm');
    instForm.addEventListener('submit', function (e) {
        e.preventDefault();
        document.getElementById('ebInstErr').style.display = 'none';

        var name = val('ebIName');
        var phone = val('ebIPhone');
        if (!name) { showErr('ebInstErr', '이름을 입력해 주세요.'); return; }
        if (!phone) { showErr('ebInstErr', '연락처를 입력해 주세요.'); return; }
        var digits = phone.replace(/[^0-9]/g, '');
        if (digits.length < 9 || digits.length > 11) {
            showErr('ebInstErr', '연락처 형식이 올바르지 않습니다. (예: 010-1234-5678)');
            return;
        }

        var btn = document.getElementById('ebInstBtn');
        btn.disabled = true;
        btn.textContent = '접수 중…';

        var fileEl = document.getElementById('ebIPdf');
        var file = fileEl && fileEl.files ? fileEl.files[0] : null;

        function doSubmit(pdfPath, pdfName) {
            var qs = new URLSearchParams({
                name: name,
                phone: phone,
                email: val('ebIEmail'),
                region: val('ebIRegion'),
                organization: val('ebIOrg'),
                memo: val('ebIMemo'),
                birth_date: val('ebIBirth'),
                career: val('ebICareer'),
                has_certificate: val('ebICert'),
                certificate_detail: val('ebICertDetail'),
                pdf_path: pdfPath || '',
                pdf_name: pdfName || ''
            });
            return fetch(API + '/instructor/submit?' + qs.toString(), { method: 'POST' })
                .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
                .then(function (res) {
                    if (!res.ok) throw new Error((res.body && res.body.detail) || '접수에 실패했습니다.');
                    document.getElementById('ebInstFormWrap').style.display = 'none';
                    document.getElementById('ebInstOk').style.display = 'block';
                })
                .catch(function (err) {
                    showErr('ebInstErr', err.message || '네트워크 오류가 발생했습니다.');
                })
                .then(function () {
                    btn.disabled = false;
                    btn.textContent = '소속 강사 신청하기';
                });
        }

        if (file) {
            if (file.size > 10 * 1024 * 1024) {
                showErr('ebInstErr', '파일 크기는 10MB 이하여야 합니다.');
                btn.disabled = false; btn.textContent = '소속 강사 신청하기';
                return;
            }
            var fd = new FormData();
            fd.append('file', file);
            fetch(API + '/instructor/upload', { method: 'POST', body: fd })
                .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
                .then(function (res) {
                    if (!res.ok) throw new Error((res.body && res.body.detail) || 'PDF 업로드에 실패했습니다.');
                    return doSubmit(res.body.data.path, res.body.data.name);
                })
                .catch(function (err) {
                    showErr('ebInstErr', err.message || 'PDF 업로드에 실패했습니다.');
                    btn.disabled = false;
                    btn.textContent = '소속 강사 신청하기';
                });
        } else {
            doSubmit('', '');
        }
    });

    loadPrograms();

    // ?instructor=1 로 진입하면 소속 강사 신청 팝업을 자동으로 연다.
    try {
        if (/[?&]instructor=1/.test(location.search)) {
            setTimeout(window.ebOpenInstructor, 260);
        }
    } catch (e) { /* noop */ }
})();
