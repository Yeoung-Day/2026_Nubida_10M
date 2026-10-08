#include <Servo.h>
#include <SoftwareSerial.h>
#include <stdio.h>

/* ── 부품/서보 객체 (파트2 에서 먼저 참조하므로 맨 앞에 선언) ── */
Servo srvObj9;
Servo srvObj7;
Servo myServo;
SoftwareSerial BTSerial(2, 3);   // RX=2, TX=3

/* 서보 객체 얻기 (핀별 단일 객체 — 같은 핀을 두 객체가 잡으면 타이머 충돌) */
Servo* servoForPin(uint8_t pin) {
  if (pin == 7) return &srvObj7;
  return &srvObj9;
}

/* 전방 선언 — StepDef 를 쓰지 않는 것만 여기 둔다
 *  (StepDef 를 인자로 받는 runStep 은 구조체 정의 직후에 선언한다) */
void finishAction();
void startAction(int idx);
void stepServos();
void processLine(String line);
bool handleLegacyCommand(String cmd);
bool actionDispatch(String cmd);
String decodeFrame(String frame);
int  hexVal(char c);
void drainBle();

/* ============================================================================
 *                                                                            
 *   누비다머신 통합 펌웨어  v20  (부품표 + 동작표 방식)                       
 *                                                                            
 * ============================================================================
 *
 *  ★★★  윤비스님 사용법 (딱 3단계)  ★★★
 *
 *  ┌──────────────────────────────────────────────────────────────────────┐
 *  │  1단계.  [부품표] DEVICES[]  — 내가 가진 부품을 등록한다             │
 *  │  2단계.  [신호표] SIGNALS[]  — "무엇을 어떻게 움직일지" 만든다        │
 *  │  3단계.  [동작표] ACTIONS[]  — 번호와 신호를 연결한다                │
 *  └──────────────────────────────────────────────────────────────────────┘
 *
 *  ── 이게 왜 편한가 ────────────────────────────────────────────────────
 *
 *   같은 명령(1NubidaAi)이 어떤 땐 서보, 어떤 땐 DC모터, 어떤 땐 융합.
 *   → 동작표에서 가리키는 신호표만 바꾸면 된다. 코드는 손 안 댄다.
 *
 *   ┌─ 서보만 쓰고 싶을 때 ────────────────────────────┐
 *   │  { "1NubidaAi", SIG_HEAD_ONLY, "머리숙이기" }    │
 *   └──────────────────────────────────────────────────┘
 *   ┌─ DC모터만 쓰고 싶을 때 ──────────────────────────┐
 *   │  { "1NubidaAi", SIG_MOTOR_ONLY, "앞으로" }       │
 *   └──────────────────────────────────────────────────┘
 *   ┌─ 융합하고 싶을 때 ───────────────────────────────┐
 *   │  { "1NubidaAi", SIG_GO, "출발" }                 │
 *   │  (신호표에서 서보+모터+LED+부저를 한꺼번에)       │
 *   └──────────────────────────────────────────────────┘
 *
 * ==========================================================================*/


/* ============================================================================
 *  [ 1 ] 부품표  —  내가 연결한 부품을 여기에 등록
 * ============================================================================
 *
 *   부품종류는 아래 6가지 중 하나:
 *      DEV_SERVO  서보모터      (값: 각도 0~180)
 *      DEV_MOTOR  DC모터(L9110S) (값: 속도 0~100)
 *      DEV_LED    LED스트립(WS2812) (값: 색상)
 *      DEV_TONE   수동부저       (값: 주파수 Hz)
 *      DEV_ULTRA  초음파(HC-SR04) (값: 거리 cm)
 *      DEV_NONE   안 씀 (자리 비우기)
 *
 *   ⚠️ 핀 번호는 실제로 꽂은 핀을 적으세요. 틀리면 안 움직입니다.
 * ==========================================================================*/

#define DEV_NONE   0
#define DEV_SERVO  1
#define DEV_MOTOR  2
#define DEV_LED    3
#define DEV_TONE   4
#define DEV_ULTRA  5

struct DeviceDef {
  uint8_t     pin;      // 신호 핀
  uint8_t     pin2;     // 두 번째 핀 (모터 IB핀, 초음파 ECHO핀)
  uint8_t     kind;     // 부품 종류
  const char* name;     // 이름 (로그용)
};

const DeviceDef DEVICES[] = {
  /*   핀   보조핀  부품종류    이름                                              */
  {    9,     0,    DEV_SERVO, "머리서보"   },    // 번호 0
  {    7,     0,    DEV_SERVO, "팔서보"     },    // 번호 1
  {    5,     4,    DEV_MOTOR, "바퀴모터"   },    // 번호 2  ← L9110S: IA=5, IB=4
  {    3,     0,    DEV_LED,   "눈LED"      },    // 번호 3  ← WS2812
  {    6,     0,    DEV_TONE,  "부저"       },    // 번호 4
  {   10,    11,    DEV_ULTRA, "거리센서"   },    // 번호 5  ← TRIG=10, ECHO=11
};
const uint8_t DEVICE_COUNT = sizeof(DEVICES) / sizeof(DEVICES[0]);

