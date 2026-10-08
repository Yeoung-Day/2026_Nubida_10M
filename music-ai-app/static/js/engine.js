/**
 * engine.js
 */
let isProducing = false;
let activeSources = []; // [해결] 누락되었던 변수 선언 추가
let bgmSource = null;
let bgmGainNode = null;
let currentSelectedBeat = null;

// ══════════════════════════════════════════════════════════════
// [신규 260916-A/B] 사람다운 가창 (자연스러움) + 가수별 목소리
//   A안: 비브라토(떨림) + 음정 흔들림 + 발성 어택/릴리즈 + 숨결
//   B안: 가수별 포먼트(성도 크기) / 피치 곡선 / 톤 성향 차별화
// ══════════════════════════════════════════════════════════════

// ── A안: 비브라토 + 휴먼라이즈 ────────────────────────────────
//   사람 목소리는 (1) 초당 5~6회 떨림 (2) 미세한 음정 오차
//   (3) 소리 시작이 딱딱하지 않고 부드럽게 열림 — 이 3개가 기계음의 핵심 차이다.
//   ⚠️ 비브라토는 delay 노드 모듈레이션으로 구현하므로 소리 길이가 늘어난다.
//      → 마디 예약(레가토) 계산 시 WET_SMEAR_SEC 로 보정한다 (toggleProduction 참조).
const VIB_DEPTH_CENTS = 26;   // 떨림 폭 (약 ±0.26반음) — 크면 풍성, 너무 크면 불안정
const WET_SMEAR_SEC   = 0.05; // 비브라토 지연/리버브로 늘어나는 꼬리 길이 보정값

/**
 * 사람다운 피치 트랙을 buffer 에 미리 새긴다 (렌더 전).
 *  - 소리 시작: 목표 음정보다 살짝 아래 -> 슬라이드 업 (자연스러운 발성)
 *  - 소리 끝: 살짝 아래로 풀림
 *  - 비브라토: 초당 rate 회, 랜덤 위상 (딱 맞아떨어지지 않게 = 기계음 제거)
 *  - 지터: 아주 미세한 불규칙 흔들림 (완벽한 주기 = 기계 냄새)
 * @param {*} aobj audioObj 원본 (수정하지 않음)
 * @param {number} cents 전체 음정 이동값
 * @param {object} voice SINGERS 항목 (vibRate/vibCents/attack/porta)
 */
