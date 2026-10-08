/**
 * mic.js — [C안 260914] 실제 사람 목소리로 가창하기 (마이크 녹음 모드)
 * ══════════════════════════════════════════════════════════════
 * AI 가창(B안)과 완전히 별도로 동작하는 "내 목소리 녹음" 기능입니다.
 *
 *   사용법:  MR(반주) 재생 -> 마이크로 직접 랩/노래 -> 녹음 -> 재생/저장
 *
 * 설계 원칙:
 *   - engine.js 의 AI 가창과 독립 (isProducing 등 상태 공유 안 함)
 *   - MR 재생은 engine.js 의 playMRWithFadeIn / stopMRWithFadeOut 재사용
 *   - MediaRecorder 로 마이크 입력을 녹음 -> Blob -> 재생/다운로드
 *   - HTTPS 필수 (ai.nubidaplet.kr 는 HTTPS 이므로 OK)
 * ══════════════════════════════════════════════════════════════
 */

let micStream = null;          // getUserMedia 스트림
let micRecorder = null;        // MediaRecorder 인스턴스
let micChunks = [];            // 녹음 조각
let micRecording = false;      // 녹음 중 여부
let micBlob = null;            // 완성된 녹음 파일
let micBlobUrl = null;         // 재생용 URL
let micSourceNode = null;      // 모니터링 노드 (헤드폰으로 자기 목소리 듣기)
let micAnalyser = null;        // 레벨 미터용

const MIC_MIME_CANDIDATES = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus'
];

// 브라우저가 지원하는 녹음 포맷 선택 (Safari 는 audio/mp4)
function micPickMime() {
    if (typeof MediaRecorder === 'undefined') return null;
    for (const m of MIC_MIME_CANDIDATES) {
        try {
            if (MediaRecorder.isTypeSupported(m)) return m;
        } catch (e) { /* 무시 */ }
    }
    return ''; // 브라우저 기본값 사용
}

// 마이크 권한 요청 (1회)
async function micEnsureStream() {
    if (micStream && micStream.active) return micStream;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('이 브라우저는 마이크 녹음을 지원하지 않습니다. (HTTPS 필요)');
    }
    micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: false,   // 노래 녹음이므로 에코 제거 끔
            noiseSuppression: false,   // 노이즈 억제 끔 (목소리 보존)
            autoGainControl: true      // 음량 자동 조절 (작은 소리 보정)
        },
        video: false
    });
    return micStream;
}

// ── UI 갱신 ────────────────────────────────────────────────────
function micUpdateUI() {
    const btn = document.getElementById('btn-mic-rec');
    const st = document.getElementById('mic-status');
    if (btn) {
        btn.textContent = micRecording ? '⏹ 녹음 중지' : '🎤 마이크 녹음 시작';
        btn.classList.toggle('mic-on', micRecording);
    }
    if (st) {
        if (micRecording) {
            st.textContent = '🔴 녹음 중... 반주에 맞춰 불러주세요';
            st.style.color = '#ff5470';
        } else if (micBlob) {
            st.textContent = '✅ 녹음 완료 (' + micBlob.size_fmt() + ')';
            st.style.color = '#3ddc97';
        } else {
            st.textContent = '대기 중 — 마이크 권한이 필요합니다';
            st.style.color = '#8b95a7';
        }
    }
    const playBtn = document.getElementById('btn-mic-play');
    const dlBtn = document.getElementById('btn-mic-download');
    if (playBtn) playBtn.disabled = !micBlob;
    if (dlBtn) dlBtn.disabled = !micBlob;
}

// Blob 크기를 읽기 좋게 (편의용 확장 — 함수형으로 안전하게)
function micFmtSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