#define LED_COUNT 8       // ★ WS2812 LED 개수 — 실제 개수로 바꾸세요


/* ============================================================================
 *  [ 2 ] 신호표  —  "무엇을 어떻게 움직일지" 묶음
 * ============================================================================
 *
 *   한 신호 = 동시에 움직일 부품들의 목록
 *
 *   각 줄: { 부품번호, 움직임종류, 값1, 값2, 시간(ms) }
 *
 *   움직임종류(ST_*):
 *      ST_SET     서보: 각도로 이동          값1=각도
 *      ST_SWEEP   서보: 값1↔값2 부드럽게     값1,값2=각도
 *      ST_SPIN    모터: 회전                 값1=속도(0~100), 값2=방향(0앞/1뒤)
 *      ST_STOP    모터: 정지
 *      ST_COLOR   LED:  색상                 값1=색(0xRRGGBB), 값2=개수(0=전체)
 *      ST_BLINK   LED:  깜빡임               값1=색, 값2=횟수
 *      ST_OFF     LED:  끄기
 *      ST_TONE    부저: 소리                 값1=주파수, 값2=길이(ms)
 *      ST_MEASURE 초음파: 거리 측정
 *      ST_WAIT    아무것도 안 하고 대기      값1=ms
 * ==========================================================================*/

#define ST_SET     0
#define ST_SWEEP   1
#define ST_SPIN    2
#define ST_STOP    3
#define ST_COLOR   4
#define ST_BLINK   5
#define ST_OFF     6
#define ST_TONE    7
#define ST_MEASURE 8
#define ST_WAIT    9

struct StepDef {
  uint8_t  dev;     // 부품번호 (DEVICES 의 순서)
  uint8_t  act;     // 움직임종류 (ST_*)
  int      v1;      // 값1
  int      v2;      // 값2
  uint16_t ms;      // 이 단계의 시간
};

/* runStep 은 StepDef 를 인자로 받으므로 구조체 정의 뒤에 선언한다 */
void runStep(const StepDef& s);

/* ─────────────────────────────────────────────────────────────────────────
 *  ▼▼▼ 여기서부터 신호를 만드세요 ▼▼▼
 *
 *  ★ ST_SWEEP 사용법 (헷갈리기 쉬움)
 *      ST_SWEEP 은  값1 로 이동한 뒤, 이어서 값2 로 이동한다.
 *      한 줄로 "값1 → 값2" 를 표현한다.
 *
 *      예) { 0, ST_SWEEP, 90, 160, 600 }   → 90도로 간 뒤 160도로 (숙임)
 *          { 0, ST_SET,   90,   0, 600 }   → 90도로만 (v2 무시)
 *
 *      안녕처럼 왕복하려면 ST_SWEEP 을 여러 줄 이어 붙인다:
 *          { 1, ST_SWEEP, 160,  60, 500 }  → 160 → 60
 *          { 1, ST_SWEEP,  60, 160, 500 }  → 60 → 160
 * ───────────────────────────────────────────────────────────────────────── */

/* ── 신호 A: 머리 서보 90 → 160 (숙였다가 복귀) ── */
const StepDef SIG_HEAD[] = {
  //  부품  움직임     값1  값2   시간
  {   0,   ST_SWEEP,  90,   0,  600 },   // 90도로 이동
  {   0,   ST_SWEEP, 160,   0,  600 },   // 160도로 숙임
  {   0,   ST_SWEEP,  90,   0,  400 },   // 90도로 복귀
};
const uint8_t SIG_HEAD_N = sizeof(SIG_HEAD) / sizeof(SIG_HEAD[0]);

/* ── 신호 B: 팔 서보 안녕 (90 → 160 → 60 → 160 → 90) ── */
const StepDef SIG_ARM[] = {
  {   1,   ST_SWEEP,  90,   0,  400 },   // 90도 (시작 위치)
  {   1,   ST_SWEEP, 160,   0,  500 },   // 팔 올림
  {   1,   ST_SWEEP,  60,   0,  500 },   // 팔 내림
  {   1,   ST_SWEEP, 160,   0,  500 },   // 다시 올림
  {   1,   ST_SWEEP,  60,   0,  500 },   // 다시 내림
  {   1,   ST_SWEEP,  90,   0,  400 },   // 원위치
};
const uint8_t SIG_ARM_N = sizeof(SIG_ARM) / sizeof(SIG_ARM[0]);

/* ── 신호 C: 바퀴 모터만 앞으로 ── */
const StepDef SIG_MOTOR[] = {
  {   2,   ST_SPIN,   80,  0,   1200 },   // 속도 80, 앞으로, 1.2초
  {   2,   ST_STOP,    0,  0,    100 },
};
const uint8_t SIG_MOTOR_N = sizeof(SIG_MOTOR) / sizeof(SIG_MOTOR[0]);

