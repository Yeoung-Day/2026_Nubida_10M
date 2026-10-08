/**
 * ai-assistant.js — [신규 260914] 누비다 AI 스튜디오 "AI 도우미"
 * ══════════════════════════════════════════════════════════════
 * 스튜디오 안에서 바로 쓰는 AI 채팅 + 가사 자동 생성 + 노래 만들기 가이드
 *
 *   - 백엔드: /api/ai/chat  (자유 대화)
 *             /api/ai/lyrics (주제 -> 가사 마디 배열)
 *   - 같은 서버(app.py)가 ollama:11434 를 호출하므로 로그인 불필요
 *   - 생성한 가사를 작업실 마디에 원클릭 적용
 * ══════════════════════════════════════════════════════════════
 */

window.AI_HISTORY = [];      // 대화 문맥 (최근 것만 서버로 전송)
window.AI_BUSY = false;      // 요청 진행 중 여부
window.AI_LAST_LYRICS = [];  // 마지막 생성 가사 (적용용)

// ── 장르 템플릿 ────────────────────────────────────────────────
//   각 장르별 가사 스타일 + 가창 설정(튠/속도/에코/필터/패닝/거칠기/대기)
const GENRE_TEMPLATES = {
    hiphop: {
        label: '🎤 힙합',
        desc: '강한 비트, 빠른 랩',
        style: '힙합',
        presetKey: 'trap',
        tune: 18, speed: 1.15, echo: 0.10, filter: 0.0, pan: 0.0, grit: 0.35, wait: 0.2
    },
    kpop: {
        label: '✨ K-POP',
        desc: '밝고 경쾌한 아이돌',
        style: 'K-POP',
        presetKey: 'singing',
        tune: 14, speed: 1.05, echo: 0.35, filter: 0.0, pan: 0.0, grit: 0.0, wait: 0.3
    },
    ballad: {
        label: '🌙 발라드',
        desc: '감성적이고 잔잔한',
        style: '발라드',
        presetKey: 'singing',
        tune: 10, speed: 0.9, echo: 0.45, filter: 0.15, pan: 0.0, grit: 0.0, wait: 0.5
    },
    kids: {
        label: '🧸 동요',
        desc: '쉽고 밝은 어린이 노래',
        style: '동요',
        presetKey: 'default',
        tune: 12, speed: 1.0, echo: 0.20, filter: 0.0, pan: 0.0, grit: 0.0, wait: 0.4
    },
    rock: {
        label: '🎸 락',
        desc: '거칠고 강렬한',
        style: '락',
        presetKey: 'boombap',
        tune: 6, speed: 1.0, echo: 0.15, filter: 0.35, pan: 0.0, grit: 0.55, wait: 0.3
    },
    trot: {
        label: '🎺 트로트',
        desc: '흥겨운 한국 전통',
        style: '트로트',
        presetKey: 'singing',
        tune: 8, speed: 1.05, echo: 0.30, filter: 0.10, pan: 0.0, grit: 0.0, wait: 0.35
    }
};

// ── 노래 만들기 5단계 가이드 ───────────────────────────────────
const SONG_GUIDE = [
    { step: 1, icon: '💡', title: '주제 정하기', desc: '어떤 노래를 만들까요? (예: 우정, 꿈, 여행, 우리 반)' },
    { step: 2, icon: '✍️', title: '가사 만들기', desc: '직접 쓰거나, 아래 AI에게 주제를 주고 가사를 받아보세요.' },
    { step: 3, icon: '🎚️', title: '장르 고르기', desc: '장르 카드를 누르면 가창 설정이 자동으로 맞춰집니다.' },
    { step: 4, icon: '🎤', title: '가수 고르기', desc: '5명의 AI 가수 중 목소리에 맞는 친구를 선택하세요.' },
    { step: 5, icon: '🔴', title: '가창 시작!', desc: '작업실에서 [가창 시작]을 누르면 노래가 완성됩니다.' }
];

// ── API 호출 ───────────────────────────────────────────────────
async function aiFetch(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
        const msg = (data && (data.error || data.message)) || `오류 (${res.status})`;
        throw new Error(msg);
    }
    return data;
}

