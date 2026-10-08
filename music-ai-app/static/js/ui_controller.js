/**
 * ui_controller.js
 */
window.isUnlocked = true; // [260919] 4자리 핀 잠금 제거 — 앞단 이용코드(lock.html)가 접근 제어 담당


// 로딩 상태 업데이트 함수
function updateLoadProgress(current, total, message) {
    const progressFill = document.getElementById('load-progress');
    const statusText = document.getElementById('load-status');
    const percent = Math.round((current / total) * 100);
    
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (statusText) statusText.innerText = `${message} (${percent}%)`;
    console.log(`[Loading] ${percent}% : ${message}`);
}

function showPage(pageId) {
    // 1. 모든 페이지 숨기기
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
        p.style.display = 'none';
    });

    // 2. 대상 페이지 활성화
    const target = document.getElementById(pageId);
    if (target) {
        target.classList.add('active');
        // 게이트(로그인) 페이지 외에는 block으로 표시
        // [260919] 메인 페이지는 block (핀 게이트 시절의 flex 중앙정렬 제거)
        target.style.display = 'block';
    }

    // 3. 내비게이션 활성화 상태 업데이트
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    if (pageId === 'page-studio') document.getElementById('nav-studio').classList.add('active');
    
    // [중요] 게시판 페이지로 들어갈 때 DB에서 새로 불러오기 호출
    if (pageId === 'page-board') {
        document.getElementById('nav-board').classList.add('active');
        renderBoard(); // board.js에 정의된 함수 호출
    }

    // [신규 260914] AI 도우미 페이지 — 최초 진입 시 UI 구성
    if (pageId === 'page-ai') {
        const navAi = document.getElementById('nav-ai');
        if (navAi) navAi.classList.add('active');
        if (typeof aiInitUI === 'function' && !window.AI_INITED) {
            window.AI_INITED = true;
            aiInitUI();
        }
    }
}

// [260919] 작업실 입장 — 4자리 핀 잠금 제거.
//   실제 접근 제어는 앞단 lock.html(6자리 이용 코드)에서 처리한다.
function tryAccessStudio() {
    showPage('page-studio');
}

// [260919] checkPin() 은 더 이상 사용하지 않음 (핀 입력 UI 제거).
//   혹시 남은 호출이 있어도 오류가 나지 않도록 무해한 스텁만 유지한다.
function checkPin() {
    showPage('page-studio');
}

// [최적화 260914] Range 병렬 다운로드
//   기존: 60MB 를 단일 요청으로 받음 -> 5.1초 (98Mbps)
//   개선: HTTP Range 로 4분할 병렬 -> 2.7초 (183Mbps), 약 1.9배 빠름
//   실측: 1개 5135ms / 2개 3605ms / 4개 2746ms / 8개 3045ms  => 4분할이 최적
const RANGE_CHUNKS = 4;
const RANGE_MIN_SIZE = 1 * 1024 * 1024; // 1MB 이상만 분할 (작은 파일은 오히려 손해)

async function loadToVFS(url, vPath, opts) {
    const fs = Module.FS || FS;
    // opts.direct 쓰기 (분할 시 순서 보장 위해)
    const forceRange = opts && opts.range;

    // 1) HEAD 로 크기 확인 (분할 가능 여부 판단)
    let size = 0, acceptRanges = false;
    try {
        const head = await fetch(url, { method: 'HEAD' });
        size = parseInt(head.headers.get('content-length') || '0', 10);
        acceptRanges = (head.headers.get('accept-ranges') || '').includes('bytes');
    } catch (e) { /* HEAD 실패 시 단일 요청으로 */ }

    // 작은 파일이거나 Range 미지원이면 기존 방식
    if (!forceRange && (size < RANGE_MIN_SIZE || !acceptRanges)) {
        const res = await fetch(url);
        const buf = await res.arrayBuffer();
        fs.writeFile(vPath, new Uint8Array(buf));
        return;
    }

    // 2) Range 4분할 병렬 다운로드
    if (!size) { // HEAD 로 크기를 못 얻었으면 단일
        const res = await fetch(url);
        const buf = await res.arrayBuffer();
        fs.writeFile(vPath, new Uint8Array(buf));
        return;
    }

    const chunkSize = Math.ceil(size / RANGE_CHUNKS);
    const parts = await Promise.all(
        Array.from({ length: RANGE_CHUNKS }, async (_, i) => {
            const start = i * chunkSize;
            const end = Math.min(start + chunkSize - 1, size - 1);
            if (start >= size) return new Uint8Array(0);
            const r = await fetch(url, { headers: { 'Range': `bytes=${start}-${end}` } });
            const b = await r.arrayBuffer();
            return new Uint8Array(b);
        })
    );

    // 3) 순서대로 합쳐 VFS 에 쓰기
    const merged = new Uint8Array(size);
    let off = 0;
    for (const p of parts) {
        if (off + p.length > size) break;
        merged.set(p, off);
        off += p.length;
    }
    fs.writeFile(vPath, merged.subarray(0, off));
}

