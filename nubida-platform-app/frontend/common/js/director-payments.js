/* ============================================================
   누비다플랫폼 — 원장 결제 (payments.html)
   월 정산 → 본사 로열티 입금 → 승인 요청
   ============================================================ */
(function () {
    'use strict';

    const API = (window.API_BASE || '/api/v1');
    let currentPeriod = '';
    let hqAccount = '';

    function won(n) { return Number(n || 0).toLocaleString('ko-KR') + '원'; }
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function thisYm() {
        const d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    }
    function toast(msg, isError) {
        const el = document.getElementById('pmToast');
        if (!el) return;
        el.textContent = msg;
        el.classList.toggle('is-error', !!isError);
        el.classList.add('is-on');
        clearTimeout(el._t);
        el._t = setTimeout(() => el.classList.remove('is-on'), 2400);
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

    function renderSettle(d) {
        d = d || {};
        document.getElementById('pmTotal').textContent = won(d.total);
        document.getElementById('pmSupply').textContent = won(d.supply);
        document.getElementById('pmNet').textContent = won(d.net);
        document.getElementById('pmRoyalty').textContent = won(d.royalty);
        document.getElementById('pmVatSub').textContent = '부가세 ' + won(d.vat);
        document.getElementById('pmTotalSub').textContent =
            '납부 ' + (d.paid_count || 0) + '건 / 전체 ' + (d.student_count || 0) + '명';
        if (d.hq_account) {
            hqAccount = d.hq_account;
            document.getElementById('pmAccount').textContent = d.hq_account;
        }
        // 금액 기본값 = 로열티
        const amtEl = document.getElementById('pmAmount');
        if (!amtEl.value && d.royalty) amtEl.value = Number(d.royalty).toLocaleString('ko-KR');
        renderBanner(d);
    }

    function renderBanner(d) {
        const el = document.getElementById('pmStatusBanner');
        const st = d.approval_status;
        if (!st || st === 'rejected') {
            if (st === 'rejected') {
                el.innerHTML = `
                    <div class="pm-status-banner pm-rejected">
                        <div class="pm-status-icon">✕</div>
                        <div class="pm-status-text">
                            <b>반려되었습니다</b>
                            <span>${esc(d.director_note || '내용을 확인하고 다시 요청해 주세요.')}</span>
                        </div>
                    </div>`;
            } else {
                el.innerHTML = '';
            }
            return;
        }
        if (st === 'approved') {
            el.innerHTML = `
                <div class="pm-status-banner pm-approved">
                    <div class="pm-status-icon">✓</div>
                    <div class="pm-status-text">
                        <b>승인 완료</b>
                        <span>${esc(d.director_note || '')} <br>본사에서 입금을 확인했습니다.</span>
                    </div>
                </div>`;
        } else {
            el.innerHTML = `
                <div class="pm-status-banner pm-pending">
                    <div class="pm-status-icon">⋯</div>
                    <div class="pm-status-text">
                        <b>입금 확인 대기</b>
                        <span>${esc(d.director_note || '')} <br>본사에서 입금 내역을 확인하고 있습니다.</span>
                    </div>
                </div>`;
        }
    }

    function renderHistory(items) {
        const body = document.getElementById('pmHistoryBody');
        if (!items || !items.length) {
            body.innerHTML = '<tr><td colspan="5" class="pm-empty">아직 입금 요청 이력이 없습니다.</td></tr>';
            return;
        }
        body.innerHTML = items.map(it => {
            let cls = 'pm-badge-pending';
            if (it.status === 'approved' || it.status === 'paid') cls = 'pm-badge-approved';
            else if (it.status === 'rejected') cls = 'pm-badge-rejected';
            return `<tr>
                <td class="pm-ym">${esc(it.period_ym)}</td>
                <td class="pm-depositor">${esc(it.depositor_name || '—')}</td>
                <td class="pm-money">${won(it.royalty_amount)}</td>
                <td><span class="pm-badge ${cls}">${esc(it.status_label)}</span></td>
                <td class="pm-depositor">${it.created_at ? esc(String(it.created_at).slice(0, 10)) : '—'}</td>
            </tr>`;
        }).join('');
    }

    async function load() {
        const period = document.getElementById('periodYm').value || thisYm();
        currentPeriod = period;
        try {
            const [settle, hist] = await Promise.all([
                req('GET', '/director/tuition/settle?period_ym=' + encodeURIComponent(period)),
                req('GET', '/director/tuition/history'),
            ]);
            renderSettle(settle);
            renderHistory(hist && hist.items);
        } catch (e) {
            console.error(e);
            toast(e.message, true);
        }
    }

    async function submit() {
        const depositor = (document.getElementById('pmDepositor').value || '').trim();
        const amountRaw = (document.getElementById('pmAmount').value || '').replace(/[^0-9]/g, '');
        if (!depositor) { toast('입금자명을 입력해 주세요.', true); return; }
        if (!/^\[.+\].+/.test(depositor)) {
            toast('[지역]학원명 형식으로 입력해 주세요.', true); return;
        }
        if (!amountRaw) { toast('입금금액을 입력해 주세요.', true); return; }
        const btn = document.getElementById('pmSubmitBtn');
        btn.disabled = true;
        try {
            await req('POST', '/director/tuition/submit', {
                period_ym: currentPeriod,
                depositor_name: depositor,
                amount: Number(amountRaw),
            });
            toast('본사에 입금 확인을 요청했습니다.');
            await load();
        } catch (e) {
            toast(e.message, true);
        }
        btn.disabled = false;
    }

    function copyAccount() {
        const txt = document.getElementById('pmAccount').textContent || '';
        navigator.clipboard.writeText(txt).then(
            () => toast('계좌번호를 복사했습니다.'),
            () => toast('복사에 실패했습니다.', true)
        );
    }

    window.PM = { submit, copyAccount, reload: load };

    document.addEventListener('DOMContentLoaded', function () {
        const picker = document.getElementById('periodYm');
        if (picker) {
            picker.value = thisYm();
            picker.addEventListener('change', load);
        }
        const amt = document.getElementById('pmAmount');
        if (amt) {
            amt.addEventListener('input', function () {
                const v = this.value.replace(/[^0-9]/g, '');
                this.value = v ? Number(v).toLocaleString('ko-KR') : '';
            });
        }
        if (typeof requireAuth === 'function') requireAuth();
        load();
    });
})();
