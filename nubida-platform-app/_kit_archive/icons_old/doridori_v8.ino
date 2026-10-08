/* ===========================================================================
 *  도리도리 로봇 v8  (블루투스가 끊기지 않는 판)
 *  ---------------------------------------------------------------------------
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★★★ 이 파일만 보시면 됩니다 ★★★
 *      - 동작을 고치고 싶다 -> 【동작 만들기】 부분
 *      - 각도/속도를 바꾸고 싶다 -> 【설정】 부분
 *      - 새 번호를 추가하고 싶다 -> runCommand() 안의 안내 참고
 *
 *  나머지는 3개의 외부 파일로 빠졌습니다. (건드리지 않으셔도 됩니다)
 *      ① nubida_decode.h  - 암호문(난독화) 풀기
 *      ② nubida_ai.h      - AI 명령 13종
 *      ③ nubida_bt.h      - 블루투스 연결 + 수신
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  1NubidaAi  ->  도리도리   (9번 서보 · 좌우로 흔들기)              │
 *  │  2NubidaAi  ->  삐졌어     (9번 서보 · 고개 푹 떨구기)             │
 *  │  3NubidaAi  ->  안녕       (7번 서보 · 끄덕끄덕 인사)              │
 *  │  4~99번     ->  무시       (정의되지 않은 번호 · 움직이지 않음)    │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ⚠️ 2번 / 3번 핀은 블루투스 통신 전용입니다. 다른 부품을 꽂지 마세요.
 * =========================================================================== */

#include <SoftwareSerial.h>
#include <Servo.h>
#include <EEPROM.h>     /* ⚠️ 2026-09-21 : 부팅 횟수 기록용 */

/* ===========================================================================
 *  【설정】 - 여기 숫자만 바꾸시면 됩니다
 * =========================================================================== */

/* 서보가 꽂힌 핀 */
#define PIN_HEAD    9      /* 도리도리 · 삐졌어 서보 */
#define PIN_ARM     7      /* 안녕 서보 */
/* 부저가 꽂힌 핀 - 서보(9 · 7)와 절대 겹치면 안 됩니다 */
#define PIN_BUZZ    8      /* 부저 */

/* 도리도리 각도
 *   ⚠️ 2026-09-21 : 전류 부담을 줄이기 위해 흔드는 폭을 좁혔습니다.
 *      (원래 140 / 40 - 100도 이동 -> 65도 이동으로 감소)
 *      더 넓게 흔들고 싶으면 다시 140 / 40 으로 바꾸세요. */
#define DORI_LEFT   125    /* 왼쪽으로 (원래 140) */
#define DORI_RIGHT   55    /* 오른쪽으로 (원래 40) */

/* 삐졌어 각도 */
#define SAD_DOWN     45    /* 고개 푹 떨군 각도 (원래 25 - 이동거리 축소) */

/* 안녕 각도 */
#define HI_UP       120    /* 위로 들기 (원래 135) */
#define HI_DOWN      55    /* 아래로 숙이기 (원래 25) */

/* 가운데(정면) */
#define CENTER       90

/* 움직이는 속도 - 숫자가 클수록 천천히
 *   ⚠️ 2026-09-21 : 전류 문제로 전체적으로 늦췄습니다.
 *      서보는 "급하게 움직일 때" 전류를 훨씬 많이 먹습니다.
 *      천천히 움직이면 전압 강하가 줄어 보드가 리셋되지 않습니다. */
#define MS_FAST     600     /* 원래 300 */
#define MS_NORMAL   1200    /* 원래 500  ★ 가장 중요 */
#define MS_SLOW     1600    /* 원래 800 */

/* ⚠️ 2026-09-21 추가 : 서보를 움직이는 "한 칸" 의 최소 간격(ms)
 *   너무 촘촘하게 움직이면 전류가 확 튀어서 보드가 리셋될 수 있습니다.
 *   값이 크면 더 부드럽고 전류도 완만해지지만, 너무 크면 동작이 굼떠집니다.
 *   ★ 20ms : 전류 보호 + 동작 속도 균형점 */
#define SERVO_MIN_TICK   20

/* ⚠️ 2026-09-21 : 서보 이동 한 번에 최대 몇 도씩 갈지 (작을수록 부드러움)
 *   ★ 3도 : 원래 코드와 같은 값 (동작이 굼떠지지 않게) */
