/**
 * 누비다머신 — 이미지 학습 스튜디오 (ml-studio.html)
 *
 * - 100% 브라우저 학습: TensorFlow.js + MobileNet v2 전이학습 (서버 GPU 불필요)
 * - 웹캠/카메라/파일 업로드로 클래스별 샘플 수집
 * - 실시간 분류 (상위 클래스 + 확률 %)
 * - 학습 모델 서버 저장/다운로드/IndexedDB 캐시
 *
 * ── 이미지/음성 공용 추상화 ─────────────────────────────────────────────
 * 학습 파이프라인을 "입력 방식"과 분리해 두었습니다.
 *   source   : 샘플 입력 소스 — { type, start(), stop(), flip(), capture() }
 *              image → 카메라/파일, audio → 마이크 (Web Audio 스펙트로그램)
 *   extractor: 특징 추출기  — { name, load(), embed(input) }
 *              image/audio → MobileNet 특징 추출기 (음성은 스펙트로그램을
 *              224×224 이미지로 변환해 같은 MobileNet에 입력 — 전이학습 재사용)
 * 학습(학습 루프)과 분류(결과 렌더링)는 입력 방식과 무관하게 공용이며,
 * MODES[currentMode]로 소스/추출기를 교체합니다.
 *   - 프로젝트 생성 시 model_type='image'|'audio' 전달 (백엔드 Form 필드)
 *   - window.initStudio('image'|'audio')로 모드 전환 (헤더 토글 버튼)
 *   - 음성 샘플은 3초 스펙트로그램(256×129) PNG로 저장 → 기존 이미지 파이프라인 재사용
 */