Module.onRuntimeInitialized = async () => {
    try {
        const TOTAL_STEPS = 12; // 전체 로딩 단계 수
        let currentStep = 0;

        updateLoadProgress(++currentStep, TOTAL_STEPS, "오디오 장치 초기화 중...");
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        canvas = document.getElementById('visualizer');
        ctxCanvas = canvas.getContext('2d');
        
        updateLoadProgress(++currentStep, TOTAL_STEPS, "가상 파일 시스템 구축 중...");
        const fs = Module.FS || FS;
        const mkdirP = (p) => { let c = ''; p.split('/').filter(x => x).forEach(x => { c += '/' + x; try { if (!fs.analyzePath(c).exists) fs.mkdir(c); } catch(e) {} }); };
        mkdirP('/vfs/model'); mkdirP('/vfs/espeak/lang');

        const BASE = '/static/models/ko-kss';
        
        // [최적화 260914] 모델 + 토큰 동시 다운로드 (서로 독립적)
        updateLoadProgress(++currentStep, TOTAL_STEPS, "AI 음성 모델 로드 중...");
        await Promise.all([
            loadToVFS(`${BASE}/model.onnx`, '/vfs/model/m.onnx'),
            loadToVFS(`${BASE}/tokens.txt`, '/vfs/model/t.txt')
        ]);
        
        // [최적화 260914] 사전 7개를 병렬 다운로드 (기존: 직렬 6.4초 -> 병렬 1.3초, 약 5초 절감)
        // 각 파일이 개별 Cloudflare 왕복을 하므로 직렬이면 매번 ~0.9초씩 대기했음
        updateLoadProgress(++currentStep, TOTAL_STEPS, "음성 데이터 분석 중...");
        const esFiles = ['phontab', 'phonindex', 'phondata', 'phondata-manifest', 'intonations', 'ko_dict', 'en_dict'];
        await Promise.all(esFiles.map(f =>
            loadToVFS(`${BASE}/espeak-ng-data/${f}`, `/vfs/espeak/${f}`)
        ));

        updateLoadProgress(++currentStep, TOTAL_STEPS, "언어 팩 설치 중...");
        await loadToVFS(`${BASE}/espeak-ng-data/lang/ko`, '/vfs/espeak/lang/ko');

        updateLoadProgress(++currentStep, TOTAL_STEPS, "AI 가창 엔진 최적화 중...");
        ttsEngine = createOfflineTts(Module, {
            offlineTtsModelConfig: {
                offlineTtsVitsModelConfig: { model: '/vfs/model/m.onnx', tokens: '/vfs/model/t.txt', dataDir: '/vfs/espeak', noiseScale: 0.6, noiseScaleW: 0.7, lengthScale: 1.0 },
                numThreads: 1, debug: 0, provider: 'cpu', modelType: 'vits'
            },
            maxNumSentences: 1
        });

        updateLoadProgress(TOTAL_STEPS, TOTAL_STEPS, "시스템 준비 완료!");
        
        // 잠시 후 로딩창 제거
        setTimeout(() => {
            initUI();
            document.getElementById('loading').style.display = 'none';
            document.getElementById('btn-record').disabled = false;
            addLine("AI 힙합 스튜디오에 오신 것을 환영합니다.", "trap");
            visualize();
        }, 500);

    } catch (e) { 
        alert("부팅 실패: " + e.message); 
        document.getElementById('load-status').innerText = "오류 발생: " + e.message;
    }
};

function initUI() {
    const sGrid = document.getElementById('singerGrid');
    Object.keys(SINGERS).forEach(key => {
        const btn = document.createElement('div');
        btn.className = `singer-btn ${key === currentSinger ? 'active' : ''}`;
        btn.innerHTML = `<span class="avatar">${SINGERS[key].icon}</span><span class="name">${SINGERS[key].name}</span>`;
        btn.onclick = () => {
            currentSinger = key;
            document.querySelectorAll('.singer-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        };
        sGrid.appendChild(btn);
    });
}

function addLine(text = "", presetKey = 'default') {
    const list = document.getElementById('lyrics-list');
    const p = PRESETS[presetKey] || PRESETS.default;
    const row = document.createElement('div');
    row.className = 'card lyric-row';
    //row.style.borderLeft = "5px solid #e11d48";
    row.innerHTML = `
        <div style="display:flex; gap:10px; align-items:center; margin-bottom:5px;">
            <input type="text" class="lyric-text" value="${text}" placeholder="가사 입력" 
                   style="flex:1; padding:10px; border:1px solid #ddd; border-radius:8px; font-size:15px;">
            <button onclick="this.parentElement.parentElement.remove()" 
                    style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:20px;">✕</button>
        </div>
        <div class="lyric-controls">
            <div class="ctrl-item"><label>튠</label><input type="range" class="line-tune" min="0" max="20" value="${p.tune}"></div>
            <div class="ctrl-item"><label>에코</label><input type="range" class="line-echo" min="0" max="1" step="0.1" value="${p.echo}"></div>
            <div class="ctrl-item"><label>속도</label><input type="range" class="line-speed" min="0.5" max="2" step="0.1" value="${p.speed}"></div>
            <div class="ctrl-item"><label>📻필터</label><input type="range" class="line-filter" min="0" max="1" step="0.1" value="0"></div>
            <div class="ctrl-item"><label>↔패닝</label><input type="range" class="line-pan" min="-1" max="1" step="0.2" value="0"></div>
            <div class="ctrl-item"><label>🔥거칠게</label><input type="range" class="line-grit" min="0" max="1" step="0.1" value="0"></div>
            <div class="ctrl-item"><label>⏱대기</label><input type="number" class="line-wait" value="${p.wait}" step="0.1"></div>
        </div>`;
    list.appendChild(row);
}

function visualize() {
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const draw = () => {
        requestAnimationFrame(draw);
        analyser.getByteFrequencyData(dataArray);
        ctxCanvas.clearRect(0, 0, canvas.width, canvas.height);
        let x = 0;
        for(let i=0; i<bufferLength; i++) {
            const h = dataArray[i]/2;
            ctxCanvas.fillStyle = `rgb(${h+100}, 29, 72)`;
            ctxCanvas.fillRect(x, canvas.height-h, 2, h);
            x += 3;
        }
    };
    draw();
}