#define SERVO_STEP_DEG   3

/* ===========================================================================
 *  외부 파일 불러오기 (순서 중요)
 *    ⓐ 난독화 풀기
 *    ⓑ 블루투스 연결 객체 선언 + 수신 (runCommand 가 정의된 "뒤"에 다시 옵니다)
 *    ⓒ AI 명령 13종  ← runCommand() 와 servoTo() 를 쓰므로 그 뒤에 옵니다
 * =========================================================================== */
#include "nubida_decode.h"

/* 블루투스 연결 (RX = 2번 핀, TX = 3번 핀)
 *   AI 명령(nubida_ai.h)이 BTSerial.println() 을 쓰기 때문에 여기서 먼저 만듭니다 */
SoftwareSerial BTSerial(2, 3);

/* ===========================================================================
 *  서보 2개 기억장치
 *    ※ 함수 밖에 있어야 합니다 (안에 만들면 각도가 풀립니다)
 * =========================================================================== */
Servo srv[2];
int   srvPin[2] = { PIN_HEAD, PIN_ARM };
int   srvCur[2] = { CENTER,   CENTER   };

/* ⚠️ 2026-09-21 추가 : "서보에 마지막으로 실제 보낸 각도"
 *   Servo::write() 는 인터럽트를 잠깐 막기 때문에
 *   SoftwareSerial(블루투스)과 같이 쓰면 통신이 죽을 수 있습니다.
 *   -> 같은 각도를 반복해서 보내지 않도록 기록해 둡니다. */
int   srvCurSent[2] = { -1, -1 };

/* ===========================================================================
 *  【논블로킹 서보 시퀀스 엔진】 - 만들어진 코드 (건드리지 않으셔도 됩니다)
 * ---------------------------------------------------------------------------
 *  왜 필요한가?
 *    예전 servoTo() 는 delay() 로 기다리는 동안 블루투스 수신이 완전히 멈춰서
 *    "명령을 한 번만 읽고 그 다음부터 못 읽는" 문제가 있었습니다.
 *    (도리도리 동작 하나가 약 2.5초 동안 loop() 를 붙잡았습니다)
 *
 *  어떻게 해결하나?
 *    움직일 목록을 "예약"만 해두고, loop() 에서 매번 조금씩 진행합니다.
 *    -> delay() 가 없으므로 블루투스는 언제나 살아 있습니다.
 *
 *  사용법 (아래 【동작 만들기】 에서 쓰는 함수 3개)
 *      seqAdd(핀, 각도, 걸리는시간);   <- "이 각도로 이만큼에 걸쳐 가라" 예약
 *      seqWait(밀리초);                <- "여기서 잠깐 쉬어라" 예약
 *      (예약은 자동으로 순서대로 실행됩니다)
 * =========================================================================== */

/* 예약할 수 있는 최대 개수 - 동작 하나가 이보다 길면 늘리세요
 *   ⚠️ 2026-09-21 : 24 -> 20
 *      도리도리는 이제 이동4 + 대기4 + 복귀1 = 9단계입니다.
 *      여유를 두고 20으로 잡았습니다. (SRAM 약 120B 절약) */
#define SEQ_MAX 20

/* 예약 한 칸 */
struct seqStep {
  int      kind;    /* 0 = 서보이동, 1 = 기다리기, 2 = 끝 */
  int      pin;     /* 서보 핀 */
  int      deg;     /* 목표 각도 */
  int      ms;      /* 걸리는 시간 / 기다리는 시간 */
  /* 아래는 실행 중에 쓰는 값 */
  int      from;    /* 시작 각도 */
  int      cur;     /* 현재 각도 */
  int      dir;     /* +3 또는 -3 */
  int      steps;   /* 총 스텝 수 */
  int      done;    /* 지금까지 진행한 스텝 수 */
  int      tick;    /* 스텝 사이 간격(ms) */
  unsigned long nextAt;   /* 다음에 움직일 시각 */
  unsigned long endAt;    /* 기다리기 종료 시각 */
  bool     started; /* 실행을 시작했나 */
};