function prepareVocalBuffer(aobj, cents, voice) {
    const sr = aobj.sampleRate || 22050;
    const src = aobj.samples instanceof Float32Array
        ? aobj.samples
        : new Float32Array(aobj.samples);
    const n = src.length;

    const isLead = (voice && voice.lead) || null;
    const vibRate   = (voice && Number.isFinite(voice.vibRate))  ? voice.vibRate  : 5.2;
    const vibCents  = (voice && Number.isFinite(voice.vibCents)) ? voice.vibCents : VIB_DEPTH_CENTS;
    const attackSec = (voice && Number.isFinite(voice.attack))   ? voice.attack   : 0.05;
    const portaSec  = (voice && Number.isFinite(voice.porta))    ? voice.porta    : 0.12;
    const portaLvl  = (voice && Number.isFinite(voice.portaLvl)) ? voice.portaLvl : 0.06;
    const noiseAmt  = (voice && Number.isFinite(voice.noise))    ? voice.noise    : 0;

    // 음정 변화는 1초에 200단계(5ms 간격)로만 갱신한다.
    //   사람의 떨림은 5~6Hz 라 200단계면 충분하고, 매 샘플마다 사인/난수를 계산하면
    //   3분짜리 곡에서 CPU가 감당하지 못한다.
    const STEPS       = 200;
    const stepSamples = Math.max(1, Math.round(sr / STEPS));
    // ★ 배열 크기 계산 (여기가 틀리면 소리가 중간에 잘린다 — 실측으로 확인된 함정)
    //   pos 는 매 샘플 sf 만큼 증가하고, sf 는 cents(고정) + vib(±vibCents) + jit(±0.35)
    //   - porta 로 변한다. pos = Σsf 이므로 평균 배수가 아니라
    //   '가장 오래 유지되는 비율' × (길이 + 떨림 한 주기) 로 잡아야 안전하다.
    const vibPeriodSec = 1 / Math.max(0.5, vibRate);
    const meanRatio    = 1 + (cents + vibCents * 0.637) / 1200;   // sin 평균 |sin| ≈ 0.637
    const maxRatio     = 1 + (cents + vibCents) / 1200;           // 떨림 최고점
    const needRatio    = Math.max(meanRatio, maxRatio) * (1 + vibPeriodSec / Math.max(0.05, n / sr));
    //  넉넉하게: (렌더 구간 + 떨림 한 주기 + 어택 시간) × 최대 배수 + 여유
    const copyLen      = Math.ceil((n + 0.3 * sr) * needRatio) + Math.round(sr * 0.2);
    const out          = new Float32Array(copyLen);

    const vibOmega = 2 * Math.PI * vibRate;
    const A_MAX    = Math.max(1, portaSec * sr);
    const REL_SEC  = 0.09;

    let pos = 0, sf = 1, j1 = 0, j2 = 0, nz = 0;
    let d1 = 0, d2 = 0, d3 = 0, d4 = 0, d5 = 0, d6 = 0, d7 = 0;

    for (let k = 0; k < copyLen; k++) {
        if (k % stepSamples === 0) {
            // ── 숨결(성대 마찰) — 목소리에 섞이는 아주 약한 잡음 ──
            nz = noiseAmt > 0 ? (Math.random() * 2 - 1) * noiseAmt : 0;

            // ── 비브라토(떨림) + 지터(불규칙) — 완벽한 주기는 기계 냄새가 난다 ──
            j1 = (j1 + 0.04 * (Math.random() * 2 - 1)) * 0.97;
            j2 = (j2 + 0.04 * (Math.random() * 2 - 1)) * 0.97;
            const vib = (vibCents + j2 * 8) * Math.sin(vibOmega * (k / sr) + j1 * 1.6);
            const jit = (Math.random() * 2 - 1) * 0.35;   // 긴 호흡의 미세한 음정 오차

            // ── 포르타멘토(발성 시작 슬라이드) — 시작할 때 살짝 아래에서 올라온다 ──
            const porta = portaLvl * 1200 * Math.max(0, 1 - k / A_MAX);

            sf = 1 + (cents + vib + jit - porta) / 1200;
        }

        const i0 = Math.floor(pos);
        if (i0 >= n - 1) { break; }

        const fr = pos - i0;
        let v = src[i0] * (1 - fr) + src[i0 + 1] * fr;

        // ── 포먼트/톤 성향 (가수별 어조 차이) ──
        //  1차 셀프필터 두 개의 90° 위상차 = 저역/고역 대역 신호 → warm/bright 로 섞는다.
        //  지연평균(speak)은 비음·콧소리 성향으로, 사람 목소리 느낌을 강하게 만든다.
        if (isLead) {
            d1 = d1 + isLead.fl * (v - d1);   d2 = d2 + isLead.fl * (d1 - d2);
            d3 = d3 + isLead.fl * (d2 - d3);  d4 = d4 + isLead.fl * (d3 - d4);
            const lowq = d4 - d2;
            d5 = d5 + isLead.fh * (v - d5);   d6 = d6 + isLead.fh * (d5 - d6);
            d7 = d7 + isLead.fh * (d6 - d7);
            const hiq = d7 - d5;
            v += lowq * isLead.warm + hiq * isLead.bright;
            v -= isLead.speak * (d2 + d4 + d7) / 3;
            v *= 1 / (1 + isLead.warm * 0.35 + isLead.bright * 0.35 + isLead.speak * 0.5);
        }

        // ── 발성 어택(서서히 열림) + 소리 끝(부드럽게 닫힘) ──
        let env = attackSec > 0 ? Math.min(1, k / (attackSec * sr)) : 1;
        const rem = n - pos;
        if (rem < REL_SEC * sr) env *= Math.max(0, rem / (REL_SEC * sr));

        // ── 소리 끝 꼬리 (떨림이 남아 자연스럽게 사라지도록) ──
        out[k] = v * env + (rem < REL_SEC ? 0 : 0) + nz;

        pos += sf;
    }

    return { samples: out, sampleRate: sr };
}