/* ── 신호 D: 눈 LED만 빨강 → 초록 깜빡 ── */
const StepDef SIG_LED[] = {
  {   3,   ST_COLOR,  0xFF0000, 0,  400 },
  {   3,   ST_BLINK,  0x00FF00, 3,  900 },
  {   3,   ST_OFF,    0, 0,          200 },
};
const uint8_t SIG_LED_N = sizeof(SIG_LED) / sizeof(SIG_LED[0]);

/* ── 신호 E: 부저만 삐 삐 ── */
const StepDef SIG_BUZZ[] = {
  {   4,   ST_TONE,   880, 150,  250 },
  {   4,   ST_TONE,   880, 150,  250 },
};
const uint8_t SIG_BUZZ_N = sizeof(SIG_BUZZ) / sizeof(SIG_BUZZ[0]);

/* ── ★★ 신호 F: 융합! 서보 + 모터 + LED + 부저 동시 ── */
const StepDef SIG_GO[] = {
  {   0,   ST_SWEEP,  90,   0,  400 },    // 머리 90도로
  {   0,   ST_SWEEP, 160,   0,  600 },    // 머리 숙임
  {   2,   ST_SPIN,   70,   0,  600 },    // 바퀴 앞으로
  {   3,   ST_COLOR,  0x0000FF, 0, 600 }, // 눈 파랑
  {   4,   ST_TONE,  1046, 200, 600 },    // 삐!
  {   0,   ST_SWEEP,  90,   0,  400 },    // 머리 복귀
  {   2,   ST_STOP,    0,   0,  100 },    // 모터 정지
};
const uint8_t SIG_GO_N = sizeof(SIG_GO) / sizeof(SIG_GO[0]);

/* ── ★★ 신호 G: 초음파로 장애물 감지하면 멈추기 ── */
const StepDef SIG_AVOID[] = {
  {   2,   ST_SPIN,   70,   0,  300 },    // 일단 앞으로
  {   5,   ST_MEASURE, 0,   0,  500 },    // 거리 측정
  {   2,   ST_STOP,    0,   0,  100 },    // 모터 정지
  {   4,   ST_TONE,   440, 300, 400 },    // 경고음
};
const uint8_t SIG_AVOID_N = sizeof(SIG_AVOID) / sizeof(SIG_AVOID[0]);


/* ============================================================================
 *  [ 3 ] 동작표  —  번호와 신호를 연결
 * ============================================================================
 *
 *   { "명령어", 신호배열, 단계개수, "이름" }
 *
 *   ★ 바꿔가면서 쓰는 방법:
 *       서보를 쓰고 싶으면  → SIG_HEAD 로 연결
 *       모터를 쓰고 싶으면  → SIG_MOTOR 로 연결
 *       융합하고 싶으면     → SIG_GO 로 연결
 *     명령어("1NubidaAi")는 그대로 두고 신호만 바꾸면 됩니다.
 * ==========================================================================*/

struct ActionDef {
  const char*    token;   // BLE 명령 (아두이노가 복호화 후 얻는 문자열)
  const StepDef* sig;     // 신호표
  uint8_t        n;       // 단계 개수
  const char*    label;   // 이름 (로그용)
};

const ActionDef ACTIONS[] = {
  /*   명령어         신호        단계수      이름          */
  { "1NubidaAi",  SIG_HEAD,   SIG_HEAD_N,  "머리숙이기" },   // ← 서보
  { "2NubidaAi",  SIG_ARM,    SIG_ARM_N,   "안녕"       },   // ← 서보
  { "3NubidaAi",  SIG_MOTOR,  SIG_MOTOR_N, "앞으로"     },   // ← DC모터
  { "4NubidaAi",  SIG_LED,    SIG_LED_N,   "불켜기"     },   // ← LED스트립
  { "5NubidaAi",  SIG_BUZZ,   SIG_BUZZ_N,  "삐삐"       },   // ← 부저
  { "6NubidaAi",  SIG_GO,     SIG_GO_N,    "출발"       },   // ← ★융합
  { "7NubidaAi",  SIG_AVOID,  SIG_AVOID_N, "장애물감지" },   // ← ★융합
};
const uint8_t ACTION_COUNT = sizeof(ACTIONS) / sizeof(ACTIONS[0]);

/* ============================================================================
 *  [ 4 ] 실행 엔진  —  아래는 건드리지 않아도 됩니다
 * ============================================================================
 *
 *   신호표를 읽어서 부품별로 실제 동작을 실행한다.
 *   - 서보/모터/LED/부저/초음파 각각을 처리
 *   - 한 동작 안에서 여러 부품이 동시에 움직인다
 *   - 블로킹 delay 금지 (수신을 막지 않기 위해)
 * ==========================================================================*/

/* ── 진행 상태 ── */
int           actIdx     = -1;    // 실행 중인 동작 (-1 = 없음)
uint8_t       actStep    = 0;     // 현재 단계
unsigned long actStepAt  = 0;     // 이 단계 시작 시각
unsigned long actDeadline = 0;    // 전체 제한 시각