seqStep seqList[SEQ_MAX];
int     seqCount = 0;    /* 예약된 총 개수 */
int     seqIdx   = 0;    /* 지금 실행 중인 번호 */
bool    seqBusy  = false;/* 동작이 진행 중인가 */

/* 서보 배열 인덱스 찾기 (없으면 -1) */
inline int seqServoIndex(int pin) {
  for (int k = 0; k < 2; k++) if (srvPin[k] == pin) return k;
  return -1;
}

/* 각도 자르기 */
inline int seqClamp(int deg) {
  if (deg < 0)   return 0;
  if (deg > 180) return 180;
  return deg;
}

/* ---- 예약 함수 1 : 서보를 deg 로 ms 동안 부드럽게 ---- */
inline void seqAdd(int pin, int deg, int ms) {
  if (seqCount >= SEQ_MAX) return;

  int i = seqServoIndex(pin);
  if (i < 0) return;                    /* 그런 서보 없음 */

  deg = seqClamp(deg);
  int from = srvCur[i];
  /* ⚠️ 2026-09-21 수정 :
   *   예전에는 from == deg 이면 예약을 건너뛰었습니다.
   *   그런데 도리도리처럼 "좌 -> 우 -> 좌 -> 우" 처럼 같은 값이 다시
   *   나오는 동작에서는 두 번째 '좌' 가 통째로 사라져서
   *   흔들기가 어색해졌습니다. -> 이제는 그냥 예약합니다.
   *   (같은 자리면 steps=1 이 되어 즉시 끝나므로 부담도 없습니다) */

  seqStep& s = seqList[seqCount++];
  s.kind    = 0;
  s.pin     = pin;
  s.deg     = deg;
  s.ms      = ms;
  s.from    = from;
  s.cur     = from;
  s.dir     = (deg > from) ? SERVO_STEP_DEG : ((deg < from) ? -SERVO_STEP_DEG : 0);
  int total = abs(deg - from);
  s.steps   = total / SERVO_STEP_DEG; if (s.steps < 1) s.steps = 1;
  s.tick    = ms / s.steps;
  if (s.tick < SERVO_MIN_TICK) s.tick = SERVO_MIN_TICK;   /* 전류 보호 */
  s.done    = 0;
  s.nextAt  = 0;
  s.endAt   = 0;
  s.started = false;

  /* 예약하는 순간 srvCur 를 목표로 미리 옮겨둡니다.
   *   -> 같은 동작 안에서 다음 예약이 "내가 어디서 출발하는지" 를 알 수 있습니다 */
  srvCur[i] = deg;
}

/* ---- 예약 함수 2 : ms 동안 아무것도 하지 않고 대기 ---- */
inline void seqWait(int ms) {
  if (ms <= 0) return;
  if (seqCount >= SEQ_MAX) return;

  seqStep& s = seqList[seqCount++];
  s.kind    = 1;
  s.pin     = -1;
  s.deg     = 0;
  s.ms      = ms;
  s.from    = 0;
  s.cur     = 0;
  s.dir     = 0;
  s.steps   = 0;
  s.tick    = 0;
  s.done    = 0;
  s.nextAt  = 0;
  s.endAt   = 0;
  s.started = false;
}

/* 새 동작을 시작할 수 있나? (진행 중이면 false) */
inline bool seqFree() {
  return !seqBusy;
}

/* 지금 진행 중인 동작을 끝까지 마무리 (동작 함수 끝에서 자동 호출됨)
 *   ⚠️ 2026-09-21 수정 : 이미 실행 중이면 아무것도 하지 않습니다.
 *      예전에는 무조건 seqIdx = 0 으로 되돌려서
 *      실행 중이던 동작이 처음부터 다시 시작될 위험이 있었습니다. */
inline void seqCommit() {
  if (seqBusy) return;                 /* 이미 실행 중 -> 건드리지 않음 */
  if (seqCount <= 0) return;
  seqBusy = true;
  seqIdx  = 0;
}