// ── 채팅 UI ────────────────────────────────────────────────────
function aiAppendBubble(role, text) {
    const box = document.getElementById('ai-messages');
    if (!box) return;
    const div = document.createElement('div');
    div.className = 'ai-bubble ' + (role === 'user' ? 'ai-user' : 'ai-bot');
    // 줄바꿈 보존 + 간단한 **굵게** 처리
    const safe = String(text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    div.innerHTML = safe
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
}

function aiShowTyping() {
    const box = document.getElementById('ai-messages');
    if (!box) return null;
    const div = document.createElement('div');
    div.className = 'ai-bubble ai-bot ai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
}

function aiSetStatus(msg, isError) {
    const el = document.getElementById('ai-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#ff5470' : '#8b95a7';
}

async function aiSend() {
    if (window.AI_BUSY) return;
    const input = document.getElementById('ai-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    aiAppendBubble('user', text);
    window.AI_HISTORY.push({ role: 'user', content: text });
    aiSetStatus('AI가 생각하고 있어요...');

    window.AI_BUSY = true;
    const typing = aiShowTyping();
    try {
        const data = await aiFetch('/api/ai/chat', {
            message: text,
            history: window.AI_HISTORY.slice(-6)
        });
        if (typing) typing.remove();
        const reply = data.reply || '(빈 응답)';
        aiAppendBubble('assistant', reply);
        window.AI_HISTORY.push({ role: 'assistant', content: reply });
        aiSetStatus('');
        aiDetectLyricsInReply(reply);
    } catch (e) {
        if (typing) typing.remove();
        aiAppendBubble('assistant', '⚠️ ' + e.message);
        aiSetStatus('오류: ' + e.message, true);
    } finally {
        window.AI_BUSY = false;
    }
}

// AI 답변에 가사처럼 보이는 줄이 여러 개면 "마디에 넣기" 버튼 제공
function aiDetectLyricsInReply(reply) {
    const lines = String(reply).split('\n')
        .map(s => s.replace(/^\s*[-*•\d]+[\.\)]?\s*/, '').trim())
        .filter(s => s.length >= 4 && s.length <= 40);
    if (lines.length >= 3) {
        window.AI_LAST_LYRICS = lines.slice(0, 8);
        const box = document.getElementById('ai-messages');
        const btn = document.createElement('button');
        btn.className = 'ai-apply-inline';
        btn.textContent = '📥 이 가사 ' + window.AI_LAST_LYRICS.length + '마디를 작업실에 넣기';
        btn.onclick = () => applyLyricsToStudio(window.AI_LAST_LYRICS);
        box.appendChild(box.lastElementChild);
        box.lastElementChild.appendChild(document.createElement('br'));
        box.lastElementChild.appendChild(btn);
        box.scrollTop = box.scrollHeight;
    }
}

function aiQuickAsk(q) {
    const input = document.getElementById('ai-input');
    if (!input) return;
    input.value = q;
    aiSend();
}

// ── 가사 자동 생성 ─────────────────────────────────────────────
async function aiGenerateLyrics() {
    if (window.AI_BUSY) return;
    const topicEl = document.getElementById('ai-topic');
    const barsEl = document.getElementById('ai-bars');
    const genre = (window.AI_SELECTED_GENRE || 'hiphop');
    const tpl = GENRE_TEMPLATES[genre] || GENRE_TEMPLATES.hiphop;

    const topic = topicEl ? topicEl.value.trim() : '';
    if (!topic) {
        aiSetStatus('주제를 먼저 입력해 주세요 (예: 우정, 꿈, 여행)', true);
        if (topicEl) topicEl.focus();
        return;
    }
    const bars = barsEl ? parseInt(barsEl.value, 10) || 8 : 8;

    window.AI_BUSY = true;
    aiSetStatus('가사를 만들고 있어요... (10~30초)');
    const box = document.getElementById('ai-lyrics-result');
    if (box) box.innerHTML = '<div class="ai-lyr-loading">✍️ 가사 작성 중...</div>';

    try {
        const data = await aiFetch('/api/ai/lyrics', {
            topic: topic, genre: tpl.style, bars: bars
        });
        const lines = data.lines || [];
        window.AI_LAST_LYRICS = lines;
        aiRenderLyrics(lines, tpl);
        aiSetStatus('✅ ' + lines.length + '마디 가사를 만들었어요!');
    } catch (e) {
        if (box) box.innerHTML = '<div class="ai-lyr-error">⚠️ ' + e.message + '</div>';
        aiSetStatus('오류: ' + e.message, true);
    } finally {
        window.AI_BUSY = false;
    }
}

function aiRenderLyrics(lines, tpl) {
    const box = document.getElementById('ai-lyrics-result');
    if (!box) return;
    box.innerHTML = '';
    lines.forEach((ln, i) => {
        const row = document.createElement('div');
        row.className = 'ai-lyr-row';
        row.innerHTML = '<span class="ai-lyr-num">' + (i + 1) + '</span>' +
                        '<span class="ai-lyr-text"></span>';
        row.querySelector('.ai-lyr-text').textContent = ln;
        box.appendChild(row);
    });
    const actions = document.createElement('div');
    actions.className = 'ai-lyr-actions';
    const btnApply = document.createElement('button');
    btnApply.className = 'ai-btn-primary';
    btnApply.textContent = '📥 작업실에 넣기 (' + lines.length + '마디)';
    btnApply.onclick = () => applyLyricsToStudio(lines, tpl);
    const btnAgain = document.createElement('button');
    btnAgain.className = 'ai-btn-ghost';
    btnAgain.textContent = '🔄 다시 만들기';
    btnAgain.onclick = () => aiGenerateLyrics();
    actions.appendChild(btnApply);
    actions.appendChild(btnAgain);
    box.appendChild(actions);
}

// ── 작업실 마디에 적용 ─────────────────────────────────────────
function applyLyricsToStudio(lines, tpl) {
    if (!lines || !lines.length) return;

    // [260919] 4자리 핀 잠금 제거 — 앞단 이용코드(lock.html)가 접근 제어 담당

    const list = document.getElementById('lyrics-list');
    if (!list) return;

    // 기존 마디 비우기 (환영 문구만 있던 상태면 깔끔하게 교체)
    list.innerHTML = '';

    lines.forEach((text) => {
        addLine(text, tpl ? tpl.presetKey : 'default');
    });

    // 생성된 마디에 장르별 가창 설정 적용
    if (tpl) {
        list.querySelectorAll('.lyric-row').forEach(row => {
            const set = (sel, val) => {
                const el = row.querySelector(sel);
                if (el) el.value = val;
            };
            set('.line-tune', tpl.tune);
            set('.line-speed', tpl.speed);
            set('.line-echo', tpl.echo);
            set('.line-filter', tpl.filter);
            set('.line-pan', tpl.pan);
            set('.line-grit', tpl.grit);
            set('.line-wait', tpl.wait);
        });
    }

    // 장르에 맞는 MR(비트)도 자동 선택
    if (tpl && tpl.presetKey) {
        const presetBtn = document.querySelector(`.preset-btn[data-preset="${tpl.presetKey}"]`);
        if (presetBtn && typeof presetBtn.onclick === 'function') {
            try { presetBtn.onclick(); } catch (e) { /* 무시 */ }
        }
    }

    showPage('page-studio');
    aiSetStatus('✅ ' + lines.length + '마디를 작업실에 넣었어요! [🔴 가창 시작]을 눌러보세요.');
}

// ── 장르 카드 선택 ─────────────────────────────────────────────
function aiSelectGenre(key) {
    window.AI_SELECTED_GENRE = key;
    document.querySelectorAll('.ai-genre-card').forEach(c => {
        c.classList.toggle('active', c.getAttribute('data-genre') === key);
    });
    const tpl = GENRE_TEMPLATES[key];
    if (tpl) aiSetStatus('장르: ' + tpl.label + ' — ' + tpl.desc);
}

// 장르 카드를 작업실 설정에 바로 적용 (가사 없이)
function aiApplyGenreToStudio() {
    const key = window.AI_SELECTED_GENRE || 'hiphop';
    const tpl = GENRE_TEMPLATES[key];
    if (!tpl) return;
    // [260919] 4자리 핀 잠금 제거 — 앞단 이용코드(lock.html)가 접근 제어 담당
    const rows = document.querySelectorAll('.lyric-row');
    if (!rows.length) {
        aiSetStatus('⚠️ 작업실에 마디가 없습니다. 가사를 먼저 넣어주세요.', true);
        return;
    }
    rows.forEach(row => {
        const set = (sel, val) => { const el = row.querySelector(sel); if (el) el.value = val; };
        set('.line-tune', tpl.tune);
        set('.line-speed', tpl.speed);
        set('.line-echo', tpl.echo);
        set('.line-filter', tpl.filter);
        set('.line-pan', tpl.pan);
        set('.line-grit', tpl.grit);
        set('.line-wait', tpl.wait);
    });
    aiSetStatus('✅ ' + tpl.label + ' 설정을 모든 마디에 적용했어요!');
}

// ── 초기화 ─────────────────────────────────────────────────────
function aiInitUI() {
    // 장르 카드 렌더
    const gBox = document.getElementById('ai-genre-grid');
    if (gBox) {
        gBox.innerHTML = '';
        Object.keys(GENRE_TEMPLATES).forEach(key => {
            const t = GENRE_TEMPLATES[key];
            const card = document.createElement('div');
            card.className = 'ai-genre-card';
            card.setAttribute('data-genre', key);
            card.innerHTML = '<div class="ai-genre-label">' + t.label + '</div>' +
                             '<div class="ai-genre-desc">' + t.desc + '</div>';
            card.onclick = () => aiSelectGenre(key);
            gBox.appendChild(card);
        });
    }
    // 가이드 렌더
    const guideBox = document.getElementById('ai-guide-list');
    if (guideBox) {
        guideBox.innerHTML = '';
        SONG_GUIDE.forEach(g => {
            const el = document.createElement('div');
            el.className = 'ai-guide-step';
            el.innerHTML = '<div class="ai-guide-icon">' + g.icon + '</div>' +
                '<div class="ai-guide-body"><div class="ai-guide-title">' +
                g.step + '. ' + g.title + '</div><div class="ai-guide-desc">' +
                g.desc + '</div></div>';
            guideBox.appendChild(el);
        });
    }
    aiSelectGenre('hiphop');
    if (!window.AI_HISTORY.length) {
        aiAppendBubble('assistant',
            '안녕하세요! 누비다 AI 작곡가예요 🎵\n\n' +
            '노래 만드는 걸 도와드릴게요. 이렇게 물어보세요:\n' +
            '• "우정에 대한 힙합 가사 8마디 써줘"\n' +
            '• "발라드 가사인데 더 감성적으로 고쳐줘"\n' +
            '• "동요 만들기 좋은 주제 추천해줘"\n\n' +
            '또는 위에서 주제만 입력하고 [가사 만들기]를 눌러도 돼요!');
    }
}