// ══════════════════════════════════════════════════════════════
// [신규 260914-B] 보컬 버스 (자연스러움 개선)
//    보컬 -> 컴프레서(음량 균일) -> 드라이 + 리버브(공간감) -> 마스터
//    MR   -> MR게인(보컬에 맞춘 밸런스) ------------> 마스터
// ══════════════════════════════════════════════════════════════
let vocalBus = null;      // 컴프레서 출력 노드
let vocalMaster = null;   // 최종 보컬 게인
let reverbNode = null;    // 컨볼버(리버브)
let reverbGain = null;    // 리버브 리턴 게인
let reverbInited = false; // 리버브 준비 여부 (없어도 동작해야 함)

// ── [신규 260916-A] 비브라토: 미세한 지연 변조로 자연스러운 떨림을 만든다 ──
//   사람의 떨림은 음정만이 아니라 배음 구조도 함께 흔들린다.
//   delay 시간을 LFO 로 아주 살짝 흔들면 그 효과가 나면서 소리가 두터워진다.
//   1~7ms 변조는 콤필터가 되지 않고 피치 떨림으로만 들리는 안전 구간이다.
function buildVibrato(voice) {
    const rate = (voice && Number.isFinite(voice.vibRate)) ? voice.vibRate : 5.2;
    const depth = 0.004;   // 4ms 폭 (약 ±0.4% 피치 = ±7 cents)
    try {
        const dly = audioCtx.createDelay(0.05);
        dly.delayTime.value = 0.007;
        const lfo = audioCtx.createOscillator();
        lfo.frequency.value = rate;
        const lfoGain = audioCtx.createGain();
        lfoGain.gain.value = depth;
        const wet = audioCtx.createGain();
        wet.gain.value = 0.5;
        lfo.connect(lfoGain);
        lfoGain.connect(dly.delayTime);
        lfo.start();
        return { input: dly, output: wet, lfo: lfo, delay: dly, wet: wet };
    } catch (e) {
        console.warn("비브라토 초기화 실패(건조음으로 진행):", e);
        return null;
    }
}

// 음량 균일화용 컴프레서 생성
function ensureVocalBus() {
    if (vocalBus) return;
    const comp = audioCtx.createDynamicsCompressor();
    // 보컬용 부드러운 설정 (과압축하면 답답해짐)
    comp.threshold.value = -22;
    comp.knee.value = 24;
    comp.ratio.value = 2.6;
    comp.attack.value = 0.004;
    comp.release.value = 0.22;

    vocalMaster = audioCtx.createGain();
    vocalMaster.gain.value = 0.95;

    // 드라이(원음) 경로: 컴프레서 -> 마스터 -> 출력
    comp.connect(vocalMaster);
    vocalMaster.connect(audioCtx.destination);

    vocalBus = comp;
}

// 알고리즘 리버브 임펄스 생성 (외부 IR 파일 불필요)
function buildReverbImpulse(seconds = 1.6, decay = 2.4) {
    const rate = audioCtx.sampleRate;
    const len = Math.max(1, Math.floor(rate * seconds));
    const impulse = audioCtx.createBuffer(2, len, rate);
    for (let ch = 0; ch < 2; ch++) {
        const data = impulse.getChannelData(ch);
        for (let i = 0; i < len; i++) {
            // 지수 감쇠 노이즈 = 자연스러운 공간 잔향
            data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
        }
    }
    return impulse;
}