/* ===========================================================================
 *  servoTo() - 예전 이름 그대로 쓰는 호환 함수
 *    ★ nubida_ai.h(공통 파일)가 servoTo() 를 쓰기 때문에 남겨둡니다.
 *    움직임을 "예약"하고 바로 돌아옵니다 -> delay() 가 없어 블루투스가 끊기지 않습니다.
 *    ★ 여러 동작을 이어서 만들 때는 seqAdd() 를 쓰고 맨 끝에 seqCommit() 하세요.
 *
 *  ⚠️ 2026-09-21 수정 : 진행 중일 때는 예약을 아예 하지 않습니다.
 *     예전에는 진행 중에도 seqAdd() 를 불러서
 *       - srvCur[] 가 오염되고 (다음 동작의 "출발점" 이 틀어짐)
 *       - seqCount 가 계속 늘어나 SEQ_MAX(24) 를 채우면
 *         이후 모든 예약이 조용히 무시되어 "몇 번 하다가 멈추는" 원인이 되었습니다.
 * =========================================================================== */
inline void servoTo(int pin, int deg, int ms) {
  if (seqBusy) return;         /* 진행 중이면 끼어들지 않음 (핵심 수정) */
  seqAdd(pin, deg, ms);
  if (!seqBusy) seqCommit();
}

/* ---- loop() 에서 매번 부르는 진행 함수 ---- */
inline void seqUpdate() {
  if (!seqBusy) return;
  if (seqIdx >= seqCount) {          /* 전부 끝났다 */
    seqBusy  = false;
    seqCount = 0;
    seqIdx   = 0;
    return;
  }

  seqStep& s = seqList[seqIdx];
  unsigned long now = millis();

  /* ---------- 기다리기 ---------- */
  if (s.kind == 1) {
    if (!s.started) {
      s.started = true;
      s.endAt   = now + (unsigned long)s.ms;
      return;
    }
    if (now >= s.endAt) { seqIdx++; }
    return;
  }

  /* ---------- 서보 이동 ---------- */
  if (s.kind == 0) {
    int i = seqServoIndex(s.pin);
    if (i < 0) { seqIdx++; return; }

    if (!s.started) {
      s.started = true;
      s.nextAt  = now;
    }

    /* 시간이 안 됐으면 다음 기회에 */
    if (now < s.nextAt) return;

    s.cur += s.dir;
    if (s.dir > 0 && s.cur > s.deg) s.cur = s.deg;
    if (s.dir < 0 && s.cur < s.deg) s.cur = s.deg;

    /* ⚠️ 2026-09-21 : 각도가 실제로 바뀐 경우에만 write()
     *   Servo::write() 는 내부적으로 인터럽트를 잠깐 막습니다.
     *   SoftwareSerial 과 같이 쓰면 그 사이 비트를 놓쳐
     *   블루투스가 죽습니다 -> 호출 횟수를 최소로 줄입니다. */
    if (srvCurSent[i] != s.cur) {
      srv[i].write(s.cur);
      srvCurSent[i] = s.cur;
    }
    s.done++;
    s.nextAt = now + (unsigned long)s.tick;

    if (s.done >= s.steps || s.cur == s.deg) {
      if (srvCurSent[i] != s.deg) {
        srv[i].write(s.deg);
        srvCurSent[i] = s.deg;
      }
      seqIdx++;
    }
    return;
  }

  seqIdx++;   /* 알 수 없는 종류 -> 건너뜀 */
}

/* ===========================================================================
 *  【동작 만들기】 - 새 동작은 여기에 함수를 하나 만드시면 됩니다
 *
 *  ⚠️ 2026-09-21 : 동작 함수 맨 앞에
 *        if (seqBusy) return;
 *     를 넣어, 앞 동작이 끝나기 전에 새 명령이 들어와도
 *     예약이 뒤엉키지 않게 했습니다.
 * =========================================================================== */

/* -- 도리도리 -- 좌우로 흔들기 (9번 서보)
 *   ⚠️ 2026-09-21 : 단계 사이에 seqWait() 를 넣었습니다.
 *      서보가 연속으로 계속 움직이면 전류를 계속 끌어다 써서
 *      보드가 리셋됩니다. 잠깐 쉬는 틈을 주면 전압이 회복됩니다. */