/* 서보 각도 진행용 (부품별) */
int  srvCur[8];
int  srvFrom[8];
int  srvTo[8];
unsigned long srvLast[8];

/* ── 대기 큐 (최대 6개) ── */
#define Q_MAX 6
int      qIdx[Q_MAX];
uint8_t  qHead = 0, qTail = 0;

bool qEmpty() { return qHead == qTail; }
void qPush(int v) {
  uint8_t n = (uint8_t)((qTail + 1) % Q_MAX);
  if (n == qHead) { Serial.println(F("[경고] 큐 가득참")); return; }
  qIdx[qTail] = v; qTail = n;
}
int qPop() {
  if (qEmpty()) return -1;
  int v = qIdx[qHead];
  qHead = (uint8_t)((qHead + 1) % Q_MAX);
  return v;
}

/* ── 부품별 초기화 ── */
void deviceSetup() {
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    const DeviceDef& d = DEVICES[i];
    if (d.kind == DEV_SERVO) {
      // 서보는 attach 안 함 (동작 시작 시 attach — 떨림 방지)
    } else if (d.kind == DEV_MOTOR) {
      pinMode(d.pin, OUTPUT);  digitalWrite(d.pin, LOW);
      pinMode(d.pin2, OUTPUT); digitalWrite(d.pin2, LOW);
    } else if (d.kind == DEV_LED) {
      // WS2812 초기화는 준비되면 추가
    } else if (d.kind == DEV_TONE) {
      pinMode(d.pin, OUTPUT);
    } else if (d.kind == DEV_ULTRA) {
      pinMode(d.pin, OUTPUT);              // TRIG
      pinMode(d.pin2, INPUT);              // ECHO
      digitalWrite(d.pin, LOW);
    }
    srvCur[i] = 90; srvFrom[i] = 90; srvTo[i] = 90; srvLast[i] = 0;
  }
}

/* ── 부품 하나 실행 ──────────────────────────────────────────────────────── */
void runStep(const StepDef& s) {
  const DeviceDef& d = DEVICES[s.dev];

  switch (s.act) {

    case ST_SET:
      if (d.kind == DEV_SERVO) {
        srvFrom[s.dev] = srvCur[s.dev];
        srvTo[s.dev]   = s.v1;
        srvLast[s.dev] = millis();
        Serial.print(F("[서보] ")); Serial.print(d.name);
        Serial.print(F(" → ")); Serial.print(s.v1); Serial.println(F("도"));
      }
      break;

    /* ★ ST_SWEEP — 값1 ↔ 값2 를 부드럽게 왕복
     *   값2 가 0 이면 값1 로 한 번만 이동한다.
     *   (여러 단계를 이어 붙이면 안녕(90→160→60) 같은 동작이 된다) */
    case ST_SWEEP:
      if (d.kind == DEV_SERVO) {
        srvFrom[s.dev] = srvCur[s.dev];
        srvTo[s.dev]   = (s.v2 != 0) ? s.v2 : s.v1;
        srvLast[s.dev] = millis();
        Serial.print(F("[서보] ")); Serial.print(d.name);
        Serial.print(F(" ")); Serial.print(srvCur[s.dev]);
        Serial.print(F(" → ")); Serial.print(srvTo[s.dev]);
        Serial.println(F("도"));
      }
      break;

    case ST_SPIN:
      if (d.kind == DEV_MOTOR) {
        int spd = s.v1; if (spd < 0) spd = 0; if (spd > 100) spd = 100;
        int pwm = map(spd, 0, 100, 0, 255);
        if (s.v2 == 0) {                    // 앞으로
          analogWrite(d.pin, pwm); digitalWrite(d.pin2, LOW);
        } else {                            // 뒤로
          digitalWrite(d.pin, LOW); analogWrite(d.pin2, pwm);
        }
        Serial.print(F("[모터] ")); Serial.print(d.name);
        Serial.print(F(" 속도 ")); Serial.print(spd);
        Serial.println(s.v2 == 0 ? F("% 앞으로") : F("% 뒤로"));
      }
      break;

    case ST_STOP:
      if (d.kind == DEV_MOTOR) {
        digitalWrite(d.pin, LOW); digitalWrite(d.pin2, LOW);
        Serial.print(F("[모터] ")); Serial.print(d.name); Serial.println(F(" 정지"));
      }
      break;

    case ST_COLOR:
      if (d.kind == DEV_LED) {
        Serial.print(F("[LED] ")); Serial.print(d.name);
        Serial.print(F(" 색 0x"));
        { char hb[9]; snprintf(hb, sizeof(hb), "%06X", (unsigned int)(s.v1 & 0xFFFFFF));
          Serial.println(hb); }
        // ★ WS2812 라이브러리 준비되면 여기서 실행
      }
      break;

    case ST_BLINK:
      if (d.kind == DEV_LED) {
        Serial.print(F("[LED] ")); Serial.print(d.name);
        Serial.print(F(" 깜빡 ")); Serial.print(s.v2); Serial.println(F("회"));
      }
      break;

    case ST_OFF:
      if (d.kind == DEV_LED) {
        Serial.print(F("[LED] ")); Serial.print(d.name); Serial.println(F(" 끔"));
      }
      break;

    case ST_TONE:
      if (d.kind == DEV_TONE) {
        tone(d.pin, s.v1, s.v2);
        Serial.print(F("[부저] ")); Serial.print(d.name);
        Serial.print(F(" ")); Serial.print(s.v1); Serial.println(F("Hz"));
      }
      break;

    case ST_MEASURE:
      if (d.kind == DEV_ULTRA) {
        digitalWrite(d.pin, LOW);  delayMicroseconds(2);
        digitalWrite(d.pin, HIGH); delayMicroseconds(10);
        digitalWrite(d.pin, LOW);
        unsigned long dur = pulseIn(d.pin2, HIGH, 30000);
        float cm = dur / 58.0;
        Serial.print(F("[초음파] ")); Serial.print(d.name);
        Serial.print(F(" 거리 ")); Serial.print((int)cm); Serial.println(F("cm"));
      }
      break;

    case ST_WAIT:
      break;
  }
}