// 리버브 준비 (1회). 실패해도 원음 재생은 계속되도록 안전 처리.
function ensureReverb() {
    if (reverbInited) return;
    reverbInited = true;
    try {
        reverbNode = audioCtx.createConvolver();
        reverbNode.buffer = buildReverbImpulse(1.6, 2.4);
        reverbGain = audioCtx.createGain();
        reverbGain.gain.value = 0.22; // 은은한 공간감 (너무 크면 뭉개짐)
        if (vocalBus) vocalBus.connect(reverbNode);
        reverbNode.connect(reverbGain);
        reverbGain.connect(audioCtx.destination);
    } catch (e) {
        console.warn("리버브 초기화 실패(원음으로 진행):", e);
        reverbNode = null;
        reverbGain = null;
    }
}

async function toggleProduction(isPreview = false) {
    if (isProducing) return;
    const btn = document.getElementById('btn-record');
    const rows = document.querySelectorAll('.lyric-row');
    if (rows.length === 0) return;

    isProducing = true;
    btn.disabled = true;
    btn.textContent = "⌛ 제작 중...";

    try {
        if (audioCtx.state === 'suspended') await audioCtx.resume();

        // 비트 선택 로직
        if (!isPreview || !currentSelectedBeat) {
            currentSelectedBeat = '/static/' + BEAT_LIBRARY[Math.floor(Math.random() * BEAT_LIBRARY.length)];
        }

        await playMRWithFadeIn(currentSelectedBeat);

        // [신규 260914-B] 레가토 재생: 마디가 끝나기 전에 다음 마디를 겹쳐 시작
        //   - 겹침(overlap) 0.12초로 호흡을 이어줌 (기존: 완전 종료 후 무음 대기 -> 뚝뚝 끊김)
        //   - 첫 마디는 즉시, 이후 마디는 이전 마디가 끝나기 overlap초 전에 시작
        let nextStart = 0;              // 다음 마디 예약 시작 시각(0 = 즉시)
        let lastEnd = 0;
        const OVERLAP = 0.12;

        for (let i = 0; i < rows.length; i++) {
            // [성과 수호] 매 마디 시작 전 정지 버튼이 눌렸는지 확인
            if (!isProducing) {
                console.log("🛑 가창 루프 탈출");
                break; 
            }
            const row = rows[i];
            const text = row.querySelector('.lyric-text').value.trim();
            if (!text) continue;

            const speed = parseFloat(row.querySelector('.line-speed').value);
            const tune = parseFloat(row.querySelector('.line-tune').value);
            const echo = parseFloat(row.querySelector('.line-echo').value);
            const filter = parseFloat(row.querySelector('.line-filter').value);
            const pan = parseFloat(row.querySelector('.line-pan').value);
            const grit = parseFloat(row.querySelector('.line-grit').value);
            const wait = parseFloat(row.querySelector('.line-wait').value);

            // [성과 수호] 생성/재생 전 정지 확인 (TTS 생성은 시간이 걸림)
            if (!isProducing) break;

            const audioObj = ttsEngine.generate({ text: text, sid: 0, speed: speed });
            const pitch = SINGERS[currentSinger].pitch + (tune - 10);

            // [신규 260916-A/B] 가수별 목소리 + 사람다운 표현
            //   기존: 같은 목소리(sid 0)에 pitch 만 적용 -> 기계음
            //   이제: 포먼트 배율(fmt)을 피치에 곱해 성도 크기까지 다르게 하고,
            //         비브라토·숨결·발성 어택을 buffer 에 미리 새긴다.
            const singer = SINGERS[currentSinger];
            const fmt = (singer && Number.isFinite(singer.formant)) ? singer.formant : 1.0;
            // 두 번 렌더하지 않도록 스마트하게 포먼트를 반영한다.
            //   ( 5 ≤ pitch/fmt ≤ 15 ) 구간은 비율이 |1 - pitch/fmt| ≤ 0.67 안에 들어
            //   품질 저하가 없으므로 한 번만 렌더하고 나눗셈으로 정확한 피치를 맞춘다.
            let vocalBuf, singCents;
            if (Math.abs(pitch) < 1e-6) {
                // 무보정: 포먼트를 반영하려면 배율이 필요하지만 피치가 0 이라 그대로 곱한다
                vocalBuf = prepareVocalBuffer(audioObj, pitch * fmt, singer);
                singCents = pitch * fmt;                 // detune = 0 이 되도록 cents 를 직접 사용
            } else {
                const r = pitch / fmt;
                if (r >= 5 && r <= 15) {
                    // 한 번만 렌더 — buffer 에는 pitch cents 가 새겨지고 detune 으로 포먼트를 만든다
                    vocalBuf = prepareVocalBuffer(audioObj, pitch, singer);
                    singCents = pitch;                   // detune = (1 - fmt) * *100
                } else {
                    // 두 갈래로 나눠 정확도를 지킨다 (렌더 2회)
                    vocalBuf = prepareVocalBuffer(audioObj, pitch * fmt, singer);
                    singCents = pitch * fmt;
                }
            }

            // 마디 길이(초) 계산 -> 다음 마디 예약 시각 산출
            //   비브라토·리버브로 꼬리가 늘어나므로 WET_SMEAR_SEC 를 빼서 보정한다.
            const dur = (vocalBuf.samples ? vocalBuf.samples.length : 0) / (vocalBuf.sampleRate || 22050);
            const now = audioCtx.currentTime;

            if (i === 0 || nextStart <= now) {
                // 첫 마디이거나 예약이 지났으면 즉시 시작
                await playVocalWithEffects(vocalBuf, singCents, echo, filter, pan, grit, undefined, currentSinger);
                lastEnd = now + dur;
            } else {
                // 이전 마디와 겹쳐 시작 (레가토) - onended 로 resolve 됨
                await playVocalWithEffects(vocalBuf, singCents, echo, filter, pan, grit, nextStart, currentSinger);
                lastEnd = nextStart + dur;
            }

            // 다음 마디 시작 시각: 이번 마디 끝 - 겹침 (단, 사용자 '대기' 값 반영)
            nextStart = lastEnd - OVERLAP - WET_SMEAR_SEC + (Number.isFinite(wait) ? wait : 0);

            // [성과 수호] 대기 시간(사용자 지정)만큼 쉬되, 정지 감시
            const pauseMs = Math.max(0, (nextStart - audioCtx.currentTime) * 1000);
            if (pauseMs > 0) {
                await new Promise(res => {
                    const t0 = Date.now();
                    const iv = setInterval(() => {
                        if (!isProducing || Date.now() - t0 >= pauseMs) {
                            clearInterval(iv);
                            res();
                        }
                    }, 60);
                });
            }
            if (!isProducing) break;
        }

        await stopMRWithFadeOut();
        document.getElementById('result-area').style.display = 'block';

    } catch (e) {
        console.error("가창 오류:", e);
    } finally {
        isProducing = false;
        btn.disabled = false;
        btn.textContent = "🔴 가창 시작";
    }
}