void doDoriDori() {
  if (seqBusy) return;
  seqAdd(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  seqWait(150);                                /* 전류 회복 대기 */
  seqAdd(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  seqWait(150);
  seqAdd(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  seqWait(150);
  seqAdd(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  seqWait(150);
  seqAdd(PIN_HEAD, CENTER,     MS_FAST);
  seqCommit();
}

/* -- 삐졌어 -- 고개 푹 떨구기 (9번 서보) */
void doSajin() {
  if (seqBusy) return;
  seqAdd(PIN_HEAD, CENTER,   MS_FAST);
  seqAdd(PIN_HEAD, SAD_DOWN, MS_SLOW);
  seqWait(800);                    /* 잠깐 쉬기 (블루투스는 계속 살아있음) */
  seqAdd(PIN_HEAD, CENTER,   MS_NORMAL);
  seqCommit();
}

/* -- 안녕 -- 끄덕끄덕 인사 (7번 서보) */
void doHello() {
  if (seqBusy) return;
  seqAdd(PIN_ARM, HI_UP,   MS_FAST);
  seqAdd(PIN_ARM, HI_DOWN, MS_NORMAL);
  seqAdd(PIN_ARM, HI_UP,   MS_NORMAL);
  seqAdd(PIN_ARM, HI_DOWN, MS_NORMAL);
  seqAdd(PIN_ARM, CENTER,  MS_FAST);
  seqCommit();
}

/* ===========================================================================
 *  함수 미리 알리기 (전방 선언)
 *    C++ 는 위에서 아래로 읽기 때문에, 아래에 정의된 함수를 위에서 쓰려면
 *    "이런 함수가 있다"고 미리 알려줘야 합니다.
 *
 *    handleAiCommand : nubida_ai.h 에 정의되어 있습니다 (아래에서 include)
 *    runCommand      : nubida_bt.h 가 이 함수를 씁니다
 * =========================================================================== */
bool handleAiCommand(String cmd);
bool runCommand(String cmd);

/* ===========================================================================
 *  【명령 처리】 - 한 줄을 받아서 알맞은 동작 실행
 *
 *  ★ 오동작 방지 3원칙
 *    ① 두 자릿수 번호를 한 자리로 오인하지 않습니다.
 *         "11NubidaAi" -> "Nubida" 가 2번째 -> 무시
 *    ② 번호 뒤에는 반드시 "Nubida" 가 와야 합니다.
 *         BLE 는 긴 명령을 잘라 보냅니다. "1" 조각만으로는 움직이지 않습니다.
 *    ③ AI 명령 구역에 들어오면 무조건 그 안에서 끝냅니다.
 *         아래 평문 검사로 흘러가지 않습니다.
 * =========================================================================== */
bool runCommand(String cmd) {

  /* ---------------------------------------------------------------------
   *  ★ 1단계 - AI 명령(난독화를 푼 명령)인지 먼저 확인
   *     "Nubida" 라는 글자가 있으면 AI 명령으로 봅니다.
   * ------------------------------------------------------------------- */
  int np = cmd.indexOf("Nubida");

  if (np >= 0) {

    /* (1) 번호는 반드시 맨 앞 한 글자여야 합니다. */
    if (np != 1) {
      Serial.print(F("[무시] 번호 자릿수가 맞지 않습니다 -> "));
      Serial.println(cmd);
      return true;      /* 여기서 끝. 아래로 흘러가지 않습니다. */
    }

    char n = cmd.charAt(0);

    /* (2) 맨 앞이 숫자가 아니면 무시 */
    if (n < '0' || n > '9') {
      Serial.print(F("[무시] 번호가 아닙니다 -> "));
      Serial.println(cmd);
      return true;
    }

    /* (3) 1~3번 - 정해진 동작 실행 */
    if (n == '1') {
      Serial.println(F("[동작] 도리도리"));
      doDoriDori();
      return true;
    }
    if (n == '2') {
      Serial.println(F("[동작] 삐졌어"));
      doSajin();
      return true;
    }
    if (n == '3') {
      Serial.println(F("[동작] 안녕"));
      doHello();
      return true;
    }

    /* ==================================================================
     *  ★★ 새 번호에 동작을 추가하려면 여기에 넣으시면 됩니다 ★★
     *
     *      6번에 "춤추기" 를 넣고 싶다면 아래를 복사해 // 를 지우세요.
   *
   *      ★ 동작 함수 안에서는 servoTo 대신 seqAdd 를 쓰세요.
   *         seqAdd(핀, 각도, 걸리는시간);   <- 예약만 하고 바로 돌아옴
   *         seqWait(밀리초);                <- 잠깐 쉬기
   *         맨 끝에 seqCommit();            <- 반드시 넣어야 실행됩니다
     *
     *      if (n == '6') {
     *        Serial.println(F("[동작] 춤추기"));
     *        doHello();          // <- 원하는 동작 함수 이름으로 바꾸세요
     *        return true;
     *      }
     *
     *  ⚠️ return true; 를 꼭 남겨두세요. 빼면 아래 평문 검사로
     *     흘러가서 엉뚱한 동작이 실행될 수 있습니다.
     * ================================================================ */

    /* (4) 그 외 번호(0, 4~9) - 이 로봇에 정의되지 않은 번호입니다. */
    Serial.print(F("[무시] "));
    Serial.print(n);
    Serial.println(F("번 - 이 로봇에 정의되지 않은 번호입니다 (움직이지 않습니다)"));
    return true;        /* 여기서 끝. 평문 검사로 흘러가지 않습니다. */
  }

  /* ---------------------------------------------------------------------
   *  ★ 2단계 - AI 가 만들어 준 코드 명령 (digitalWrite, tone 등)
   * ------------------------------------------------------------------- */
  if (handleAiCommand(cmd)) return true;

  /* ---------------------------------------------------------------------
   *  ★ 3단계 - 그 밖의 평문 명령
   *     ⚠️ 숫자 한 글자("1","2","3")는 절대 여기에 넣지 마세요.
   *        블루투스가 명령을 잘라 보낼 때 그 조각만 도착해서
   *        로봇이 저절로 움직이는 원인이 됩니다.
   * ------------------------------------------------------------------- */

  return false;    /* 모르는 명령 */
}

/* ===========================================================================
 *  블루투스 + AI 명령 불러오기
 *    ⚠️ 둘 다 runCommand() / servoTo() 가 정의된 "뒤"에 와야 합니다.
 *       (이 파일들 안에서 그 함수들을 쓰기 때문입니다)
 * =========================================================================== */
#include "nubida_ai.h"
#include "nubida_bt.h"

/* ===========================================================================
 *  setup / loop
 * =========================================================================== */
void setup() {
  /* ⚠️ 2026-09-21 추가 : 리셋 횟수를 EEPROM 에 기록해서 "정말 리셋되었는지" 확인
   *   (부트로더가 MCUSR 플래그를 지우기 때문에 레지스터만으로는 알 수 없습니다)
   *   EEPROM 주소 0~1 에 부팅 횟수를 저장합니다. */
  uint16_t bootCount;
  EEPROM.get(0, bootCount);
  if (bootCount == 0xFFFF) bootCount = 0;   /* 새 칩 */
  bootCount++;
  EEPROM.put(0, bootCount);

  Serial.begin(9600);
  nubidaBtBegin();

  for (int i = 0; i < 2; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(CENTER);
    srvCur[i]     = CENTER;
    srvCurSent[i] = CENTER;      /* ⚠️ 2026-09-21 : 실제 전송값 기록 */
  }
  delay(300);

  Serial.print(F("[부팅횟수] "));
  Serial.println(bootCount);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  도리도리 로봇 v7  (깔끔하게 정리한 판)"));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));      Serial.println(F(__TIME__));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  도리도리 · 삐졌어  ->  "));
  Serial.print(PIN_HEAD); Serial.println(F("번 서보"));
  Serial.print(F("  안녕               ->  "));
  Serial.print(PIN_ARM);  Serial.println(F("번 서보"));
  Serial.print(F("  부저               ->  "));
  Serial.print(PIN_BUZZ); Serial.println(F("번 핀"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  1NubidaAi -> 도리도리"));
  Serial.println(F("  2NubidaAi -> 삐졌어"));
  Serial.println(F("  3NubidaAi -> 안녕"));
  Serial.println(F("  4~9NubidaAi -> 무시 (정의되지 않은 번호)"));
  Serial.println(F("  + AI 명령 13종"));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
}

void loop() {
  nubidaBtUpdate();   /* 블루투스 수신 - 항상 최우선 */
  seqUpdate();        /* 서보 움직임 - 조금씩 진행 (delay 없음) */
}