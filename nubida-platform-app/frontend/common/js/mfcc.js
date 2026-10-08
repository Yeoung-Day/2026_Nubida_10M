/* =========================================================================
 * mfcc.js — M1: MFCC 추출 모듈 (설계서_음성MFCC파일럿_0902.md 3.1절)
 * -------------------------------------------------------------------------
 * WAV(임의 샘플레이트) → 16kHz 모노 → STFT(fft512/hop160=10ms/hann)
 *   → 멜 필터뱅크 40채널(200Hz~7.5kHz) → log10(·+1e-10) → DCT-II 13차
 *   → 델타 13차 추가(26채널/프레임) → 프레임별 mean/std 정규화
 *   → 150프레임 pad/truncate → 출력 텐서 (1, 150, 26)
 *
 * TF.js 로컬 vendor만 사용(tf.signal.stft/hannWindow + 수동 행렬곱),
 * 외부 CDN 의존 없음.
 * ========================================================================= */
(function (global) {
    'use strict';

    var SR = 16000;            // 분석 샘플레이트
    var FFT = 512;             // fftSize
    var HOP = 160;             // hop = 10ms @16kHz
    var NUM_MEL = 40;          // 멜 채널
    var MEL_FMIN = 200;        // 멜 필터 대역 하한 (Hz) — 설계서: 200Hz~7.5kHz 선형→로그
    var MEL_FMAX = 7500;       // 멜 필터 대역 상한 (Hz)
    var NUM_CEP = 13;          // MFCC 차수 (델타 포함 26)
    var MAX_FRAMES = 150;      // 고정 시퀀스 길이 (1.5s = 147프레임 + pad)
    var WIN_SAMPLES = MAX_FRAMES * HOP + FFT - HOP; // 150프레임에 필요한 PCM 길이
    var N_BINS = FFT / 2 + 1;  // 257
    var LN10 = Math.log(10);
    var EPS = 1e-10;

    var melTensor = null;      // (N_BINS, NUM_MEL) Float32 → lazy
    var dctTensor = null;      // (NUM_MEL, NUM_CEP) Float32 → lazy

    /* ── 멜 스케일 변환 ─────────────────────────── */
    function hzToMel(h) { return 2595 * Math.log10(1 + h / 700); }
    function melToHz(m) { return 700 * (Math.pow(10, m / 2595) - 1); }

    /* ── 멜 필터뱅크 가중치 (NUM_MEL×257 삼각 필터) ── */
    function buildMelWeights() {
        var rows = [];
        var melMin = hzToMel(MEL_FMIN), melMax = hzToMel(MEL_FMAX);
        var pts = [];
        for (var p = 0; p < NUM_MEL + 2; p++) {
            pts.push(melToHz(melMin + p * (melMax - melMin) / (NUM_MEL + 1)));
        }
        var binHz = SR / FFT;
        for (var m = 0; m < NUM_MEL; m++) {
            var row = new Float32Array(N_BINS);
            var fL = pts[m], fC = pts[m + 1], fR = pts[m + 2];
            for (var b = 0; b < N_BINS; b++) {
                var f = b * binHz;
                if (f >= fL && f <= fC) row[b] = (f - fL) / (fC - fL);
                else if (f > fC && f <= fR) row[b] = (fR - f) / (fR - fC);
            }
            rows.push(row);
        }
        // 열 우선(column-major) 변환: tf.tensor2d는 row-major 1차원 배열이므로
        // (N_BINS, NUM_MEL) 행렬 = weights[m][b] → flat[ b*NUM_MEL + m ]
        var flat = new Float32Array(N_BINS * NUM_MEL);
        for (var mm = 0; mm < NUM_MEL; mm++) {
            var r = rows[mm];
            for (var bb = 0; bb < N_BINS; bb++) flat[bb * NUM_MEL + mm] = r[bb];
        }
        return flat;
    }

    /* ── DCT-II 행렬 (13×40, 정규직교) ─────────────
     * X[k] = Σ_m c[k][m]·x[m]
     * c[k][m] = cos(π·k·(m+0.5)/M) × √(2/M)  (k=0 → √(1/M))
     */
    function buildDctWeights() {
        var flat = new Float32Array(NUM_MEL * NUM_CEP);
        var s0 = Math.sqrt(1 / NUM_MEL);
        var s = Math.sqrt(2 / NUM_MEL);
        for (var k = 0; k < NUM_CEP; k++) {
            var scale = (k === 0) ? s0 : s;
            for (var m = 0; m < NUM_MEL; m++) {
                // (NUM_MEL, NUM_CEP) row-major: flat[m*NUM_CEP + k]
                flat[m * NUM_CEP + k] = scale * Math.cos(Math.PI * k * (m + 0.5) / NUM_MEL);
            }
        }
        return flat;
    }

    /* ── lazy 가중치 텐서 (tf 로드 후 1회) ────────── */
    function ensureTensors() {
        if (melTensor && dctTensor) return;
        melTensor = tf.tensor2d(buildMelWeights(), [N_BINS, NUM_MEL]);   // (257,40)
        dctTensor = tf.tensor2d(buildDctWeights(), [NUM_MEL, NUM_CEP]);  // (40,13)
    }

    /* ── [핵심] 16k PCM → MFCC (1,150,26) Float32Array ──
     * stft/mel/log/dct는 tf 연산, 델타·정규화·패딩은 JS 후처리(경량).
     */
    function computeFromPcm16k(pcm) {
        if (!pcm || pcm.length < FFT) {
            // 너무 짧은 입력 → 전부 0 (방어)
            return new Float32Array(MAX_FRAMES * NUM_CEP * 2);
        }
        ensureTensors();
        var ceps = tf.tidy(function () {
            var sig = tf.tensor1d(pcm);
            // STFT: tf.signal.stft(fft512/hop160) — complex64 반환 → tf.abs로 magnitude
            // (windowFn은 함수 자체 전달; frame+rfft는 tf.signal에 rfft 미존재로 사용 불가)
            var spec = tf.signal.stft(sig, FFT, HOP, FFT, tf.signal.hannWindow); // complex (F,257)
            var mag = tf.abs(spec);                                              // (F,257)
            var melE = mag.matMul(melTensor);                            // (F,40)
            var logMel = tf.log(melE.add(EPS)).div(LN10);            // log10
            var c = logMel.matMul(dctTensor);                        // (F,13)
            return c.dataSync();
        });
        var F = ceps.length / NUM_CEP;
        return postProcess(ceps, F);
    }

    /* ── 델타 + 프레임별 정규화 + 150프레임 pad/truncate ── */
    function postProcess(ceps, F) {
        var D = NUM_CEP * 2;                       // 26
        var out = new Float32Array(MAX_FRAMES * D);
        var useF = Math.min(F, MAX_FRAMES);
        var W = 2;                                 // 델타 윈도우
        var i, t, k;

        // 델타 가중치 (표준: Σ i·(c[t+i]−c[t−i]) / 2Σi², 경계는 가용 항만)
        for (t = 0; t < useF; t++) {
            var num = new Float64Array(NUM_CEP);
            var den = 0;
            for (i = 1; i <= W; i++) {
                var a = t - i, b = t + i;
                if (a < 0 || b >= F) continue;
                for (k = 0; k < NUM_CEP; k++) {
                    num[k] += i * (ceps[(b) * NUM_CEP + k] - ceps[(a) * NUM_CEP + k]);
                }
                den += i * i;
            }
            var dsum = 2 * den || 1;
            var row = new Float64Array(D);
            for (k = 0; k < NUM_CEP; k++) row[k] = ceps[t * NUM_CEP + k];
            for (k = 0; k < NUM_CEP; k++) row[NUM_CEP + k] = num[k] / dsum;

            // 프레임별 mean/std 정규화 — 성문 주파수·음량 차이 압축 (설계서 3.1)
            var mean = 0, sd = 0;
            for (k = 0; k < D; k++) mean += row[k];
            mean /= D;
            for (k = 0; k < D; k++) { var dv = row[k] - mean; sd += dv * dv; }
            sd = Math.sqrt(sd / D);
            for (k = 0; k < D; k++) {
                out[t * D + k] = (sd > 1e-6) ? (row[k] - mean) / sd : 0;
            }
        }
        return out;   // 나머지 프레임은 0 pad
    }

    /* ── [유틸] 임의 샘플레이트 AudioBuffer → 16k 모노 Float32Array ──
     * OfflineAudioContext 렌더로 하드웨어 리샘플 품질 확보.
     */
    async function resampleTo16k(audioBuffer) {
        var ac = audioBuffer;
        if (ac.sampleRate === SR && ac.numberOfChannels === 1) {
            return ac.getChannelData(0);
        }
        var targetLen = Math.max(1, Math.ceil(ac.duration * SR));
        var OC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        var ctx = new OC(1, targetLen, SR);
        var src = ctx.createBufferSource();
        src.buffer = ac;
        src.connect(ctx.destination);
        src.start(0);
        var rendered = await ctx.startRendering();
        return rendered.getChannelData(0);
    }

    /* ── [유틸] ArrayBuffer(webm/wav 등) → 16k PCM ── */
    async function decodeToPcm16k(arrayBuf) {
        var AC = window.AudioContext || window.webkitAudioContext;
        var ctx = new AC();
        try {
            var buf = await ctx.decodeAudioData(arrayBuf.slice(0));
            return await resampleTo16k(buf);
        } finally {
            if (ctx.state !== 'closed') ctx.close().catch(function () {});
        }
    }

    /* ── [유틸] URL → 16k PCM ── */
    async function pcmFromUrl(url) {
        var res = await fetch(url);
        if (!res.ok) throw new Error('fetch 실패: ' + url + ' → ' + res.status);
        var buf = await res.arrayBuffer();
        return await decodeToPcm16k(buf);
    }

    /* ── [유틸] 발화 중심 1.5s(24352샘플) 창 추출 ──
     * 입력이 고정 길이보다 길면 슬라이딩 RMS 에너지가 최대인 구간 선택.
     * (실시간 발화 감지 실패 폴백 — M2 Voice Hold는 상위에서 중앙 정렬)
     */
    function centerUtterance(pcm) {
        var need = WIN_SAMPLES;   // 24352
        if (pcm.length <= need) return pcm;
        var step = 160;           // 10ms
        var best = 0, bestE = -1;
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

    /* ── [테스트] 16k 사인파 생성 ── */
    function sinePcm16k(freq, secs, amp) {
        var n = Math.floor(SR * secs);
        var out = new Float32Array(n);
        for (var i = 0; i < n; i++) {
            out[i] = (amp || 0.5) * Math.sin(2 * Math.PI * freq * i / SR);
        }
        return out;
    }

    global.NubidaMFCC = {
        SR: SR, FFT: FFT, HOP: HOP, NUM_MEL: NUM_MEL, NUM_CEP: NUM_CEP,
        MAX_FRAMES: MAX_FRAMES,
        computeFromPcm16k: computeFromPcm16k,
        resampleTo16k: resampleTo16k,
        decodeToPcm16k: decodeToPcm16k,
        pcmFromUrl: pcmFromUrl,
        centerUtterance: centerUtterance,
        sinePcm16k: sinePcm16k,
        // 텐서 빌드(내부 디버그용)
        _ensureTensors: ensureTensors,
    };
})(window);