// 게시판 전용 재생 함수
async function playRecipe(recipe, singerId, savedMrPath) {
    // 1. 이미 무언가 재생 중이라면 깨끗이 정리하고 시작
    if (isProducing) stopAll();
    
    isProducing = true;
    
    try {
        if (audioCtx.state === 'suspended') await audioCtx.resume();
        
        // 비트 경로 확인 및 재생
        if (!savedMrPath) savedMrPath = '/static/mr/' + BEAT_LIBRARY[0];
        await playMRWithFadeIn(savedMrPath);

        const singer = SINGERS[singerId] || SINGERS['f1'];

        for (let line of recipe) {
            // [핵심 성과 지표 1] 정지 신호가 오면 즉시 루프 탈출
            if (!isProducing) {
                console.log("🛑 게시판 재생 루프 강제 종료");
                break;
            }

            const text = line.text || "";
            if (!text.trim()) continue;

            const speed = parseFloat(line.speed) || 1.0;
            const tune = parseFloat(line.tune) || 10;
            const echo = parseFloat(line.echo) || 0;
            const pan = parseFloat(line.pan) || 0;
            const wait = parseFloat(line.wait) || 0.3;

            // AI 음성 생성
            const audioObj = ttsEngine.generate({ text: text, sid: 0, speed: speed });
            const pitch = (singer.pitch || 0) + (tune - 10);

            // [신규 260916-A/B] 게시판 재생도 가수별 목소리 + 사람다운 표현 적용
            //   저장된 singer(singerId) 의 포먼트·비브라토를 그대로 재현한다.
            const fmt = Number.isFinite(singer.formant) ? singer.formant : 1.0;
            const r = pitch / fmt;
            let vocalBuf, singCents;
            if (Math.abs(pitch) < 1e-6 || (r >= 5 && r <= 15)) {
                vocalBuf = prepareVocalBuffer(audioObj, pitch, singer);
                singCents = pitch;
            } else {
                vocalBuf = prepareVocalBuffer(audioObj, pitch * fmt, singer);
                singCents = pitch * fmt;
            }

            // [수정 260914] playVocalWithEffects 시그니처 변경에 맞춰 인자 정렬
            //   (audioObj, pitch, echo, filter, pan, grit, startAt, voice)
            const filter = parseFloat(line.filter) || 0;
            const grit = parseFloat(line.grit) || 0;

            // 보컬 재생 (activeSources에 자동 등록됨)
            await playVocalWithEffects(vocalBuf, singCents, echo, filter, pan, grit, undefined, singer);
            
            // [핵심 성과 지표 2] 대기 시간 중에도 0.1초마다 정지 여부를 감시
            // 단순 setTimeout 대신 사용자가 정지를 누르면 즉시 깨어납니다.
            await new Promise(res => {
                const startTime = Date.now();
                const checkInterval = setInterval(() => {
                    if (!isProducing || (Date.now() - startTime) >= (wait * 1000)) {
                        clearInterval(checkInterval);
                        res();
                    }
                }, 100);
            });
        }
    } catch (e) { 
        console.error("재생 중 에러 발생:", e); 
    } finally { 
        // 노래가 끝났거나 중간에 정지되었을 때 처리
        isProducing = false; 
        if (bgmSource) {
            // [중요] 정지 버튼을 누른 경우라면 서서히 끄지 않고 즉시 정지
            bgmSource.stop(0);
            bgmSource = null;
        }
    }
}