// ── 녹음 시작 ──────────────────────────────────────────────────
async function micStartRecording() {
    if (micRecording) return;
    const status = document.getElementById('mic-status');
    try {
        if (typeof stopAll === 'function') stopAll(); // AI 가창이 돌고 있으면 정지
        const stream = await micEnsureStream();

        const mime = micPickMime();
        if (mime === null) throw new Error('MediaRecorder 미지원 브라우저입니다.');

        micChunks = [];
        micBlob = null;
        micRecorder = mime ? new MediaRecorder(stream, { mimeType: mime })
                           : new MediaRecorder(stream);

        micRecorder.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) micChunks.push(e.data);
        };
        micRecorder.onstop = () => {
            micBlob = new Blob(micChunks, { type: micRecorder.mimeType || 'audio/webm' });
            micBlob.size_fmt = function () { return micFmtSize(this.size); };
            if (micBlobUrl) URL.revokeObjectURL(micBlobUrl);
            micBlobUrl = URL.createObjectURL(micBlob);
            const audioEl = document.getElementById('mic-playback');
            if (audioEl) audioEl.src = micBlobUrl;
            micRecording = false;
            micStopMonitor();
            if (typeof stopMRWithFadeOut === 'function') stopMRWithFadeOut();
            micUpdateUI();
        };

        // 반주 재생 (engine.js 재사용) — 랜덤 비트
        if (typeof BEAT_LIBRARY !== 'undefined' && typeof playMRWithFadeIn === 'function') {
            const beat = '/static/' + BEAT_LIBRARY[Math.floor(Math.random() * BEAT_LIBRARY.length)];
            await playMRWithFadeIn(beat);
        }
        // 자기 목소리 모니터링 (헤드폰 착용 시 유용, 스피커면 하울링 주의)
        micStartMonitor(stream);

        micRecorder.start(250); // 250ms 단위로 조각 수집
        micRecording = true;
        micUpdateUI();
    } catch (e) {
        console.error('마이크 녹음 시작 실패:', e);
        if (status) {
            status.textContent = '❌ ' + (e.message || '마이크를 사용할 수 없습니다');
            status.style.color = '#ff5470';
        }
        micRecording = false;
        micUpdateUI();
    }
}

// ── 녹음 중지 ──────────────────────────────────────────────────
function micStopRecording() {
    if (!micRecording) return;
    try {
        if (micRecorder && micRecorder.state !== 'inactive') micRecorder.stop();
    } catch (e) {
        console.warn('녹음 중지 오류:', e);
        micRecording = false;
        micUpdateUI();
    }
}

// 토글
function micToggle() {
    if (micRecording) micStopRecording();
    else micStartRecording();
}

// ── 모니터링 (자기 목소리 미터) ─────────────────────────────────
function micStartMonitor(stream) {
    try {
        if (typeof audioCtx === 'undefined') return;
        if (audioCtx.state === 'suspended') audioCtx.resume();
        // 스피커 하울링 방지를 위해 출력에는 연결하지 않고 레벨만 측정
        micSourceNode = audioCtx.createMediaStreamSource(stream);
        micAnalyser = audioCtx.createAnalyser();
        micAnalyser.fftSize = 512;
        micSourceNode.connect(micAnalyser);
        micDrawMeter();
    } catch (e) {
        console.warn('마이크 모니터 실패:', e);
    }
}

function micStopMonitor() {
    try {
        if (micSourceNode) { micSourceNode.disconnect(); micSourceNode = null; }
        micAnalyser = null;
    } catch (e) { /* 무시 */ }
}

// 녹음 중 레벨 표시 (마이크 입력 확인용)
function micDrawMeter() {
    if (!micRecording || !micAnalyser) return;
    const bar = document.getElementById('mic-level-bar');
    if (bar) {
        const data = new Uint8Array(micAnalyser.frequencyBinCount);
        micAnalyser.getByteTimeDomainData(data);
        let peak = 0;
        for (let i = 0; i < data.length; i++) {
            const v = Math.abs(data[i] - 128) / 128;
            if (v > peak) peak = v;
        }
        bar.style.width = Math.min(100, Math.round(peak * 140)) + '%';
        bar.style.background = peak > 0.9 ? '#ff5470' : '#3ddc97';
    }
    requestAnimationFrame(micDrawMeter);
}

// ── 재생 / 다운로드 ────────────────────────────────────────────
function micPlayRecording() {
    const audioEl = document.getElementById('mic-playback');
    if (!audioEl || !micBlobUrl) return;
    audioEl.currentTime = 0;
    audioEl.play().catch(e => console.warn('재생 실패:', e));
}

function micDownloadRecording() {
    if (!micBlob || !micBlobUrl) return;
    const ext = (micBlob.type || '').includes('mp4') ? 'm4a'
              : (micBlob.type || '').includes('ogg') ? 'ogg' : 'webm';
    const a = document.createElement('a');
    a.href = micBlobUrl;
    const title = (document.getElementById('song-title-input') || {}).value || 'my_vocal';
    a.download = (title.trim() || 'my_vocal') + '.' + ext;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// 페이지 이탈 시 마이크 해제
window.addEventListener('beforeunload', () => {
    try {
        if (micStream) micStream.getTracks().forEach(t => t.stop());
    } catch (e) { /* 무시 */ }
});