/* ── 동작 시작 ───────────────────────────────────────────────────────────── */
void startAction(int idx) {
  const ActionDef& a = ACTIONS[idx];
  actIdx    = idx;
  actStep   = 0;
  actStepAt = millis();

  /* ★ 서보 attach + 각도 상태 초기화
   *   ⚠️ srvTo 를 반드시 여기서 잡아준다.
   *      초기값(90)이 그대로면 stepServos() 가 "이미 목표에 도달"로 판단해
   *      서보가 전혀 움직이지 않는다. */
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind == DEV_SERVO) {
      Servo* sv = servoForPin(DEVICES[i].pin);
      sv->attach(DEVICES[i].pin);
      srvFrom[i] = srvCur[i];      // 지금 위치에서
      srvTo[i]   = srvCur[i];      // 일단 목표 = 현재 (움직임 없음)
      srvLast[i] = millis();
    }
  }
  delay(15);

  /* 전체 제한 시간 = 단계 시간 합 × 3 + 3초 */
  unsigned long total = 0;
  for (uint8_t i = 0; i < a.n; i++) total += a.sig[i].ms;
  actDeadline = millis() + total * 3UL + 3000UL;

  Serial.print(F("[동작] ")); Serial.print(a.label);
  Serial.print(F(" 시작 (단계 ")); Serial.print(a.n); Serial.println(F("개)"));

  /* 첫 단계 실행 — runStep 이 srvTo 를 목표각으로 세팅한다 */
  if (a.n > 0) runStep(a.sig[0]);
}

/* ── 서보 부드럽게 이동 (매 루프) ────────────────────────────────────────── */
void stepServos() {
  if (actIdx < 0) return;
  unsigned long now = millis();
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind != DEV_SERVO) continue;
    if (srvCur[i] == srvTo[i]) continue;
    if (now - srvLast[i] < 25) continue;
    srvLast[i] = now;

    int target = srvTo[i];
    if (srvCur[i] < target) {
      srvCur[i] += 3;
      if (srvCur[i] > target) srvCur[i] = target;
    } else {
      srvCur[i] -= 3;
      if (srvCur[i] < target) srvCur[i] = target;
    }
    if (srvCur[i] < 0) srvCur[i] = 0;
    if (srvCur[i] > 180) srvCur[i] = 180;

    Servo* sv = servoForPin(DEVICES[i].pin);
    sv->write(srvCur[i]);
  }
}

/* ── 동작 1스텝 (loop 에서 매번 호출) ────────────────────────────────────── */
void stepAction() {

  /* 실행 중인 게 없으면 큐에서 꺼내 시작 */
  if (actIdx < 0) {
    int nx = qPop();
    if (nx >= 0) startAction(nx);
    return;
  }

  /* 제한 시간 초과 → 강제 종료 */
  if (actDeadline != 0 && (long)(millis() - actDeadline) > 0) {
    Serial.println(F("[경고] 시간 초과 — 강제 종료"));
    finishAction();
    return;
  }

  stepServos();

  const ActionDef& a = ACTIONS[actIdx];

  /* 서보가 아직 이동 중이면 기다림 */
  bool moving = false;
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind == DEV_SERVO && srvCur[i] != srvTo[i]) moving = true;
  }
  if (moving) return;

  /* 현재 단계 시간이 끝났으면 다음 단계 */
  if (millis() - actStepAt < (unsigned long)a.sig[actStep].ms) return;

  actStep++;
  if (actStep >= a.n) {
    finishAction();
    return;
  }

  actStepAt = millis();
  runStep(a.sig[actStep]);
}