(function () {
    'use strict';

    /* ── 성능 모드 (100명 동시 대비 — 저사양 기기 옵션) ────────────────────
     * 학습/분류는 100% 학생 브라우저(TF.js)에서 실행되므로 서버 부담이 없고,
     * 저사양 옵션은 구형 기기(저가 태블릿/노트북)에서의 연산·메모리만 줄인다.
     *   high: MobileNet 1.0_224 + fftSize 512 — 품질 우선 (기본)
     *   low : MobileNet 0.25_224(연산 1/16) + fftSize 256 + 캠 320×240 — 가벼움 우선
     * 선택은 localStorage('ml_perf_mode')에 유지되고, 페이지 진입 시 적용된다.
     * ※ 주의: 128px 입력 모델(mobilenet_v1_*_128)은 tfjs CDN에 존재하지 않아(404)
     *   저사양 모델은 alpha 0.25 + 224px 조합으로 대체한다.
     */
    var PERF_MODES = {
        high: {
            label: '고성능(기본)',
            imgSize: 224,
            camW: 640, camH: 480,
            fftSize: 512,
            specFrames: 129,   // ≈3초 (rAF ~60fps × 3s)
            specMaxBin: 48,
            // 로컬 서버 서빙 — 방화벽/오프라인 환경에서도 학습이 가능하도록
            mobilenetUrl: '/common/js/vendor/mobilenet/model.json',
        },
        low: {
            label: '저사양 기기',
            imgSize: 224,
            camW: 320, camH: 240,
            fftSize: 256,
            specFrames: 96,    // ≈3초
            specMaxBin: 24,
            mobilenetUrl: '/common/js/vendor/mobilenet_025/model.json',
        },
    };
    // ★ 260913 윤비스 지시: 성능은 "저사양" 고정 (고성능/저사양 선택 UI 제거).
    //   - 이미지/음성 두 모드 모두 저사양 프로파일(320×240, fft256, spec 96×24)을 쓴다.
    //   - localStorage('ml_perf_mode') 를 무시하고 항상 'low' 로 동작시킨다.
    function loadPerfMode() { return 'low'; }
    var perfKey = loadPerfMode();
    var perf = PERF_MODES[perfKey];
    var MOBILENET_URL = perf.mobilenetUrl;
    var IMG_SIZE = perf.imgSize;
    var MIN_CLASSES = 2;        // 학습 최소 클래스 수
    var MIN_SAMPLES = 5;        // 클래스당 최소 샘플 수
    var EPOCHS = 40;
    var SPEC_BINS = perf.fftSize / 2;    // AnalyserNode fftSize/2 (512→256, 256→128)
    var SPEC_FRAMES = perf.specFrames;   // 스펙트로그램 시간 프레임 (rAF ~60fps → ≈3초)
    var SPEC_MAX_BIN = perf.specMaxBin;  // 주파수 상한(빈) — 고성능 48빈(≈4.13kHz),
                                         // 저사양 24빈(fftSize=256, bin 폭 172Hz → ≈4.13kHz 동일 대역.
                                         // 440Hz/880Hz는 224px에서도 ~26px 간격으로 분리 가능)
    var CLASS_COLORS = ['#4F5EF8', '#F59E0B', '#10B981', '#EF4444', '#8B5CF6', '#06B6D4', '#EC4899', '#84CC16', '#F97316', '#6366F1'];

    /* ── 모드 설정 (이미지/음성 공용 구조) ───────── */
    // currentMode에 따라 source(입력 소스)와 extractor(특징 추출기)를 교체한다.
    // audio 항목은 골격만 정의 — 다음 단계(음성 방식 확장)에서 구현 예정.
    var MODES = {
        image: {
            modelType: 'image',
            label: '이미지 분류',
            source: null,      // imageSource로 초기화 (아래)
            extractor: null,   // imageExtractor로 초기화 (아래)
        },
        audio: {
            modelType: 'audio',
            label: '음성 분류',
            source: null,      // audioSource — Phase 2 실구현 (스펙트로그램 → MobileNet)
            extractor: null,   // audioExtractor — Phase 2 실구현 (MobileNet 재사용)
        },
    };
    var currentMode = 'image';
    var currentModeDef = MODES[currentMode];

    /* ── Voice Hold — 음성 모드 결과 유지(Latch) ─────────────────────────
     * 문제: runClassifyOnce()가 120ms마다 결과를 갱신해, 말이 끝나면(무음)
     *       판단 결과가 사라지거나 흔들린다.
     * 해결: 오디오 RMS(음량)로 발화 구간을 감지하고, 무음이 0.6초 지속되면
     *       그 시점의 분류 결과를 "확정·고정"한다. 다음 발화가 시작되기
     *       전까지 확정 결과를 계속 표시하고, 확정 결과만 {클래스번호}{접두어}
     *       명령으로 시리얼 전송한다 (무음 중 재전송 금지 = 중복 방지).
     *       이미지 모드에는 적용하지 않는다 (연속 실시간 유지).
     * 상태 전이: idle → speaking → (무음 0.6s) → holding → (소리) → speaking ...
     */
    /* ★ [2026-09-14] 카메라(이미지) 전송 상태 — 음성 voiceHold 와 별도로 관리한다.
     *   카메라는 120ms 마다 같은 클래스를 반복 검출하므로, 같은 값은 1초에 1회만
     *   전송하도록 막는다. (음성은 발화 단위라 이 중복 차단이 불필요)
     */
    var camHold = {
        lastSentIdx: -1,        // 마지막으로 전송한 클래스(0-based)
        lastSentAt: 0,          // 마지막 전송 시각
        lastSkipLogAt: 0,       // 확정 보류 로그 마지막 출력 시각
    };

    var voiceHold = {
        state: 'idle',           // idle | speaking | holding
        // [발화 감지] RMS 게이트 — 낮출수록 작은 소리도 발화로 인정한다.
        //  ★ 2026-09-13: 0.06 은 노트북/폰 내장마이크로 또박또박 말해야 겨우 넘는 값이라
        //    "말을 인식 못 한다" 증상이 잦았다. 0.02 로 낮춰 일반 대화 음량에서도 잡히게 한다.
        //    (너무 낮으면 주변 잡음을 발화로 오인 → 0.01~0.02 권장)
        SPEECH_RMS: 0.02,        // 발화 판단 RMS 임계값 (0~1, 128중심 파형)
        SILENCE_HOLD_MS: 600,    // 무음 0.6초 지속 → 결과 확정
        // [2클래스 거부 튜닝] softmax 가 2클래스면 정상 발화도 55~70% 에 머문다.
        //  · MIN_LOCK_PROB : 1위 확률 하한 (낮게 — 정상 발화를 살린다)
        //  · MIN_LOCK_GAP  : 1위-2위 격차 하한 (이게 실질적 "확신" 판단)
        //    미학습 단어/잡음은 52% vs 48% 처럼 격차가 작아 여기서 걸린다.
        //  ★ 2026-09-13 3차: 정상 발화까지 차단되어 "아예 아무것도 안 됨" 보고 → 
        //    오검출 방지선은 유지하되 정상 인식이 살아나도록 두 값을 완화했다.
        //    (로그의 "격차 %p" 를 보고 최종 조정할 것)
        //  ★ 2026-09-13 4차: "2번은 되는데 1번만 안 된다" 보고 → 특정 클래스가
        //    구조적으로 확률이 낮게 나오는 경우(데이터 불균형/편향)에도 확정되도록
        //    하한을 추가 완화하고, 아래 runClassifyOnce 에서 "1·2위 격차가 충분하면
        //    1위 확률 하한을 낮춰주는" 보완 규칙을 둔다.
        MIN_LOCK_PROB: 0.40,     // 확정 최소 1위 확률
        MIN_LOCK_GAP: 0.08,      // 확정 최소 격차(1위-2위)
        MIN_SHOW_PROB: 0.35,     // 실시간 표시 최소 확률 (미만이면 "판별 중…")
        rms: 0,
        silenceMs: 0,            // 연속 무음 누적(ms) — runClassifyOnce 틱(120ms) 기준
        speechBuf: [],           // 발화 구간 스펙트로그램 프레임 누적 (시작→확정, 120ms 틱)
        startPcmMark: -1,        // [MFCC] 발화 시작 시점 audioSource.pcmTotal 스냅샷 (PCM 분류 기준)
        liveLabel: null,         // 발화 중 실시간 top 후보
        livePct: 0,
        lockedLabel: null,       // 확정·고정된 라벨
        lockedPct: 0,
        lockedIdx: -1,           // 확정 클래스 번호(0-based)
        lastSentValue: '',       // 시리얼 중복 전송 방지
        txState: '',             // '' | 'sending' | 'ok' | 'fail' — 화면 전송값 표시용
        lastSentAt: 0,
        reset: function () {
            this.state = 'idle';
            this.rms = 0; this.silenceMs = 0;
            this.speechBuf = [];
            this.startPcmMark = -1;
            this.liveLabel = null; this.livePct = 0;
            this.lockedLabel = null; this.lockedPct = 0; this.lockedIdx = -1;
        },
    };

    // 현재 마이크 입력의 RMS(0~1) — AnalyserNode time-domain 파형 기반
    function currentRms() {
        var a = audioSource;
        if (!a || !a.analyser || !a.waveArr) return 0;
        a.analyser.getByteTimeDomainData(a.waveArr);
        var sum = 0, v;
        for (var i = 0; i < a.waveArr.length; i++) {
            v = (a.waveArr[i] - 128) / 128;
            sum += v * v;
        }
        return Math.sqrt(sum / a.waveArr.length);
    }

    var projectId = null;
    var classes = [];           // [{name, color, samples:[{dataUrl, width, height, serverId}]}]

    /* ── ★ 8차: MFCC 샘플 영속화 (IndexedDB) ────────────────────────────
     * 기존에는 MFCC PCM 샘플이 '로컬 세션 전용'이라 페이지를 나갔다 오면
     * (1) 수집한 발화 PCM 과 (2) 학습된 Conv1D 헤드가 모두 사라졌다.
     * 또 클래스 삭제 시 서버에 남는 게 없어 되살아나는 문제도 있었다.
     * → 프로젝트별로 클래스 이름 + MFCC PCM(Int16 양자화) 를 IndexedDB 에 저장한다.
     *   · PCM 은 Float32 그대로면 용량이 크므로 Int16 으로 양자화(±1 → ±32767)
     *   · 클래스 삭제/프로젝트 전환 시 해당 스토어를 정리해 '완전 삭제' 보장
     *   · 서버 스키마 변경이 필요 없어 백엔드 무수정으로 해결된다.
     */
    var MLDB_NAME = 'nubida-ml-store';
    var MLDB_STORE = 'mfcc-samples';

    function mlDbOpen() {
        return new Promise(function (resolve, reject) {
            if (!window.indexedDB) { reject(new Error('IndexedDB 미지원')); return; }
            var req = indexedDB.open(MLDB_NAME, 1);
            req.onupgradeneeded = function () {
                var db = req.result;
                if (!db.objectStoreNames.contains(MLDB_STORE)) {
                    db.createObjectStore(MLDB_STORE, { keyPath: 'key' });
                }
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { reject(req.error || new Error('IndexedDB 열기 실패')); };
        });
    }

    function mlDbPut(rec) {
        return mlDbOpen().then(function (db) {
            return new Promise(function (resolve, reject) {
                var tx = db.transaction(MLDB_STORE, 'readwrite');
                tx.objectStore(MLDB_STORE).put(rec);
                tx.oncomplete = function () { db.close(); resolve(true); };
                tx.onerror = function () { db.close(); reject(tx.error); };
            });
        });
    }

    function mlDbGet(key) {
        return mlDbOpen().then(function (db) {
            return new Promise(function (resolve, reject) {
                var tx = db.transaction(MLDB_STORE, 'readonly');
                var rq = tx.objectStore(MLDB_STORE).get(key);
                rq.onsuccess = function () { db.close(); resolve(rq.result || null); };
                rq.onerror = function () { db.close(); reject(rq.error); };
            });
        });
    }

    function mlDbDelete(key) {
        return mlDbOpen().then(function (db) {
            return new Promise(function (resolve, reject) {
                var tx = db.transaction(MLDB_STORE, 'readwrite');
                tx.objectStore(MLDB_STORE).delete(key);
                tx.oncomplete = function () { db.close(); resolve(true); };
                tx.onerror = function () { db.close(); reject(tx.error); };
            });
        });
    }

    // 프로젝트의 MFCC 샘플 전체를 IndexedDB 에 저장 (클래스 구조 + 각 발화 PCM)
    async function saveMfccSamples() {
        if (!projectId || !useMfccPath()) return;
        try {
            var payload = classes.map(function (c) {
                return {
                    name: c.name,
                    samples: c.samples.filter(function (s) { return !!s.mfccPcm; }).map(function (s) {
                        var pcm = s.mfccPcm, n = pcm.length;
                        var i16 = new Int16Array(n);
                        for (var i = 0; i < n; i++) {
                            var v = pcm[i]; if (v > 1) v = 1; else if (v < -1) v = -1;
                            i16[i] = Math.round(v * 32767);
                        }
                        return { pcm: Array.from(i16), n: n };   // ✱ Array.from(Int16Array)
                    })
                };
            });
            var total = payload.reduce(function (a, c) { return a + c.samples.length; }, 0);
            if (!total) { await mlDbDelete('proj-' + projectId); return; }
            await mlDbPut({ key: 'proj-' + projectId, ts: Date.now(), classes: payload });
            console.log('[ml-studio] MFCC 샘플 저장:', total, '개');
        } catch (e) {
            console.warn('[ml-studio] MFCC 샘플 저장 실패:', e.message);
        }
    }

    // IndexedDB 에서 MFCC 샘플 복원 → classes 구조 재구성 (서버 클래스 정보와 병합)
    async function loadMfccSamples() {
        if (!projectId || !useMfccPath()) return false;
        try {
            var rec = await mlDbGet('proj-' + projectId);
            if (!rec || !rec.classes || !rec.classes.length) return false;
            var restored = 0;
            rec.classes.forEach(function (rc) {
                var cls = classes.filter(function (c) { return c.name === rc.name; })[0];
                if (!cls) {   // 서버에 없는 클래스(로컬에서 추가 후 서버 미업로드) → 되살린다
                    cls = { name: rc.name, color: CLASS_COLORS[classes.length % CLASS_COLORS.length], samples: [] };
                    classes.push(cls);
                }
                (rc.samples || []).forEach(function (rs) {
                    if (!rs || !rs.n) return;
                    var i16 = Int16Array.from(rs.pcm || []);
                    var f32 = new Float32Array(rs.n);
                    for (var i = 0; i < rs.n; i++) f32[i] = i16[i] / 32767;
                    cls.samples.push({ dataUrl: null, width: IMG_SIZE, height: IMG_SIZE, serverId: null, mfccPcm: f32 });
                    restored++;
                });
            });
            if (restored) {
                console.log('[ml-studio] MFCC 샘플 복원:', restored, '개');
                renderClasses();
                updateTrainState();
            }
            return restored > 0;
        } catch (e) {
            console.warn('[ml-studio] MFCC 샘플 복원 실패:', e.message);
            return false;
        }
    }

    var selectedIdx = 0;
    var stream = null;
    var facingMode = 'user';
    var mobilenet = null;
    var truncModel = null;      // MobileNet 특징 추출기 (동결)
    var headModel = null;       // 전이학습 분류 헤드
    var classLabels = [];
    var trained = false;
    var classifying = false;
    var classifyTimer = null;
    var classifyRunning = false;      // ★ 260916: 자기재귀 루프 구동 플래그 (적체 방지)
    var holdTimer = null;
    var holdCount = 0;
    var busy = false;
    var mfccTickBusy = false;      // [MFCC 파일럿] 발화 중 실시간 MFCC 분류 중복 방지
    var mfccLastLiveAt = 0;        // [MFCC 파일럿] 마지막 실시간 MFCC 분류 시각

    /* ═══════════════════════════════════════════════════════════════════
     * [MFCC 파일럿] M1 모듈 통합 (설계서_음성MFCC파일럿_0902.md 3.1절)
     * ───────────────────────────────────────────────────────────────────
     * WAV/마이크 PCM(임의 sr) → 16kHz 모노 → STFT(fft512/hop160=10ms/hann)
     *   → 멜 필터뱅크 40채널(200Hz~7.5kHz) → log10(·+1e-10) → DCT-II 13차
     *   → 델타 13차 추가(26채널/프레임) → 프레임별 mean/std 정규화
     *   → 150프레임 pad/truncate → 출력 (1, 150, 26)
     * TF.js 로컬 vendor만 사용 — 외부 CDN 의존 없음 (스튜디오와 동일)
     * ───────────────────────────────────────────────────────────────────
     * M2: audio 모드의 특징 방식을 'spec'(기존 스펙트로그램→MobileNet)과
     * 'mfcc'(본 모듈 → Conv1D 헤드)로 전환 가능하게 한다.
     * ═══════════════════════════════════════════════════════════════════ */
    var MFCC_SR = 16000, MFCC_FFT = 512, MFCC_HOP = 160;
    var MFCC_NUM_MEL = 40, MFCC_CEP = 13, MFCC_MAX_FRAMES = 150;
    var MFCC_DIM = MFCC_CEP * 2;                 // 26
    var MFCC_WIN_SAMPLES = MFCC_MAX_FRAMES * MFCC_HOP + MFCC_FFT - MFCC_HOP;  // 24352 (1.522s)
    var MFCC_N_BINS = MFCC_FFT / 2 + 1;          // 257
    var melTensor = null, dctTensor = null;      // lazy (tf 로드 후 1회)

    function mfccHzToMel(h) { return 2595 * Math.log10(1 + h / 700); }
    function mfccMelToHz(m) { return 700 * (Math.pow(10, m / 2595) - 1); }

    // 멜 필터뱅크 가중치 (257×40, 열 우선 flat — matMul용)
    function mfccBuildMelWeights() {
        var rows = [];
        var melMin = mfccHzToMel(200), melMax = mfccHzToMel(7500);
        var pts = [];
        for (var p = 0; p < MFCC_NUM_MEL + 2; p++) {
            pts.push(mfccMelToHz(melMin + p * (melMax - melMin) / (MFCC_NUM_MEL + 1)));
        }
        var binHz = MFCC_SR / MFCC_FFT;
        for (var m = 0; m < MFCC_NUM_MEL; m++) {
            var row = new Float32Array(MFCC_N_BINS);
            var fL = pts[m], fC = pts[m + 1], fR = pts[m + 2];
            for (var b = 0; b < MFCC_N_BINS; b++) {
                var f = b * binHz;
                if (f >= fL && f <= fC) row[b] = (f - fL) / (fC - fL);
                else if (f > fC && f <= fR) row[b] = (fR - f) / (fR - fC);
            }
            rows.push(row);
        }
        var flat = new Float32Array(MFCC_N_BINS * MFCC_NUM_MEL);
        for (var mm = 0; mm < MFCC_NUM_MEL; mm++) {
            var r = rows[mm];
            for (var bb = 0; bb < MFCC_N_BINS; bb++) flat[bb * MFCC_NUM_MEL + mm] = r[bb];
        }
        return flat;
    }

    // DCT-II 행렬 (40×13, 정규직교) — c[k][m] = cos(π·k·(m+0.5)/M)·√(2/M)
    function mfccBuildDctWeights() {
        var flat = new Float32Array(MFCC_NUM_MEL * MFCC_CEP);
        var s0 = Math.sqrt(1 / MFCC_NUM_MEL), s = Math.sqrt(2 / MFCC_NUM_MEL);
        for (var k = 0; k < MFCC_CEP; k++) {
            var scale = (k === 0) ? s0 : s;
            for (var m = 0; m < MFCC_NUM_MEL; m++) {
                flat[m * MFCC_CEP + k] = scale * Math.cos(Math.PI * k * (m + 0.5) / MFCC_NUM_MEL);
            }
        }
        return flat;
    }

    function mfccEnsureTensors() {
        if (melTensor && dctTensor) return;
        melTensor = tf.tensor2d(mfccBuildMelWeights(), [MFCC_N_BINS, MFCC_NUM_MEL]);
        dctTensor = tf.tensor2d(mfccBuildDctWeights(), [MFCC_NUM_MEL, MFCC_CEP]);
    }

    // [핵심] 16k PCM → MFCC Float32Array(150×26) — stft/mel/log/dct는 tf, 델타·정규화·pad는 JS
    function mfccComputeFromPcm16k(pcm) {
        if (!pcm || pcm.length < MFCC_FFT) {
            return new Float32Array(MFCC_MAX_FRAMES * MFCC_DIM);   // 너무 짧음 → 0
        }
        mfccEnsureTensors();
        var ceps = tf.tidy(function () {
            var sig = tf.tensor1d(pcm);
            // STFT complex64 → tf.abs로 magnitude (windowFn은 함수 자체 전달)
            var spec = tf.signal.stft(sig, MFCC_FFT, MFCC_HOP, MFCC_FFT, tf.signal.hannWindow);
            var mag = tf.abs(spec);                                   // (F,257)
            var melE = mag.matMul(melTensor);                         // (F,40)
            var logMel = tf.log(melE.add(1e-10)).div(Math.log(10));   // log10
            var c = logMel.matMul(dctTensor);                         // (F,13)
            return c.dataSync();
        });
        return mfccPostProcess(ceps, ceps.length / MFCC_CEP);
    }

    // 델타(Δ13) + 프레임별 mean/std 정규화 + 150프레임 pad/truncate
    function mfccPostProcess(ceps, F) {
        var out = new Float32Array(MFCC_MAX_FRAMES * MFCC_DIM);
        var useF = Math.min(F, MFCC_MAX_FRAMES);
        var W = 2, i, t, k;
        for (t = 0; t < useF; t++) {
            var num = new Float64Array(MFCC_CEP);
            var den = 0;
            for (i = 1; i <= W; i++) {
                var a = t - i, b = t + i;
                if (a < 0 || b >= F) continue;
                for (k = 0; k < MFCC_CEP; k++) num[k] += i * (ceps[b * MFCC_CEP + k] - ceps[a * MFCC_CEP + k]);
                den += i * i;
            }
            var dsum = 2 * den || 1;
            var row = new Float64Array(MFCC_DIM);
            for (k = 0; k < MFCC_CEP; k++) row[k] = ceps[t * MFCC_CEP + k];
            for (k = 0; k < MFCC_CEP; k++) row[MFCC_CEP + k] = num[k] / dsum;
            var mean = 0, sd = 0;
            for (k = 0; k < MFCC_DIM; k++) mean += row[k];
            mean /= MFCC_DIM;
            for (k = 0; k < MFCC_DIM; k++) { var dv = row[k] - mean; sd += dv * dv; }
            sd = Math.sqrt(sd / MFCC_DIM);
            for (k = 0; k < MFCC_DIM; k++) out[t * MFCC_DIM + k] = (sd > 1e-6) ? (row[k] - mean) / sd : 0;
        }
        return out;   // 나머지 프레임 0 pad
    }

    // [유틸] 임의 sr AudioBuffer → 16k 모노 (OfflineAudioContext 하드웨어 리샘플)
    async function mfccResampleTo16k(audioBuffer) {
        if (audioBuffer.sampleRate === MFCC_SR && audioBuffer.numberOfChannels === 1) {
            return audioBuffer.getChannelData(0);
        }
        var targetLen = Math.max(1, Math.ceil(audioBuffer.duration * MFCC_SR));
        var OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        var ctx = new OC(1, targetLen, MFCC_SR);
        var src = ctx.createBufferSource();
        src.buffer = audioBuffer;
        src.connect(ctx.destination);
        src.start(0);
        var rendered = await ctx.startRendering();
        return rendered.getChannelData(0);
    }

    // [유틸] Float32Array(마이크 PCM, sr) → 16k (AudioBuffer 경유 — 정확한 리샘플)
    async function mfccResampleFloat32(pcm, sr) {
        if (sr === MFCC_SR) return pcm;
        var buf;
        try {
            buf = new AudioBuffer({ length: pcm.length, sampleRate: sr, numberOfChannels: 1 });
            buf.copyToChannel(pcm, 0);
        } catch (e) {
            var AC = window.AudioContext || window.webkitAudioContext;
            var tmp = new AC();
            buf = tmp.createBuffer(1, pcm.length, sr);
            buf.copyToChannel(pcm, 0);
            tmp.close().catch(function () {});
        }
        return await mfccResampleTo16k(buf);
    }

    // [유틸] ArrayBuffer(webm/wav) → 16k PCM
    async function mfccDecodeToPcm16k(arrayBuf) {
        var AC = window.AudioContext || window.webkitAudioContext;
        var ctx = new AC();
        try {
            var b = await ctx.decodeAudioData(arrayBuf.slice(0));
            return await mfccResampleTo16k(b);
        } finally {
            if (ctx.state !== 'closed') ctx.close().catch(function () {});
        }
    }

    // [유틸] 발화 중심 1.522s(24352샘플) 창 추출 — 슬라이딩 RMS 에너지 최대 구간
    function mfccCenterUtterance(pcm) {
        var need = MFCC_WIN_SAMPLES;
        if (pcm.length <= need) return pcm;
        var step = 160, best = 0, bestE = -1;
        for (var s = 0; s + need <= pcm.length; s += step) {
            var e = 0;
            for (var i = 0; i < need; i += 160) {
                var v = pcm[s + i];
                e += v * v;
            }
            if (e > bestE) { bestE = e; best = s; }
        }
        return pcm.subarray(best, best + need);
    }

    // [테스트] 16k 사인파 생성
    function mfccSinePcm16k(freq, secs, amp) {
        var n = Math.floor(MFCC_SR * secs);
        var out = new Float32Array(n);
        for (var i = 0; i < n; i++) out[i] = (amp || 0.5) * Math.sin(2 * Math.PI * freq * i / MFCC_SR);
        return out;
    }

    // [테스트] 16k PCM → 표시용 스펙트로그램 프레임(0~255, 기존 규격과 동일 변환)
    function mfccSpecFramesForDisplay(pcm16) {
        // PCM(최대 1.6s) → STFT 256빈 magnitude → 0~255 로그 스케일
        try {
            mfccEnsureTensors();
            var spec = tf.tidy(function () {
                var sig = tf.tensor1d(pcm16);
                var s = tf.signal.stft(sig, MFCC_FFT, MFCC_HOP, MFCC_FFT, tf.signal.hannWindow);
                var mag = tf.abs(s);                       // (F,257)
                return mag;
            });
            var F = spec.shape[0];
            var data = spec.dataSync();
            spec.dispose();
            var frames = [];
            for (var f = 0; f < F; f++) {
                var row = new Uint8Array(SPEC_MAX_BIN);
                for (var b = 0; b < SPEC_MAX_BIN; b++) {
                    var v = data[f * MFCC_N_BINS + b];
                    var db = 20 * Math.log10(v + 1e-6);    // dB
                    var norm = Math.min(255, Math.max(0, Math.round((db + 60) * 255 / 70)));
                    row[b] = norm;
                }
                frames.push(row);
            }
            return frames;
        } catch (e) {
            console.warn('[ml-studio] mfcc display spec error:', e.message);
            return [];
        }
    }

    /* ── M2: 특징 방식 토글 (audio 모드) ─────────────────────────────
     * spec: 기존 스펙트로그램 PNG → MobileNet 전이학습 (기본, 서버 저장 지원)
     * mfcc: PCM → MFCC(150×26) → Conv1D 헤드 (파일럿, 로컬 세션 전용)
     */
    // ★ 260913 윤비스 지시: 특징 방식은 "MFCC" 고정 (스펙트로그램 방식 폐기).
    //   이유: 스펙트로그램은 주파수 48빈(≈4.13kHz)뿐이라 한국어 자음 대역이 잘리고
    //   "일번/이번" 같은 유사 단어를 구분하지 못했다. MFCC(40멜·13차+델타·정규화)가
    //   음성 분류의 정식 특징이다. 선택 UI 는 제거했고 항상 'mfcc' 로 동작한다.
    var featureMode = 'mfcc';
    updateFeatUI();   // [M2] 복원 모드(mfcc)에 맞춰 토글/녹음버튼 UI 동기화 — 초기화 누락 버그 수정

    window.setFeatureMode = function (mode) {
        if (mode !== 'spec' && mode !== 'mfcc') return;
        if (mode === featureMode) return;
        if (classifying) stopClassify();
        voiceHold.reset();
        featureMode = mode;
        try { localStorage.setItem('ml-feature-mode', featureMode); } catch (e) {}
        // 특징 방식 변경 → 메모리 헤드 모델 무효화 (분류 입력 규격이 달라짐)
        trained = false;
        headModel = null;
        classLabels = [];
        var td = $('trainDone');
        if (td) td.style.display = 'none';
        updateFeatUI();
        updateTrainState();
        if (mode === 'mfcc') {
            showAlert('🧪 MFCC 파일럿: [🔴 3초 녹음]으로 샘플 수집 → 학습 → 말하면 분류. 샘플은 로컬 세션 전용이에요.');
        } else {
            showAlert('📊 스펙트로그램 방식으로 전환했어요. (서버 저장 지원)');
        }
    };

    function updateFeatUI() {
        // ★ 260913: 특징 방식은 MFCC 고정 (스펙트로그램 폐기) — 토글 UI 없음.
        //   과거 토글 요소가 캐시에 남아 있어도 안전하도록 null 가드만 유지한다.
        var isMfcc = (featureMode === 'mfcc' && currentMode === 'audio');
        var b1 = $('featBtnSpec'), b2 = $('featBtnMfcc');
        if (b1) b1.classList.toggle('active', !isMfcc);
        if (b2) b2.classList.toggle('active', isMfcc);
        var n = $('mfccNotice');
        if (n) n.style.display = isMfcc ? '' : 'none';
        var cap = $('btnAudioCapture');
        if (cap) cap.textContent = isMfcc ? '🔴 3초 녹음' : '🔴 3초 녹음';
        var help = $('panelHelp');
        if (help) help.textContent = isMfcc
            ? '음성 분류(MFCC) — 클래스별 10회 이상 발화 녹음 후 학습하세요. 유사한 단어보다 확실히 다른 단어가 잘 인식돼요.'
            : '클래스를 선택한 뒤 촬영/녹음하면 샘플이 쌓여요. 클래스당 20장 이상 권장!';
    }

    // MFCC 전용 경로 활성 판정 — 음성 모드에서만 참.
    // (trainModel/warmUp/오디오 캡처 분기에서 사용 — 이미지 모드에서 MFCC 잔류 상태로
    //  Conv1D 학습·워밍업이 실행되던 버그 수정: 2026-09-08)
    function useMfccPath() { return featureMode === 'mfcc' && currentMode === 'audio'; }


    function $(id) { return document.getElementById(id); }
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }
    function token() { return localStorage.getItem('token') || localStorage.getItem('access_token') || ''; }

    /* ── 프로젝트 ─────────────────────────────── */

    window.openCreateProject = function () {
        $('newProjectTitle').value = '';
        $('newProjectDesc').value = '';
        var m = $('createProjectModal');
        m.classList.add('active');
        m.style.display = 'flex';
    };

    window.closeCreateProject = function () {
        var m = $('createProjectModal');
        m.classList.remove('active');
        m.style.display = 'none';
    };

    window.createProject = async function () {
        var title = ($('newProjectTitle').value || '').trim() || '새 프로젝트';
        var desc = ($('newProjectDesc').value || '').trim();
        try {
            var res = await apiPost('/ml/projects', { title: title, description: desc, model_type: currentModeDef.modelType });
            closeCreateProject();
            await loadProjects(res.data.id);
        } catch (e) { showAlert(e.message || '프로젝트 생성 실패', 'error'); }
    };

    async function loadProjects(selectId) {
        var res = await apiGet('/ml/projects');
        var sel = $('projectSelect');
        sel.innerHTML = '';
        (res.data || []).forEach(function (p) {
            var opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.title + (p.status === 'ready' ? ' ✓' : '');
            sel.appendChild(opt);
        });
        if (selectId) sel.value = selectId;
        if (sel.value) {
            await selectProject(sel.value);
        } else {
            $('studioBox').style.display = 'none';
            $('noProjectBox').style.display = 'block';
        }
    }

    $('projectSelect') && $('projectSelect').addEventListener('change', function () {
        if (this.value) selectProject(this.value);
    });

    async function selectProject(id) {
        stopCamera();
        stopClassify();
        projectId = parseInt(id, 10);
        var res = await apiGet('/ml/projects/' + projectId);
        var data = res.data || {};
        // 클래스 복원
        classes = [];
        Object.keys(data.classes || {}).forEach(function (clsName, i) {
            var samples = (data.classes[clsName] || []).map(function (s) {
                return { dataUrl: '/uploads/ml' + s.file_path.replace('/uploads/ml', ''), width: s.width, height: s.height, serverId: s.id };
            });
            classes.push({ name: clsName, color: CLASS_COLORS[i % CLASS_COLORS.length], samples: samples });
        });
        if (classes.length) selectedIdx = 0;
        $('noProjectBox').style.display = 'none';
        $('studioBox').style.display = 'block';
        // ★ 8차: IndexedDB 에 저장해 둔 MFCC 샘플(클래스 + 발화 PCM)을 복원한다.
        //   MFCC 모드의 PCM·모델은 서버에 없으므로 이게 없으면 페이지를 나갔다 오면
        //   수집 데이터가 전부 사라진다(사용자 보고: "데이터가 사라지는 문제").
        await loadMfccSamples();
        renderClasses();
        updateTrainState();
        // 로컬 모델 캐시 로드 (IndexedDB) — [MFCC 파일럿] MFCC 모드는 Conv1D 헤드라
        // MobileNet Dense 헤드 캐시(IndexedDB) 로드를 스킵 (입력 규격 불일치 방지)
        trained = false;
        headModel = null;
        if (!useMfccPath()) {
            try {
                var cached = await tf.loadLayersModel('indexeddb://nubida-ml-' + projectId);
                if (cached) {
                    headModel = cached;
                    // 특징 추출기(truncModel)도 복원 — MobileNet 재로드 (없으면 분류 시 TypeError)
                    if (!truncModel) {
                        mobilenet = await tf.loadLayersModel(MOBILENET_URL);
                        var layer = findFeatureLayer(mobilenet);
                        truncModel = tf.model({ inputs: mobilenet.inputs, outputs: layer.output });
                        truncModel.trainable = false;
                    }
                    trained = true;
                    classLabels = JSON.parse(localStorage.getItem('nubida-ml-labels-' + projectId) || '[]');
                }
            } catch (e) { /* 캐시 없음 */ }
        }
        // [사전학습 서버 모델 자동 복원] ready 프로젝트의 model_path에서 모델+라벨 로드.
        // IndexedDB 캐시(이 브라우저 전용)에 의존하던 갭 해소 — 새 브라우저/기기에서도
        // 사전학습 세트를 즉시 분류 가능.
        // ★ 10차: MFCC 모델도 서버에서 복원한다(기존 `!useMfccPath()` 조건 제거).
        //   MFCC 모델을 서버에 저장하게 되었으므로, 새 브라우저·다른 기기에서도
        //   재학습 없이 바로 분류할 수 있어야 한다. 학습한 모델은 클래스 삭제와
        //   무관하게 서버에 보존된다.
        if (!trained && data.model_path) {
            try {
                var labRes = await fetch(data.model_path + '/labels.json', { cache: 'no-store' });
                if (labRes.ok) {
                    var labArr = await labRes.json();
                    if (Array.isArray(labArr) && labArr.length === classes.length) {
                        var srvModel = await tf.loadLayersModel(data.model_path + '/model.json');
                        if (!truncModel) {
                            mobilenet = await tf.loadLayersModel(MOBILENET_URL);
                            var srvLayer = findFeatureLayer(mobilenet);
                            truncModel = tf.model({ inputs: mobilenet.inputs, outputs: srvLayer.output });
                            truncModel.trainable = false;
                        }
                        headModel = srvModel;
                        classLabels = labArr;
                        trained = true;
                        try { localStorage.setItem('nubida-ml-labels-' + projectId, JSON.stringify(classLabels)); } catch (e4) {}
                    }
                }
            } catch (e5) { /* 서버 모델 로드 실패 → IndexedDB/학습 대기 상태 유지 */ }
        }
        updateTrainState();
        // 첫 분류 지연 제거 — GPU 셰이더 사전 컴파일 (방식별 워밍업)
        if (trained) {
            if (useMfccPath()) warmUpMfccModel(); else warmUpModel();
        }
        // 아두이노 링크 갱신
        var ardLink = document.querySelector('#trainDone a[href^="ml-arduino.html"]');
        if (ardLink) ardLink.setAttribute('href', 'ml-arduino.html?project=' + projectId);
    }

    /* ── 클래스 ───────────────────────────────── */

    window.addClass = function () {
        if (classes.length >= 10) { showAlert('클래스는 최대 10개까지 만들 수 있어요.', 'error'); return; }
        $('classModalInput').value = '';
        var m = $('classModal');
        m.classList.add('active');
        m.style.display = 'flex';
        setTimeout(function () { var i = $('classModalInput'); if (i) i.focus(); }, 60);
    };

    window.closeClassModal = function () {
        var m = $('classModal');
        if (!m) return;
        m.classList.remove('active');
        m.style.display = 'none';
    };

    window.confirmAddClass = function () {
        var name = ($('classModalInput').value || '').trim().slice(0, 50);
        if (!name) { showAlert('클래스 이름을 입력하세요.', 'error'); return; }
        if (classes.some(function (c) { return c.name === name; })) { showAlert('같은 이름의 클래스가 있어요.', 'error'); return; }
        classes.push({ name: name, color: CLASS_COLORS[classes.length % CLASS_COLORS.length], samples: [] });
        selectedIdx = classes.length - 1;
        closeClassModal();
        renderClasses();
        updateTrainState();
    };

    var pendingRemoveIdx = -1;

    window.removeClass = function (idx) {
        if (idx < 0 || idx >= classes.length) return;
        pendingRemoveIdx = idx;
        $('confirmModalMsg').textContent = '클래스 "' + classes[idx].name + '"와 샘플 ' + classes[idx].samples.length + '장을 삭제할까요?';
        var m = $('confirmModal');
        m.classList.add('active');
        m.style.display = 'flex';
    };

    window.closeConfirmModal = function () {
        pendingRemoveIdx = -1;
        var m = $('confirmModal');
        if (!m) return;
        m.classList.remove('active');
        m.style.display = 'none';
    };

    window.confirmRemoveClass = function () {
        var idx = pendingRemoveIdx;
        pendingRemoveIdx = -1;
        closeConfirmModal();
        if (idx < 0 || idx >= classes.length) return;
        var removedName = classes[idx].name;
        var delIds = [];
        if (classes[idx].samples.length) {
            classes[idx].samples.forEach(function (s) {
                if (s.serverId) delIds.push(s.serverId);
            });
        }
        classes.splice(idx, 1);
        if (selectedIdx >= classes.length) selectedIdx = Math.max(0, classes.length - 1);
        renderClasses();
        updateTrainState();
        // ★ 9차: "샘플 삭제 500 (MariaDB 1020 Record has changed)" 수정.
        //   기존 코드는 클래스의 샘플 수만큼 DELETE 를 동시에 발사했다.
        //   서버는 각 DELETE 마다 ml_projects.sample_count 를 UPDATE 하는데,
        //   요청들이 겹치면서 MariaDB 가 1020(읽은 뒤 레코드 변경) 을 던져 500 이 났다.
        //   → 하나씩 await 로 순차 처리하고, 실패해도 화면에는 오류를 띄우지 않는다.
        //     (서버 샘플은 시각화용일 뿐, 학습 데이터 원본은 IndexedDB 에 있다)
        if (delIds.length) {
            (async function () {
                var ok = 0, fail = 0;
                for (var i = 0; i < delIds.length; i++) {
                    try {
                        await apiDelete('/ml/projects/' + projectId + '/samples/' + delIds[i]);
                        ok++;
                    } catch (e) {
                        fail++;
                    }
                    // 서버가 샘플마다 sample_count 를 갱신하므로 요청 간 간격을 둔다
                    if (i < delIds.length - 1) await new Promise(function (r) { setTimeout(r, 60); });
                }
                if (fail) logStudio('🗑 서버 샘플 삭제: 성공 ' + ok + ' / 실패 ' + fail + ' (화면에서는 제거됨)', 'warn');
            })();
        }
        // ★ 8차: "클래스 추가해도 완전 삭제가 되지 않는 문제" 수정.
        //   MFCC 샘플은 서버에 없고 IndexedDB 에만 있어서, 여기서 지워주지 않으면
        //   새로고침 시 loadMfccSamples() 가 그대로 되살렸다.
        //   → 삭제된 클래스가 IndexedDB 에 없도록 현재 구조를 통째로 다시 저장한다.
        //     (saveMfccSamples 는 classes 전체를 덮어쓰므로 남은 클래스만 유지된다)
        if (useMfccPath()) {
            saveMfccSamples().then(function () {
                logStudio('🗑 클래스 "' + removedName + '" 삭제 완료 (저장소에서도 제거)', 'ok');
            });
        }
    };

    window.selectClass = function (idx) { selectedIdx = idx; renderClasses(); };

    function renderClasses() {
        var list = $('classList');
        list.innerHTML = '';
        if (!classes.length) {
            list.appendChild(el('div', 'ml-class-empty', '클래스를 추가하고 샘플을 모아 보세요!'));
            var cta = el('button', 'btn btn-accent btn-sm', '🎓 사전학습 기본 세트 바로 불러오기');
            cta.type = 'button';
            cta.style.cssText = 'display:block;margin:12px auto 0;';
            cta.addEventListener('click', function () { openPresetModal(); });
            list.appendChild(cta);
        }
        classes.forEach(function (c, i) {
            var card = el('div', 'ml-class-card' + (i === selectedIdx ? ' selected' : ''));
            card.addEventListener('click', function () { selectClass(i); });

            var head = el('div', 'ml-class-card-head');
            var dot = el('span', 'ml-class-dot');
            dot.style.background = c.color;
            head.appendChild(dot);
            head.appendChild(el('span', 'ml-class-num', String(i + 1)));
            head.appendChild(el('span', 'ml-class-name', c.name));
            head.appendChild(el('span', 'ml-class-count', c.samples.length + '장'));
            var del = el('button', 'ml-class-del', '✕');
            del.addEventListener('click', function (ev) { ev.stopPropagation(); removeClass(i); });
            head.appendChild(del);
            card.appendChild(head);

            var thumbs = el('div', 'ml-thumbs');
            if (!c.samples.length) {
                thumbs.appendChild(el('div', 'ml-class-empty', '샘플 0장'));
            } else {
                c.samples.slice(0, 12).forEach(function (s) { thumbs.appendChild(thumbEl(s.dataUrl)); });
                if (c.samples.length > 12) thumbs.appendChild(el('div', 'ml-thumb-more', '+' + (c.samples.length - 12)));
            }
            card.appendChild(thumbs);
            list.appendChild(card);
        });
        var total = classes.reduce(function (a, c) { return a + c.samples.length; }, 0);
        $('classTotal').textContent = '샘플 ' + total + '장';
    }

    function thumbEl(dataUrl) {
        var img = new Image();
        img.className = 'ml-thumb';
        img.src = dataUrl;
        img.loading = 'lazy';
        return img;
    }

    /* ── 카메라 ───────────────────────────────── */

    window.toggleCamera = async function () {
        if (stream) { stopCamera(); return; }
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: facingMode, width: { ideal: perf.camW }, height: { ideal: perf.camH } },
                audio: false,
            });
            var video = $('cameraVideo');
            video.srcObject = stream;
            await video.play();
            $('cameraOverlay').classList.add('hidden');
            $('cameraBadge').style.display = 'block';
            $('btnCameraToggle').textContent = '📷 카메라 끄기';
            $('btnCameraFlip').style.display = '';
            $('btnCapture').disabled = false;
            $('holdCapture').style.display = 'flex';
        } catch (e) {
            showAlert('카메라를 사용할 수 없어요. 브라우저 권한을 확인하거나 파일 업로드를 이용하세요. (' + e.message + ')', 'error');
        }
    };

    window.flipCamera = async function () {
        facingMode = facingMode === 'user' ? 'environment' : 'user';
        var wasOn = !!stream;
        stopCamera();
        if (wasOn) setTimeout(toggleCamera, 150);
    };

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(function (t) { t.stop(); });
            stream = null;
        }
        $('cameraVideo').srcObject = null;
        $('cameraOverlay').classList.remove('hidden');
        $('cameraBadge').style.display = 'none';
        $('btnCameraToggle').textContent = '📷 카메라 켜기';
        $('btnCameraFlip').style.display = 'none';
        $('btnCapture').disabled = true;
        $('holdCapture').style.display = 'none';
    }

    /* ── 입력 소스 / 특징 추출기 (이미지·음성 공용 인터페이스) ── */

    // imageSource — 기존 카메라/파일 로직을 공용 인터페이스로 래핑
    var imageSource = {
        type: 'image',
        start: function () { return window.toggleCamera(); },
        stop: function () { stopCamera(); },
        flip: function () { return window.flipCamera(); },
        capture: function () { return window.captureSample(); },
        get active() { return !!stream; },
    };

    /* ── audioSource — 음성(마이크) 입력 소스 (Phase 2 실구현) ─────────────
     * Web Audio API로 3초 스펙트로그램(129×48)을 수집해 224×224 캔버스로 변환.
     * 스펙트로그램 PNG는 "이미지"로 취급되므로 이후 파이프라인(MobileNet 전이학습,
     * 샘플 업로드/저장, 분류 루프)은 이미지 모드와 완전히 동일 경로를 탄다.
     */
    var audioSource = {
        type: 'audio',
        _active: false,
        audioCtx: null,          // AudioContext (사용자 제스처 후 생성)
        analyser: null,          // AnalyserNode (fftSize=512 → 256 bins)
        micStream: null,         // getUserMedia 스트림
        freqArr: null,           // Uint8Array(256) — 주파수 도메인
        waveArr: null,           // Uint8Array(512) — 시간 도메인(파형)
        specFrames: [],          // 스펙트로그램 프레임 버퍼 (최대 SPEC_FRAMES=129, ≈3초)
        specBuf: null,           // 256×43 그레이스케일 버퍼 캔버스
        _224Canvas: null,        // 분류용 재사용 224×224 캔버스
        rafId: null,
        recorder: null,          // MediaRecorder (재생용 3초 오디오)
        recChunks: [],
        recUrl: null,
        pendingCapture: false,   // [3초 녹음] 진행 중 여부
        captureTimer: null,
        capBuf: [],              // [3초 녹음] 발화 구간 프레임 누적 (중앙 정렬 저장용)
        capSpeech: false,        // [3초 녹음] 발화 감지 여부
        capSilenceMs: 0,         // [3초 녹음] 연속 무음 누적(rAF 틱 근사)
        // [MFCC 파일럿] PCM 캡처 — ScriptProcessor로 원시 PCM 링 버퍼 수집 (마이크 켜짐 동안 상시)
        pcmScript: null,         // ScriptProcessorNode (없으면 MFCC 기능 비활성)
        pcmRing: null,           // Float32Array 순환 버퍼 (최근 ~5.0초)
        pcmW: 0,                 // 절대 쓰기 인덱스
        pcmTotal: 0,             // 누적 샘플 수 (readPcmSince 기준)
        pcmSr: 0,                // audioCtx.sampleRate
        pcmCaptureMark: -1,      // [3초 녹음] 시작 시점의 pcmTotal 스냅샷
        get active() { return this._active; },

        // 마이크 시작 — AudioContext + AnalyserNode 구성, rAF 수집 루프 기동
        start: async function () {
            if (this._active) return;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('이 브라우저는 마이크 입력을 지원하지 않아요.');
            }
            try {
                this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (e) {
                throw new Error('마이크 접근이 거부됐어요. 브라우저 권한을 허용해 주세요.');
            }
            // 방어: 오디오 트랙이 없는 스트림(가상 장치 등)이면 명확한 에러 처리
            if (!this.micStream.getAudioTracks || !this.micStream.getAudioTracks().length) {
                this.micStream.getTracks().forEach(function (t) { t.stop(); });
                this.micStream = null;
                throw new Error('마이크에서 소리 신호를 받지 못했어요. 마이크 장치를 확인해 주세요.');
            }
            var AC = window.AudioContext || window.webkitAudioContext;
            this.audioCtx = new AC();
            this.analyser = this.audioCtx.createAnalyser();
            this.analyser.fftSize = perf.fftSize;
            this.analyser.smoothingTimeConstant = 0.35;
            var srcNode = this.audioCtx.createMediaStreamSource(this.micStream);
            srcNode.connect(this.analyser);
            // [MFCC 파일럿] 원시 PCM 링 버퍼 수집 (5.0초) — ScriptProcessor 4096
            // (확정 분류: 발화 시작~종료 최대 5초 PCM을 startPcmMark부터 읽어야 함)
            this.pcmSr = this.audioCtx.sampleRate || 48000;
            this.pcmRing = new Float32Array(Math.round(this.pcmSr * 5.0));
            this.pcmW = 0; this.pcmTotal = 0; this.pcmCaptureMark = -1;
            if (typeof this.audioCtx.createScriptProcessor === 'function') {
                var self2 = this;
                this.pcmScript = this.audioCtx.createScriptProcessor(4096, 1, 1);
                this.pcmScript.onaudioprocess = function (e) {
                    var ch = e.inputBuffer.getChannelData(0);
                    var cap = self2.pcmRing.length;
                    var w = self2.pcmW % cap;
                    var first = Math.min(ch.length, cap - w);
                    self2.pcmRing.set(ch.subarray(0, first), w);
                    if (first < ch.length) self2.pcmRing.set(ch.subarray(first), 0);
                    self2.pcmW += ch.length;
                    self2.pcmTotal += ch.length;
                };
                srcNode.connect(this.pcmScript);
                // [FIX 2026-09-04] Chrome은 ScriptProcessor의 output이 연결돼야
                // onaudioprocess가 호출됨 (input만 연결 시 영구 미호출 → PCM 0수집).
                // 스피커로 소리가 새지 않도록 gain 0 노드를 경유해 destination에 연결.
                if (!this._pcmMute) {
                    this._pcmMute = this.audioCtx.createGain();
                    this._pcmMute.gain.value = 0;
                }
                this.pcmScript.connect(this._pcmMute);
                this._pcmMute.connect(this.audioCtx.destination);
            }
            this.freqArr = new Uint8Array(this.analyser.frequencyBinCount);  // fftSize/2
            this.waveArr = new Uint8Array(this.analyser.fftSize);
            this.specFrames = [];
            if (!this.specBuf) {
                this.specBuf = document.createElement('canvas');
            }
            // 가로=시간(SPEC_FRAMES), 세로=주파수(SPEC_MAX_BIN) — 성능 모드별 크기 적용
            // (고성능 43×48 / 저사양 32×24. 이전: 256×43으로 생성 + 256×256 가정 인덱스
            //  → 18kHz 이하 전부 범위 밖으로 잘림. 모드 변경 시 크기도 함께 갱신)
            this.specBuf.width = SPEC_FRAMES;
            this.specBuf.height = SPEC_MAX_BIN;
            this._active = true;
            this._loop();
            // UI 상태
            var btn = $('btnMicToggle');
            if (btn) { btn.textContent = '⏹ 마이크 끄기'; btn.classList.remove('btn-secondary'); btn.classList.add('btn-danger'); }
            var hint = $('audioHint');
            if (hint) hint.textContent = '소리를 내면 파형/스펙트로그램이 표시돼요! [🔴 3초 녹음]으로 샘플을 추가하세요.';
            var cap = $('btnAudioCapture');
            if (cap) cap.disabled = false;
        },

        // 마이크 정지 — 트랙/컨텍스트/애니메이션 정리
        stop: function () {
            this._active = false;
            if (this.pendingCapture) {
                this.pendingCapture = false;
                if (this.captureTimer) { clearTimeout(this.captureTimer); this.captureTimer = null; }
                var c1 = $('btnAudioCapture');
                if (c1) { c1.disabled = true; c1.textContent = '🔴 3초 녹음'; }
            }
            if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = null; }
            if (this.recorder && this.recorder.state === 'recording') { try { this.recorder.stop(); } catch (e) {} }
            if (this.pcmScript) {   // [MFCC 파일럿] PCM 캡처 해제
                try { this.pcmScript.onaudioprocess = null; this.pcmScript.disconnect(); } catch (e) {}
                this.pcmScript = null;
            }
            if (this.micStream) { this.micStream.getTracks().forEach(function (t) { t.stop(); }); this.micStream = null; }
            if (this.audioCtx && this.audioCtx.state !== 'closed') { this.audioCtx.close().catch(function () {}); }
            this.audioCtx = null; this.analyser = null;
            var btn = $('btnMicToggle');
            if (btn) { btn.textContent = '🎙️ 마이크 시작'; btn.classList.add('btn-secondary'); btn.classList.remove('btn-danger'); }
            var hint = $('audioHint');
            if (hint) hint.textContent = '마이크가 꺼져 있어요. [🎙️ 마이크 시작]을 누르면 소리를 녹음할 수 있어요.';
        },

        flip: function () { /* 음성엔 카메라 전환 없음 (no-op) */ },

        // [🔴 3초 녹음] — 버퍼를 비우고 새로 3초 수집 후 클래스 샘플로 저장
        capture: function () {
            if (!this._active) { showAlert('마이크를 먼저 켜주세요.', 'error'); return; }
            if (!classes.length) { showAlert('먼저 클래스를 추가하세요.', 'error'); return; }
            if (this.pendingCapture) { showAlert('이미 녹음 중이에요. 잠시만 기다려 주세요.'); return; }
            this.pendingCapture = true;
            this.pcmCaptureMark = this.pcmTotal;   // [MFCC 파일럿] 이 시점 이후 PCM 수집
            this.specFrames = [];          // 3초 새로 수집
            this.capBuf = []; this.capSpeech = false; this.capSilenceMs = 0;   // 발화 구간 초기화
            this._recordForPlayback();     // 재생용 오디오 동시 녹음 (3.2초)
            var btn = $('btnAudioCapture');
            if (btn) { btn.disabled = true; btn.textContent = '🔴 녹음 중...'; }
            var self = this;
            // 안전망: 아주 느린 환경에서도 3.5초 후 강제 저장
            this.captureTimer = setTimeout(function () {
                if (!self.pendingCapture) return;
                self.pendingCapture = false;
                self.captureTimer = null;
                self._finishCapture();
            }, 3500);
        },

        // [MFCC 파일럿] 순환 버퍼에서 절대 인덱스 mark 이후 PCM을 선형 배열로 복사
        readPcmSince: function (markAbs) {
            if (!this.pcmRing || this.pcmRing.length === 0) return new Float32Array(0);
            var cap = this.pcmRing.length;
            var avail = Math.min(Math.max(0, this.pcmTotal - markAbs), cap);
            if (avail <= 0) return new Float32Array(0);
            var out = new Float32Array(avail);
            var srcStart = markAbs % cap;
            var first = Math.min(avail, cap - srcStart);
            out.set(this.pcmRing.subarray(srcStart, srcStart + first), 0);
            if (first < avail) out.set(this.pcmRing.subarray(0, avail - first), first);
            return out;
        },

        _finishCapture: async function () {
            if (this.captureTimer) { clearTimeout(this.captureTimer); this.captureTimer = null; }
            this._draw();
            // ★ 발화 중앙 정렬: 녹음 중 말한 구간의 중앙 3초(SPEC_FRAMES)를 샘플로 저장.
            //   분류 확정도 동일한 centerWindow()를 사용 → 학습/분류 스펙트로그램 위치 정합
            //   (발화 감지 실패 시 기존 3초 전체 폴백)
            var frames = (this.capSpeech && this.capBuf.length) ? centerWindow(this.capBuf) : this.specFrames;
            var c = specCanvasFromFrames(frames);
            if (useMfccPath()) {
                // [MFCC 파일럿] PCM → 16k → 발화 중심 1.522s → 샘플 저장 (표시는 스펙트로그램 재사용)
                try {
                    var seg = this.readPcmSince(this.pcmCaptureMark);
                    if (seg.length < MFCC_SR) {
                        showAlert('MFCC 샘플 저장 실패: PCM 부족(' + seg.length + '샘플). 마이크/권한을 확인하세요.', 'error');
                        addSample(c, true, 'audio', null);   // 표시용이라도 저장
                    } else {
                        var pcm16 = await mfccResampleFloat32(seg, this.pcmSr);
                        var win = mfccCenterUtterance(pcm16);
                        if (win.length < MFCC_FFT) throw new Error('발화 창 부족');
                        addSample(c, true, 'audio', win);
                        showAlert('🧪 MFCC 샘플 저장! (발화 ' + (win.length / MFCC_SR).toFixed(2) + 's → ' + MFCC_MAX_FRAMES + '프레임)');
                    }
                } catch (e) {
                    console.warn('[ml-studio] MFCC 캡처 오류:', e);
                    addSample(c, true, 'audio', null);
                    showAlert('MFCC PCM 변환 실패 — 스펙트로그램 샘플로만 저장했어요: ' + e.message, 'error');
                }
            } else {
                addSample(c, true, 'audio');
            }
            this._flash();
            var btn = $('btnAudioCapture');
            if (btn) { btn.disabled = false; btn.textContent = (featureMode === 'mfcc') ? '🔴 3초 녹음 (MFCC)' : '🔴 3초 녹음'; }
        },

        // 재생용: 3초 오디오를 MediaRecorder로 녹음 → blob URL (▶️ 재생 버튼)
        _recordForPlayback: function () {
            var self = this;
            if (!this.micStream || typeof MediaRecorder === 'undefined') return;
            try {
                if (this.recorder && this.recorder.state === 'recording') { try { this.recorder.stop(); } catch (e) {} }
                this.recChunks = [];
                this.recorder = new MediaRecorder(this.micStream);
                this.recorder.ondataavailable = function (ev) { if (ev.data && ev.data.size) self.recChunks.push(ev.data); };
                this.recorder.onstop = function () {
                    if (self.recChunks.length) {
                        var blob = new Blob(self.recChunks, { type: self.recorder.mimeType || 'audio/webm' });
                        if (self.recUrl) URL.revokeObjectURL(self.recUrl);
                        self.recUrl = URL.createObjectURL(blob);
                        var p = $('btnAudioPlay');
                        if (p) p.disabled = false;
                    }
                };
                this.recorder.start();
                setTimeout(function () { if (self.recorder && self.recorder.state === 'recording') self.recorder.stop(); }, 3200);
            } catch (e) { /* MediaRecorder 미지원 — 재생 버튼만 비활성 유지 */ }
        },

        // 현재 스펙트로그램 버퍼를 그레이스케일로 렌더링 (빈 프레임은 검정)
        // 캔버스: 가로=시간(SPEC_FRAMES), 세로=주파수(SPEC_MAX_BIN) — 129×48
        _draw: function () {
            if (!this.specBuf) return;
            var bctx = this.specBuf.getContext('2d');
            var img = bctx.createImageData(SPEC_FRAMES, SPEC_MAX_BIN);
            var d = img.data;
            for (var f = 0; f < SPEC_FRAMES; f++) {
                var frame = this.specFrames[f];
                if (!frame) continue;
                for (var b = 0; b < SPEC_MAX_BIN; b++) {
                    var v = frame[b];                                  // 0~255
                    var y = SPEC_MAX_BIN - 1 - b;                      // y=주파수(상단=고주파)
                    var idx = (y * SPEC_FRAMES + f) * 4;               // x=시간, y=주파수
                    d[idx] = v; d[idx + 1] = v; d[idx + 2] = v; d[idx + 3] = 255;
                }
            }
            bctx.putImageData(img, 0, 0);
            // 표시 캔버스(IMG_SIZE×IMG_SIZE) + 파형 캔버스 갱신
            var spec = $('audioSpecCanvas');
            if (spec) {
                if (spec.width !== IMG_SIZE) { spec.width = IMG_SIZE; spec.height = IMG_SIZE; }
                spec.getContext('2d').drawImage(this.specBuf, 0, 0, IMG_SIZE, IMG_SIZE);
            }
            var wave = $('audioWaveCanvas');
            if (wave && this.waveArr) this._drawWave(wave);
        },

        _drawWave: function (c) {
            var ctx = c.getContext('2d');
            var w = c.width, h = c.height;
            ctx.clearRect(0, 0, w, h);
            ctx.strokeStyle = '#4F5EF8';
            ctx.lineWidth = 2;
            ctx.beginPath();
            var n = this.waveArr.length;
            for (var i = 0; i < n; i++) {
                var x = (i / (n - 1)) * w;
                var y = (this.waveArr[i] / 255) * h;
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        },

        // 분류용 224×224 캔버스 (재사용) — 현재 스펙트로그램 버퍼
        specCanvas224: function () {
            if (!this._224Canvas) {
                this._224Canvas = document.createElement('canvas');
                this._224Canvas.width = IMG_SIZE;
                this._224Canvas.height = IMG_SIZE;
            }
            this._224Canvas.getContext('2d').drawImage(this.specBuf, 0, 0, IMG_SIZE, IMG_SIZE);
            return this._224Canvas;
        },

        // rAF 수집 루프 — 주파수/파형 캡처 + 스펙트로그램 버퍼 갱신 + 녹음 완료 감지
        _loop: function () {
            var self = this;
            if (this.analyser) {
                this.analyser.getByteFrequencyData(this.freqArr);
                this.specFrames.push(this.freqArr.slice());
                if (this.specFrames.length > SPEC_FRAMES) this.specFrames.shift();
                this.analyser.getByteTimeDomainData(this.waveArr);
                this._draw();
                // [3초 녹음] 발화 구간 수집 — RMS로 발화 감지해 프레임 누적 (중앙 정렬 저장용)
                if (this.pendingCapture) {
                    var rms = currentRms();
                    if (rms >= voiceHold.SPEECH_RMS) {
                        this.capSpeech = true;
                        this.capSilenceMs = 0;
                        this.capBuf.push(this.freqArr.slice());
                        /* ★★ [2026-09-16] 상한 추가 — 무한 누적 방지
                         *   저장은 3초분(SPEC_FRAMES)이면 충분하다.
                         *   상한이 없으면 녹음이 길어질 때 몇 MB 가 계속 쌓여
                         *   GC 부담 → 시간이 지날수록 렉. */
                        if (this.capBuf.length > SPEC_FRAMES * 3) this.capBuf.shift();
                    } else if (this.capSpeech) {
                        this.capSilenceMs += 16;   // rAF 틱(≈16ms) 근사 — 발화 종료 기록만
                    }
                }
                // [음성 확정] 실시간 발화 프레임 수집 — 학습 캡처(capBuf)와 동일 규칙 적용:
                // rAF 틱에서 RMS 게이트 통과 프레임만 speechBuf에 누적한다. (기존 120ms 틱 +
                // 무음 프레임 포함 수집은 단발 발화의 시간 폭이 학습 샘플의 ~1/6로 압축돼
                // 확정 분류가 실패했다 — 2026-09-04 수정)
                if (voiceHold.state === 'speaking') {
                    if (currentRms() >= voiceHold.SPEECH_RMS) {
                        voiceHold.speechBuf.push(this.freqArr.slice());
                        /* ★★ [2026-09-16] 상한 추가 — 무한 누적 방지 (주범)
                         *   centerWindow() 는 중앙 SPEC_FRAMES(129)개만 쓰는데,
                         *   상한이 없으면 'speaking' 이 유지되는 동안 계속 쌓여
                         *   · 배열 메모리 영구 점유
                         *   · GC mark 단계에서 TypedArray 수만 개 순회
                         *   · 그 결과 시간이 지날수록 렉이 심해진다.
                         *   최근 SPEC_FRAMES*4 개만 유지한다. */
                        if (voiceHold.speechBuf.length > SPEC_FRAMES * 4) voiceHold.speechBuf.shift();
                        // [진단] 발화 프레임이 실제로 쌓이는지 확인 — 안 쌓이면 마이크 볼륨 문제
                        voiceHold._framesPushed = (voiceHold._framesPushed || 0) + 1;
                    }
                }
                // [3초 녹음] 완료 감지 — 129프레임 채워지면 즉시 저장
                if (this.pendingCapture && this.specFrames.length >= SPEC_FRAMES) {
                    this.pendingCapture = false;
                    if (this.captureTimer) { clearTimeout(this.captureTimer); this.captureTimer = null; }
                    this._finishCapture();
                }
            }
            if (this._active) {
                this.rafId = requestAnimationFrame(function () { self._loop(); });
            }
        },

        _flash: function () {
            var c = $('audioSpecCanvas');
            if (!c) return;
            c.style.transition = 'outline .15s';
            c.style.outline = '3px solid #10B981';
            setTimeout(function () { c.style.outline = ''; }, 180);
        },
    };

    // ── 음성 공용: 발화 구간 중앙 3초(SPEC_FRAMES) 윈도우 추출 ──────────────
    // 학습 샘플 저장과 분류 확정이 동일한 정렬을 쓰도록 공용화한다.
    // 길면 중앙 슬라이스, 짧으면 앞뒤 균등 패딩(빈 프레임=검정) → 발화가 항상 이미지 중앙
    function centerWindow(frames) {
        var out = new Array(SPEC_FRAMES);
        var i;
        for (i = 0; i < SPEC_FRAMES; i++) out[i] = null;
        if (!frames || !frames.length) return out;
        if (frames.length >= SPEC_FRAMES) {
            var start = Math.floor((frames.length - SPEC_FRAMES) / 2);
            for (i = 0; i < SPEC_FRAMES; i++) out[i] = frames[start + i];
        } else {
            var padL = Math.floor((SPEC_FRAMES - frames.length) / 2);
            for (i = 0; i < frames.length; i++) out[padL + i] = frames[i];
        }
        return out;
    }

    /* ★★ [2026-09-16] canvas 재사용 — 매 호출 생성 제거
     *   기존 : 호출마다 canvas 2개(document.createElement) 생성
     *          → 분류 주기마다 반복되어 초당 16개 → 30분이면 3만 개 → GC 압박
     *   수정 : 모듈 스코프에 1회만 만들어 재사용한다.
     *          (같은 크기로 덮어쓰므로 결과는 완전히 동일하다)                 */
    var _specC = null, _specTmp = null, _specCtx = null, _specTmpCtx = null, _specImgData = null;

    // 주어진 프레임 배열(SPEC_FRAMES×SPEC_MAX_BIN)로 224×224 스펙트로그램 캔버스 생성.
    // 학습 샘플 저장과 분류 확정이 동일한 픽셀 변환을 사용 (기존 _draw/specCanvas224와 동일 규칙)
    function specCanvasFromFrames(frames) {
        var c, tmp, ctx, img, d;
        if (!_specC) {
            _specC = document.createElement('canvas');
            _specC.width = IMG_SIZE; _specC.height = IMG_SIZE;
            _specCtx = _specC.getContext('2d');
            _specTmp = document.createElement('canvas');
            _specTmp.width = SPEC_FRAMES; _specTmp.height = SPEC_MAX_BIN;
            _specTmpCtx = _specTmp.getContext('2d');
            _specImgData = _specTmpCtx.createImageData(SPEC_FRAMES, SPEC_MAX_BIN);
        }
        c = _specC; tmp = _specTmp; ctx = _specTmpCtx; img = _specImgData;
        d = img.data;
        /* ★ 재사용 시 이전 프레임 잔상 제거 — 원본은 매번 새 canvas 라 자동으로
         *   검정이었지만, 재사용하면 지난 값이 남는다. 빈 프레임은 검정으로 덮는다.
         *   (알파까지 255 로 채워야 원본과 완전히 동일한 픽셀이 된다)          */
        for (var _z = 0; _z < d.length; _z += 4) {
            d[_z] = 0; d[_z + 1] = 0; d[_z + 2] = 0; d[_z + 3] = 255;
        }
        for (var f = 0; f < SPEC_FRAMES; f++) {
            var frame = frames[f];
            if (!frame) continue;   // null = 빈(무음) 프레임 → 검정 유지
            for (var b = 0; b < SPEC_MAX_BIN; b++) {
                var v = frame[b];
                var y = SPEC_MAX_BIN - 1 - b;
                var idx = (y * SPEC_FRAMES + f) * 4;
                d[idx] = v; d[idx + 1] = v; d[idx + 2] = v; d[idx + 3] = 255;
            }
        }
        ctx.putImageData(img, 0, 0);
        c.getContext('2d').drawImage(tmp, 0, 0, IMG_SIZE, IMG_SIZE);
        return c;
    }

    // imageExtractor — MobileNet 특징 추출기 (동결, 학습 안 함)
    var imageExtractor = {
        name: 'mobilenet',
        load: function () { return ensureMobileNet(); },
        embed: function (tensor) { return truncModel.predict(tensor); },
    };

    // audioExtractor — 음성 특징 추출기 (Phase 2 실구현)
    // 음성 샘플이 "스펙트로그램 224×224 이미지"로 저장되므로,
    // 특징 추출은 이미지와 동일하게 MobileNet을 재사용한다 (전이학습 파이프라인 공용).
    var audioExtractor = {
        name: 'mobilenet-spec',
        load: function () { return ensureMobileNet(); },
        embed: function (tensor) { return truncModel.predict(tensor); },
    };

    // 모드 → 소스/추출기 연결 (image/audio 모두 실구현)
    MODES.image.source = imageSource;
    MODES.image.extractor = imageExtractor;
    MODES.audio.source = audioSource;
    MODES.audio.extractor = audioExtractor;

    // 스튜디오 모드 전환 (헤더 토글: 이미지/음성)
    // - 소스/추출기 교체 + 카메라/마이크 정리 + UI 패널 전환
    window.initStudio = function (mode) {
        if (!MODES[mode]) { console.warn('[ml-studio] 알 수 없는 모드:', mode); return; }
        currentMode = mode;
        currentModeDef = MODES[mode];
        stopCamera();
        audioSource.stop();
        stopClassify();
        voiceHold.reset();
        var isAudio = (mode === 'audio');
        var modeLabel = $('modeLabel');
        if (modeLabel) modeLabel.textContent = currentModeDef.label;
        var panelTitle = $('panelTitle');
        if (panelTitle) panelTitle.textContent = isAudio ? '🎤 샘플 수집' : '📷 샘플 수집';
        var cameraPanel = $('cameraPanel');
        if (cameraPanel) cameraPanel.style.display = isAudio ? 'none' : '';
        var audioPanel = $('audioPanel');
        if (audioPanel) audioPanel.style.display = isAudio ? '' : 'none';
        var bImg = $('modeBtnImage'), bAud = $('modeBtnAudio');
        if (bImg) bImg.classList.toggle('active', !isAudio);
        if (bAud) bAud.classList.toggle('active', isAudio);
        var serialBox = $('serialBoxStudio');
        // ★ 8차: "카메라도 바로 분류" — 아두이노 연결 박스를 모든 모드에서 노출한다.
        //   (기존: 음성 모드 전용 → 이미지 모드에서 연결 버튼 자체가 안 보였다)
        // ★ 260913: 카메라/음성 패널 안에도 각각 아두이노 연결 박스가 생겼으므로
        //   하단 공용 박스는 항상 보이게 두고(중복이지만 어느 쪽이든 누를 수 있게),
        //   3곳의 연결 상태를 한 번에 동기화한다.
        if (serialBox) serialBox.style.display = '';
        updateBleStudioStatus(bleStudio ? 'connected' : 'disconnected', bleStudio && bleStudio.name);
        updateBleStudioButtonLabel();
        updateFeatUI();   // [MFCC 파일럿] 특징 방식 토글(spec/mfcc) 활성 상태 동기화
        console.log('[ml-studio] 모드 전환:', currentModeDef.label, '(소스:', currentModeDef.source.type, ')');
    };

    /* ── 샘플 수집 ────────────────────────────── */

    function canvasFromVideo() {
        var video = $('cameraVideo');
        var c = $('captureCanvas');
        // 성능 모드별 크기(224/128)에 맞춰 캔버스 동적 설정
        if (c.width !== IMG_SIZE) { c.width = IMG_SIZE; c.height = IMG_SIZE; }
        var ctx = c.getContext('2d');
        var vw = video.videoWidth || 640, vh = video.videoHeight || 480;
        // 중앙 크롭 → 정사각형
        var side = Math.min(vw, vh);
        var sx = (vw - side) / 2, sy = (vh - side) / 2;
        ctx.drawImage(video, sx, sy, side, side, 0, 0, IMG_SIZE, IMG_SIZE);
        return c;
    }

    window.captureSample = function () {
        if (!classes.length) { showAlert('먼저 클래스를 추가하세요.', 'error'); return; }
        if (currentMode === 'audio') { audioSource.capture(); return; }   // 음성 모드 — 1초 녹음
        if (!stream) { showAlert('카메라를 먼저 켜주세요.', 'error'); return; }
        addSample(canvasFromVideo());
    };

    window.handleFiles = function (files) {
        if (!classes.length) { showAlert('먼저 클래스를 추가하세요.', 'error'); return; }
        if (!files || !files.length) return;
        var remaining = Math.min(files.length, 50);
        Array.from(files).slice(0, 50).forEach(function (file) {
            var reader = new FileReader();
            reader.onload = function (ev) {
                var img = new Image();
                img.onload = function () {
                    var c = document.createElement('canvas');
                    c.width = IMG_SIZE; c.height = IMG_SIZE;
                    var ctx = c.getContext('2d');
                    var side = Math.min(img.width, img.height);
                    ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, IMG_SIZE, IMG_SIZE);
                    addSample(c, true);
                };
                img.src = ev.target.result;
            };
            reader.readAsDataURL(file);
        });
        showAlert('이미지 ' + remaining + '장을 처리 중이에요.');
    };

    function addSample(canvas, silent, mediaType, mfccPcm) {
        if (!classes.length || selectedIdx === null) return;
        var cls = classes[selectedIdx];
        var dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        cls.samples.push({ dataUrl: dataUrl, width: IMG_SIZE, height: IMG_SIZE, serverId: null, mfccPcm: mfccPcm || null });
        renderClasses();
        updateTrainState();
        if (!silent) flashCapture();
        /* ★★ [2026-09-14] 음성(MFCC) 샘플도 서버에 업로드한다.
         *   ── 이전 동작 ──────────────────────────────────────────
         *   if (!mfccPcm) uploadSampleAsync(...)  // 카메라(이미지)만 서버 업로드
         *   else          saveMfccSamples();      // 음성은 로컬 IndexedDB 전용
         *   → 음성 데이터셋이 서버에 저장되지 않아
         *     ① 페이지를 나가거나 캐시를 지우면 사라지고
         *     ② 다른 기기에서 보이지 않으며
         *     ③ 본사/원장 화면에도 집계되지 않았다.
         *   ── 변경 ────────────────────────────────────────────────
         *   백엔드 POST /ml/projects/{id}/samples 는 이미 media_type='audio' 를
         *   정식 지원한다(스펙트로그램 PNG 로 저장 + DB 기록).
         *   따라서 음성도 동일하게 업로드하고, 로컬 IndexedDB 저장은
         *   MFCC 학습용 PCM(f32) 보존을 위해 그대로 병행한다.
         */
        uploadSampleAsync(cls.name, dataUrl, mediaType || (mfccPcm ? 'audio' : 'image'));
        if (mfccPcm) saveMfccSamples();   // MFCC 학습용 PCM 은 로컬에도 보존
    }

    function flashCapture() {
        var v = $('cameraVideo');
        v.style.transition = 'filter .12s';
        v.style.filter = 'brightness(1.6)';
        setTimeout(function () { v.style.filter = ''; }, 120);
    }

    // CSP connect-src에 data:가 없어 fetch(dataUrl)이 실패하는 환경 대비 — base64 직접 디코딩
    function dataUrlToBlob(dataUrl) {
        var parts = dataUrl.split(',');
        var mime = (parts[0].match(/:(.*?);/) || [])[1] || 'image/png';
        var bin = atob(parts[1]);
        var arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        return new Blob([arr], { type: mime });
    }

    async function uploadSampleAsync(clsName, dataUrl, mediaType) {
        try {
            var blob = dataUrlToBlob(dataUrl);
            var isAudio = (mediaType === 'audio');
            var fd = new FormData();
            fd.append('class_name', clsName);
            fd.append('file', blob, 'sample_' + Date.now() + (isAudio ? '.png' : '.jpg'));
            fd.append('width', String(IMG_SIZE));
            fd.append('height', String(IMG_SIZE));
            fd.append('media_type', mediaType || 'image');
            var res = await fetch(API_BASE + '/ml/projects/' + projectId + '/samples', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token() },
                body: fd,
            });
            if (res.ok) {
                var j = await res.json();
                if (j.data && j.data.id) {
                    var cls = classes.find(function (c) { return c.name === clsName; });
                    if (cls) {
                        var s = cls.samples.find(function (x) { return x.serverId === null; });
                        if (s) s.serverId = j.data.id;
                    }
                }
                uploadFailCount = 0;               // 성공 시 실패 카운터 리셋
                if (uploadFailNotified) { hideUploadWarning(); uploadFailNotified = false; }
            } else {
                // 서버가 거절(401/403/404/413/500 등) — 조용히 넘기면 나중에 404 로 터진다
                handleUploadFailure(res.status, 'HTTP ' + res.status);
            }
        } catch (e) {
            // 오프라인/네트워크 예외 — 로컬 샘플은 유지하되 사용자에게는 반드시 알린다
            handleUploadFailure(0, (e && e.message) || '네트워크 오류');
        }
    }

    /* ── 업로드 실패 가시화 (2026-10-06) ─────────────────────────────
     *  기존: catch (e) { /* 무음 *​/ } → 실패해도 화면엔 정상처럼 보이고,
     *        나중에 샘플 이미지가 404 로 깨졌다 (project_23/27 실증).
     *  변경: 실패를 누적 카운트해 경고 배너로 노출하고, 원인별 안내를 띄운다.
     *        (로컬 학습은 계속 가능 — 데이터 유실은 아니라는 점도 함께 안내)
     */
    var uploadFailCount = 0;
    var uploadFailNotified = false;

    function _uploadHint(status) {
        if (status === 401 || status === 403) return '로그인이 만료됐어요. 새로고침 후 다시 로그인해 주세요.';
        if (status === 404) return '프로젝트를 찾을 수 없어요. 페이지를 새로고침해 주세요.';
        if (status === 413) return '이미지 용량이 너무 커요. 잠시 후 다시 시도해 주세요.';
        if (status >= 500) return '서버가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.';
        return '인터넷 연결을 확인한 뒤 다시 시도해 주세요.';
    }

    function showUploadWarning(count, hint) {
        var el = $('uploadWarn');
        if (!el) return;
        el.style.display = 'flex';
        var msg = $('uploadWarnMsg');
        if (msg) {
            msg.textContent = '⚠️ 샘플 ' + count + '개가 서버에 저장되지 않았어요. ' + hint
                + ' (화면의 샘플로 학습은 계속 할 수 있지만, 페이지를 벗어나면 사라져요.)';
        }
    }
    function hideUploadWarning() {
        var el = $('uploadWarn'); if (el) el.style.display = 'none';
    }
    window.hideUploadWarning = hideUploadWarning;

    function handleUploadFailure(status, detail) {
        uploadFailCount++;
        uploadFailNotified = true;
        showUploadWarning(uploadFailCount, _uploadHint(status));
        // 진단용: 콘솔에도 남긴다 (화면 로그는 logStudio 가 담당)
        try { console.log('[ml-studio] 샘플 저장 실패', status, detail); } catch (e) {}
        try { logStudio('⚠️ 샘플 서버 저장 실패 (' + detail + ') — ' + _uploadHint(status), 'err'); } catch (e) {}
    }

    /* ── 사전학습(기본) 세트 ──────────────────────
     * 대표님 지시(9/4): 수업 시작 전 샘플 수집 부담 없이 바로 학습 가능한 기본 세트.
     *   image: 색상 카드 3종(빨강/파랑/초록) × 10장 — 카메라에 같은 색을 보여주면 분류
     *   audio: 방향 음성 명령 4종(전진/후진/우회전/좌회전) × 9화자 — 말로 방향 지시
     * 구조 = 프로젝트 단위(공용 preset 없음): 불러오면 현재 프로젝트에 실제 클래스+샘플이
     * 일반 수집과 동일하게 저장·업로드된다. (에셋: frontend/common/assets/voice|color_samples)
     */
    // 사전학습 세트 — 모드별 다중 세트 배열 (2026-09-08 확장: image 색상/모양/동물, audio 방향/동작/강아지)
    var PRESET_SETS = {
        image: [
            {
                key: 'color',
                modelType: 'image',
                title: '색상 인식 — 빨강 · 파랑 · 초록',
                icon: '🟥🟦🟩',
                desc: '색상 카드/색종이를 카메라에 보여주면 구분해요.',
                dir: '/common/assets/color_samples/',
                classes: [
                    { name: '빨강', color: '#EF4444', n: 10, stem: 'red', shape: 'solid' },
                    { name: '파랑', color: '#4F5EF8', n: 10, stem: 'blue', shape: 'solid' },
                    { name: '초록', color: '#10B981', n: 10, stem: 'green', shape: 'solid' },
                ],
            },
            {
                key: 'shape',
                modelType: 'image',
                title: '모양 인식 — 동그라미 · 세모',
                icon: '🟠🔺',
                desc: '모양 카드를 카메라에 보여주면 구분해요. (동그라미/세모)',
                dir: '/common/assets/shape_samples/',
                classes: [
                    { name: '동그라미', color: '#F59E0B', n: 10, stem: 'circle', shape: 'circle' },
                    { name: '세모', color: '#3B82F6', n: 10, stem: 'triangle', shape: 'triangle' },
                ],
            },
            {
                key: 'animal',
                modelType: 'image',
                title: '동물 인식 — 동물 10종',
                icon: '🐶🐱🐰🐘',
                desc: '강아지·고양이·토끼·코끼리·사자·호랑이·원숭이·말·소·돼지 실제 사진 샘플(각 10장)이에요. 사진/그림/장난감을 카메라에 보여주면 구분해요.',
                dir: '/common/assets/animal_samples/',
                classes: [
                    { name: '강아지', color: '#D97706', n: 10, stem: 'dog', shape: 'animal' },
                    { name: '고양이', color: '#8B5CF6', n: 10, stem: 'cat', shape: 'animal' },
                    { name: '토끼', color: '#EC4899', n: 10, stem: 'rabbit', shape: 'animal' },
                    { name: '코끼리', color: '#6B7280', n: 10, stem: 'elephant', shape: 'animal' },
                    { name: '사자', color: '#F59E0B', n: 10, stem: 'lion', shape: 'animal' },
                    { name: '호랑이', color: '#F97316', n: 10, stem: 'tiger', shape: 'animal' },
                    { name: '원숭이', color: '#A16207', n: 10, stem: 'monkey', shape: 'animal' },
                    { name: '말', color: '#92400E', n: 10, stem: 'horse', shape: 'animal' },
                    { name: '소', color: '#374151', n: 10, stem: 'cow', shape: 'animal' },
                    { name: '돼지', color: '#F472B6', n: 10, stem: 'pig', shape: 'animal' },
                ],
            },
            {
                key: 'dog_breed',
                modelType: 'image',
                title: '강아지 견종 인식 — 견종 10종',
                icon: '🐶',
                desc: '치와와·말티즈·페키니즈·시츄·토이테리어·비글·골든리트리버·저먼셰퍼드·시베리안허스키·퍼그 실제 사진 샘플(각 10장)이에요. 실제 강아지 사진/그림/장난감을 카메라에 보여주면 견종을 구분해요.',
                dir: '/common/assets/dog_breed_samples/',
                classes: [
                    { name: '치와와', color: '#D97706', n: 10, stem: 'chihuahua', shape: 'photo' },
                    { name: '말티즈', color: '#F3F4F6', n: 10, stem: 'maltese', shape: 'photo' },
                    { name: '페키니즈', color: '#92400E', n: 10, stem: 'pekinese', shape: 'photo' },
                    { name: '시츄', color: '#B45309', n: 10, stem: 'shihtzu', shape: 'photo' },
                    { name: '토이테리어', color: '#78350F', n: 10, stem: 'toyterrier', shape: 'photo' },
                    { name: '비글', color: '#EA580C', n: 10, stem: 'beagle', shape: 'photo' },
                    { name: '골든리트리버', color: '#F59E0B', n: 10, stem: 'golden', shape: 'photo' },
                    { name: '저먼셰퍼드', color: '#374151', n: 10, stem: 'shepherd', shape: 'photo' },
                    { name: '시베리안허스키', color: '#6B7280', n: 10, stem: 'husky', shape: 'photo' },
                    { name: '퍼그', color: '#A16207', n: 10, stem: 'pug', shape: 'photo' },
                ],
            },
        ],
    audio: [
            {
                key: 'direction',
                modelType: 'audio',
                title: '방향 음성 명령 — 전진 · 후진 · 우회전 · 좌회전',
                icon: '🗣️🧭',
                desc: '9명의 목소리로 녹음된 음성 명령이에요. 말로 방향을 지시하는 모델을 만들 수 있어요.',
                dir: '/common/assets/voice_samples/',
                classes: [
                    { name: '전진', n: 9, word: '전진' },
                    { name: '후진', n: 9, word: '후진' },
                    { name: '우회전', n: 9, word: '우회전' },
                    { name: '좌회전', n: 9, word: '좌회전' },
                ],
            },
            {
                key: 'action',
                modelType: 'audio',
                title: '동작 음성 명령 — 멈춰 · 움직여 · 켜줘',
                icon: '🗣️🫷',
                desc: '로봇/기기를 말로 제어하는 명령이에요. (멈춰/움직여/켜줘)',
                dir: '/common/assets/voice_samples/',
                classes: [
                    { name: '멈춰', n: 9, word: '멈춰' },
                    { name: '움직여', n: 9, word: '움직여' },
                    { name: '켜줘', n: 9, word: '켜줘' },
                ],
            },
            {
                key: 'pet',
                modelType: 'audio',
                title: '강아지 훈련 명령 — 손 · 앉아 · 기다려 · 이리 와 · 물어 · 짖어 · 하이파이브',
                icon: '🐶',
                desc: '강아지 훈련에 쓰는 7가지 목소리 명령이에요. 말로 지시하면 행동을 구분하는 모델을 만들 수 있어요.',
                dir: '/common/assets/voice_samples/',
                classes: [
                    { name: '손', n: 9, word: '손' },
                    { name: '앉아', n: 9, word: '앉아' },
                    { name: '기다려', n: 9, word: '기다려' },
                    { name: '이리 와', n: 9, word: '이리와' },
                    { name: '물어', n: 9, word: '물어' },
                    { name: '짖어', n: 9, word: '짖어' },
                    { name: '하이파이브', n: 9, word: '하이파이브' },
                ],
            },
        ],
    };

    function presetFiles(set, def) {
        var a = [], i;
        for (i = 1; i <= def.n; i++) {
            if (set.modelType === 'image') {
                a.push(set.dir + def.stem + '_' + (i < 10 ? '0' + i : i) + '.png');
            } else {
                a.push(set.dir + 'V' + i + '_' + def.word + '.wav');
            }
        }
        return a;
    }

    /* ── 사전학습 샘플 생성기 (260913 윤비스 지시) ──────────────
     * 문제: 사전학습 세트 에셋(/common/assets/*_samples/)이 서버에 없어
     *   (전수 검색 결과 전 디스크·GitHub 저장소 모두 0건) 클래스만 생기고
     *   "안에 데이터가 없는" 상태가 됐다.
     * 해결: 에셋 파일에 의존하지 않고 브라우저에서 샘플을 직접 생성한다.
     *   · 이미지(색상/모양): 캔버스에 도형을 그려 이미지 분류기의 실제 학습 특징을 만든다.
     *   · 음성(방향/동작/강아지): 명령마다 고유한 합성 음성(포먼트 + 피치 윤곽)을
     *     만들어 MFCC 학습 경로에 그대로 넣는다.
     * 이 방식이면 서버에 어떤 파일이 있든 항상 데이터가 채워진다.
     * ─────────────────────────────────────────────────────── */

    // 결정적 의사난수 (샘플마다 조금씩 다르게 → 모델이 외우지 않고 일반화)
    function presetRng(seed) {
        var s = seed >>> 0;
        return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    }

    // 이미지 사전학습 샘플 1장 생성 — 224×224 캔버스
    function presetSynthesizeImage(def, idx) {
        var c = document.createElement('canvas');
        c.width = IMG_SIZE; c.height = IMG_SIZE;
        var g = c.getContext('2d');
        var rnd = presetRng((idx + 1) * 7919 + (def.stem || '').length * 131);
        var base = def.color || '#888888';
        var kind = def.shape;          // 'solid' | 'circle' | 'triangle' | 'animal'
        // 배경: 밝은 중립 + 약한 노이즈 (실제 카메라 배경과 유사하게)
        var bgL = 232 + Math.floor(rnd() * 16);
        g.fillStyle = 'rgb(' + bgL + ',' + bgL + ',' + bgL + ')';
        g.fillRect(0, 0, IMG_SIZE, IMG_SIZE);
        var cx = IMG_SIZE / 2 + (rnd() - 0.5) * 26;
        var cy = IMG_SIZE / 2 + (rnd() - 0.5) * 26;
        var r = IMG_SIZE * 0.30 + rnd() * IMG_SIZE * 0.06;
        g.fillStyle = base;
        g.strokeStyle = base;

        if (kind === 'circle') {
            g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
        } else if (kind === 'triangle') {
            g.beginPath();
            g.moveTo(cx, cy - r);
            g.lineTo(cx + r * 0.92, cy + r * 0.72);
            g.lineTo(cx - r * 0.92, cy + r * 0.72);
            g.closePath(); g.fill();
        } else if (kind === 'animal') {
            // 동물: 머리(원) + 귀 2개 + 눈 2개 — 클래스별 색/비율만 다르게
            g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
            var earR = r * 0.36, ey = cy - r * 0.62;
            g.beginPath(); g.arc(cx - r * 0.62, ey, earR, 0, Math.PI * 2); g.fill();
            g.beginPath(); g.arc(cx + r * 0.62, ey, earR, 0, Math.PI * 2); g.fill();
            g.fillStyle = '#FFFFFF';
            var er = r * 0.16;
            g.beginPath(); g.arc(cx - r * 0.34, cy - r * 0.12, er, 0, Math.PI * 2); g.fill();
            g.beginPath(); g.arc(cx + r * 0.34, cy - r * 0.12, er, 0, Math.PI * 2); g.fill();
            g.fillStyle = '#111827';
            var pr = er * 0.5;
            g.beginPath(); g.arc(cx - r * 0.34, cy - r * 0.12, pr, 0, Math.PI * 2); g.fill();
            g.beginPath(); g.arc(cx + r * 0.34, cy - r * 0.12, pr, 0, Math.PI * 2); g.fill();
        } else {
            // 색상(단색 카드) — 채도 높은 사각형 + 살짝 회전
            g.save();
            g.translate(cx, cy);
            g.rotate((rnd() - 0.5) * 0.22);
            var s = r * 1.55;
            g.fillRect(-s / 2, -s / 2, s, s);
            g.restore();
        }
        // 실제 촬영처럼 약한 조명 그라데이션
        var grd = g.createRadialGradient(IMG_SIZE * 0.35, IMG_SIZE * 0.3, IMG_SIZE * 0.1, IMG_SIZE / 2, IMG_SIZE / 2, IMG_SIZE * 0.78);
        grd.addColorStop(0, 'rgba(255,255,255,0.16)');
        grd.addColorStop(1, 'rgba(0,0,0,0.12)');
        g.fillStyle = grd; g.fillRect(0, 0, IMG_SIZE, IMG_SIZE);
        return c;
    }

    // 음성 사전학습 샘플 1개 생성 — 16kHz Float32 PCM (MFCC 학습 입력 규격)
    //   명령마다 고유한 음절수·포먼트·피치 윤곽을 써서 서로 구분 가능한 신호를 만든다.
    function presetSynthesizePcm(def, idx) {
        var sr = (typeof MFCC_SR === 'number') ? MFCC_SR : 16000;
        var rnd = presetRng((idx + 1) * 104729 + (def.word || '').length * 3571);
        var word = def.word || def.name || 'X';
        var syll = Math.max(1, word.replace(/\s/g, '').length);
        var total = Math.floor(sr * (0.55 + 0.30 * syll));   // 음절 많을수록 길게
        var pcm = new Float32Array(total);
        // 말소리: 음절마다 모음 포먼트 3개 + 앞뒤 자음성 노이즈
        var f0base = 108 + (word.charCodeAt(0) % 9) * 13;     // 화자/단어별 기본 피치
        for (var s = 0; s < syll; s++) {
            var segLen = Math.floor(total / syll);
            var st = Math.floor(s * segLen + segLen * 0.06);
            var en = Math.floor((s + 1) * segLen - segLen * 0.12);
            var code = word.replace(/\s/g, '').charCodeAt(s) || 65;
            // 모음 포먼트 (한국어 모음 근사) — 단어 코드로 한 단계 시프트해 단어 간 차이 강화
            var F1 = 320 + (code % 7) * 95 + (code % 3) * 40;
            var F2 = 900 + (code % 11) * 160;
            var F3 = 2450 + (code % 5) * 160;
            for (var i = st; i < en && i < total; i++) {
                var t = (i - st) / sr;
                // 음절 엔벨로프 (울림 → 감쇠)
                var pos = (i - st) / Math.max(1, en - st);
                var env = Math.sin(Math.PI * pos);
                env = Math.pow(env, 1.35);
                // 피치 윤곽 (문장 억양) + 비브라토
                var f0 = f0base * (1 + 0.10 * Math.sin(2 * Math.PI * 0.9 * t))
                              * (1 + 0.06 * Math.sin(2 * Math.PI * 5.5 * t));
                var v = 0;
                // 성대 펄스열 (하모닉) — 3개 포먼트로 필터링된 모음
                for (var h = 1; h <= 24; h++) {
                    var hf = f0 * h;
                    var a1 = 1 / (1 + Math.pow((hf - F1) / 130, 2));
                    var a2 = 0.65 / (1 + Math.pow((hf - F2) / 190, 2));
                    var a3 = 0.38 / (1 + Math.pow((hf - F3) / 240, 2));
                    v += (a1 + a2 + a3) * Math.sin(2 * Math.PI * hf * t);
                }
                v *= 0.055 * env;
                pcm[i] += v;
            }
            // 자음성 노이즈 버스트 (음절 앞머리) — 마찰음/파열음 흉내
            var nb = Math.floor(sr * 0.028);
            for (var k = 0; k < nb && st + k < total; k++) {
                pcm[st + k] += (rnd() * 2 - 1) * 0.045 * (1 - k / nb);
            }
        }
        // 전체 엔벨로프 (발화 시작/끝 완만)
        var fade = Math.floor(sr * 0.02);
        for (var i2 = 0; i2 < fade && i2 < total; i2++) {
            pcm[i2] *= i2 / fade;
            pcm[total - 1 - i2] *= i2 / fade;
        }
        // 약한 배경 잡음 (실제 마이크 환경)
        for (var j = 0; j < total; j++) pcm[j] += (rnd() * 2 - 1) * 0.004;
        // 정규화
        var peak = 0;
        for (var p = 0; p < total; p++) { var ab = Math.abs(pcm[p]); if (ab > peak) peak = ab; }
        if (peak > 0) { var g = 0.72 / peak; for (var q = 0; q < total; q++) pcm[q] *= g; }
        return pcm;
    }

    // PCM → [MFCC] 학습 샘플 커밋 (현재 선택 클래스). addMfccSampleFromWav 와 동일 규격.
    function presetCommitPcm(pcm) {
        var win = mfccCenterUtterance(pcm);
        if (win.length < MFCC_FFT) throw new Error('PCM 부족(' + win.length + ')');
        var disp = mfccSpecFramesForDisplay(win);
        var c = specCanvasFromFrames(centerWindow(disp));
        addSample(c, true, 'audio', win);
    }

    function presetFileTotal(set) {
        var t = 0;
        set.classes.forEach(function (d) { t += d.n; });
        return t;
    }

    function presetSetProgress(text, done, total) {
        var pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
        $('presetStatus').textContent = text;
        $('presetPct').textContent = pct + '%';
        $('presetFill').style.width = pct + '%';
    }

    // ── 사전학습 모달 상태 (다중 세트 선택) ──────────────
    var presetSelSets = null;   // 현재 모드의 세트 배열 (openPresetModal에서 고정)
    var presetSelIdx = 0;       // 선택된 세트 인덱스

    // 모달 상단 세트 선택 칩 렌더 — 세트가 2개 이상일 때만 표시
    function renderPresetChips() {
        var wrap = $('presetChips');
        if (!wrap) return;
        wrap.innerHTML = '';
        if (!presetSelSets || presetSelSets.length < 2) { wrap.style.display = 'none'; return; }
        wrap.style.display = 'flex';
        presetSelSets.forEach(function (s, i) {
            var chip = el('button', 'ml-preset-chip' + (i === presetSelIdx ? ' active' : ''), s.icon + ' ' + s.title.split('—').pop().trim());
            chip.type = 'button';
            chip.title = s.title;
            chip.style.cssText = 'padding:6px 12px;border-radius:99px;border:1px solid #d8dbe3;background:#fff;'
                + 'font-size:12px;cursor:pointer;color:#5a5f6a;font-family:inherit;'
                + (i === presetSelIdx
                    ? 'background:linear-gradient(135deg,#4F5EF8,#8B5CF6);color:#fff;border-color:transparent;font-weight:700;'
                    : '');
            chip.onclick = function () { presetSelIdx = i; renderPresetChips(); renderPresetSet(presetSelSets[i]); };
            wrap.appendChild(chip);
        });
    }

    // 선택된 세트 상세(설명 + 클래스 목록) 렌더
    function renderPresetSet(set) {
        var featNote = '';
        if (set.modelType === 'audio') {
            featNote = useMfccPath()
                ? ' (현재 🧪 MFCC 모드 — 샘플은 이 브라우저에만 저장돼요)'
                : ' (현재 📊 스펙트로그램 — 서버에 저장돼요)';
        }
        $('presetDesc').textContent = set.icon + ' ' + set.desc + featNote;
        var box = $('presetSetList');
        box.innerHTML = '';
        var totalN = presetFileTotal(set);
        var head = el('div', 'ml-preset-head', set.title + ' — 총 ' + set.classes.length + '개 클래스 · ' + totalN + '장');
        head.style.cssText = 'font-size:13px;font-weight:700;margin-bottom:6px;';
        box.appendChild(head);
        set.classes.forEach(function (def) {
            var row = el('div', 'ml-preset-row', '');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 2px;border-bottom:1px solid #f1f3f9;font-size:13px;';
            var dot = el('span', 'ml-class-dot', '');
            dot.style.background = def.color || '#888';
            var nm = el('span', 'ml-preset-name', def.name);
            nm.style.cssText = 'font-weight:600;';
            var cnt = el('span', 'ml-preset-cnt', def.n + '장');
            cnt.style.cssText = 'margin-left:auto;color:#8a8f98;font-size:12px;';
            row.appendChild(dot); row.appendChild(nm); row.appendChild(cnt);
            var exists = classes.some(function (c) { return c.name === def.name; });
            if (exists) {
                var tag = el('span', 'ml-preset-tag', '이미 있음 — 건너뜀');
                tag.style.cssText = 'font-size:11px;color:#EF4444;background:#FEF2F2;padding:2px 8px;border-radius:99px;';
                row.appendChild(tag);
            }
            box.appendChild(row);
        });
        $('presetProgress').style.display = 'none';
        var btn = $('presetBtnLoad');
        btn.disabled = false; btn.textContent = '불러오기';
        $('presetBtnCancel').disabled = false;
    }

    window.openPresetModal = function () {
        if (!projectId) { showAlert('먼저 프로젝트를 선택하거나 만들어 주세요.', 'error'); return; }
        var sets = PRESET_SETS[currentMode];
        if (!sets || !sets.length) { showAlert('이 모드에는 사전학습 세트가 없어요.', 'error'); return; }
        presetSelSets = sets;
        presetSelIdx = 0;
        renderPresetChips();
        renderPresetSet(sets[0]);
        $('presetModal').style.display = 'flex';
    };

    window.closePresetModal = function () {
        $('presetModal').style.display = 'none';
        $('presetProgress').style.display = 'none';
    };

    window.confirmLoadPreset = async function () {
        if (!projectId) { closePresetModal(); return; }
        var set = (presetSelSets && presetSelSets[presetSelIdx]) || null;
        if (!set) { closePresetModal(); return; }
        var btn = $('presetBtnLoad'), cancel = $('presetBtnCancel');
        btn.disabled = true; cancel.disabled = true;
        btn.textContent = '불러오는 중...';
        $('presetProgress').style.display = 'block';
        var totalFiles = presetFileTotal(set);
        var doneFiles = 0, addedCls = 0, skippedCls = 0, addedSamples = 0, errors = [];
        var ac = null;  // AudioContext 1개 재사용 — 파일마다 새로 만들면 자동재생 정책으로 suspended될 수 있음
        try {
            for (var ci = 0; ci < set.classes.length; ci++) {
                var def = set.classes[ci];
                if (classes.some(function (c) { return c.name === def.name; })) { skippedCls++; continue; }
                if (classes.length >= 10) {
                    errors.push('클래스 10개 제한으로 \'' + def.name + '\' 건너뜀');
                    break;
                }
                classes.push({
                    name: def.name,
                    color: def.color || CLASS_COLORS[classes.length % CLASS_COLORS.length],
                    samples: [],
                });
                selectedIdx = classes.length - 1;
                renderClasses(); updateTrainState();
                addedCls++;
                var files = presetFiles(set, def);
                for (var fi = 0; fi < files.length; fi++) {
                    presetSetProgress(def.name + ' — ' + (fi + 1) + '/' + files.length, doneFiles, totalFiles);
                    try {
                        if (set.modelType === 'image') {
                            // 260913: 서버 에셋이 없으므로 브라우저에서 직접 생성한다
                            //   (에셋이 있으면 그 파일을 우선 사용 — 있으면 더 사실적)
                            var c;
                            try {
                                c = await presetCanvasFromImageUrl(files[fi]);
                            } catch (eAsset) {
                                c = presetSynthesizeImage(def, fi);
                            }
                            await presetCommitCanvas(c, 'image');
                        } else if (useMfccPath()) {
                            // 260913: 음성도 동일 — 에셋 없으면 합성 PCM 으로 MFCC 샘플 생성
                            try {
                                await __mlTest.addMfccSampleFromWav(files[fi]);
                            } catch (eAsset2) {
                                presetCommitPcm(presetSynthesizePcm(def, fi));
                            }
                        } else {
                            if (!ac) ac = new (window.AudioContext || window.webkitAudioContext)();
                            try {
                                await presetSpecFromWavUrl(files[fi], ac);
                            } catch (eAsset3) {
                                var pcmFallback = presetSynthesizePcm(def, fi);
                                var dispFb = mfccSpecFramesForDisplay(mfccCenterUtterance(pcmFallback));
                                await presetCommitCanvas(specCanvasFromFrames(centerWindow(dispFb)), 'audio');
                            }
                        }
                        addedSamples++;
                    } catch (e) {
                        errors.push(files[fi].split('/').pop() + ' → ' + e.message);
                    }
                    doneFiles++;
                    presetSetProgress(def.name + ' — ' + (fi + 1) + '/' + files.length, doneFiles, totalFiles);
                }
            }
        } finally {
            if (ac) ac.close().catch(function () {});
        }
        presetSetProgress('마무리 중...', doneFiles, totalFiles);
        renderClasses(); updateTrainState();
        var msg = '🎓 사전학습 세트 불러오기 완료 — 클래스 ' + addedCls + '개 · 샘플 ' + addedSamples + '장 추가';
        if (skippedCls) msg += '\n(이미 있던 클래스 ' + skippedCls + '개는 건너뛰었어요)';
        if (errors.length) msg += '\n⚠️ 실패 ' + errors.length + '건: ' + errors.slice(0, 3).join(' | ');
        closePresetModal();
        btn.disabled = false; btn.textContent = '불러오기';
        cancel.disabled = false;
        showAlert(msg, errors.length ? 'error' : 'success');
    };

    // 이미지 URL → 224×224 중앙 크롭 캔버스 (사전학습 색상 PNG)
    function presetCanvasFromImageUrl(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.blob();
        }).then(function (blob) {
            return createImageBitmap(blob);
        }).then(function (bmp) {
            var c = document.createElement('canvas');
            c.width = IMG_SIZE; c.height = IMG_SIZE;
            var ctx = c.getContext('2d');
            var side = Math.min(bmp.width, bmp.height);
            ctx.drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, IMG_SIZE, IMG_SIZE);
            if (bmp.close) bmp.close();
            return c;
        });
    }

    // WAV URL → 마이크 수집과 동일 변환 규칙(fftSize/smoothing → 60Hz 캡처 → centerWindow → 224 spec)
    // → 학습 샘플 커밋. AudioContext는 호출부에서 1개만 만들어 재사용한다.
    async function presetSpecFromWavUrl(url, ctx) {
        var res = await fetch(url);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        var ab = await res.arrayBuffer();
        var audioBuf;
        try { audioBuf = await ctx.decodeAudioData(ab); }
        catch (e) { throw new Error('WAV 디코드 실패 (44100Hz PCM 필요)'); }
        if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) {} }
        var src = ctx.createBufferSource();
        src.buffer = audioBuf;
        var an = ctx.createAnalyser();
        an.fftSize = perf.fftSize;
        an.smoothingTimeConstant = 0.35;
        src.connect(an);                       // 분석만 (스피커 출력 없음)
        var freqArr = new Uint8Array(an.frequencyBinCount);
        var frames = [];
        var ended = false;
        src.onended = function () { ended = true; };
        var nextT = ctx.currentTime + 0.05;
        src.start();
        var t0 = Date.now();
        while (!ended) {
            if (ctx.currentTime >= nextT) {
                an.getByteFrequencyData(freqArr);
                frames.push(freqArr.slice());
                nextT += 1 / 60;               // rAF ≈60Hz와 동일 캡처 간격
            }
            if (Date.now() - t0 > 8000) { try { src.stop(); } catch (e) {} break; }
            await new Promise(function (r) { setTimeout(r, 5); });
        }
        if (frames.length < 10) throw new Error('프레임 부족(' + frames.length + ')');
        var aligned = centerWindow(frames);
        var c = specCanvasFromFrames(aligned);
        await presetCommitCanvas(c, 'audio');
    }

    // 현재 선택 클래스에 샘플 push + 서버 업로드(완료 대기) — 연속 업로드의 serverId 꼬임 방지
    async function presetCommitCanvas(canvas, mediaType) {
        var cls = classes[selectedIdx];
        if (!cls) throw new Error('클래스를 먼저 선택하세요');
        var dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        cls.samples.push({ dataUrl: dataUrl, width: IMG_SIZE, height: IMG_SIZE, serverId: null, mfccPcm: null });
        renderClasses();
        updateTrainState();
        await uploadSampleAsync(cls.name, dataUrl, mediaType || 'image');
    }

    /* ── 다중 수집 (꾹 누르기) ─────────────────── */
    /*  [260919] 버그 수정: 손을 떼도 계속 수집되던 문제
        원인 — 모바일에서 touchstart/mousedown 이 중복 발생해
        setInterval 이 여러 개 만들어지고, stop 시 마지막 것만
        clear 되어 나머지(좀비) 타이머가 계속 돌았다.
        대책 — ① 시작 시 항상 기존 타이머 정리 ② 전용 타이머 ID 를
        보관해 확실히 중지 ③ 모든 종료 경로(up/leave/cancel/blur) 처리 */

    var holdActive = false;

    function _clearHoldTimer() {
        if (holdTimer) {
            clearInterval(holdTimer);
            holdTimer = null;
        }
    }

    window.startHoldCapture = function (ev) {
        if (ev && ev.preventDefault) { try { ev.preventDefault(); } catch (e) {} }
        if (!classes.length || !stream) return;

        // 이미 수집 중이면 무시 (중복 이벤트 → 좀비 타이머 방지)
        if (holdActive) return;

        // 혹시 남아있는 타이머가 있으면 먼저 정리
        _clearHoldTimer();

        holdActive = true;
        holdCount = 0;
        $('holdCount').textContent = '0장';
        holdTimer = setInterval(function () {
            if (!holdActive) { _clearHoldTimer(); return; }
            holdCount++;
            $('holdCount').textContent = holdCount + '장';
            addSample(canvasFromVideo(), true);
            if (holdCount > 60) { window.stopHoldCapture(); }
        }, 180);
    };

    window.stopHoldCapture = function (ev) {
        holdActive = false;
        _clearHoldTimer();
    };

    /* [260919] 안전장치 — 탭 전환/창 이탈/스크롤 중에도 반드시 중지 */
    window.addEventListener('blur', function () { window.stopHoldCapture(); });
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) { window.stopHoldCapture(); }
    });
    document.addEventListener('mouseup', function () { window.stopHoldCapture(); });
    document.addEventListener('touchend', function () { window.stopHoldCapture(); });
    document.addEventListener('touchcancel', function () { window.stopHoldCapture(); });

    /* ── 학습 (TF.js 전이학습) ─────────────────── */

    function updateTrainState() {
        var ok = classes.length >= MIN_CLASSES && classes.every(function (c) { return c.samples.length >= MIN_SAMPLES; });
        $('btnTrain').disabled = !ok || busy;
        $('btnClassify').disabled = !trained || busy;
        var ti = $('trainInfo');
        if (!trained) {
            $('trainDone').style.display = 'none';
            // ── 상황별 안내 힌트: 부족 원인을 버튼 위에 명확히 노출 (UX 개선) ──
            if (busy) {
                setTrainHint(ti, '⏳ 학습이 진행 중이에요. 잠시만 기다려 주세요.', false);
            } else if (!ok) {
                if (classes.length === 0) {
                    setTrainHint(ti, 'ⓘ 학습하려면 클래스가 2개 필요해요. 먼저 클래스를 만들어 주세요. (클래스 2개 × 클래스당 ' + MIN_SAMPLES + '장)', true);
                } else if (classes.length < MIN_CLASSES) {
                    setTrainHint(ti, 'ⓘ 클래스가 ' + classes.length + '/' + MIN_CLASSES + '개예요. 클래스를 ' + (MIN_CLASSES - classes.length) + '개 더 추가하세요. (학습 조건: 클래스 2개 × 클래스당 ' + MIN_SAMPLES + '장)', true);
                } else {
                    var lacks = [];
                    classes.forEach(function (c) {
                        if (c.samples.length < MIN_SAMPLES) {
                            lacks.push("'" + c.name + "' 클래스 " + c.samples.length + '/' + MIN_SAMPLES + '장');
                        }
                    });
                    setTrainHint(ti, 'ⓘ 샘플이 부족해요 — ' + lacks.join(', ') + '. 각 클래스에 ' + MIN_SAMPLES + '장 이상 수집하면 학습 버튼이 활성화돼요.', true);
                }
            } else {
                setTrainHint(ti, '✅ 학습 준비 완료! 버튼을 눌러 모델을 학습하세요.', false);
            }
        } else {
            $('trainDone').style.display = 'block';
            setTrainHint(ti, '모델이 준비됐어요! 실시간 분류를 테스트하거나, 아두이노와 연결해 보세요.', false);
        }
        // 비활성 버튼에 마우스 올리면 사유 툴팁 표시
        var btn = $('btnTrain');
        if (btn) btn.title = (!ok || busy) && !trained ? ti.textContent : '';
    }

    function setTrainHint(el, msg, warn) {
        el.textContent = msg;
        if (warn) { el.classList.add('ml-train-warn'); } else { el.classList.remove('ml-train-warn'); }
    }

    function findFeatureLayer(m) {
        var names = m.layers.map(function (l) { return l.name; });
        var name = names.find(function (n) { return n.indexOf('global_average_pooling') !== -1; });
        if (!name) name = names[names.length - 3];
        return m.getLayer(name);
    }

    var loadedPerfKey = null;    // 현재 로드된 MobileNet의 성능 모드 (변경 시 재로드)

    async function ensureMobileNet() {
        if (mobilenet && loadedPerfKey === perfKey) return;
        // 성능 모드 변경(고성능↔저사양) 시 기존 모델 해제 후 재로드
        // (0.25 alpha는 특징 차원이 256이라 1.0_224의 1024와 달라 headModel도 초기화)
        if (mobilenet) {
            try { mobilenet.dispose(); } catch (e) {}
            mobilenet = null;
            truncModel = null;
            headModel = null;
            trained = false;
            classLabels = [];
            if (classifying) stopClassify();
        }
        $('trainStatus').textContent = 'MobileNet 불러오는 중...';
        $('trainProgress').style.display = 'block';
        try {
            mobilenet = await tf.loadLayersModel(MOBILENET_URL);
            var layer = findFeatureLayer(mobilenet);
            truncModel = tf.model({ inputs: mobilenet.inputs, outputs: layer.output });
            truncModel.trainable = false;
            loadedPerfKey = perfKey;
        } catch (e) {
            throw new Error('MobileNet 모델을 불러오지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도하세요.');
        }
    }

    // 공용 특징 추출기 로드 — currentMode에 따라 image/audio 추출기 선택
    async function ensureExtractor() {
        if (currentMode === 'image') return ensureMobileNet();
        return currentModeDef.extractor.load();
    }

    async function buildTrainData() {
        // 음성 모드도 스펙트로그램 PNG(dataUrl) → 이미지 로드 경로를 그대로 사용
        var imgs = [], labels = [];
        for (var ci = 0; ci < classes.length; ci++) {
            var cls = classes[ci];
            for (var si = 0; si < cls.samples.length; si++) {
                var img = await loadImage(cls.samples[si].dataUrl);
                imgs.push(img);
                labels.push(ci);
                // 증강: 좌우 반전 — 이미지 모드만. 음성 스펙트로그램의
                // 좌우반전은 시간축 역전(소리가 거꾸로 재생)이라 의미 왜곡 → 생략
                if (currentMode === 'image') {
                    imgs.push(flipCanvas(img));
                    labels.push(ci);
                }
            }
        }
        var tensor = tf.browser.fromPixels(imgs[0]);
        var batch = tf.stack(imgs.map(function (im) {
            return tf.browser.fromPixels(im).toFloat().div(255);
        }));
        var y = tf.oneHot(tf.tensor1d(labels, 'int32'), classes.length);
        imgs.forEach(function (im) { im.width = im.height = 0; });
        return { x: batch, y: y };
    }

    function loadImage(src) {
        return new Promise(function (resolve, reject) {
            var img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = function () {
                var c = document.createElement('canvas');
                c.width = IMG_SIZE; c.height = IMG_SIZE;
                var ctx = c.getContext('2d');
                ctx.drawImage(img, 0, 0, IMG_SIZE, IMG_SIZE);
                resolve(c);
            };
            img.onerror = reject;
            img.src = src;
        });
    }

    function flipCanvas(c) {
        var c2 = document.createElement('canvas');
        c2.width = IMG_SIZE; c2.height = IMG_SIZE;
        var ctx = c2.getContext('2d');
        ctx.translate(IMG_SIZE, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(c, 0, 0);
        return c2;
    }

    // [MFCC 파일럿] MFCC 학습 — 샘플.mfccPcm(16k Float32Array) → MFCC(150×26) → 1D-CNN
    // 입력 규격 (150, 26): MFCC 13차 + Δ13차, 프레임별 정규화 (mfccComputeFromPcm16k와 동일)
    async function trainMfccHead(lossCtx) {
        $('trainStatus').textContent = 'MFCC 특징 추출 중...';
        var xs = [], labels = [], skipped = 0;
        for (var ci = 0; ci < classes.length; ci++) {
            var cls = classes[ci];
            for (var si = 0; si < cls.samples.length; si++) {
                var pcm = cls.samples[si].mfccPcm;
                if (!pcm) { skipped++; continue; }   // [MFCC] 스펙/이미지 샘플은 MFCC 학습에서 제외 (throw 대신 skip)
                xs.push(mfccComputeFromPcm16k(pcm));
                labels.push(ci);
            }
        }
        if (!xs.length) throw new Error('MFCC 샘플이 없어요. MFCC 모드로 샘플을 수집해 주세요.');
        if (skipped) $('trainStatus').textContent = 'MFCC 특징 추출 중... (MFCC 아닌 샘플 ' + skipped + '장 제외)';
        // ★ 6차 자가검증: 학습에 쓸 샘플들의 특징벡터를 보관해 두었다가, 학습 직후
        //   "그 샘플을 다시 분류"시켜 본다. 저장 데이터를 스스로 못 맞히면
        //   (= 사용자 표현 "저장한 데이터가 분류랑 동일하게 분류 못함")
        //   모델/특징/정렬 중 어디가 어긋났는지 즉시 드러난다.
        var selfXs = xs.slice();      // Float32Array[] (각 150×26 flat)
        var selfLabels = labels.slice();
        selfCheckMfcc._xs = selfXs;   // 자가검증에서 사용
        selfCheckMfcc._ys = selfLabels;
        // xs: flat Float32Array[] → 단일 flat TypedArray (tf.tensor3d 요구 규격)
        var flat = new Float32Array(xs.length * MFCC_MAX_FRAMES * MFCC_DIM);
        for (var fi = 0; fi < xs.length; fi++) flat.set(xs[fi], fi * MFCC_MAX_FRAMES * MFCC_DIM);
        var feats = tf.tensor3d(flat, [xs.length, MFCC_MAX_FRAMES, MFCC_DIM]);
        var y = tf.oneHot(tf.tensor1d(labels, 'int32'), classes.length);
        // ★ 클래스 가중치 계산용으로 라벨 배열을 해제 전에 보존한다.
        var labelsArr = labels.slice(), labelsLen = labels.length;
        xs = null; labels = null;   // 원본 Float32Array 해제

        $('trainStatus').textContent = '1D-CNN 분류기 학습 중...';
        headModel = tf.sequential();
        headModel.add(tf.layers.conv1d({ filters: 32, kernelSize: 3, activation: 'relu', inputShape: [MFCC_MAX_FRAMES, MFCC_DIM], padding: 'same' }));
        headModel.add(tf.layers.maxPooling1d({ poolSize: 2 }));
        headModel.add(tf.layers.conv1d({ filters: 64, kernelSize: 3, activation: 'relu', padding: 'same' }));
        headModel.add(tf.layers.globalAveragePooling1d({}));
        headModel.add(tf.layers.dense({ units: classes.length, activation: 'softmax' }));
        headModel.compile({ optimizer: tf.train.adam(0.001), loss: 'categoricalCrossentropy', metrics: ['accuracy'] });

        var losses = [];
        // ★ 4차 보완: 클래스별 샘플 수가 다르면 적은 쪽(예: "1번")이 학습에서 눌려
        //   확률이 낮게 나온다 → 샘플 수 역수 가중치로 균등 학습시킨다.
        var _cnt = new Array(classes.length).fill(0);
        for (var _i = 0; _i < labelsLen; _i++) _cnt[labelsArr[_i]]++;
        var _maxC = Math.max.apply(null, _cnt.concat([1]));
        var classWeight = {};
        for (var _c2 = 0; _c2 < classes.length; _c2++) {
            classWeight[_c2] = (_cnt[_c2] > 0) ? (_maxC / _cnt[_c2]) : 1;
        }
        logStudio('⚖️ 클래스 가중치: ' + classes.map(function (c, i) {
            return c.name + '(' + _cnt[i] + '개 ×' + classWeight[i].toFixed(2) + ')';
        }).join(' / '));
        await headModel.fit(feats, y, {
            epochs: EPOCHS,
            batchSize: 8,
            classWeight: classWeight,
            shuffle: true,
            callbacks: {
                onEpochEnd: function (epoch, logs) {
                    losses.push(logs.loss);
                    var pct = Math.round(((epoch + 1) / EPOCHS) * 100);
                    var acc = (logs.acc !== undefined) ? Math.round(logs.acc * 100) + '%' : '-';
                    $('trainStatus').textContent = '학습 중... (정확도 ' + acc + ')';
                    $('trainFill').style.width = pct + '%';
                    $('trainPct').textContent = pct + '%';
                    drawLoss(lossCtx, losses);
                },
            },
        });
        feats.dispose(); y.dispose();
    }

    /* ── ★ 6차 자가검증: 학습 샘플을 그대로 다시 분류 ──────────────────
     * "저장한 데이터가 분류랑 동일하게 분류 못한다"는 보고의 원인을 가른다.
     *  · 정확도 높음(≥90%) → 모델·특징은 정상. 실전 인식 문제는 (a) 마이크 입력
     *    (b) 발화 구간 자르기 (c) 임계값 쪽이다.
     *  · 정확도 낮음(<70%)  → 학습 특징과 분류 특징이 어긋났거나 모델이 미학습.
     * selfXs 는 학습에 쓴 것과 '완전히 같은' Float32Array 이므로 여기서 틀리면
     * 모델 자체(또는 라벨 순서)가 문제임이 100% 확정된다.
     */
    async function selfCheckMfcc() {
        try {
            if (!headModel || !selfCheckMfcc._xs || !selfCheckMfcc._xs.length) return;
            var xs = selfCheckMfcc._xs, ys = selfCheckMfcc._ys;
            var correct = 0, total = xs.length;
            var conf = {};   // 실제라벨 → {맞음, 전체}
            for (var i = 0; i < total; i++) {
                var t = tf.tensor3d(xs[i], [1, MFCC_MAX_FRAMES, MFCC_DIM]);
                var preds = headModel.predict(t);
                var probs = await preds.data();
                t.dispose(); preds.dispose();
                var best = 0;
                for (var k = 1; k < probs.length; k++) if (probs[k] > probs[best]) best = k;
                var realL = ys[i];
                conf[realL] = conf[realL] || { ok: 0, n: 0 };
                conf[realL].n++;
                if (best === realL) { correct++; conf[realL].ok++; }
            }
            var acc = Math.round((correct / total) * 100);
            var detail = classes.map(function (c, ci) {
                var r = conf[ci] || { ok: 0, n: 0 };
                return c.name + ' ' + r.ok + '/' + r.n;
            }).join(' · ');
            logStudio('🧪 자가검증(학습샘플 재분류): ' + acc + '% (' + correct + '/' + total + ') — ' + detail,
                acc >= 90 ? 'ok' : 'err');
            if (acc < 70) {
                logStudio('⚠️ 자가검증 실패 — 학습 특징과 분류 특징이 어긋났거나 모델이 덜 학습됐습니다. 발화를 더 모아 재학습하세요.', 'err');
            } else if (acc < 90) {
                logStudio('⚠️ 자가검증 보통 — 오분류된 클래스의 샘플을 더 모으거나, 그 단어를 또렷하게 재녹음하세요.', 'err');
            } else {
                logStudio('✅ 자가검증 양호 — 모델은 정상입니다. 인식이 안 되면 마이크 거리/발화 길이를 조정하세요.', 'ok');
            }
        } catch (e) {
            console.warn('[ml-studio] selfCheckMfcc error:', e.message);
        }
    }

    window.trainModel = async function () {
        if (busy) return;
        if (classes.length < MIN_CLASSES) { showAlert('클래스를 ' + MIN_CLASSES + '개 이상 만들어 주세요.', 'error'); return; }
        for (var i = 0; i < classes.length; i++) {
            if (classes[i].samples.length < MIN_SAMPLES) {
                showAlert('"' + classes[i].name + '" 클래스에 샘플을 ' + MIN_SAMPLES + '장 이상 모아 주세요.', 'error');
                return;
            }
        }
        busy = true;
        $('btnTrain').disabled = true;
        $('trainProgress').style.display = 'block';
        $('trainStatus').textContent = '데이터 준비 중...';
        $('trainFill').style.width = '0%';
        $('trainPct').textContent = '0%';
        var lossCtx = $('lossCanvas').getContext('2d');

        try {
            if (useMfccPath()) {
                // [MFCC 파일럿] PCM → MFCC(150×26) → Conv1D — 로컬 세션 전용
                // (서버 샘플·IndexedDB 캐시·서버 상태 저장 없음 — spec 캐시 오염 방지)
                await trainMfccHead(lossCtx);
                // ★ 6차 자가검증: 방금 학습에 쓴 샘플을 그대로 다시 분류시켜
                //   "저장 데이터를 스스로 맞히는지"를 즉시 확인한다.
                await selfCheckMfcc();
            } else {
                // ── 기존 스펙트로그램(MobileNet 특징) 전이학습 경로 ──
                await ensureExtractor();
                $('trainStatus').textContent = '특징 추출 중...';
                var data = await buildTrainData();
                var features = currentModeDef.extractor.embed(data.x);
                data.x.dispose();

                $('trainStatus').textContent = '분류기 학습 중...';
                var numClasses = classes.length;
                headModel = tf.sequential();
                headModel.add(tf.layers.dense({ units: 64, activation: 'relu', inputShape: [features.shape[1]] }));
                headModel.add(tf.layers.dropout({ rate: 0.2 }));
                headModel.add(tf.layers.dense({ units: numClasses, activation: 'softmax' }));
                headModel.compile({ optimizer: tf.train.adam(0.001), loss: 'categoricalCrossentropy', metrics: ['accuracy'] });

                var losses = [];
                await headModel.fit(features, data.y, {
                    epochs: EPOCHS,
                    batchSize: 16,
                    shuffle: true,
                    callbacks: {
                        onEpochEnd: function (epoch, logs) {
                            losses.push(logs.loss);
                            var pct = Math.round(((epoch + 1) / EPOCHS) * 100);
                            $('trainStatus').textContent = '학습 중... (정확도 ' + (logs.acc ? Math.round(logs.acc * 100) + '%' : '-') + ')';
                            $('trainFill').style.width = pct + '%';
                            $('trainPct').textContent = pct + '%';
                            drawLoss(lossCtx, losses);
                        },
                    },
                });
                data.y.dispose();
                features.dispose();
            }

            classLabels = classes.map(function (c) { return c.name; });
            trained = true;
            if (!useMfccPath()) {
                // IndexedDB 캐시 + 서버 상태 — spec 경로만 (MFCC는 로컬 세션 전용)
                try { await headModel.save('indexeddb://nubida-ml-' + projectId); } catch (e) {}
                localStorage.setItem('nubida-ml-labels-' + projectId, JSON.stringify(classLabels));
                // ⚠️ status='ready'는 서버 모델 파일이 실제로 저장된 뒤에만 설정해야 한다.
                //    (파일 없이 ready만 찍히면 아두이노 페이지에서 모델을 못 찾고 조용히 실패)
                //    → 아래에서 서버 자동 저장을 먼저 수행하고, 성공 시에만 ready로 표시한다.
            }

            // ── [자동 서버 저장] 학습 완료 즉시 서버에 모델 업로드 ──
            //  이전에는 [💾 모델 저장] 버튼을 따로 눌러야 했고, 누르지 않으면
            //  아두이노 연동 페이지에서 모델을 찾지 못해 '분류 시작'이 동작하지 않았다.
            //  ★ 10차: MFCC 모델도 서버 저장 대상에 포함.
            //   기존에는 "MFCC 파일럿 = 로컬 세션 전용" 이라 서버 저장을 건너뛰었는데,
            //   그 결과 브라우저 캐시(IndexedDB)를 지우거나 클래스를 삭제하면
            //   학습한 모델이 통째로 사라졌다(사용자 신고: "학습한 모델은 저장돼있어야 해").
            //   → 이미지·MFCC 모두 서버(model.json + weights.bin + labels.json)에 저장한다.
            var serverSaved = false;
            $('trainStatus').textContent = '모델을 서버에 저장하는 중...';
            serverSaved = await saveModelToServerCore(true);
            if (serverSaved) {
                try { await apiPatch('/ml/projects/' + projectId, { status: 'ready' }); } catch (e) {}
            } else {
                // 저장 실패 시 상태를 ready로 남기지 않음 (다음 실행에서 재학습/재저장 유도)
                try { await apiPatch('/ml/projects/' + projectId, { status: 'collecting' }); } catch (e) {}
            }
            // ★ 10차: 자동 저장 성공 시 [💾 모델 저장] 버튼은 숨긴 채로 두고,
            //   저장 실패일 때만 '재시도' 버튼을 노출한다.
            var _manualBtn = $('btnSaveModelManual');
            if (_manualBtn) _manualBtn.style.display = serverSaved ? 'none' : '';

            $('trainDone').style.display = 'block';
            var doneMsg = $('trainDone').querySelector('p');
            if (doneMsg) {
                doneMsg.textContent = useMfccPath()
                    ? (serverSaved
                        ? '🎉 학습 완료! 서버에 저장됐어요. 실시간 분류를 테스트해 보세요.'
                        : '🎉 학습 완료! (서버 저장 실패 — [💾 모델 저장]을 다시 눌러 주세요)')
                    : (serverSaved
                        ? '🎉 학습 완료! 서버에 자동 저장됐어요. 아두이노 연동도 바로 가능해요.'
                        : '⚠️ 학습은 완료됐지만 서버 저장에 실패했어요. [💾 모델 저장]을 다시 눌러 주세요.');
            }
            $('trainStatus').textContent = serverSaved || useMfccPath() ? '🎉 학습 완료!' : '⚠️ 학습 완료 (서버 저장 실패)';
            $('trainPct').textContent = '100%';
            if (useMfccPath()) {
                showAlert('🎉 학습이 완료됐어요! 실시간 분류를 시작해 보세요.', 'success');
            } else if (!serverSaved) {
                showAlert('학습은 완료됐지만 서버 저장에 실패했어요. [💾 모델 저장]을 다시 눌러 주세요.', 'error');
                log('서버 저장 실패 — [💾 모델 저장] 버튼으로 재시도하세요.', 'err');
            }
            // 첫 분류 지연 제거 (방식별 워밍업)
            if (useMfccPath()) warmUpMfccModel(); else warmUpModel();
        } catch (e) {
            $('trainStatus').textContent = '학습 실패';
            showAlert(e.message || '학습 중 오류가 발생했어요.', 'error');
        }
        busy = false;
        updateTrainState();
    };

    function drawLoss(ctx, losses) {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        if (losses.length < 2) return;
        ctx.strokeStyle = '#4F5EF8'; ctx.lineWidth = 2;
        ctx.beginPath();
        var w = ctx.canvas.width, h = ctx.canvas.height;
        var max = Math.max.apply(null, losses) || 1;
        losses.forEach(function (v, i) {
            var x = (i / (losses.length - 1)) * w;
            var y = h - 8 - (v / max) * (h - 20);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.fillStyle = '#9CA3AF'; ctx.font = '10px sans-serif';
        ctx.fillText('손실(loss) ↓', 6, 12);
    }

    /* ── 실시간 분류 ───────────────────────────── */

    window.toggleClassify = function () {
        if (classifying) stopClassify();
        else startClassify();
    };

    window.startClassify = async function () {
        if (!trained || !headModel) { showAlert('먼저 모델을 학습하세요.', 'error'); return; }
        if (!currentModeDef.source.active) await currentModeDef.source.start();
        classifying = true;
        $('btnClassify').textContent = '⏹ 분류 중지';
        // [진단] 분류 시작 시 경로/모델 상태를 한 번에 남긴다 — "인식이 안 된다"의 1차 판별.
        logStudio('▶ 분류 시작 — 모드=' + currentMode +
            ' / MFCC경로=' + (useMfccPath() ? 'Y' : 'N') +
            ' / 성능=' + perfKey +
            ' / 클래스=' + classLabels.length + '개 [' +
            classLabels.map(function (l, i) { return (i + 1) + ':' + l; }).join(', ') + ']');
        if (currentMode === 'audio') {
            // 음성 모드 — Voice Hold 시작 (결과 유지 모드)
            voiceHold.reset();
            renderHoldState();
        }
        /* ★★★ 260916 윤비스: setInterval + async 조합 = 큐 적체(랙) 수정
         *   ── 원인 ──────────────────────────────────────────────
         *   runClassifyOnce() 는 async 함수다. 내부에 await(preds.data()) 가
         *   있어서 실행이 끝나기 전에 즉시 반환된다.
         *   setInterval(120) 은 "끝났는지" 를 보지 않고 120ms 마다 무조건 호출한다.
         *   → 추론이 120ms 보다 오래 걸리는 순간부터 호출이 무한히 쌓인다.
         *     (추론 250ms 기준 +4.3개/초, 700ms 기준 +6.9개/초 적체)
         *   → 아두이노 동작(도리도리 4.2초) 동안 수십 개가 쌓여,
         *     동작이 끝나면 밀린 명령이 우르르 실행된다.
         *   ── 해결 ──────────────────────────────────────────────
         *   자기재귀 setTimeout — 앞 실행이 "끝난 뒤" 다음을 예약한다.
         *   어떤 기기에서도 큐가 쌓이지 않는다.
         *   ──────────────────────────────────────────────────── */
        classifyRunning = true;
        (function classifyLoop() {
            if (!classifyRunning) return;
            classifyTimer = setTimeout(function () {
                var p;
                try { p = runClassifyOnce(); } catch (e) { p = null; }
                // 추론이 끝난 뒤에만 다음 틱 예약 (await 체인 소진 대기)
                if (p && typeof p.then === 'function') {
                    p.then(function () { if (classifyRunning) classifyLoop(); },
                           function () { if (classifyRunning) classifyLoop(); });
                } else {
                    if (classifyRunning) classifyLoop();
                }
            }, 120);
        })();
    }

    function stopClassify() {
        classifying = false;
        classifyRunning = false;     // ★ 260916: 자기재귀 루프 중단
        if (classifyTimer) { clearTimeout(classifyTimer); classifyTimer = null; }
        $('btnClassify').textContent = '🎯 분류 시작';
        if (currentMode === 'audio') voiceHold.reset();
    }

    // 첫 predict 지연(GPU 셰이더 컴파일) 제거용 워밍업 — 모델 로드/학습 직후 1회 실행
    // (음성 모드도 동일 MobileNet이므로 공용)
    async function warmUpModel() {
        if (!truncModel || !headModel) return;
        try {
            var t = tf.zeros([1, IMG_SIZE, IMG_SIZE, 3]);
            var feats = truncModel.predict(t);
            var preds = headModel.predict(feats);
            await preds.data();
            t.dispose(); feats.dispose(); preds.dispose();
        } catch (e) { /* 워밍업 실패는 무시 (분류 중 다시 컴파일됨) */ }
    }

    // [MFCC 파일럿] Conv1D 헤드 워밍업 — truncModel(MobileNet) 없이 MFCC 텐서 직접 predict
    async function warmUpMfccModel() {
        if (!headModel) return;
        try {
            var t = tf.zeros([1, MFCC_MAX_FRAMES, MFCC_DIM]);
            var preds = headModel.predict(t);
            await preds.data();
            t.dispose(); preds.dispose();
        } catch (e) { /* 워밍업 실패는 무시 */ }
    }

    // 발화 구간 중앙 스펙트로그램 윈도우를 분류해 최종 후보 반환 (Voice Hold 확정용)
    // 학습 샘플과 동일한 centerWindow + specCanvasFromFrames 변환 → 위치 정합
    // [MFCC 파일럿] MFCC 모드는 발화 시작(startPcmMark) 이후 PCM → centerUtterance → Conv1D
    async function classifySpeechWindow() {
        if (useMfccPath()) {
            var rows = await classifyMfccRows();
            if (!rows || !rows.length) return null;
            // ★ [2클래스 거부] 1위만 넘기면 "2위와의 격차"를 판단할 수 없다.
            //   rows 전체를 붙여 반환 → 호출부에서 prob + gap(1위-2위) 로 확정 여부를 정한다.
            var top = rows[0];
            top.gap = rows.length > 1 ? (rows[0].prob - rows[1].prob) : rows[0].prob;
            return top;
        }
        var frames = centerWindow(voiceHold.speechBuf);
        var c = specCanvasFromFrames(frames);
        try {
            /* ★★★ [2026-09-16] 텐서 누수 완전 해결 — tf.tidy() (위 classify 경로와 동일) */
            var tensor = tf.tidy(function () {
                return tf.browser.fromPixels(c).toFloat().div(255).expandDims(0);
            });
            var feats = currentModeDef.extractor.embed(tensor);
            var preds = headModel.predict(feats);
            var probs = await preds.data();
            tensor.dispose(); feats.dispose(); preds.dispose();
            var rows = classLabels.map(function (label, i) { return { label: label, prob: probs[i] }; })
                .sort(function (a, b) { return b.prob - a.prob; });
            var t2 = rows[0];
            t2.gap = rows.length > 1 ? (rows[0].prob - rows[1].prob) : rows[0].prob;
            return t2;
        } catch (e) {
            console.warn('[ml-studio] speech-window classify error:', e.message);
            return null;
        }
    }

    // [MFCC 파일럿] 발화 시작(startPcmMark) 이후 PCM → 16k → centerUtterance(1.522s) →
    // MFCC(150×26) → Conv1D 분류. 학습 샘플과 동일 정렬/변환 — 전체 rows 반환(실시간·확정 공용).
    async function classifyMfccRows() {
        try {
            if (!audioSource.pcmRing || voiceHold.startPcmMark < 0) return null;
            var seg = audioSource.readPcmSince(voiceHold.startPcmMark);
            if (seg.length < MFCC_SR / 2) return null;                // 0.5초 미만 발화는 생략
            var pcm16 = (audioSource.pcmSr === MFCC_SR) ? seg : await mfccResampleFloat32(seg, audioSource.pcmSr);
            var win = mfccCenterUtterance(pcm16);
            if (win.length < MFCC_FFT) return null;
            var m = mfccComputeFromPcm16k(win);
            var t = tf.tensor3d(m, [1, MFCC_MAX_FRAMES, MFCC_DIM]);   // m은 flat Float32Array(150×26)
            var preds = headModel.predict(t);
            var probs = await preds.data();
            t.dispose(); preds.dispose();
            var rows = classLabels.map(function (label, i) { return { label: label, prob: probs[i] }; })
                .sort(function (a, b) { return b.prob - a.prob; });
            // [진단] 전체 클래스 확률 분포 로그 — "특정 번호만 인식 안 됨"의 원인 판별용.
            //  (a) 해당 클래스 확률이 항상 낮은가 (b) 라벨↔노드 순서가 어긋났나
            //  (c) 격차가 작아 임계에 걸리나 — 이 한 줄로 구분된다.
            try {
                var _dist = classLabels.map(function (label, i) {
                    return label + '=' + Math.round(probs[i] * 100) + '%';
                }).join(' ');
                logStudio('📊 확률분포 [' + _dist + '] → 1위 ' + rows[0].label +
                    (rows.length > 1 ? ' (격차 ' + Math.round((rows[0].prob - rows[1].prob) * 100) + '%p)' : ''));
            } catch (e3) {}
            return rows;
        } catch (e) {
            console.warn('[ml-studio] MFCC window classify error:', e.message);
            return null;
        }
    }

    async function runClassifyOnce() {
        if (!currentModeDef.source.active || !headModel) return;
        var c;
        if (currentMode === 'audio') {
            // [진단] 3초마다 마이크 레벨을 로그로 남긴다 — "말을 인식 못 한다"의 1차 판별.
            //  RMS 가 계속 0.00x 이면 마이크 권한/볼륨/장치 문제이고,
            //  RMS 가 0.02~0.2 로 움직이는데 결과가 없으면 모델/임계 문제다.
            var _now = Date.now();
            if (!voiceHold._lastRmsLog || _now - voiceHold._lastRmsLog > 3000) {
                voiceHold._lastRmsLog = _now;
                var _r = currentRms();
                logStudio('🎚 마이크 RMS ' + (Math.round(_r * 1000) / 1000) +
                    ' (게이트 ' + voiceHold.SPEECH_RMS + ') — ' +
                    (_r >= voiceHold.SPEECH_RMS ? '발화 감지됨 ✅' : '소리를 크게/가까이 🎤'));
            }
            // 음성 모드 — 실시간 스펙트로그램(3초 유동 버퍼)을 224×224로 변환해 분류
            if (!useMfccPath() && audioSource.specFrames.length < SPEC_FRAMES) return;   // 아직 3초 미만 (MFCC는 PCM 기반이라 불필요)
            // ── Voice Hold: 발화 구간 감지(RMS) + 결과 Latch ──
            voiceHold.rms = currentRms();
            var speaking = voiceHold.rms >= voiceHold.SPEECH_RMS;
            if (voiceHold.state === 'holding') {
                if (speaking) {
                    // 새 발화 시작 → 실시간 판정 재개 (확정 결과는 다음 확정까지 유지)
                    voiceHold.state = 'speaking';
                    voiceHold.silenceMs = 0;
                    voiceHold.speechBuf = [];                          // 새 발화 구간 수집 시작
                    voiceHold.startPcmMark = audioSource.pcmTotal;     // [MFCC] 새 발화 시작점 기록
                    // 프레임 push는 rAF _loop에서 수행 (학습 캡처와 동일 규칙)
                } else {
                    renderHoldState();   // 무음 유지 — 고정 결과 계속 표시 (분류 생략)
                    return;
                }
            } else if (voiceHold.state === 'idle') {
                if (!speaking) { renderHoldState(); return; }  // 최초 무음 — 대기 안내
                voiceHold.state = 'speaking';                  // 발화 시작
                voiceHold.silenceMs = 0;
                voiceHold.speechBuf = [];                      // 발화 구간 프레임 수집 시작
                voiceHold.startPcmMark = audioSource.pcmTotal; // [MFCC] 발화 시작점 기록
                // 프레임 push는 rAF _loop에서 수행 (학습 캡처와 동일 규칙)
            } else { // speaking
                if (speaking) {
                    voiceHold.silenceMs = 0;                   // 말하는 중 — 무음 누적 초기화
                } else {
                    voiceHold.silenceMs += 120;                // runClassifyOnce 틱 간격
                    if (voiceHold.silenceMs >= voiceHold.SILENCE_HOLD_MS) {
                        // 발화 종료 → ★ 발화 구간 중앙 스펙트로그램으로 재분류·확정
                        // (기존: 확정 시점의 유동 윈도우 — 발화가 밀려나 학습 샘플과 위치 불일치)
                        voiceHold.state = 'holding';
                        // [진단] MFCC 경로는 startPcmMark 기준으로 PCM 을 잘라 분류한다.
                        //  이 값이 -1 이면 classifyMfccRows 가 즉시 null 을 반환해
                        //  "아무 로그도 없이" 인식이 안 된다 (마이크는 정상인데 결과만 없음).
                        logStudio('🎙 발화 종료 — MFCC경로=' + (useMfccPath() ? 'Y' : 'N') +
                            ' PCM시작=' + voiceHold.startPcmMark +
                            ' / RMS ' + (Math.round(currentRms() * 1000) / 1000) +
                            ' (게이트 ' + voiceHold.SPEECH_RMS + ')' +
                            (useMfccPath() ? '' : ' / 프레임 ' + (voiceHold.speechBuf ? voiceHold.speechBuf.length : 0)));
                        var locked = await classifySpeechWindow();
                        if (!locked) {
                            logStudio('⚠️ 분류 결과 없음 — PCM 미수집이거나 발화가 0.5초 미만이에요', 'err');
                        }
                        // ★ [2클래스 거부 문제 수정] softmax 는 클래스가 2개면 어떤 소리를
                        //   넣어도 두 값의 합이 1 이 되어 반드시 하나가 이긴다(= 학습에 없는
                        //   "춤춰" 같은 단어도 무조건 1번/2번으로 나옴). 또 확률이 임계 미만일 때
                        //   이전 확정값을 그대로 두면 엉뚱한 값이 계속 전송된다.
                        //   → 임계 이상일 때만 확정하고, 미달이면 확정을 "비운다".
                        //  ★ 2026-09-13 4차 보완: "2번은 되는데 1번만 안 된다" 대응.
                        //    특정 클래스가 학습 데이터 부족/편향으로 확률이 30%대에 머물러도
                        //    1·2위 격차가 크면(그 클래스가 유일하게 유력하면) 확정해 준다.
                        //    → (prob≥하한 AND gap≥하한)  OR  (gap≥큰격차 0.20)
                        var strongGap = (locked && locked.gap !== undefined && locked.gap >= 0.20);
                        var lockOk = !!(locked &&
                            ((locked.prob >= voiceHold.MIN_LOCK_PROB &&
                              (locked.gap === undefined || locked.gap >= voiceHold.MIN_LOCK_GAP)) ||
                             (strongGap && locked.prob >= 0.25)));
                        if (lockOk) {
                            voiceHold.lockedLabel = locked.label;
                            voiceHold.lockedPct = locked.prob;
                            voiceHold.lockedIdx = classLabels.indexOf(locked.label);
                            // 🔒 보안(260913 윤비스 지시): 아두이노로 나가는 값({번호}{접두어})은
                            //   화면·로그에 절대 표시하지 않는다. 사람이 읽을 수 있는 라벨만 남긴다.
                            logStudio('🔒 확정: ' + locked.label + ' ' +
                                Math.round(locked.prob * 100) + '%' +
                                (locked.gap !== undefined ? ' (격차 ' + Math.round(locked.gap * 100) + '%p)' : ''));
                        } else {
                            // 미달 = 미학습 단어/불명확 → 이전 확정을 지워 재전송을 막는다
                            voiceHold.lockedLabel = null;
                            voiceHold.lockedPct = 0;
                            voiceHold.lockedIdx = -1;
                            if (locked) {
                                logStudio('🔇 확정 보류 — ' + Math.round(locked.prob * 100) + '%' +
                                    (locked.gap !== undefined ? ' 격차 ' + Math.round(locked.gap * 100) + '%p' : '') +
                                    ' (필요: ' + Math.round(voiceHold.MIN_LOCK_PROB * 100) + '% / ' +
                                    Math.round(voiceHold.MIN_LOCK_GAP * 100) + '%p) : ' + locked.label);
                            }
                        }
                        if (lockOk) sendHeldValue();   // ★ 확정된 경우에만 전송
                        renderHoldState();
                        return;
                    }
                }
            }
            if (useMfccPath()) {
                // [MFCC 파일럿] 발화 중 실시간 — 600ms throttling으로 MFCC 재분류
                // (120ms 틱마다 리샘플+STFT를 돌리면 CPU 과부하 — 마지막 분류 후 600ms 경과 시만)
                // 확정(무음 0.6s) 시점은 classifySpeechWindow → classifyMfccRows가 정확히 1회 수행
                if (voiceHold.state === 'speaking' && !mfccTickBusy && (Date.now() - mfccLastLiveAt) >= 600) {
                    mfccTickBusy = true;
                    classifyMfccRows().then(function (rows) {
                        mfccTickBusy = false;
                        mfccLastLiveAt = Date.now();
                        if (!rows || !rows.length || voiceHold.state !== 'speaking') return;
                        voiceHold.liveLabel = rows[0].label;
                        voiceHold.livePct = rows[0].prob;
                        renderLiveResults(rows);
                    }).catch(function () { mfccTickBusy = false; });
                }
                return;
            }
            c = audioSource.specCanvas224();
        } else {
            c = canvasFromVideo();
        }
        try {
            /* ★★★ [2026-09-16] 텐서 누수 완전 해결 — tf.tidy() ────────────
             *  기존 : tf.browser.fromPixels(c).toFloat().div(255).expandDims(0)
             *         → fromPixels / toFloat / div 가 만든 **중간 텐서가 유실**된다.
             *           (마지막 expandDims 결과만 변수에 담겨 dispose 되던 구조)
             *  실측(Chromium, 200회 반복, GC 강제 후):
             *      · 기존 체이닝        : 텐서 600개 잔존 (회당 3.0개, 344 MB) ← 심각
             *      · 단계분리+dispose   : 텐서 200개 잔존 (회당 1.0개, 115 MB) ← 부분 개선
             *      · tf.tidy()          : 텐서   0개 잔존 (회당 0.0개,   0 MB) ← 완전 해결
             *    ※ toFloat() 자체가 이 TF.js 버전에서 텐서 1개를 남긴다(실측 확인).
             *       명시적 dispose 로는 회수되지 않아 tidy() 만이 유일한 해법이다.
             *  카메라는 초당 8회 분류 → 이 누수가 GPU(WebGL) 메모리까지 잠식해
             *  "카메라가 더 심하게 느려지는" 직접 원인이었다.
             * ────────────────────────────────────────────────────────── */
            var tensor = tf.tidy(function () {
                return tf.browser.fromPixels(c).toFloat().div(255).expandDims(0);
            });
            var feats = currentModeDef.extractor.embed(tensor);
            var preds = headModel.predict(feats);
            var probs = await preds.data();
            tensor.dispose(); feats.dispose(); preds.dispose();

            var rows = classLabels.map(function (label, i) { return { label: label, prob: probs[i] }; })
                .sort(function (a, b) { return b.prob - a.prob; });

            if (currentMode === 'audio') {
                // 음성 모드 — 발화 중 실시간 후보 기록 + 흐린(미확정) 표시
                // (state 체크: 무음 0.6s 후 holding/확정된 뒤 도착한 실시간 결과가
                //  🔒 고정 표시를 덮는 렌더 레이스를 방지 — 2026-09-04)
                if (voiceHold.state !== 'speaking') return;
                voiceHold.liveLabel = rows[0].label;
                voiceHold.livePct = rows[0].prob;
                renderLiveResults(rows);
            } else {
                renderResults(rows);   // 이미지 모드 — 기존 연속 실시간 유지

                /* ★★ [2026-09-14] 카메라(이미지) 모드도 아두이노로 전송한다.
                 *   ── 발견된 근본 원인 ──────────────────────────────────
                 *   sendHeldValue() 호출은 runClassifyOnce() 의 **음성 분기**
                 *   (if (currentMode === 'audio') { ... if (lockOk) sendHeldValue(); })
                 *   안에만 있었다. 카메라 분기는 renderResults() 로 화면만 그리고
                 *   전송 호출이 아예 없었다.
                 *   → "음성은 되는데 카메라는 분류만 되고 값이 안 간다"의 100% 원인.
                 *   ────────────────────────────────────────────────────
                 *   음성과 동일한 경로(btCommandFrame → bleStudio.writeLine)를 쓰되,
                 *   카메라는 초당 8회(120ms) 틱이므로 **같은 클래스 반복은 걸러**낸다.
                 *   (음성은 발화 단위라 자연히 1회지만, 카메라는 연속 프레임이다)
                 */
                var camTop = rows[0];
                var camGap = (rows.length > 1) ? (camTop.prob - rows[1].prob) : camTop.prob;
                // 확정 기준 — 음성과 동일한 임계 사용
                var camLockOk = (camTop.prob >= voiceHold.MIN_LOCK_PROB &&
                                 (rows.length < 2 || camGap >= voiceHold.MIN_LOCK_GAP));
                var camIdx = camLockOk ? classLabels.indexOf(camTop.label) : -1;

                if (camIdx < 0) {
                    // 확정 실패 — 사유를 남긴다 (조용한 실패 금지)
                    //   같은 메시지가 매 프레임 반복되면 로그가 덮이므로 1초에 1회만.
                    var nowC = Date.now();
                    if (!camHold.lastSkipLogAt || nowC - camHold.lastSkipLogAt > 1000) {
                        camHold.lastSkipLogAt = nowC;
                        logStudio('🔇 카메라 확정 보류 — ' + Math.round(camTop.prob * 100) + '%'
                            + (rows.length > 1 ? ' 격차 ' + Math.round(camGap * 100) + '%p' : '')
                            + ' (필요: ' + Math.round(voiceHold.MIN_LOCK_PROB * 100) + '% / '
                            + Math.round(voiceHold.MIN_LOCK_GAP * 100) + '%p) : ' + camTop.label,
                            'info');
                    }
                } else {
                    // 같은 클래스 반복 전송 차단 — 카메라는 120ms 마다 같은 결과가 나온다.
                    //   (음성의 voiceHold.lastSentValue/1초 로직과 동일한 취지)
                    var nowC2 = Date.now();
                    var CAM_REPEAT_MS = 1000;
                    if (camHold.lastSentIdx === camIdx && (nowC2 - camHold.lastSentAt) < CAM_REPEAT_MS) {
                        // 같은 값 반복 — 조용히 생략 (로그 폭주 방지)
                    } else if (sendingHeld) {
                        // 이전 전송 진행 중 — 다음 틱에 재시도
                    } else {
                        if (camHold.lastSentIdx !== camIdx) {
                            logStudio('🔒 카메라 확정: ' + camTop.label + ' '
                                + Math.round(camTop.prob * 100) + '%'
                                + (rows.length > 1 ? ' (격차 ' + Math.round(camGap * 100) + '%p)' : ''));
                        }
                        camHold.lastSentIdx = camIdx;
                        camHold.lastSentAt = nowC2;
                        // 음성과 완전히 동일한 전송 경로 사용
                        voiceHold.lockedIdx = camIdx;
                        voiceHold.lockedLabel = camTop.label;
                        voiceHold.lockedPct = camTop.prob;
                        sendHeldValue();
                    }
                }
            }
        } catch (e) {
            // 프레임 누락(드물게 발생) 외 오류는 콘솔에 남겨 디버깅 가능하게
            if (e && e.message && e.message.indexOf('Requested texture size') === -1) {
                console.warn('[ml-studio] classify error:', e.message);
            }
        }
    }

    /* ★★★ 260916 윤비스: DOM 재생성 최적화 (화면 멈칫 수정)
     *   ── 원인 ──────────────────────────────────────────────
     *   카메라 모드는 120ms(초당 8회)마다 renderResults() 를 부른다.
     *   그런데 매번 box.innerHTML = '' 로 결과 박스를 통째로 파괴하고
     *   5줄을 새로 만든다 → 레이아웃 재계산(thrash) → 화면이 멈칫거린다.
     *   ── 해결 ──────────────────────────────────────────────
     *   1위 라벨/확률/막대가 지난 프레임과 같으면 즉시 반환한다.
     *   값이 실제로 바뀔 때만 DOM 을 다시 그린다.
     *   (초당 8회 → 값 변동 시에만. 변화 없는 프레임은 DOM 비용 0)
     *   ──────────────────────────────────────────────────── */
    var lastRenderKey = '';
    function renderResults(rows) {
        if (!rows || !rows.length) return;                  // 빈 결과 가드
        var box = $('resultBox');
        var top = rows[0];

        // 렌더 키 — 표시되는 5줄의 (라벨, 확률) 이 모두 같으면 다시 안 그린다
        var renderKey = top.label + '|' + Math.round(top.prob * 100);
        var nShow = Math.min(rows.length, 5);
        for (var k = 0; k < nShow; k++) {
            renderKey += '-' + rows[k].label + ':' + Math.round(rows[k].prob * 100);
        }
        if (renderKey === lastRenderKey && box.childElementCount > 0) {
            return;                                          // ★ 변화 없음 → DOM 작업 생략
        }
        lastRenderKey = renderKey;

        box.innerHTML = '';
        $('resultTop').style.display = 'block';
        $('resultLabel').textContent = top.label;
        $('resultPct').textContent = Math.round(top.prob * 100) + '%';
        $('resultTop').style.background = 'linear-gradient(135deg,' + classColor(top.label) + ', #8B5CF6)';

        rows.slice(0, 5).forEach(function (r) {
            var row = el('div', 'ml-result-bar-row');
            row.appendChild(el('span', 'ml-result-bar-label', r.label));
            var track = el('div', 'ml-result-bar-track');
            var fill = el('div', 'ml-result-bar-fill');
            fill.style.width = Math.max(2, Math.round(r.prob * 100)) + '%';
            fill.style.background = classColor(r.label);
            track.appendChild(fill);
            row.appendChild(track);
            row.appendChild(el('span', 'ml-result-bar-pct', Math.round(r.prob * 100) + '%'));
            box.appendChild(row);
        });
    }

    // 음성 모드 — 발화 중 실시간(미확정) 결과 표시
    // 흔들림 최소화: 임계 확률 미만이면 "판별 중…"으로 대체, 바는 흐리게(0.4)
    function renderLiveResults(rows) {
        if (!rows || !rows.length) return;   // [MFCC 파일럿] 빈 결과 가드 (throttling 비동기 도착 지연 등)
        var box = $('resultBox');
        box.innerHTML = '';
        var top = rows[0];
        // ★ 4차 보완: 특정 클래스가 데이터 편향으로 확률이 낮아도 1·2위 격차가 크면
        //   (= 다른 후보를 압도하면) 표시해 준다. 그래야 "1번만 인식 안 됨"이 사라진다.
        var liveGap = (rows.length > 1) ? (rows[0].prob - rows[1].prob) : rows[0].prob;
        var show = (top.prob >= voiceHold.MIN_SHOW_PROB) || (liveGap >= 0.20 && top.prob >= 0.22);
        $('resultTop').style.display = 'block';
        $('resultLabel').textContent = show ? top.label : '판별 중…';
        $('resultPct').textContent = show ? Math.round(top.prob * 100) + '%' : '';
        $('resultTop').style.background = show
            ? 'linear-gradient(135deg,' + classColor(top.label) + ', #8B5CF6)'
            : 'linear-gradient(135deg,#6B7280,#9CA3AF)';
        rows.slice(0, 5).forEach(function (r) {
            var row = el('div', 'ml-result-bar-row');
            row.appendChild(el('span', 'ml-result-bar-label', r.label));
            var track = el('div', 'ml-result-bar-track');
            var fill = el('div', 'ml-result-bar-fill');
            fill.style.width = Math.max(2, Math.round(r.prob * 100)) + '%';
            fill.style.background = classColor(r.label);
            fill.style.opacity = show ? '0.85' : '0.4';
            track.appendChild(fill);
            row.appendChild(track);
            row.appendChild(el('span', 'ml-result-bar-pct', Math.round(r.prob * 100) + '%'));
            box.appendChild(row);
        });
    }

    // 음성 모드 — 확정·고정(🔒) 결과 표시. 다음 발화가 시작되기 전까지 유지
    function renderHoldState() {
        var box = $('resultBox');
        box.innerHTML = '';
        $('resultTop').style.display = 'block';
        if (voiceHold.lockedLabel) {
            var idx = voiceHold.lockedIdx >= 0 ? '[' + (voiceHold.lockedIdx + 1) + '] ' : '';
            // 🔒 보안(260913 윤비스 지시): 아두이노로 나가는 값({번호}{접두어})은
            //   화면에 절대 표시하지 않는다. 전송 성공/실패 여부만 사람이 읽는 문장으로 알린다.
            $('resultLabel').textContent = '🔒 ' + idx + voiceHold.lockedLabel;
            $('resultPct').textContent = Math.round(voiceHold.lockedPct * 100) + '%';
            $('resultTop').style.background = 'linear-gradient(135deg,' + classColor(voiceHold.lockedLabel) + ', #8B5CF6)';
            var row = el('div', 'ml-result-bar-row');
            row.appendChild(el('span', 'ml-result-bar-label', '🔒 ' + idx + voiceHold.lockedLabel + ' (확정)'));
            var track = el('div', 'ml-result-bar-track');
            var fill = el('div', 'ml-result-bar-fill');
            fill.style.width = Math.max(10, Math.round(voiceHold.lockedPct * 100)) + '%';
            fill.style.background = classColor(voiceHold.lockedLabel);
            track.appendChild(fill);
            row.appendChild(track);
            row.appendChild(el('span', 'ml-result-bar-pct', Math.round(voiceHold.lockedPct * 100) + '%'));
            box.appendChild(row);
            // ★ 전송 상태 표시 — 값은 숨기고 성공/실패만 알린다
            if (voiceHold.lockedIdx >= 0) {
                if (bleStudio) {
                    box.appendChild(el('div', 'ml-result-empty',
                        voiceHold.txState === 'fail'
                            ? '📡 아두이노 전송 실패 ⚠️ — 연결을 확인해 주세요'
                            : (voiceHold.txState === 'sending'
                                ? '📡 아두이노로 전송 중...'
                                : '📡 아두이노 전송 완료 ✅')));
                } else {
                    box.appendChild(el('div', 'ml-result-empty',
                        '🔗 BLE 연결하면 아두이노로 전송돼요'));
                }
            }
            box.appendChild(el('div', 'ml-result-empty', '다음 말이 나올 때까지 이 결과를 유지합니다.'));
        } else {
            $('resultLabel').textContent = '🎤 말씀해 주세요';
            $('resultPct').textContent = '';
            $('resultTop').style.background = 'linear-gradient(135deg,#6B7280,#9CA3AF)';
            box.appendChild(el('div', 'ml-result-empty', '말한 내용을 판별하면 결과를 고정해 드려요.'));
        }
    }

    function classColor(label) {
        for (var i = 0; i < classes.length; i++) if (classes[i].name === label) return classes[i].color;
        return '#4F5EF8';
    }

    /* ── BLE (Web Bluetooth) — 음성 확정 결과를 난독화 명령으로 전송 ──────
     * 확정된 클래스 번호 + 본사 설정 접두어(예: 1NubidaAi)를 NubidaBT로
     * 난독화한 뒤 1회 전송한다(같은 값 2초 내 재전송 금지). 수신 펌웨어는
     * 동일 KEY로 복호화 후 클래스 번호를 해석한다. (common/js/nubida-bt.js)
     * BLE 연결은 공용 모듈 NubidaBLE(common/js/nubida-ble.js) 사용.
     */
    // 2026-09-08: Web Serial → Web Bluetooth(BLE) 전환 — NubidaBLE 공용 모듈 사용
    var bleStudio = null;       // BLE 세션

    /* 🔒 보안(260913 윤비스 지시): 아두이노 통신값은 브라우저로 내려받지 않는다.
     *   기존: GET /ml/bt-prefix 로 접두어 평문('NubidaAi')을 받아
     *         브라우저에서 {번호}{접두어} 를 만들고 NubidaBT 로 난독화 → 전송.
     *         (개발자도구 Network 탭에서 통신값이 그대로 보였다)
     *   변경: 클래스 번호만 POST /ml/bt-command 로 보내고,
     *         서버가 접두어 결합 + 난독화를 마친 '프레임'만 받아 그대로 쓴다.
     *         → 브라우저·콘솔·네트워크 어디에도 접두어/평문이 등장하지 않는다.
     */
    async function btCommandFrame(classNo) {
        var r = await apiPost('/ml/bt-command', { class_no: classNo });
        if (!r || !r.data || !r.data.frame) throw new Error('전송 명령 생성 실패');
        return r.data.frame;
    }

    /* ★ [2026-09-14] 로그를 화면에 다시 표시한다.
     *   260913에는 "화면이 복잡하다"는 지시로 콘솔 전용으로 바꿨는데,
     *   그 결과 "값이 안 간다"의 원인(전송 보류/실패 사유)을 사용자가
     *   전혀 볼 수 없게 되었다. 진단이 불가능하므로 로그 박스를 부활한다.
     *   (콘솔 출력은 그대로 유지)
     *   스마트폰에서 확인·복사가 쉽도록 details 패널(기본 펼침)로 띄운다.
     */
    var studioCommRows = 0;
    var STUDIO_COMM_MAX = 120;          // ★ 렉 방지: 300 → 120 (DOM 노드 수 제한)
    var studioLogBuffer = [];           // ★ 렉 방지: 패널이 닫혀 있으면 DOM 대신 메모리에만 적재
    var STUDIO_LOG_MEM_MAX = 400;       //   메모리 로그 상한 (초과 시 오래된 것부터 폐기)
    /* ★ [2026-09-14] 성능 개선 근거:
     *   이전에는 통신 로그가 항상 화면에 떠 있었고 프레임마다 DOM 을 다시 그렸다.
     *   카메라 분류는 120ms 간격으로 로그를 만들기 때문에, 로그가 계속 쌓이면
     *   DOM 노드가 수백 개로 늘어 레이아웃/페인트 비용이 누적 → 화면 렉.
     *   해결: ① 패널이 닫혀 있으면 DOM 을 건드리지 않고 메모리 링버퍼에만 쌓는다.
     *         ② 펼치는 순간에만 한 번에 렌더한다.
     *         ③ DOM 최대 노드 120개 / 메모리 최대 400줄로 상한을 둔다.
     */
    function _studioLogRow(t, type) {
        var row = document.createElement('div');
        var cls = 'row';
        if (type === 'err') cls += ' err';
        else if (t.indexOf('📥') === 0) cls += ' rx';
        else if (t.indexOf('📤') === 0) cls += ' tx';
        else if (t.indexOf('✅') === 0 || t.indexOf('🧪') === 0) cls += ' tx';
        else if (type === 'info' || t.indexOf('ℹ️') === 0) cls += ' info';
        row.className = cls;
        var d = new Date();
        var ts = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2)
               + ':' + ('0' + d.getSeconds()).slice(-2);
        var span = document.createElement('span');
        span.className = 'ts';
        span.textContent = ts;
        row.appendChild(span);
        row.appendChild(document.createTextNode(t));
        return row;
    }
    function _studioLogPanelOpen() {
        var w = $('studioCommWrap');
        return !!(w && w.open);
    }
    function _studioLogFlush() {
        var body = $('studioCommLog');
        if (!body) return;
        body.innerHTML = '';
        var frag = document.createDocumentFragment();
        studioLogBuffer.forEach(function (it) { frag.appendChild(_studioLogRow(it.t, it.type)); });
        body.appendChild(frag);
        body.scrollTop = body.scrollHeight;
        var cnt = $('studioCommCount');
        if (cnt) cnt.textContent = '(' + studioCommRows + ')';
    }
    function logStudio(msg, type) {
        try { console.log('[ml-studio]', msg); } catch (e) {}
        try {
            var t = String(msg);
            studioCommRows++;
            // ① 메모리 링버퍼에 적재 (상한 초과 시 오래된 것부터 폐기 — 메모리 누수 방지)
            studioLogBuffer.push({ t: t, type: type });
            if (studioLogBuffer.length > STUDIO_LOG_MEM_MAX) {
                studioLogBuffer.splice(0, studioLogBuffer.length - STUDIO_LOG_MEM_MAX);
            }
            // ② 패널이 닫혀 있으면 DOM 을 건드리지 않는다 → 렉 없음
            if (!_studioLogPanelOpen()) return;
            var body = $('studioCommLog');
            if (!body) return;
            body.appendChild(_studioLogRow(t, type));
            while (body.childElementCount > STUDIO_COMM_MAX) body.removeChild(body.firstChild);
            body.scrollTop = body.scrollHeight;
            var cnt = $('studioCommCount');
            if (cnt) cnt.textContent = '(' + studioCommRows + ')';
        } catch (e2) {}
    }
    /* 패널을 펼칠 때만 한 번에 렌더 — 사용자가 <details> 를 토글하면 호출된다 */
    document.addEventListener('DOMContentLoaded', function () {
        var w = $('studioCommWrap');
        if (w) w.addEventListener('toggle', function () { if (w.open) _studioLogFlush(); });
    });
    window.clearStudioCommLog = function () {
        var body = $('studioCommLog');
        if (body) body.innerHTML = '';
        studioLogBuffer = [];
        studioCommRows = 0;
        var cnt = $('studioCommCount');
        if (cnt) cnt.textContent = '(0)';
    };
    window.copyStudioCommLog = function () {
        var txt = studioLogBuffer.map(function (it) {
            return it.t;
        }).join('\n');
        if (!txt) { var _b = $('studioCommLog'); if (_b) txt = _b.innerText || ''; }
        function fallback() {
            try {
                var ta = document.createElement('textarea');
                ta.value = txt;
                ta.setAttribute('readonly', '');
                ta.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:60vh;'
                    + 'z-index:99999;font:12px monospace;padding:10px;border:2px solid #4F5EF8;'
                    + 'border-radius:10px;background:#fff;color:#111;';
                document.body.appendChild(ta);
                ta.focus(); ta.select();
                try { document.execCommand('copy'); } catch (e2) {}
                var b = document.createElement('button');
                b.textContent = '닫기 (길게 눌러 직접 복사하세요)';
                b.style.cssText = 'position:fixed;left:10px;right:10px;bottom:12px;z-index:100000;'
                    + 'padding:12px;font-size:14px;font-weight:700;border:0;border-radius:10px;'
                    + 'background:#4F5EF8;color:#fff;';
                b.onclick = function () { ta.remove(); b.remove(); };
                document.body.appendChild(b);
                logStudio('📋 로그 창을 띄웠어요 — 길게 눌러 "전체 선택 → 복사" 해주세요', 'info');
            } catch (e3) {
                logStudio('📋 복사 실패 — 로그를 길게 눌러 직접 선택해 주세요', 'err');
            }
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(txt).then(function () {
                logStudio('📋 통신 로그를 복사했어요 (' + studioCommRows + '줄)', 'info');
            }).catch(fallback);
        } else {
            fallback();
        }
    };

    // ── BLE 연결 상태 UI ─────────────────────────
    //  260913 윤비스 지시: 아두이노 연결 박스를 [카메라 패널]·[음성 패널]·[하단 공용]
    //  3곳에 두고, 어느 박스에서 눌러도 동일하게 동작하도록 상태를 전부 동기화한다.
    var BLE_BOXES = [
        { box: 'serialBoxStudio',      st: 'serialStatusStudio',      btn: 'btnSerialStudio' },
        { box: 'serialBoxStudioCam',   st: 'serialStatusStudioCam',   btn: 'btnSerialStudioCam' },
        { box: 'serialBoxStudioAudio', st: 'serialStatusStudioAudio', btn: 'btnSerialStudioAudio' },
    ];

    function updateBleStudioStatus(kind, name) {
        BLE_BOXES.forEach(function (ids) {
            var st = $(ids.st), btn = $(ids.btn);
            if (kind === 'connected') {
                if (st) { st.textContent = '📡 BLE 연결됨: ' + (name || '장치'); st.className = 'ml-serial-status connected'; }
                if (btn) btn.textContent = '⛓️ 연결 해제';
            } else {
                if (st) { st.textContent = '📡 블루투스 미연결'; st.className = 'ml-serial-status'; }
            }
        });
        if (kind !== 'connected') updateBleStudioButtonLabel();
    }

    // 버튼 라벨 — 이미 연결됐으면 해제, 아니면 "연결 후 바로 분류"
    function updateBleStudioButtonLabel() {
        var label = bleStudio
            ? '⛓️ 연결 해제'
            : ((currentMode === 'audio')
                ? '🔗 아두이노 연결 (연결 후 바로 분류)'
                : '🔗 아두이노 연결 (연결 후 카메라 분류)');
        BLE_BOXES.forEach(function (ids) {
            var btn = $(ids.btn);
            if (btn) btn.textContent = label;
        });
    }

    function handleBleStudioClosed(reason) {
        bleStudio = null;
        updateBleStudioStatus('disconnected');
        logStudio(reason || '블루투스 연결 해제');
    }

    window.toggleSerialStudio = async function () {
        if (bleStudio) {
            try { await bleStudio.disconnect(); } catch (e) {}
            handleBleStudioClosed();
            return;
        }
        if (!window.NubidaBLE || !window.NubidaBLE.supported) {
            showAlert('이 브라우저는 Web Bluetooth를 지원하지 않아요.\nChrome 또는 Edge 브라우저(데스크톱/Android)를 사용해 주세요.', 'error');
            return;
        }
        try {
            bleStudio = await window.NubidaBLE.connect({
                onLine: function (line) { logStudio('📥 아두이노: ' + line, 'ok'); },
                onDisconnect: function () { handleBleStudioClosed('📡 블루투스 연결이 끊어졌어요. 다시 연결해 주세요.'); },
                // ★ 9차: "연결은 되는데 값이 안 간다" 진단 — 모듈이 제공하는 서비스와
                //   쓰기 후보 특성(write/notify 가능 여부)을 화면에 그대로 노출한다.
                //   AT-09 클론은 properties 를 거짓으로 광고하는 경우가 많아,
                //   쓰기 조합 탐색 실패의 원인이 이 한 줄로 드러난다.
                onDiag: function (msg) { logStudio('🔎 ' + msg, 'ok'); }
            });
            updateBleStudioStatus('connected', bleStudio.name);
            logStudio('✅ 블루투스(BLE) 연결 성공: ' + bleStudio.name);
            // ★ 7차: "아두이노 연결 버튼 하나로 바로 분류까지" — 연결 성공 시
            //   모델이 학습돼 있으면 자동으로 분류를 시작한다. 사용자가 페이지를
            //   옮겨 다니지 않고 이 화면에서 바로 말해 서보를 움직일 수 있다.
            //   · 모드는 그대로 둔다 — 음성이면 음성, 카메라(이미지)면 카메라로 바로 분류.
            //     (기존: 무조건 음성 모드로 전환 → 카메라 사용자가 음성으로 튕겼다)
            //   · 이미 분류 중이면 그대로 둔다 (중복 시작 금지)
            if (!trained || !headModel) {
                logStudio('⚠️ 학습된 모델이 없어 분류를 시작하지 못했습니다. 먼저 [⚙️ 모델 학습 시작]을 눌러주세요.', 'err');
            } else {
                try {
                    if (!classifying) await window.startClassify();
                    logStudio((currentMode === 'audio')
                        ? '🎯 분류 준비 완료 — 이제 말하면 아두이노로 전송됩니다.'
                        : '🎯 분류 준비 완료 — 카메라가 인식하면 아두이노로 전송됩니다.', 'ok');
                } catch (e2) {
                    logStudio('분류 자동 시작 실패(수동으로 [🎯 분류 시작] 눌러주세요): ' + (e2 && e2.message), 'err');
                }
            }
        } catch (e) {
            logStudio('블루투스 연결 실패/취소: ' + e.message, 'err');
            bleStudio = null;
            updateBleStudioStatus('disconnected');
        }
    };

    async function closeSerialStudio() {
        try { if (bleStudio) { await bleStudio.disconnect(); } } catch (e) {}
        bleStudio = null;
        updateBleStudioStatus('disconnected');
    }

    // 확정된 결과만 {클래스번호}{접두어} → NubidaBT 난독화 후 1회 전송
    // ★ [2026-09-13 BLE 교착 수정] BLE writeLine 은 confirmed 조합을 못 찾으면 후보×방식
    //   전수 시도로 수 초~수십 초를 잡아먹는다. 그 사이 classifyTimer(120ms) 가 계속 쌓여
    //   음성 분류가 통째로 멈춘다("블루투스 연결하면 인식이 안 된다"의 원인).
    //   → (1) 동시 실행 금지, (2) 전송은 분류 루프 밖에서, (3) 실패해도 분류는 계속.
    var sendingHeld = false;     // 전송 중 재진입 차단
    async function sendHeldValue() {
        // ★ 9차: "값이 안 간다"를 조용히 삼키지 않는다 — 어느 조건에서 멈췄는지 로그로 남긴다.
        if (!bleStudio) { logStudio('⏸ 전송 보류 — BLE 미연결 (🔗 아두이노 연결을 눌러주세요)', 'err'); return; }
        if (voiceHold.lockedIdx < 0) { logStudio('⏸ 전송 보류 — 확정된 클래스 없음(lockedIdx=-1)', 'err'); return; }
        if (sendingHeld) { logStudio('⏸ 전송 보류 — 이전 전송이 아직 진행 중', 'err'); return; }
        var classNo = voiceHold.lockedIdx + 1;
        var now = Date.now();
        // ★ 5차: 중복 차단 2초 → 1초로 완화. 같은 값을 연속으로 말해도
        //   "안 된다"고 느끼지 않도록(사람은 1초 안에 두 번 말하지 않는다).
        if (classNo === voiceHold.lastSentValue && now - voiceHold.lastSentAt < 1000) {
            // ★ [2026-09-14] 정상 동작이므로 '오류(빨강)' 가 아니라 정보로 낮춘다.
            //   1초 내 재전송 차단은 의도된 동작인데 err 로 찍혀 사용자가 고장으로 오해했다.
            logStudio('⏸ 전송 보류 — 같은 값 1초 내 재전송 (정상 동작)', 'info');
            return;
        }
        voiceHold.lastSentValue = classNo; voiceHold.lastSentAt = now;
        sendingHeld = true;
        voiceHold.txState = 'sending';
        // ★ 5차: sendingHeld 고착 방지 — BLE 쓰기가 응답 없이 매달리면 이후 모든
        //   전송이 영구 차단된다("1NubidaAi 가 안 뜬다"의 원인). 3초 강제 해제.
        if (voiceHold._txWatchdog) clearTimeout(voiceHold._txWatchdog);
        voiceHold._txWatchdog = setTimeout(function () {
            if (sendingHeld) {
                sendingHeld = false;
                voiceHold.txState = 'fail';
                logStudio('⚠️ BLE 쓰기 응답 없음 — 전송 잠금을 강제 해제했습니다(다음 전송 허용)', 'err');
                renderHoldState();
            }
        }, 3000);
        // ★ await 하지 않는다 — 분류 루프(runClassifyOnce)를 여기서 붙잡으면 안 된다.
        //   BLE 쓰기는 백그라운드로 흘려보내고 실패해도 로그만 남긴다.
        // 🔒 서버가 난독화한 프레임을 받아 그대로 전송한다 (브라우저에 평문 없음).
        Promise.resolve().then(function () {
            return btCommandFrame(classNo);
        }).then(function (frame) {
            return bleStudio.writeLine(frame).then(function () {
                voiceHold.txState = 'ok';
                logStudio('📤 아두이노 전송 완료');
                renderHoldState();
            }).catch(function (e) {
                voiceHold.txState = 'fail';
                logStudio('전송 실패: ' + ((e && e.message) || e), 'err');
                renderHoldState();
                // ★ 9차: 전송 실패는 화면에서도 크게 알린다 — 로그를 안 보는 사용자도
                //   "인식은 되는데 아두이노가 안 움직인다"의 원인을 바로 알 수 있게.
                var emsg = (e && e.message) || String(e);
                showAlert('⚠️ 아두이노 전송 실패: ' + emsg +
                    '\n\n· BLE 연결 상태를 확인하고 다시 시도해 주세요.' +
                    '\n· 계속 실패하면 [⛓️ 연결 해제] 후 재연결해 주세요.', 'error');
            });
        }).catch(function (e) {
            // 명령 생성(서버) 실패 — 화면에는 값 없이 안내만
            voiceHold.txState = 'fail';
            logStudio('전송 명령 생성 실패: ' + ((e && e.message) || e), 'err');
            renderHoldState();
        }).then(function () { sendingHeld = false; clearTimeout(voiceHold._txWatchdog); },
                function () { sendingHeld = false; clearTimeout(voiceHold._txWatchdog); });
    }

    /* ── 모델 저장/다운로드 ─────────────────────── */

    // ── 서버 저장 코어 (학습 완료 자동 저장 + 버튼 공용) ──
    //  returns: true=성공, false=실패 (실패 사유는 showAlert로 노출)
    async function saveModelToServerCore(silent) {
        if (!headModel) {
            if (!silent) showAlert('저장할 모델이 없어요. 먼저 [모델 학습 시작]을 눌러 주세요.', 'error');
            return false;
        }
        var btn = document.querySelector('button[onclick="saveModelToServer()"]');
        var oldLabel = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = '💾 저장 중...'; }
        try {
            if (!silent) showAlert('모델을 서버에 저장하는 중...', 'info');
            var saved = false;
            await headModel.save(tf.io.withSaveHandler(async function (artifacts) {
                var modelJson = JSON.stringify({
                    format: 'layers-model',
                    generatedBy: 'TensorFlow.js',
                    convertedBy: 'NubidaMachine',
                    modelTopology: artifacts.modelTopology,
                    // TF.js 로드 호환 weightsManifest — {paths, weights} 묶음 필수
                    weightsManifest: [{ paths: ['model.weights.bin'], weights: artifacts.weightSpecs }],
                });
                var b64 = arrayBufferToBase64(artifacts.weightData);
                var fd = new FormData();
                fd.append('model_json', modelJson);
                fd.append('weights_b64', b64);
                fd.append('labels', JSON.stringify(classLabels));
                fd.append('model_type', currentModeDef.modelType);
                var res = await fetch(API_BASE + '/ml/projects/' + projectId + '/model', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token() },
                    body: fd,
                });
                if (!res.ok) {
                    // 서버 응답 본문(detail)까지 노출 — 404/500 원인 파악용
                    var detail = 'HTTP ' + res.status;
                    try { detail = (await res.json()).detail || detail; } catch (e0) {}
                    throw new Error(detail);
                }
                saved = true;
                return { modelArtifactsInfo: { dateSaved: new Date(), modelTopologyType: 'JSON' } };
            }));
            if (saved) {
                showAlert('✅ 모델이 서버에 저장됐어요! 이제 아두이노 연동이 가능해요.', 'success');
                // ★ 10차: 저장 성공 → 수동 저장 버튼(재시도)은 숨긴다.
                var _mb = document.getElementById('btnSaveModelManual');
                if (_mb) _mb.style.display = 'none';
                return true;
            }
            return false;
        } catch (e) {
            showAlert('모델 저장 실패: ' + (e.message || '알 수 없는 오류'), 'error');
            // ★ 10차: 저장 실패 → 수동 재시도 버튼을 노출한다.
            var _mb2 = document.getElementById('btnSaveModelManual');
            if (_mb2) _mb2.style.display = '';
            return false;
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = oldLabel || '💾 모델 저장'; }
        }
    }

    window.saveModelToServer = async function () {
        await saveModelToServerCore(false);
    };

    window.downloadModel = async function () {
        if (!headModel) return;
        try {
            await headModel.save(tf.io.withSaveHandler(async function (artifacts) {
                var modelJson = JSON.stringify({
                    format: 'layers-model',
                    generatedBy: 'TensorFlow.js',
                    convertedBy: 'NubidaMachine',
                    modelTopology: artifacts.modelTopology,
                    // TF.js 로드 호환 weightsManifest — {paths, weights} 묶음 필수
                    weightsManifest: [{ paths: ['model.weights.bin'], weights: artifacts.weightSpecs }],
                });
                var blob = new Blob([modelJson], { type: 'application/json' });
                triggerDownload(blob, 'nubida-machine-model.json');
                triggerDownload(new Blob([artifacts.weightData]), 'nubida-machine-model.weights.bin');
                var labelsBlob = new Blob([JSON.stringify(classLabels, null, 2)], { type: 'application/json' });
                triggerDownload(labelsBlob, 'nubida-machine-labels.json');
                showAlert('모델 파일을 다운로드했어요! ⬇️');
                return { modelArtifactsInfo: { dateSaved: new Date(), modelTopologyType: 'JSON' } };
            }));
        } catch (e) {
            showAlert(e.message || '다운로드 실패', 'error');
        }
    };

    function triggerDownload(blob, filename) {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }

    function arrayBufferToBase64(buffer) {
        var bytes = new Uint8Array(buffer);
        var chunk = 0x8000, bin = '';
        for (var i = 0; i < bytes.length; i += chunk) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return btoa(bin);
    }

    /* ── 성능 모드 — 저사양 고정 (선택 UI 제거됨 / 260913) ───── */

    // UI 는 제거됐지만 과거 북마크·캐시된 HTML 이 호출할 수 있어 함수는 남겨둔다.
    //  어떤 값을 넘겨도 "저사양"으로 동작한다.
    window.setPerfMode = function (mode) {
        showAlert('성능은 저사양으로 고정되어 있어요.');
    };
    window.getPerfMode = function () { return 'low'; };

    /* ── 초기화 ───────────────────────────────── */

    document.addEventListener('DOMContentLoaded', function () {
        // 성능 옵션 UI 는 제거됨 (저사양 고정) — 토글 표시 코드 불필요
        // 학생 권한 확인 (pages-student.js가 requireAuth 처리)
        if (window.location.protocol === 'http:' && window.location.hostname !== '127.0.0.1' && window.location.hostname !== 'localhost') {
            // HTTPS 강제는 nginx가 처리 — 여기선 생략
        }
        loadProjects().catch(function (e) {
            showAlert(e.message || '프로젝트 목록을 불러오지 못했어요.', 'error');
        });
        // 🔒 보안(260913): 접두어 조회(loadBtPrefix) 제거 — 통신값은 서버에서만 결합/난독화한다.
        window.addEventListener('beforeunload', function () {
            stopCamera();
            audioSource.stop();
            stopClassify();
            closeSerialStudio();
        });
    });

    // ── 음성 모드 전역 컨트롤 (HTML onclick) ──

    // 🎙️ 마이크 시작/끄기 토글
    window.toggleMic = async function () {
        if (audioSource.active) { audioSource.stop(); return; }
        try {
            await audioSource.start();
        } catch (e) {
            showAlert(e.message || '마이크를 켜지 못했어요. 브라우저 권한을 확인해 주세요.', 'error');
        }
    };

    // ▶️ 마지막 녹음 재생 (MediaRecorder blob)
    window.playLastRecording = function () {
        var src = audioSource.recUrl;
        if (!src) { showAlert('아직 재생할 녹음이 없어요. [🔴 1초 녹음]을 먼저 해주세요.', 'error'); return; }
        var a = $('audioPlayer');
        if (!a) { a = document.createElement('audio'); a.id = 'audioPlayer'; document.body.appendChild(a); }
        a.src = src;
        a.play().catch(function () { /* autoplay 정책 등 — 무시 */ });
    };

    // 디버그 상태 노출 (콘솔 디버깅용 — 실서버에도 무해)
    window.__mlDebug = function () {
        return {
            mode: currentMode,
            modeLabel: currentModeDef.label,
            perfMode: perfKey,
            imgSize: IMG_SIZE,
            fftSize: perf.fftSize,
            specFrames: SPEC_FRAMES,
            specMaxBin: SPEC_MAX_BIN,
            mobilenetUrl: MOBILENET_URL,
            stream: !!stream,
            headModel: !!headModel,
            truncModel: !!truncModel,
            mobilenet: !!mobilenet,
            trained: trained,
            classifying: classifying,
            classifyTimer: !!classifyTimer,
            classes: classes.length,
            labels: classLabels,
            projectId: projectId,
            audioActive: audioSource.active,
            audioFrames: audioSource.specFrames.length,
            // 실제 모델 참조 (직접 추론 검증용)
            head: headModel,
            trunc: truncModel,
            mnet: mobilenet,
            cls: classes,
            audioRecUrl: !!audioSource.recUrl,
        };
    };

    // ── WAV 파일 기반 검증 드라이버 (마이크 없는 E2E/다중 화자 실측용) ─────
    // 실제 마이크 수집과 동일한 변환 규칙을 그대로 사용한다:
    //   fftSize/smoothing = 마이크 AnalyserNode 동일 → 실시간 재생하며 60Hz 캡처
    //   centerWindow + specCanvasFromFrames → 224×224 (학습 샘플·분류 확정 경로와 동일)
    // addSample() 경유 → 서버 업로드·클래스 샘플 적재까지 기존 파이프라인 그대로.
    window.__mlTest = {
        // WAV URL → 129프레임(≈3초 규칙) 정렬용 원본 프레임 배열
        framesFromUrl: async function (url, maxSec) {
            var res = await fetch(url);
            if (!res.ok) throw new Error('fetch 실패: HTTP ' + res.status);
            var ab = await res.arrayBuffer();
            var AC = window.AudioContext || window.webkitAudioContext;
            var ctx = new AC();
            if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) {} }
            var audioBuf;
            try { audioBuf = await ctx.decodeAudioData(ab); }
            catch (e) { throw new Error('decodeAudioData 실패: ' + e.message + ' — 44100Hz PCM WAV 필요'); }
            var src = ctx.createBufferSource();
            src.buffer = audioBuf;
            var an = ctx.createAnalyser();
            an.fftSize = perf.fftSize;
            an.smoothingTimeConstant = 0.35;
            src.connect(an);                       // 분석만 (스피커 출력 없음)
            var freqArr = new Uint8Array(an.frequencyBinCount);
            var frames = [];
            var ended = false;
            src.onended = function () { ended = true; };
            var nextT = ctx.currentTime;
            src.start();
            var maxMs = (maxSec || 15) * 1000;
            var t0 = Date.now();
            while (!ended) {
                if (ctx.currentTime >= nextT) {
                    an.getByteFrequencyData(freqArr);
                    frames.push(freqArr.slice());
                    nextT += 1 / 60;               // rAF ≈60Hz와 동일 캡처 간격
                }
                if (Date.now() - t0 > maxMs) { try { src.stop(); } catch (e) {} break; }
                await new Promise(function (r) { setTimeout(r, 5); });
            }
            ctx.close().catch(function () {});
            return { frames: frames, duration: audioBuf.duration };
        },

        // 1) WAV → 현재 선택 클래스에 학습 샘플 추가 (기존 addSample 경로)
        addSampleFromWav: async function (url) {
            if (!classes.length || selectedIdx === null) throw new Error('클래스를 먼저 선택하세요');
            var clsName = classes[selectedIdx].name;
            var r = await this.framesFromUrl(url);
            if (r.frames.length < 10) throw new Error('프레임 부족(' + r.frames.length + ') — 파일이 무음이거나 너무 짧음');
            var aligned = centerWindow(r.frames);
            var c = specCanvasFromFrames(aligned);
            addSample(c, true, 'audio');
            return { added: true, cls: clsName, url: url, durSec: +r.duration.toFixed(2), frames: r.frames.length };
        },

        // 2) WAV → 학습 모델 분류 (centerWindow 경로 = 음성 실시간 확정과 동일)
        classifyWav: async function (url) {
            if (!trained || !headModel) throw new Error('모델 미학습 (trainModel 먼저)');
            if (!truncModel) await ensureMobileNet();
            var r = await this.framesFromUrl(url);
            if (r.frames.length < 10) throw new Error('프레임 부족(' + r.frames.length + ')');
            var aligned = centerWindow(r.frames);
            var c = specCanvasFromFrames(aligned);
            /* ★★★ [2026-09-16] 텐서 누수 완전 해결 — tf.tidy() (WAV 파일 분류 경로) */
            var tensor = tf.tidy(function () {
                return tf.browser.fromPixels(c).toFloat().div(255).expandDims(0);
            });
            var feats = truncModel.predict(tensor);
            var preds = headModel.predict(feats);
            var probs = await preds.data();
            tensor.dispose(); feats.dispose(); preds.dispose();
            var rows = classLabels.map(function (label, i) { return { label: label, prob: probs[i] }; })
                .sort(function (a, b) { return b.prob - a.prob; });
            return rows;
        },

        // [MFCC 파일럿] 3) WAV URL → 16kHz PCM (mfccDecodeToPcm16k — WAV 파서 + 리샘플 포함)
        pcmFromUrl: async function (url) {
            var res = await fetch(url);
            if (!res.ok) throw new Error('fetch 실패: HTTP ' + res.status);
            var ab = await res.arrayBuffer();
            var pcm16 = await mfccDecodeToPcm16k(ab);
            return { pcm16: pcm16, durSec: pcm16.length / MFCC_SR };
        },

        // [MFCC 파일럿] 4) WAV → MFCC 학습 샘플 추가 (현재 선택 클래스, 로컬 세션 전용)
        addMfccSampleFromWav: async function (url) {
            if (!classes.length || selectedIdx === null) throw new Error('클래스를 먼저 선택하세요');
            var clsName = classes[selectedIdx].name;
            var r = await this.pcmFromUrl(url);
            var win = mfccCenterUtterance(r.pcm16);
            if (win.length < MFCC_FFT) throw new Error('PCM 부족(' + win.length + ') — 파일이 무음이거나 너무 짧음');
            // 표시용 썸네일: MFCC 정렬 창 → 스펙트로그램 프레임 → 224 캔버스 (학습에는 win만 사용)
            var disp = mfccSpecFramesForDisplay(win);
            var c = specCanvasFromFrames(centerWindow(disp));
            addSample(c, true, 'audio', win);
            return { added: true, cls: clsName, url: url, durSec: +r.durSec.toFixed(2), winSec: +(win.length / MFCC_SR).toFixed(2) };
        },

        // [MFCC 파일럿] 5) WAV → MFCC 모델 분류 (centerUtterance 정렬 = 마이크 확정과 동일)
        classifyWavMfcc: async function (url) {
            if (!trained || !headModel) throw new Error('모델 미학습 (MFCC 모드에서 trainModel 먼저)');
            var r = await this.pcmFromUrl(url);
            if (r.pcm16.length < MFCC_FFT) throw new Error('PCM 부족(' + r.pcm16.length + ') — 파일이 무음이거나 너무 짧음');
            var win = mfccCenterUtterance(r.pcm16);
            if (win.length < MFCC_FFT) throw new Error('centerUtterance 창 부족');
            var m = mfccComputeFromPcm16k(win);
            var t = tf.tensor3d(m, [1, MFCC_MAX_FRAMES, MFCC_DIM]);   // m은 flat Float32Array(150×26)
            var preds = headModel.predict(t);
            var probs = await preds.data();
            t.dispose(); preds.dispose();
            var rows = classLabels.map(function (label, i) { return { label: label, prob: probs[i] }; })
                .sort(function (a, b) { return b.prob - a.prob; });
            return rows;
        },
    };
})();