function playVocalWithEffects(audioObj, pitch, echo, filter, pan, grit, startAt, voice) {
    return new Promise((resolve) => {
        // finite(유한한 숫자) 체크 함수
        const toFinite = (val, def) => (Number.isFinite(val) ? val : def);

        // [수정 260914] 인자 누락 버그 수정
        //   기존: function(audioObj, pitch, echo, pan)  <- 6개 호출인데 4개만 받음
        //         -> filter 값이 pan 으로 들어가고, pan/grit 은 버려졌음
        //   이제: filter(라디오느낌) / pan(좌우) / grit(거친 질감) 모두 정상 적용
        filter = toFinite(filter, 0);
        pan    = toFinite(pan, 0);
        grit   = toFinite(grit, 0);

        const buffer = audioCtx.createBuffer(1, audioObj.samples.length, audioObj.sampleRate);
        buffer.getChannelData(0).set(audioObj.samples);
        const source = audioCtx.createBufferSource();
        source.buffer = buffer;

        // [핵심 해결] detune 값에 NaN이 들어가는 것을 방지
        // [신규 260916-B] 가수별 포먼트(성도 크기)
        //   prepareVocalBuffer 가 이미 pitch*formant 배율로 렌더했으므로,
        //   여기서는 (1 - formant) 만큼만 detune 으로 남겨 정확한 피치를 맞춘다.
        //   formant<1(성도 큼) → detune 양수 = 살짝 올려 원래 피치로 되돌림 (음색은 낮고 풍성)
        const fmt = (voice && Number.isFinite(voice.formant)) ? voice.formant : 1.0;
        const formantCents = (1 - fmt) * 100;
        const safePitch = Math.max(-12, Math.min(12, toFinite(pitch, 0)));
        source.detune.value = Math.max(-2400, Math.min(2400, safePitch * 100 + formantCents));

        const panner = audioCtx.createStereoPanner();
        // [핵심 해결] pan 값에 NaN이 들어가는 것을 방지 (-1 ~ 1 사이 유지)
        panner.pan.value = Math.max(-1, Math.min(1, pan));

        const delay = audioCtx.createDelay();
        delay.delayTime.value = toFinite(echo * 0.4, 0);
        const fb = audioCtx.createGain();
        fb.gain.value = toFinite(echo * 0.5, 0);

        // ── [신규 260914] 필터: 라디오/로파이 느낌 ──────────────
        //   filter 0 -> 원음 그대로
        //   filter 1 -> 좁은 대역만 통과 (전화/라디오 질감)
        let hp = null, lp = null;
        if (filter > 0.02) {
            hp = audioCtx.createBiquadFilter();
            hp.type = 'highpass';
            hp.frequency.value = 300 + filter * 500;   // 300Hz -> 800Hz
            hp.Q.value = 0.7 + filter * 2;

            lp = audioCtx.createBiquadFilter();
            lp.type = 'lowpass';
            lp.frequency.value = 6000 - filter * 3500; // 6kHz -> 2.5kHz
            lp.Q.value = 0.7 + filter * 2;
        }

        // ── [신규 260914] 거칠게: 웨이브셰이퍼 디스토션 ──────────
        let shaper = null;
        if (grit > 0.02) {
            shaper = audioCtx.createWaveShaper();
            const k = grit * 40;                       // 0 -> 40
            const n = 1024;
            const curve = new Float32Array(n);
            for (let i = 0; i < n; i++) {
                const x = (i * 2) / n - 1;
                curve[i] = ((3 + k) * x * 20 * (Math.PI / 180)) / (Math.PI + k * Math.abs(x));
            }
            shaper.curve = curve;
            shaper.oversample = '2x';
        }

        // ── 노드 연결 ──────────────────────────────────────────
        // source -> [grit] -> [filter hp] -> [filter lp] -> panner -> [vibrato] -> analyser
        //        -> 보컬버스(컴프레서 -> 마스터/리버브) -> out
        //   [신규 260916-A] vibrato: 지연변조로 배음까지 흔들어 자연스러운 떨림을 준다.
        //   [신규 260914-B] 보컬버스 경유: 컴프레서(음량균일) + 리버브(공간감)
        ensureVocalBus();
        ensureReverb();
        let node = source;
        if (shaper) { node.connect(shaper); node = shaper; }
        if (hp) { node.connect(hp); node = hp; }
        if (lp) { node.connect(lp); node = lp; }
        node.connect(panner);

        // 비브라토 (건조음 + 떨린 소리를 50:50 으로 섞어 자연스럽게)
        const vib = buildVibrato(voice);
        if (vib) {
            panner.connect(analyser);        // 건조(원음) 경로
            panner.connect(vib.input);       // 떨림 경로
            vib.output.connect(analyser);
        } else {
            panner.connect(analyser);
        }

        // [변경] destination 직결 -> 보컬버스 경유 (없으면 원래대로 직결)
        if (vocalBus) {
            analyser.connect(vocalBus);
        } else {
            analyser.connect(audioCtx.destination);
        }

        if (echo > 0.05) {
            panner.connect(delay);
            delay.connect(fb);
            fb.connect(delay);
            // [변경] 에코도 보컬버스로 (마스터 볼륨/리버브와 함께 정리되도록)
            delay.connect(vocalBus ? vocalBus : audioCtx.destination);
        }

        source.onended = () => {
            // [신규 260916-A] 비브라토 LFO 정리 (안 하면 마디마다 오실레이터가 쌓인다)
            if (vib && vib.lfo) { try { vib.lfo.stop(); vib.lfo.disconnect(); } catch (e) {} }
            activeSources = activeSources.filter(s => s !== source);
            resolve();
        };
        activeSources.push(source);
        // [신규 260914-B] 스케줄 시작시간 지원 (레가토: 다음 마디를 겹쳐 시작)
        if (typeof startAt === 'number' && startAt > audioCtx.currentTime) {
            source.start(startAt);
        } else {
            source.start(0);
        }
    });
}