/* ── 동작 종료 ───────────────────────────────────────────────────────────── */
void finishAction() {
  if (actIdx < 0) return;

  /* 서보 전원 해제 (떨림 방지) */
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind == DEV_SERVO) {
      Servo* sv = servoForPin(DEVICES[i].pin);
      sv->write(srvCur[i]);
      delay(30);
      sv->detach();
    }
    /* 모터는 반드시 정지 */
    if (DEVICES[i].kind == DEV_MOTOR) {
      digitalWrite(DEVICES[i].pin, LOW);
      digitalWrite(DEVICES[i].pin2, LOW);
    }
    /* 부저 끄기 */
    if (DEVICES[i].kind == DEV_TONE) {
      noTone(DEVICES[i].pin);
    }
  }

  Serial.print(F("[완료] "));
  Serial.println(ACTIONS[actIdx].label);

  actIdx = -1;
  actDeadline = 0;
}

/* ============================================================================
 *  [ 5 ] 통신부  —  BLE 수신 · 복호화 · 기존문법 (v18 기능 전부 유지)
 * ==========================================================================*/

#define NB_KEY       0x2F
#define FRAME_GAP_MS 30
#define MAX_RX       256

char          rxBuf[MAX_RX];
int           rxLen    = 0;
unsigned long lastRxAt = 0;

/* 기존문법 변수 (원본 유지) */
int piezo, buzzer, buzzer1, SeRe, pwm, cho, pos1, pos2, pos;
int Servopin, Servopos, serial;
int trig5, echo5, trig, echo, digitalHIGH, digitalLOW;

/* ── 난독화 복호화 ── */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";

  String out = "";
  for (unsigned int i = 2; i + 1 < hexs.length(); i += 2) {
    int h1 = hexVal(hexs.charAt(i));
    int h2 = hexVal(hexs.charAt(i + 1));
    if (h1 < 0 || h2 < 0) continue;
    char c = (char)((h1 * 16 + h2) ^ seed);
    if (c != '\0' && c >= 32 && c < 127) out += c;
  }
  out.trim();
  return out;
}

/* ── 동작 판정 ── */
bool actionDispatch(String cmd) {
  for (uint8_t i = 0; i < ACTION_COUNT; i++) {
    const char* tok = ACTIONS[i].token;
    String full(tok);
    String pre = full.substring(0, full.length() - 2);

    bool hit = false;
    if (cmd.equals(full))            hit = true;
    else if (cmd.indexOf(pre) >= 0)  hit = true;
    else if (cmd.length() == 1 && cmd.charAt(0) == tok[0]) hit = true;

    if (hit) {
      if (actIdx < 0) startAction(i);
      else            qPush(i);
      return true;
    }
  }
  return false;
}

