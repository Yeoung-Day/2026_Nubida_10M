let currentSinger = 'f1';

const STUDIO_PIN = "1234";
const ADMIN_PIN = "admin0000";
const BANNED_WORDS = ["바보", "멍청이", "미친", "죽어"];

if (!localStorage.getItem('studio_user_id')) {
    localStorage.setItem('studio_user_id', 'user_' + Math.random().toString(36).substr(2, 9));
}
window.STUDIO_USER_ID = localStorage.getItem('studio_user_id');

// ══════════════════════════════════════════════════════════════
// [신규 260916-B] 가수별 목소리 차별화
//   기존: 5명 모두 sid 0 (같은 목소리) 에 pitch 만 달리 적용 -> "한 사람을 기계로 비튼 소리"
//   이제: 가수마다 ① 기준 음정(pitch) ② 포먼트(성도 크기) ③ 톤 성향 ④ 비브라토 ⑤ 숨결
//         를 모두 다르게 준다. 성도가 크면(formant<1) 낮고 따뜻한 목소리가 된다.
//
//   fmt  = 피치에 곱하는 포먼트 배율 (1.00 기준, 작을수록 성도가 큼 = 낮고 풍성)
//          소리의 스펙트럼 포락선을 옮겨 "다른 사람"처럼 들리게 하는 핵심 값이다.
//   lead = 타임도메인 톤 성향 (§ engine.js prepareVocalBuffer)
//          fl/fh  : 저역/고역 셀프필터 계수 (0.05 = 약 3kHz / 0.018 = 약 8.8kHz)
//          warm   : 저역 강조 (따뜻하고 두꺼움)   bright : 고역 강조 (맑고 쨍함)
//          speak  : 지연평균 혼합 = 비음·콧소리 성향 (사람 목소리 느낌)
//          ⚠️ warm/bright/speak 를 0.5 이상으로 올리면 소리가 뭉개진다. 0.05~0.25 권장.
//   vibRate/vibCents : 떨림 속도(초당) / 폭(센트)
//   attack : 소리 시작이 열리는 시간(초)  porta : 발성 시작 슬라이드(초)
//   noise  : 숨결(성막 마찰) 양 — 0.004~0.014 권장
// ══════════════════════════════════════════════════════════════
const SINGERS = {
    f1: { name: '수진', pitch: 0,   formant: 1.00, icon: '👩‍🎤',
          lead: { fl: 0.050, fh: 0.018, warm: 0.04, bright: 0.04, speak: 0.05 },
          vibRate: 5.4, vibCents: 30, attack: 0.05, porta: 0.12, portaLvl: 0.07, noise: 0.008 },
    f2: { name: '민서', pitch: 6,   formant: 0.82, icon: '👧',
          lead: { fl: 0.070, fh: 0.030, warm: 0.04, bright: 0.16, speak: 0.07 },
          vibRate: 6.1, vibCents: 20, attack: 0.04, porta: 0.14, portaLvl: 0.06, noise: 0.006 },
    f3: { name: '유나', pitch: 3,   formant: 0.90, icon: '👸',
          lead: { fl: 0.060, fh: 0.026, warm: 0.02, bright: 0.21, speak: 0.05 },
          vibRate: 5.0, vibCents: 34, attack: 0.08, porta: 0.18, portaLvl: 0.09, noise: 0.012 },
    f4: { name: '서현', pitch: -1,  formant: 1.03, icon: '👩',
          lead: { fl: 0.038, fh: 0.013, warm: 0.13, bright: 0.03, speak: 0.12 },
          vibRate: 4.7, vibCents: 24, attack: 0.06, porta: 0.20, portaLvl: 0.05, noise: 0.010 },
    f5: { name: '은정', pitch: -1.5, formant: 1.15, icon: '👩‍💼',
          lead: { fl: 0.028, fh: 0.010, warm: 0.22, bright: 0.01, speak: 0.16 },
          vibRate: 4.3, vibCents: 28, attack: 0.07, porta: 0.12, portaLvl: 0.04, noise: 0.009 }
};

const PRESETS = {
    default: { name: '기본', tune: 8, echo: 0.15, wait: 0.3, pan: 0, vol: 1.0, speed: 1.0 },
    trap: { name: '트랩', tune: 18, echo: 0.1, wait: 0.2, pan: 0, vol: 1.1, speed: 1.15 },
    boombap: { name: '붐뱁', tune: 4, echo: 0.05, wait: 0.4, pan: 0, vol: 1.2, speed: 1.0 },
    singing: { name: '싱잉랩', tune: 14, echo: 0.35, wait: 0.3, pan: 0, vol: 0.9, speed: 1.05 }
};

const BEAT_LIBRARY = [
        'mr/Sunny Days - Anno Domini Beats.mp3',
        'mr/Misdirection - The Grey Room _ Density & Time.mp3',
        'mr/No Rush - Dyalla.mp3',
        'mr/Cocktail Lounge - Dyalla.mp3',
        'mr/Cosy - Dyalla.mp3',
        'mr/Cooked - Dyalla.mp3',
        'mr/Boom - Dyalla.mp3',
        'mr/Kicking It - Dyalla.mp3',
        'mr/Trilogy - Telecasted.mp3',
        'mr/Broken Circuits - Telecasted.mp3'
    ];