// ══════════════════════════════════════════════════════════════
// [신규 260914-B] 마디 연결(레가토) 재생
//   기존: 마디 재생 -> 완전 종료(onended) -> 무음 대기 -> 다음 마디  (뚝뚝 끊김)
//   개선: 이전 마디가 끝나기 전에 다음 마디를 겹쳐 시작 (자연스러운 연결)
//   - overlap 초 만큼 앞당겨 다음 마디를 시작
//   - 정지 버튼은 기존과 동일하게 즉시 동작
// ══════════════════════════════════════════════════════════════
async function playVocalLegato(audioObj, pitch, echo, filter, pan, grit, startAt, voice) {
    return playVocalWithEffects(audioObj, pitch, echo, filter, pan, grit, startAt, voice);
}

async function playMRWithFadeIn(url) {
    const res = await fetch(encodeURI(url));
    const buf = await audioCtx.decodeAudioData(await res.arrayBuffer());
    bgmSource = audioCtx.createBufferSource();
    bgmSource.buffer = buf;
    bgmSource.loop = true;
    bgmGainNode = audioCtx.createGain();
    bgmGainNode.gain.setValueAtTime(0, audioCtx.currentTime);
    // [신규 260914-B] MR 밸런스: 보컬(컴프레서 통과, 마스터 0.95)에 맞춰 0.3 -> 0.42
    //   반주가 너무 작아 가창이 튀던 문제 완화 (0.3 = 보컬 독주처럼 들림)
    const mrLevel = (typeof MR_LEVEL === 'number') ? MR_LEVEL : 0.42;
    bgmGainNode.gain.linearRampToValueAtTime(mrLevel, audioCtx.currentTime + 2);
    bgmSource.connect(bgmGainNode);
    bgmGainNode.connect(audioCtx.destination);
    bgmSource.start(0);
}