/* ── 기존문법 (원본 유지) ── */
bool handleLegacyCommand(String cmd) {

  int HIGHa = cmd.indexOf("digitalWrite(");
  int HIGHb = cmd.indexOf(",H);");
  String HIGHResult = (HIGHa >= 0 && HIGHb > HIGHa) ? cmd.substring(HIGHa + 13, HIGHb) : "";

  int LOWa = cmd.indexOf("digitalWrite(");
  int LOWb = cmd.indexOf(",L);");
  String LOWResult = (LOWa >= 0 && LOWb > LOWa) ? cmd.substring(LOWa + 13, LOWb) : "";

  int ifa = cmd.indexOf("if(cho < ");
  int ifb = cmd.indexOf(")");
  String ifResult1 = (ifa >= 0 && ifb > ifa) ? cmd.substring(ifa + 9, ifb) : "";

  int ifposa = cmd.indexOf("if(pos < ");
  int ifposb = cmd.indexOf(")");
  String ifposResult1 = (ifposa >= 0 && ifposb > ifposa) ? cmd.substring(ifposa + 9, ifposb) : "";

  int ifpos2a = cmd.indexOf("if(pos > ");
  int ifpos2b = cmd.indexOf(")");
  String ifposResult2 = (ifpos2a >= 0 && ifpos2b > ifpos2a) ? cmd.substring(ifpos2a + 9, ifpos2b) : "";

  int tonea = cmd.indexOf("tone(");
  int toneb = cmd.indexOf(",");
  int tonec = cmd.indexOf(");");
  String toneResult1 = (tonea >= 0 && toneb > tonea) ? cmd.substring(tonea + 5, toneb) : "";
  String toneResult2 = (toneb >= 0 && tonec > toneb) ? cmd.substring(toneb + 1, tonec) : "";

  int notonea = cmd.indexOf("noTone(");
  int notoneb = cmd.indexOf(");");
  String notoneResult1 = (notonea >= 0 && notoneb > notonea) ? cmd.substring(notonea + 7, notoneb) : "";

  int inta = cmd.indexOf("int ");
  int intb = cmd.indexOf(" = ");
  int intc = cmd.indexOf(";");
  String intResult1 = (inta >= 0 && intb > inta) ? cmd.substring(inta + 4, intb) : "";
  String intResult2 = (intb >= 0 && intc > intb) ? cmd.substring(intb + 3, intc) : "";

  int Seriala = cmd.indexOf("Serial.print(");
  int Serialb = cmd.indexOf(");");
  String SerialResult = (Seriala >= 0 && Serialb > Seriala) ? cmd.substring(Seriala + 13, Serialb) : "";

  int cho_modea = cmd.indexOf("BT.print(t");
  int cho_modeb = cmd.indexOf(",e");
  int cho_modec = cmd.indexOf(");");
  String cho_modeaResult1 = (cho_modea >= 0 && cho_modeb > cho_modea) ? cmd.substring(cho_modea + 10, cho_modeb) : "";
  String cho_modeaResult2 = (cho_modeb >= 0 && cho_modec > cho_modeb) ? cmd.substring(cho_modeb + 2, cho_modec) : "";

  int Servoa = cmd.indexOf("pos.write(m");
  int Servob = cmd.indexOf(",");
  int Servoc = cmd.indexOf(");");
  String ServoResult1 = (Servoa >= 0 && Servob > Servoa) ? cmd.substring(Servoa + 11, Servob) : "";
  String ServoResult2 = (Servob >= 0 && Servoc > Servob) ? cmd.substring(Servob + 1, Servoc) : "";

  int Piano_modea = cmd.indexOf("Piano.mode(t");
  int Piano_modeb = cmd.indexOf(",e");
  int Piano_modec = cmd.indexOf(",m");
  int Piano_moded = cmd.indexOf(");");
  String Piano_modeaResult1 = (Piano_modea >= 0 && Piano_modeb > Piano_modea) ? cmd.substring(Piano_modea + 12, Piano_modeb) : "";
  String Piano_modeaResult2 = (Piano_modeb >= 0 && Piano_modec > Piano_modeb) ? cmd.substring(Piano_modeb + 2, Piano_modec) : "";
  String Piano_modeaResult3 = (Piano_modec >= 0 && Piano_moded > Piano_modec) ? cmd.substring(Piano_modec + 2, Piano_moded) : "";

  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
    pinMode(digitalHIGH, OUTPUT); digitalWrite(digitalHIGH, HIGH); delay(100); return true;
  }
  else if (cmd.equals("digitalWrite(" + LOWResult + ",L);")) {
    pinMode(digitalLOW, OUTPUT); digitalWrite(digitalLOW, LOW); delay(100); return true;
  }
  else if (cmd.equals("int " + intResult1 + " = " + intResult2 + ";")) {
    BTSerial.println(intResult1 + "의 변수명은 " + intResult2 + "번의 핀을 사용합니다.");
    delay(100); return true;
  }
  else if (cmd.equals("Serial.print(" + SerialResult + ");")) {
    int Result; pinMode(SeRe, INPUT); Result = digitalRead(SeRe);
    BTSerial.println(Result); delay(100); return true;
  }
  else if (cmd.equals("if(cho < " + ifResult1 + ")")) {
    pinMode(7, OUTPUT); srvObj9.attach(9); pinMode(10, OUTPUT); pinMode(11, INPUT);
    digitalWrite(10, LOW); digitalWrite(11, LOW); delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);
    unsigned long d1 = pulseIn(11, HIGH);
    float distance = d1 / 29.0 / 2.0; delay(10);
    if (distance < 11) { tone(7, 262); srvObj9.write(170); delay(1000); }
    else               { noTone(7);    srvObj9.write(90);  delay(1000); }
    srvObj9.detach(); return true;
  }
  else if (cmd.equals("if(pos < " + ifposResult1 + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    srvObj9.attach(9); srvObj9.write(45);
    digitalWrite(4, HIGH); digitalWrite(5, LOW);
    digitalWrite(6, HIGH); digitalWrite(7, LOW);
    delay(100); return true;
  }
  else if (cmd.equals("stop")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    digitalWrite(4, LOW); digitalWrite(5, LOW);
    digitalWrite(6, LOW); digitalWrite(7, LOW);
    delay(100); return true;
  }
  else if (cmd.equals("if(pos > " + ifposResult2 + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    srvObj9.attach(9); srvObj9.write(135);
    digitalWrite(4, LOW); digitalWrite(6, LOW); digitalWrite(7, HIGH);
    delay(100); return true;
  }
  else if (cmd.equals("BT.print(t" + cho_modeaResult1 + ",e" + cho_modeaResult2 + ");")) {
    pinMode(trig5, OUTPUT); pinMode(echo5, INPUT);
    digitalWrite(trig5, LOW); digitalWrite(echo5, LOW); delayMicroseconds(2);
    digitalWrite(trig5, HIGH); delayMicroseconds(10); digitalWrite(trig5, LOW);
    unsigned long d1 = pulseIn(echo5, HIGH);
    float distance = d1 / 29.0 / 2.0; delay(10);
    Serial.print(distance); Serial.println("cm");
    BTSerial.print(distance); BTSerial.println("cm");
    delay(1000); return true;
  }
  else if (cmd.equals("tone(" + toneResult1 + "," + toneResult2 + ");")) {
    pinMode(buzzer, OUTPUT); tone(buzzer, pwm); return true;
  }
  else if (cmd.equals("noTone(" + notoneResult1 + ");")) {
    pinMode(buzzer1, OUTPUT); noTone(buzzer1); return true;
  }
  else if (cmd.equals("Piano.mode")) {
    pinMode(7, OUTPUT); pinMode(10, OUTPUT); pinMode(11, INPUT);
    digitalWrite(10, LOW); digitalWrite(11, LOW); delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);
    unsigned long d1 = pulseIn(11, HIGH);
    float distance = d1 / 29.0 / 2.0; delay(10);
    if (distance < 4)         { tone(7, 262, 1000); delay(100); }
    else if (distance < 6.9)  { tone(7, 294, 1000); delay(100); }
    else if (distance < 9.8)  { tone(7, 330, 1000); delay(100); }
    else if (distance < 12.5) { tone(7, 349, 1000); delay(100); }
    else if (distance < 14.6) { tone(7, 392, 1000); delay(100); }
    else if (distance < 16)   { tone(7, 440, 1000); delay(100); }
    else if (distance < 18)   { tone(7, 494, 1000); delay(100); }
    else if (distance < 20.1) { tone(7, 523, 1000); delay(100); }
    else                      { noTone(7); delay(100); }
    return true;
  }
  else if (cmd.equals("pos.write(m" + ServoResult1 + "," + ServoResult2 + ");")) {
    myServo.attach(Servopin); srvObj9.write(Servopos); delay(100); return true;
  }
  else if (cmd.equals("Trash.mode")) {
    srvObj9.attach(9); pinMode(10, OUTPUT); pinMode(11, INPUT);
    digitalWrite(10, LOW); digitalWrite(11, LOW); delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);
    unsigned long d1 = pulseIn(11, HIGH);
    float distance = d1 / 29.0 / 2.0; delay(10);
    if (distance < 15) { srvObj9.write(180); delay(3000); }
    else               { srvObj9.write(85);  delay(1000); }
    srvObj9.detach(); return true;
  }

  return false;
}

