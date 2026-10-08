/* ============================================================
   누비다플랫폼 — 원장 매출 관리 (revenue.html)
   월별 학생 납부 체크 + 정산(부가세 10% / 로열티 45% / 순수익)
   ============================================================ */
(function () {
    'use strict';

    const API = (window.API_BASE || '/api/v1');
    let currentPeriod = '';
    let currentItems = [];
    let courseTypes = [
        { type: 'ai_art', label: 'AI아트', amount: 98000 },
        { type: 'ai_robot', label: 'AI로봇', amount: 198000 },
    ];

    // ---------- 유틸 ----------
    function won(n) {
        n = Number(n || 0);
        return n.toLocaleString('ko-KR') + '원';
    }
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function thisYm() {
        const d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    }
    function ymLabel(ym) {
        if (!ym || ym.length < 7) return '—';
        return ym.slice(0, 4) + '년 ' + Number(ym.slice(5, 7)) + '월';
    }
    function toast(msg, isError) {
        const el = document.getElementById('rvToast');
        if (!el) return;
        el.textContent = msg;
        el.classList.toggle('is-error', !!isError);
        el.classList.add('is-on');
        clearTimeout(el._t);
        el._t = setTimeout(() => el.classList.remove('is-on'), 2200);
    }
    async function req(method, path, body) {
        const token = (typeof getToken === 'function' ? getToken() : localStorage.getItem('token')) || '';
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const res = await fetch(API + path, opts);
        let json = null;
        try { json = await res.json(); } catch (e) { json = null; }
        if (!res.ok) {
            const detail = (json && (json.detail || json.message)) || ('오류 ' + res.status);
            throw new Error(typeof detail === 'string' ? detail : '요청을 처리하지 못했습니다.');
        }
        return json && Object.prototype.hasOwnProperty.call(json, 'data') ? json.data : json;
    }

    // ---------- 렌더 ----------
    function renderSummary(sum) {
        sum = sum || {};
        document.getElementById('rvTotalExpected').textContent = won(sum.total_expected);
        document.getElementById('rvStudentCount').textContent = (sum.student_count || 0) + '명';
        document.getElementById('rvPaidCount').textContent = (sum.paid_count || 0);
        document.getElementById('rvTotalPaid').textContent = won(sum.total_paid);
        document.getElementById('rvUnpaid').textContent = won(sum.unpaid);
        document.getElementById('rvUnpaidCount').textContent = (sum.unpaid_count || 0);

        document.getElementById('rvCalcPeriod').textContent = ymLabel(currentPeriod) + ' 기준';
        document.getElementById('rvCalcTotal').textContent = won(sum.total);
        document.getElementById('rvCalcSupply').textContent = won(sum.supply);
        document.getElementById('rvCalcVat').textContent = won(sum.vat);
        document.getElementById('rvCalcRoyalty').textContent = won(sum.royalty);
        document.getElementById('rvCalcNet').textContent = won(sum.net);
        document.getElementById('rvCalcNet2').textContent = won(sum.net);
    }

    function courseOptions(selected) {
        return courseTypes.map(c =>
            `<option value="${c.type}" ${c.type === selected ? 'selected' : ''}>${esc(c.label)} ${c.amount.toLocaleString('ko-KR')}원</option>`
        ).join('');
    }

    function renderStudents(items) {
        currentItems = items || [];
        const body = document.getElementById('rvStudentBody');
        if (!currentItems.length) {
            body.innerHTML = '<tr><td colspan="5" class="rv-empty">소속 학생이 없습니다.</td></tr>';
            document.getElementById('rvFootNote').textContent = '—';
            return;
        }
        body.innerHTML = currentItems.map(it => `
            <tr data-sid="${it.student_id}">
                <td class="rv-col-check">
                    <input type="checkbox" class="rv-check" ${it.paid ? 'checked' : ''}
                           onchange="RV.togglePaid(${it.student_id}, this.checked)">
                </td>
                <td>
                    <div class="rv-student-name">${esc(it.student_name)}</div>
                    ${it.student_username ? `<div class="rv-student-user">@${esc(it.student_username)}</div>` : ''}
                </td>
                <td class="rv-col-course">
                    <select class="rv-course-select ${it.course_type === 'ai_robot' ? 'is-robot' : ''}"
                            onchange="RV.changeCourse(${it.student_id}, this.value, this)">
                        ${courseOptions(it.course_type)}
                    </select>
                </td>
                <td class="rv-col-amount"><span class="rv-amount">${won(it.amount)}</span></td>
                <td class="rv-col-status">
                    <span class="rv-status ${it.paid ? 'rv-status-paid' : 'rv-status-unpaid'}">
                        ${it.paid ? '납부 완료' : '미납'}
                    </span>
                </td>
            </tr>
        `).join('');
        const paidN = currentItems.filter(i => i.paid).length;
        document.getElementById('rvFootNote').textContent =
            `전체 ${currentItems.length}명 · 납부 ${paidN}명 · 미납 ${currentItems.length - paidN}명`;
    }

    // ---------- 로드 ----------
    async function load() {
        const period = document.getElementById('periodYm').value || thisYm();
        currentPeriod = period;
        try {
            const data = await req('GET', '/director/tuition/students?period_ym=' + encodeURIComponent(period));
            if (data && Array.isArray(data.course_types) && data.course_types.length) {
                courseTypes = data.course_types;
            }
            renderSummary(data && data.summary);
            renderStudents(data && data.items);
        } catch (e) {
            console.error(e);
            document.getElementById('rvStudentBody').innerHTML =
                `<tr><td colspan="5" class="rv-empty">${esc(e.message)}</td></tr>`;
            toast(e.message, true);
        }
    }

    async function refreshSummaryOnly() {
        try {
            const data = await req('GET', '/director/tuition/students?period_ym=' + encodeURIComponent(currentPeriod));
            renderSummary(data && data.summary);
        } catch (e) { /* noop */ }
    }

    // ---------- 액션 ----------
    async function togglePaid(studentId, paid) {
        try {
            await req('PUT', '/director/tuition/students/' + studentId, {
                period_ym: currentPeriod, paid: !!paid,
            });
            // 행 상태 갱신
            const row = document.querySelector(`tr[data-sid="${studentId}"]`);
            if (row) {
                const badge = row.querySelector('.rv-status');
                badge.className = 'rv-status ' + (paid ? 'rv-status-paid' : 'rv-status-unpaid');
                badge.textContent = paid ? '납부 완료' : '미납';
            }
            const item = currentItems.find(i => i.student_id === studentId);
            if (item) item.paid = !!paid;
            await refreshSummaryOnly();
            toast(paid ? '납부 처리했습니다.' : '납부를 해제했습니다.');
        } catch (e) {
            toast(e.message, true);
            const cb = document.querySelector(`tr[data-sid="${studentId}"] .rv-check`);
            if (cb) cb.checked = !paid;
        }
    }

    async function changeCourse(studentId, courseType, sel) {
        const c = courseTypes.find(x => x.type === courseType);
        try {
            await req('PUT', '/director/tuition/students/' + studentId, {
                period_ym: currentPeriod, course_type: courseType,
            });
            const item = currentItems.find(i => i.student_id === studentId);
            if (item) { item.course_type = courseType; item.amount = c ? c.amount : item.amount; }
            const row = document.querySelector(`tr[data-sid="${studentId}"]`);
            if (row) {
                row.querySelector('.rv-amount').textContent = won(c ? c.amount : 0);
                sel.classList.toggle('is-robot', courseType === 'ai_robot');
            }
            await refreshSummaryOnly();
            toast((c ? c.label : '') + ' 과정으로 변경했습니다.');
        } catch (e) {
            toast(e.message, true);
        }
    }

    // ---------- 초기화 ----------
    window.RV = { togglePaid, changeCourse, reload: load };

    document.addEventListener('DOMContentLoaded', function () {
        const picker = document.getElementById('periodYm');
        if (picker) {
            picker.value = thisYm();
            picker.addEventListener('change', load);
        }
        if (typeof requireAuth === 'function') requireAuth();
        load();
    });
})();