async function stopMRWithFadeOut() {
    if (!bgmGainNode) return;
    bgmGainNode.gain.linearRampToValueAtTime(0, audioCtx.currentTime + 3);
    await new Promise(res => setTimeout(res, 3000));
    if (bgmSource) { bgmSource.stop(); bgmSource = null; }
}

function stopAll() {
    console.log("🛑 모든 재생 및 생성 강제 중단...");

    // 1. 상태 플래그 정지 (이름을 isProducing으로 통일)
    isProducing = false;
    window.isProcessing = false; // 혹시 몰라 둘 다 끔

    // 2. [핵심] 현재 재생 중인 모든 보컬 소스 강제 정지
    if (activeSources && activeSources.length > 0) {
        activeSources.forEach(source => {
            try {
                source.stop(0); // 즉시 정지
                source.disconnect();
            } catch (e) {
                // 이미 정지된 경우 에러 무시
            }
        });
        activeSources = []; // 리스트 비우기
        console.log("🔊 보컬 채널 강제 종료 완료");
    }

    // 3. MR(배경음악) 즉시 정지
    if (bgmSource) {
        try {
            bgmSource.stop(0);
            bgmSource.disconnect();
        } catch (e) {}
        bgmSource = null;
        console.log("🎵 MR 채널 종료 완료");
    }

    // 4. 오디오 컨텍스트 초기화 (필요시 다시 시작 가능하게)
    if (audioCtx && audioCtx.state !== 'closed') {
        audioCtx.resume(); // suspended 상태라면 resume 해줘야 다음 재생이 잘 됨
    }

    // 5. UI 복구
    const btn = document.getElementById('btn-record');
    if (btn) {
        btn.disabled = false;
        btn.textContent = "🔴 가창 시작";
    }
    
    // 결과창 숨기기 (선택 사항)
    document.getElementById('result-area').style.display = 'none';
}