/* ── 한 줄 처리 ── */
void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  String cmd = line;

  if (cmd.charAt(0) == 'x') {
    String d = decodeFrame(cmd);
    Serial.print(F("[복호화] "));
    Serial.print(cmd);
    Serial.print(F("  →  "));
    Serial.println(d.length() > 0 ? d : F("(빈값)"));
    if (d.length() == 0) return;
    cmd = d;
  }

  if (cmd.charAt(0) == '+') {
    Serial.print(F("[BLE이벤트] "));
    Serial.println(cmd);
    return;
  }

  if (actionDispatch(cmd)) return;

  if (handleLegacyCommand(cmd)) return;

  Serial.print(F("[무시] 알 수 없는 명령: '"));
  Serial.print(cmd);
  Serial.println(F("'"));
}

/* ── BLE 수신 (loop 최우선) ── */
void drainBle() {
  while (BTSerial.available() > 0) {
    char c = (char)BTSerial.read();
    if (rxLen < MAX_RX - 1) {
      rxBuf[rxLen++] = c;
    } else {
      rxLen = 0;   // 오버플로 → 리셋
    }
    lastRxAt = millis();
  }

  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    rxBuf[rxLen] = '\0';
    String line(rxBuf);
    rxLen = 0;

    // 개행 단위로 쪼개서 처리
    int start = 0;
    for (int i = 0; i < (int)line.length(); i++) {
      if (line.charAt(i) == '\n' || line.charAt(i) == '\r') {
        String one = line.substring(start, i);
        one.trim();
        if (one.length() > 0) processLine(one);
        start = i + 1;
      }
    }
    String tail = line.substring(start);
    tail.trim();
    if (tail.length() > 0) processLine(tail);
  }
}

/* ── 배너 ── */
void printBanner() {
  Serial.println(F(""));
  Serial.println(F("=== 누비다머신 v20 (부품표+동작표) ==="));
  Serial.print(F("[빌드] "));
  Serial.print(F(__DATE__));
  Serial.print(F(" "));
  Serial.println(F(__TIME__));
  Serial.print(F("[부품] 총 "));
  Serial.print(DEVICE_COUNT);
  Serial.println(F("개 등록됨"));
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    Serial.print(F("  "));
    Serial.print(i);
    Serial.print(F(") "));
    Serial.print(DEVICES[i].name);
    Serial.print(F(" — "));
    Serial.print(DEVICES[i].pin);
    Serial.println(F("번"));
  }
  Serial.print(F("[동작] 총 "));
  Serial.print(ACTION_COUNT);
  Serial.println(F("개 등록됨"));
  for (uint8_t i = 0; i < ACTION_COUNT; i++) {
    Serial.print(F("  "));
    Serial.print(ACTIONS[i].token);
    Serial.print(F(" → "));
    Serial.print(ACTIONS[i].label);
    Serial.print(F(" (단계 "));
    Serial.print(ACTIONS[i].n);
    Serial.println(F("개)"));
  }
  Serial.println(F("준비 완료"));
  Serial.println(F(""));
}

/* ── setup / loop ── */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  deviceSetup();
  printBanner();
}

void loop() {
  /* ★ 수신을 최우선으로 — 버퍼 오버플로 방지 */
  drainBle();

  /* 동작 진행 */
  stepAction();
}
