#include <Servo.h>
#include <SoftwareSerial.h>
#include <stdio.h>

/* ── 부품/서보 객체 (파트2 에서 먼저 참조하므로 맨 앞에 선언) ── */
/* ── 안전 상한 (윤비스님이 부품을 늘려도 깨지지 않게) ── */
#define MAX_DEVICES 24      // 부품 최대 24개
#define MAX_SERVO   12      // 서보 최대 12개

/* ── 서보 객체 풀: 부품표에 적은 핀마다 자동 배정 ──
 *   v20 은 핀 7,9 만 하드코딩이라 다른 핀에 서보를 달면 오동작했다.
 *   v21 은 어느 핀에 달아도 그 핀 전용 객체가 자동 생성된다. */
Servo   srvPool[MAX_SERVO];
int8_t  srvPinOf[MAX_SERVO];     // -1 = 빈 슬롯

SoftwareSerial BTSerial(2, 3);   // RX=2, TX=3

/* 이 핀용 서보 객체 반환 (없으면 자동 생성) */
Servo* servoForPin(uint8_t pin) {
  for (uint8_t i = 0; i < MAX_SERVO; i++)
    if (srvPinOf[i] == (int8_t)pin) return &srvPool[i];
  for (uint8_t i = 0; i < MAX_SERVO; i++) {
    if (srvPinOf[i] == -1) { srvPinOf[i] = (int8_t)pin; return &srvPool[i]; }
  }
  return &srvPool[0];            // 풀 초과 (setup 에서 경고)
}

/* 전방 선언 — StepDef 를 쓰지 않는 것만 여기 둔다
 *  (StepDef 를 인자로 받는 runStep 은 구조체 정의 직후에 선언한다) */
void finishAction();
void checkWiring();
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
 *  │  2단계.  [신호표] SIG_*[]    — "무엇을 어떻게 움직일지" 만든다        │
 *  │  3단계.  [동작 연결]         — actionDispatch() 의 if 문에서 연결     │
 *  └──────────────────────────────────────────────────────────────────────┘
 *
 *  ── 이게 왜 편한가 ────────────────────────────────────────────────────
 *
 *   같은 명령(1NubidaAi)이 어떤 땐 서보, 어떤 땐 DC모터, 어떤 땐 융합.
 *   → actionDispatch() 의 if 문에서 가리키는 신호표만 바꾸면 된다.
 *
 *   ┌─ 서보만 쓰고 싶을 때 ─────────────────────────────┐
 *   │  tryStart(SIG_HEAD,  SIG_HEAD_N,  "머리숙이기")   │
 *   └───────────────────────────────────────────────────┘
 *   ┌─ DC모터만 쓰고 싶을 때 ───────────────────────────┐
 *   │  tryStart(SIG_MOTOR, SIG_MOTOR_N, "앞으로")       │
 *   └───────────────────────────────────────────────────┘
 *   ┌─ 융합하고 싶을 때 ────────────────────────────────┐
 *   │  tryStart(SIG_GO,    SIG_GO_N,    "출발")         │
 *   │  (신호표에서 서보+모터+LED+부저를 한꺼번에)       │
 *   └───────────────────────────────────────────────────┘
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
  {    9,   255,    DEV_SERVO, "머리서보"   },    // 번호 0
  {    7,   255,    DEV_SERVO, "팔서보"     },    // 번호 1
  {    5,     4,    DEV_MOTOR, "바퀴L"      },    // 번호 2  ← L9110S: IA=5, IB=4
  {    3,   255,    DEV_LED,   "눈LED"      },    // 번호 3  ← WS2812
  {    6,   255,    DEV_TONE,  "부저"       },    // 번호 4
  {   10,    11,    DEV_ULTRA, "거리센서"   },    // 번호 5  ← TRIG=10, ECHO=11

/* ══════════════════════════════════════════════════════════════════════════
 *  ★★ 아래는 "늘리는 예시" 입니다. 필요할 때 // 를 지우면 바로 동작 ★★
 *      - 부품은 최대 24개(MAX_DEVICES), 서보는 최대 12개(MAX_SERVO) 까지 OK
 *      - 번호는 위에서부터 0,1,2,... 순서대로 자동 부여됩니다
 *      - 줄을 추가하면 번호가 밀리므로, 신호표의 부품번호도 같이 고치세요
 * ══════════════════════════════════════════════════════════════════════════ */

  // ── DC모터를 4개로 늘릴 때 (L9110S 4개: 핀 8개 필요) ──
  // {    8,    12,    DEV_MOTOR, "바퀴R"      },   // 번호 6
  // {   13,    A0,    DEV_MOTOR, "바퀴L2"     },   // 번호 7
  // {   A1,    A2,    DEV_MOTOR, "바퀴R2"     },   // 번호 8

  // ── 서보를 3개로 늘릴 때 ──
  // {    A3,   255,    DEV_SERVO, "꼬리서보"   },   // 번호 9

  // ── LED 스트립을 하나 더 달 때 ──
  // {   A4,   255,    DEV_LED,   "입LED"      },

/* ★ 위 3줄(모터 2개 추가)을 살리면 → 부품 9개 / 필요핀 16개
 *   4개까지 늘리면          → 부품 11개 / 필요핀 18개 (나노 만땅)
 *
 *   ⚠️ 모터 3개 이상은 나노 5V 로 전류 부족 → 외부 6~9V 전원 필수
 *      (외부 전원 GND 와 나노 GND 를 반드시 연결)
 * ══════════════════════════════════════════════════════════════════════════ */
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
 *  [ 3 ] 동작 연결  —  명령어와 신호를 if 문으로 연결
 * ============================================================================
 *
 *  ★ 추가하는 방법 (딱 한 덩어리)
 *
 *     else if (cmd.equals("8NubidaAi")) { startSig(SIG_HEAD, SIG_HEAD_N, "새동작"); return true; }
 *                        ↑명령어                              ↑신호표  ↑단계수  ↑이름
 *
 *  ★ 명령어 규칙 (기존과 동일하게 동작)
 *     "1NubidaAi" →  풀네임 "1NubidaAi" / 접두어 "1Nubida" / 한 글자 "1" 모두 인식
 *
 *  ★ 신호를 바꿔가며 쓰기
 *     서보를 쓰고 싶으면  → SIG_HEAD 로 연결
 *     모터를 쓰고 싶으면  → SIG_MOTOR 로 연결
 *     융합하고 싶으면     → SIG_GO 로 연결
 *     명령어("1NubidaAi")는 그대로 두고 신호표 이름만 바꾸면 됩니다.
 * ==========================================================================*/

/* 신호표를 받아 실행을 시작한다 (정의는 아래 실행 엔진부) */
void startSig(const StepDef* sig, uint8_t n, const char* label);


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
bool             actRun    = false;      // 실행 중인가
const StepDef*   actSig    = nullptr;    // 실행 중인 신호표
uint8_t          actSigN   = 0;          // 신호표 단계수
const char*      actLabel  = "";         // 동작 이름 (로그용)
uint8_t          actStep   = 0;          // 현재 단계
unsigned long    actStepAt = 0;          // 이 단계 시작 시각
unsigned long    actDeadline = 0;        // 전체 제한 시각

/* 서보 각도 진행용 (부품별) — v21: MAX_DEVICES 로 확장 */
int  srvCur[MAX_DEVICES];
int  srvFrom[MAX_DEVICES];
int  srvTo[MAX_DEVICES];
unsigned long srvLast[MAX_DEVICES];

/* 모터 상태 (부품별) — v21 추가. 모터 개수가 늘어도 자동 */
int     motSpd[MAX_DEVICES];      // 0~100
uint8_t motDir[MAX_DEVICES];      // 0=앞, 1=뒤
int     ledHue[MAX_DEVICES];      // LED 색
/* LED 깜빡임 상태 (비블로킹) */
uint16_t ledBlinks[MAX_DEVICES];      // 남은 횟수
uint16_t ledColor[MAX_DEVICES];       // 깜빡일 색
unsigned long ledNextAt[MAX_DEVICES]; // 다음 토글 시각
bool     ledOn[MAX_DEVICES];

/* ── 대기 큐 (최대 6개) — 신호표를 직접 담는다 ── */
#define Q_MAX 6
const StepDef* qSig[Q_MAX];
uint8_t        qN[Q_MAX];
const char*    qLabel[Q_MAX];
uint8_t  qHead = 0, qTail = 0;

bool qEmpty() { return qHead == qTail; }
void qPush(const StepDef* sig, uint8_t n, const char* label) {
  uint8_t nx = (uint8_t)((qTail + 1) % Q_MAX);
  if (nx == qHead) { Serial.println(F("[경고] 큐 가득참")); return; }
  qSig[qTail] = sig; qN[qTail] = n; qLabel[qTail] = label; qTail = nx;
}
bool qPop(const StepDef** sig, uint8_t* n, const char** label) {
  if (qEmpty()) return false;
  *sig = qSig[qHead]; *n = qN[qHead]; *label = qLabel[qHead];
  qHead = (uint8_t)((qHead + 1) % Q_MAX);
  return true;
}

/* ── 부품별 초기화 ── */
void deviceSetup() {
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    const DeviceDef& d = DEVICES[i];
    if (d.kind == DEV_SERVO) {
      // 서보는 attach 안 함 (동작 시작 시 attach — 떨림 방지)
    } else if (d.kind == DEV_MOTOR) {
      pinMode(d.pin, OUTPUT);  digitalWrite(d.pin, LOW);
      if (d.pin2 != 255) {                 // ★ pin2 미사용(255) 보호
        pinMode(d.pin2, OUTPUT); digitalWrite(d.pin2, LOW);
      } else {
        Serial.print(F("[경고] '"));
        Serial.print(d.name);
        Serial.println(F("' 모터에 보조핀(pin2)이 없습니다"));
      }
    } else if (d.kind == DEV_LED) {
      pinMode(d.pin, OUTPUT);              // 단색 LED / 릴레이
      digitalWrite(d.pin, LOW);
    } else if (d.kind == DEV_TONE) {
      pinMode(d.pin, OUTPUT);
    } else if (d.kind == DEV_ULTRA) {
      pinMode(d.pin, OUTPUT);              // TRIG
      if (d.pin2 != 255) pinMode(d.pin2, INPUT);   // ECHO (255 보호)
      digitalWrite(d.pin, LOW);
    }
    srvCur[i] = 90; srvFrom[i] = 90; srvTo[i] = 90; srvLast[i] = 0;
    motSpd[i] = 0; motDir[i] = 0; ledHue[i] = 0;
    ledBlinks[i] = 0; ledColor[i] = 0; ledNextAt[i] = 0; ledOn[i] = false;
  }
}

/* ══════════════════════════════════════════════════════════════════════════
 *  LED 제어  —  라이브러리 없이 동작 (핀 하나로 켜기/끄기 + PWM 밝기)
 * ══════════════════════════════════════════════════════════════════════════
 *
 *  ★ LED 종류별 동작
 *    - 단색 LED / 릴레이  → 디지털 ON/OFF (색은 무시, 밝기만 반영)
 *    - WS2812 스트립      → 아래 USE_WS2812 를 1 로 바꾸고 라이브러리 설치
 *
 *  ★ 지금 상태 (USE_WS2812 0)
 *    색 0x000000 이면 끔, 그 외면 켬.
 *    밝기는 analogWrite 로 (PWM 지원 핀 3,5,6,9,10,11).
 *    → 눈LED(3번) 처럼 "켜졌다 꺼졌다" 만 해도 충분한 경우 바로 사용 가능.
 * ══════════════════════════════════════════════════════════════════════════ */

#define USE_WS2812 0     // ★ 1 로 바꾸면 WS2812 사용 (Adafruit_NeoPixel 필요)

#if USE_WS2812
  #include <Adafruit_NeoPixel.h>
  Adafruit_NeoPixel* ledStrip[MAX_DEVICES] = {nullptr};
#endif

/* LED 켜기 (color = 0xRRGGBB, 0 이면 끔) */
void ledWrite(const DeviceDef& d, unsigned long color) {
  bool on = (color != 0);
  /* 밝기 추출 (R,G,B 중 최대값) */
  uint8_t bright = (uint8_t)(((color >> 16) & 0xFF) > (color & 0xFF) ?
                             ((color >> 16) & 0xFF) : (color & 0xFF));
  if (bright == 0 && on) bright = 255;

#if USE_WS2812
  /* WS2812: 핀당 스트립 객체 생성 후 색 전송 */
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].pin == d.pin && DEVICES[i].kind == DEV_LED) {
      if (!ledStrip[i]) {
        ledStrip[i] = new Adafruit_NeoPixel(LED_COUNT, d.pin, NEO_GRB + NEO_KHZ800);
        ledStrip[i]->begin();
      }
      uint32_t c = ledStrip[i]->Color((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF);
      for (uint16_t p = 0; p < LED_COUNT; p++) ledStrip[i]->setPixelColor(p, on ? c : 0);
      ledStrip[i]->show();
      return;
    }
  }
#else
  /* 라이브러리 없이: 디지털 ON/OFF + PWM 밝기 */
  if (!on) {
    digitalWrite(d.pin, LOW);
  } else {
    /* PWM 핀이면 밝기 조절, 아니면 그냥 켬 */
    if (d.pin == 3 || d.pin == 5 || d.pin == 6 ||
        d.pin == 9 || d.pin == 10 || d.pin == 11) {
      analogWrite(d.pin, bright);
    } else {
      digitalWrite(d.pin, HIGH);
    }
  }
#endif
}

/* 깜빡임 시작 (비블로킹) */
void ledBlinkStart(uint8_t devIdx, unsigned long color, uint16_t times, uint16_t ms) {
  if (devIdx >= MAX_DEVICES) return;
  ledBlinks[devIdx] = times * 2;          // 켬/꺼짐 각 1회 = 2토글
  ledColor[devIdx]  = (uint16_t)color;
  ledNextAt[devIdx] = millis() + (ms / 2);
  ledOn[devIdx]     = true;
}

/* 매 loop 호출 — 깜빡임 진행 */
void ledTick() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind != DEV_LED) continue;
    if (ledBlinks[i] == 0) continue;
    if ((long)(now - ledNextAt[i]) < 0) continue;

    ledOn[i] = !ledOn[i];
    ledWrite(DEVICES[i], ledOn[i] ? ledColor[i] : 0);
    ledBlinks[i]--;
    ledNextAt[i] = now + 250;             // 토글 간격 250ms
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
        ledWrite(d, s.v1);                 // ★ 실제로 켠다
        Serial.print(F("[LED] ")); Serial.print(d.name);
        Serial.print(F(" 색 0x"));
        { char hb[9]; snprintf(hb, sizeof(hb), "%06X", (unsigned int)(s.v1 & 0xFFFFFF));
          Serial.println(hb); }
      }
      break;

    case ST_BLINK:
      if (d.kind == DEV_LED) {
        /* 비블로킹 깜빡임 시작 (stepAction 에서 진행) */
        ledBlinkStart(s.dev, s.v1, s.v2, s.ms);
        Serial.print(F("[LED] ")); Serial.print(d.name);
        Serial.print(F(" 깜빡 ")); Serial.print(s.v2); Serial.println(F("회"));
      }
      break;

    case ST_OFF:
      if (d.kind == DEV_LED) {
        ledWrite(d, 0);
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
void startSig(const StepDef* sig, uint8_t n, const char* label) {
  actRun    = true;
  actSig    = sig;
  actSigN   = n;
  actLabel  = label;
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
  for (uint8_t i = 0; i < n; i++) total += sig[i].ms;
  actDeadline = millis() + total * 3UL + 3000UL;

  Serial.print(F("[동작] ")); Serial.print(label);
  Serial.print(F(" 시작 (단계 ")); Serial.print(n); Serial.println(F("개)"));

  /* 첫 단계 실행 — runStep 이 srvTo 를 목표각으로 세팅한다 */
  if (n > 0) runStep(sig[0]);
}

/* ── 서보 부드럽게 이동 (매 루프) ────────────────────────────────────────── */
void stepServos() {
  if (!actRun) return;
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
  if (!actRun) {
    const StepDef* s; uint8_t n; const char* lab;
    if (qPop(&s, &n, &lab)) startSig(s, n, lab);
    return;
  }

  /* 제한 시간 초과 → 강제 종료 */
  if (actDeadline != 0 && (long)(millis() - actDeadline) > 0) {
    Serial.println(F("[경고] 시간 초과 — 강제 종료"));
    finishAction();
    return;
  }

  stepServos();

  /* 서보가 아직 이동 중이면 기다림 */
  bool moving = false;
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind == DEV_SERVO && srvCur[i] != srvTo[i]) moving = true;
  }
  if (moving) return;

  /* 현재 단계 시간이 끝났으면 다음 단계 */
  if (millis() - actStepAt < (unsigned long)actSig[actStep].ms) return;

  actStep++;
  if (actStep >= actSigN) {
    finishAction();
    return;
  }

  actStepAt = millis();
  runStep(actSig[actStep]);
}

/* ── 동작 종료 ───────────────────────────────────────────────────────────── */
void finishAction() {
  if (!actRun) return;

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
  Serial.println(actLabel);

  actRun      = false;
  actSig      = nullptr;
  actSigN     = 0;
  actLabel    = "";
  actStep     = 0;
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

/* ── 동작 판정 ─────────────────────────────────────────────────────────────
 *  ★★★ 윤비스님 — 동작 추가하는 방법 (딱 한 줄) ★★★
 *
 *     else if (cmd.equals("8NubidaAi")) { startSig(SIG_HEAD, SIG_HEAD_N, "새동작"); return true; }
 *                        ↑명령어                              ↑신호표   ↑단계수    ↑이름
 *
 *  명령어 규칙:  "1NubidaAi" → 풀네임 / 접두어 "1Nubida" / 한 글자 "1" 모두 인식
 * ───────────────────────────────────────────────────────────────────────── */

/* 동작 실행/대기 등록 */
void tryStart(const StepDef* sig, uint8_t n, const char* label) {
  if (!actRun) startSig(sig, n, label);
  else         qPush(sig, n, label);
}

bool actionDispatch(String cmd) {

  /* ── 명령어 → 신호 연결 (여기에 한 줄씩 추가) ── */

  if (cmd.equals("1NubidaAi") || cmd.equals("1Nubida") || cmd.equals("1")) {
    tryStart(SIG_HEAD,  SIG_HEAD_N,  "머리숙이기");   // ← 서보
    return true;
  }
  else if (cmd.equals("2NubidaAi") || cmd.equals("2Nubida") || cmd.equals("2")) {
    tryStart(SIG_ARM,   SIG_ARM_N,   "안녕");         // ← 서보
    return true;
  }
  else if (cmd.equals("3NubidaAi") || cmd.equals("3Nubida") || cmd.equals("3")) {
    tryStart(SIG_MOTOR, SIG_MOTOR_N, "앞으로");       // ← DC모터
    return true;
  }
  else if (cmd.equals("4NubidaAi") || cmd.equals("4Nubida") || cmd.equals("4")) {
    tryStart(SIG_LED,   SIG_LED_N,   "불켜기");       // ← LED스트립
    return true;
  }
  else if (cmd.equals("5NubidaAi") || cmd.equals("5Nubida") || cmd.equals("5")) {
    tryStart(SIG_BUZZ,  SIG_BUZZ_N,  "삐삐");         // ← 부저
    return true;
  }
  else if (cmd.equals("6NubidaAi") || cmd.equals("6Nubida") || cmd.equals("6")) {
    tryStart(SIG_GO,    SIG_GO_N,    "출발");         // ← ★융합
    return true;
  }
  else if (cmd.equals("7NubidaAi") || cmd.equals("7Nubida") || cmd.equals("7")) {
    tryStart(SIG_AVOID, SIG_AVOID_N, "장애물감지");   // ← ★융합
    return true;
  }

  return false;
}

/* ── 기존문법 (원본 유지) ── */
/* ============================================================================
 *  [ 6 ] 기존문법 처리  —  AI 가 만든 코드를 아두이노에서 실행
 * ============================================================================
 *
 *  ★★★ 윤비스님 — 명령 추가하는 방법 (딱 2단계) ★★★
 *
 *  ┌─────────────────────────────────────────────────────────────────────┐
 *  │  1. 아래 표에 한 줄 추가 (명령어 · 설명)                            │
 *  │  2. 아래 LEGACY_ 명령 블록에 하나 추가 (실제 동작)                  │
 *  └─────────────────────────────────────────────────────────────────────┘
 *
 *  ── 예시: "digitalWrite(13,H);" 를 추가하고 싶을 때 ──
 *
 *    1) 표에 추가:
 *         { "digitalWrite(13,H);",  "13번 핀 켜기" },
 *
 *    2) 블록에 추가:
 *         LEGACY("digitalWrite(13,H);") {
 *           pinMode(13, OUTPUT);
 *           digitalWrite(13, HIGH);
 *           return true;
 *         }
 *
 *  ★ LEGACY("...") 는 아래 매크로가 자동으로 처리합니다.
 *    - 명령어가 정확히 일치하면 { } 안이 실행됩니다
 *    - 따옴표 안 숫자는 바뀌어도 됩니다 (예: 13 → 7 도 매칭)
 *    - 끝나면 return true; 만 써주면 됩니다
 *
 * ==========================================================================*/

/* ── 명령 목록표 (사람이 보기 위한 목록 — 여기에 추가) ─────────────────
 *     실제 동작은 아래 LEGACY_ 블록이 합니다. 둘 다 추가하세요. */
struct LegacyDef {
  const char* cmd;     // AI 가 보내는 명령
  const char* desc;    // 설명
};

const LegacyDef LEGACY_TABLE[] = {
  /*  명령어                              설명                          */
  { "digitalWrite(N,H);",                "N번 핀 켜기 (HIGH)"          },
  { "digitalWrite(N,L);",                "N번 핀 끄기 (LOW)"           },
  { "int 변수명 = N;",                   "N번 핀을 변수로 쓰기"        },
  { "Serial.print(N);",                  "N번 핀 읽어서 보내기"        },
  { "if(cho < N)",                       "초음파: N보다 가까우면"      },
  { "if(pos < N)",                       "모터 앞으로"                 },
  { "if(pos > N)",                       "모터 뒤로"                   },
  { "stop",                              "모터 정지"                   },
  { "tone(N1,N2);",                      "N1번 부저에 N2 주파수"       },
  { "noTone(N);",                        "N번 부저 끄기"               },
  { "BT.print(tN,eN);",                  "초음파 거리 측정해서 보내기" },
  { "Piano.mode",                        "초음파 피아노"               },
  { "Trash.mode",                        "초음파 쓰레기통"             },
};
const uint8_t LEGACY_COUNT = sizeof(LEGACY_TABLE) / sizeof(LEGACY_TABLE[0]);


/* ══════════════════════════════════════════════════════════════════════════
 *  ▼▼▼▼▼▼▼▼▼▼  여기부터 명령 실행  ▼▼▼▼▼▼▼▼▼▼
 *
 *  ★ 추가하는 방법
 *     ① 함수 위쪽 '1단계: 값 꺼내기' 에 위치 계산 한 줄 추가
 *     ② 아래 '2단계: 실행' 에  else if (...) { ... }  한 덩어리 추가
 *
 *    예)  13번 핀 켜기
 *
 *    [1단계]
 *      int d13a = cmd.indexOf("digitalWrite(");
 *      int d13b = cmd.indexOf(",H);");
 *      String d13Result = (d13a>=0 && d13b>d13a)
 *                         ? cmd.substring(d13a+13, d13b) : "";
 *
 *    [2단계]
 *      if (cmd.equals("digitalWrite(" + d13Result + ",H);")) {
 *        pinMode(13, OUTPUT);
 *        digitalWrite(13, HIGH);
 *        delay(100); return true;
 *      }
 * ══════════════════════════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════════════════════════════
 *  ▼▼▼▼▼▼▼▼▼▼  여기부터 명령 실행  ▼▼▼▼▼▼▼▼▼▼
 *
 *  ★ 추가하는 방법
 *     LEGACY("명령문자열") {
 *        ...동작...
 *        return true;
 *     }
 *
 *  ★ 숫자 꺼내기:  n1, n2, n3, n4
 * ══════════════════════════════════════════════════════════════════════════ */

bool handleLegacyCommand(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  ★★ 1단계: 값 꺼내기 (여기만 고치면 됨) ★★
   *
   *  명령에서 숫자를 뽑아 변수에 담습니다.
   *  예)  digitalWrite(13,H);   →  HIGHResult = "13"
   *       int lamp = 13;        →  intResult2 = "13"
   * ══════════════════════════════════════════════════════════════════════ */

  /* digitalWrite(13,H); 에서 13 뽑기 */
  int HIGH_a = cmd.indexOf("digitalWrite(");
  int HIGH_b = cmd.indexOf(",H);");
  String HIGHResult = (HIGH_a >= 0 && HIGH_b > HIGH_a)
                      ? cmd.substring(HIGH_a + 13, HIGH_b) : "";

  /* digitalWrite(13,L); 에서 13 뽑기 */
  int LOW_a = cmd.indexOf("digitalWrite(");
  int LOW_b = cmd.indexOf(",L);");
  String LOWResult = (LOW_a >= 0 && LOW_b > LOW_a)
                     ? cmd.substring(LOW_a + 13, LOW_b) : "";

  /* int 변수명 = 13; 에서 변수명과 13 뽑기 */
  int INT_a = cmd.indexOf("int ");
  int INT_b = cmd.indexOf(" = ");
  int INT_c = cmd.indexOf(";");
  String INTResult1 = (INT_a >= 0 && INT_b > INT_a)
                      ? cmd.substring(INT_a + 4, INT_b) : "";
  String INTResult2 = (INT_b > 0 && INT_c > INT_b)
                      ? cmd.substring(INT_b + 3, INT_c) : "";

  /* Serial.print(13); 에서 13 뽑기 */
  int SR_a = cmd.indexOf("Serial.print(");
  int SR_b = cmd.indexOf(");");
  String SRResult = (SR_a >= 0 && SR_b > SR_a)
                    ? cmd.substring(SR_a + 13, SR_b) : "";

  /* tone(7,262); 에서 7 과 262 뽑기 */
  int TN_a = cmd.indexOf("tone(");
  int TN_c = cmd.indexOf(",");
  int TN_b = cmd.indexOf(");");
  String TNResult1 = (TN_a >= 0 && TN_c > TN_a)
                     ? cmd.substring(TN_a + 5, TN_c) : "";
  String TNResult2 = (TN_c > 0 && TN_b > TN_c)
                     ? cmd.substring(TN_c + 1, TN_b) : "";

  /* noTone(7); 에서 7 뽑기 */
  int NT_a = cmd.indexOf("noTone(");
  int NT_b = cmd.indexOf(");");
  String NTResult = (NT_a >= 0 && NT_b > NT_a)
                    ? cmd.substring(NT_a + 7, NT_b) : "";

  /* if(cho < 20) 에서 20 뽑기 */
  int CHO_a = cmd.indexOf("if(cho <");
  String CHOResult = "";
  if (CHO_a >= 0) {
    String t = cmd.substring(CHO_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) CHOResult = t.substring(0, e);
  }

  /* if(pos < 90) 에서 90 뽑기 */
  int POSL_a = cmd.indexOf("if(pos <");
  String POSLResult = "";
  if (POSL_a >= 0) {
    String t = cmd.substring(POSL_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSLResult = t.substring(0, e);
  }

  /* if(pos > 90) 에서 90 뽑기 */
  int POSG_a = cmd.indexOf("if(pos >");
  String POSGResult = "";
  if (POSG_a >= 0) {
    String t = cmd.substring(POSG_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSGResult = t.substring(0, e);
  }

  /* BT.print(t10,e11); 에서 10 과 11 뽑기 */
  int BP_a = cmd.indexOf("BT.print(t");
  int BP_c = cmd.indexOf(",e");
  int BP_b = cmd.indexOf(");");
  String BPResult1 = (BP_a >= 0 && BP_c > BP_a)
                     ? cmd.substring(BP_a + 10, BP_c) : "";
  String BPResult2 = (BP_c > 0 && BP_b > BP_c)
                     ? cmd.substring(BP_c + 2, BP_b) : "";


  /* ══════════════════════════════════════════════════════════════════════
   *  ★★ 2단계: 실행 (여기에 if 문으로 추가) ★★
   *
   *  위에서 뽑은 변수를 그대로 씁니다.
   *  새 명령은  else if (...) { ... }  한 덩어리만 추가하면 됩니다.
   * ══════════════════════════════════════════════════════════════════════ */

/* ── ① digitalWrite(13,H);  →  13번 핀 켜기 ─────────────────────────── */
  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
    digitalHIGH = HIGHResult.toInt();
    pinMode(digitalHIGH, OUTPUT); digitalWrite(digitalHIGH, HIGH); delay(100); return true;
  }

/* ── ② digitalWrite(13,L);  →  13번 핀 끄기 ─────────────────────────── */
  else if (cmd.equals("digitalWrite(" + LOWResult + ",L);")) {
    digitalLOW = LOWResult.toInt();
    pinMode(digitalLOW, OUTPUT); digitalWrite(digitalLOW, LOW); delay(100); return true;
  }

/* ── ③ int lamp = 13;  →  13번 핀을 변수로 쓰기 ─────────────────────── */
  else if (cmd.equals("int " + INTResult1 + " = " + INTResult2 + ";")) {
    BTSerial.println(INTResult1 + "의 변수명은 " + INTResult2 + "번의 핀을 사용합니다.");
    delay(100); return true;
  }

/* ── ④ Serial.print(13);  →  13번 핀 읽어서 보내기 ──────────────────── */
  else if (cmd.equals("Serial.print(" + SRResult + ");")) {
    serial = SRResult.toInt();
    pinMode(serial, INPUT);
    BTSerial.println(digitalRead(serial));
    delay(100); return true;
  }

/* ── ⑤ if(cho < 20)  →  초음파 20cm 이내면 부저 ─────────────────────── */
  else if (cmd.equals("if(cho < " + CHOResult + ")")) {
    int cho = CHOResult.toInt();
    int trig = 10, echo = 11, bz = 7;
    pinMode(trig, OUTPUT); pinMode(echo, INPUT);
    digitalWrite(trig, LOW); delayMicroseconds(2);
    digitalWrite(trig, HIGH); delayMicroseconds(10); digitalWrite(trig, LOW);
    float distance = pulseIn(echo, HIGH) / 29.0 / 2.0;
    delay(10);
    pinMode(bz, OUTPUT);
    if (distance < cho) { tone(bz, 262); delay(1000); }
    else                { noTone(bz);    delay(1000); }
    return true;
  }

/* ── ⑥ if(pos < 90)  →  모터 앞으로 ─────────────────────────────────── */
  else if (cmd.equals("if(pos < " + POSLResult + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT);
    pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    digitalWrite(4, HIGH); digitalWrite(5, LOW);
    digitalWrite(6, HIGH); digitalWrite(7, LOW);
    delay(100); return true;
  }

/* ── ⑦ if(pos > 90)  →  모터 뒤로 ───────────────────────────────────── */
  else if (cmd.equals("if(pos > " + POSGResult + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT);
    pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    digitalWrite(4, LOW); digitalWrite(5, HIGH);
    digitalWrite(6, LOW); digitalWrite(7, HIGH);
    delay(100); return true;
  }

/* ── ⑧ stop  →  모터 정지 ───────────────────────────────────────────── */
  else if (cmd.equals("stop")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT);
    pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    digitalWrite(4, LOW); digitalWrite(5, LOW);
    digitalWrite(6, LOW); digitalWrite(7, LOW);
    delay(100); return true;
  }

/* ── ⑨ tone(7,262);  →  7번 부저에 262 주파수 ───────────────────────── */
  else if (cmd.equals("tone(" + TNResult1 + "," + TNResult2 + ");")) {
    int bz = TNResult1.toInt(), freq = TNResult2.toInt();
    pinMode(bz, OUTPUT);
    tone(bz, freq);
    return true;
  }

/* ── ⑩ noTone(7);  →  7번 부저 끄기 ─────────────────────────────────── */
  else if (cmd.equals("noTone(" + NTResult + ");")) {
    int bz = NTResult.toInt();
    pinMode(bz, OUTPUT);
    noTone(bz);
    return true;
  }

/* ── ⑪ BT.print(t10,e11);  →  초음파 거리 측정해서 보내기 ───────────── */
  else if (cmd.equals("BT.print(t" + BPResult1 + ",e" + BPResult2 + ");")) {
    int trig = BPResult1.toInt(), echo = BPResult2.toInt();
    pinMode(trig, OUTPUT); pinMode(echo, INPUT);
    digitalWrite(trig, LOW); delayMicroseconds(2);
    digitalWrite(trig, HIGH); delayMicroseconds(10); digitalWrite(trig, LOW);
    float distance = pulseIn(echo, HIGH) / 29.0 / 2.0;
    delay(10);
    Serial.println(distance); BTSerial.println(distance);
    delay(1000);
    return true;
  }

/* ── ⑫ Piano.mode  →  초음파 피아노 ─────────────────────────────────── */
  else if (cmd.equals("Piano.mode")) {
    int bz = 7, trig = 10, echo = 11;
    pinMode(bz, OUTPUT); pinMode(trig, OUTPUT); pinMode(echo, INPUT);
    digitalWrite(trig, LOW); delayMicroseconds(2);
    digitalWrite(trig, HIGH); delayMicroseconds(10); digitalWrite(trig, LOW);
    float distance = pulseIn(echo, HIGH) / 29.0 / 2.0;
    delay(10);
    if      (distance < 4)    { tone(bz, 262, 1000); delay(100); }
    else if (distance < 6.9)  { tone(bz, 294, 1000); delay(100); }
    else if (distance < 9.8)  { tone(bz, 330, 1000); delay(100); }
    else if (distance < 12.5) { tone(bz, 349, 1000); delay(100); }
    else if (distance < 14.6) { tone(bz, 392, 1000); delay(100); }
    else if (distance < 16)   { tone(bz, 440, 1000); delay(100); }
    else if (distance < 18)   { tone(bz, 494, 1000); delay(100); }
    else if (distance < 20.1) { tone(bz, 523, 1000); delay(100); }
    else                      { noTone(bz); delay(100); }
    return true;
  }

/* ── ⑬ Trash.mode  →  초음파 쓰레기통 (15cm 이내면 열림) ────────────── */
  else if (cmd.equals("Trash.mode")) {
    int trig = 10, echo = 11;
    pinMode(trig, OUTPUT); pinMode(echo, INPUT);
    digitalWrite(trig, LOW); delayMicroseconds(2);
    digitalWrite(trig, HIGH); delayMicroseconds(10); digitalWrite(trig, LOW);
    float distance = pulseIn(echo, HIGH) / 29.0 / 2.0;
    delay(10);
    Serial.println(distance); BTSerial.println(distance);
    delay(1000);
    return true;
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
  Serial.println(F("[동작] 7개 등록됨"));
  Serial.println(F("  1NubidaAi → 머리숙이기"));
  Serial.println(F("  2NubidaAi → 안녕"));
  Serial.println(F("  3NubidaAi → 앞으로"));
  Serial.println(F("  4NubidaAi → 불켜기"));
  Serial.println(F("  5NubidaAi → 삐삐"));
  Serial.println(F("  6NubidaAi → 출발"));
  Serial.println(F("  7NubidaAi → 장애물감지"));
  Serial.println(F("준비 완료"));
  Serial.println(F(""));
}

/* ── setup / loop ── */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  /* 서보 풀 초기화 (반드시 deviceSetup 전에) */
  for (uint8_t i = 0; i < MAX_SERVO; i++) srvPinOf[i] = -1;

  deviceSetup();
  checkWiring();        // ★ 부품 늘렸을 때 문제를 바로 알려준다
  printBanner();
}

/* ★ v21 자동 점검 — 부품표를 늘린 뒤 여기서 문제를 바로 확인
 *   [점검] 부품 6개 / 서보 2개 / 모터 1개
 *   [점검] 사용핀: 9 7 5 4 3 6 10 11
 *   [경고] 5번핀 중복! (부품 2 '바퀴모터' / 부품 3 '...' )
 *   [오류] 부품이 MAX_DEVICES(24) 초과 → 초과분 무시
 */
void checkWiring() {
  Serial.print(F("[점검] 부품 "));
  Serial.print(DEVICE_COUNT);
  Serial.print(F("개  (최대 "));
  Serial.print(MAX_DEVICES);
  Serial.println(F("개)"));

  uint8_t nServo = 0, nMotor = 0, nLed = 0, nBuzz = 0, nUltra = 0;
  Serial.print(F("[점검] 사용핀:"));
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    Serial.print(' ');
    Serial.print(DEVICES[i].pin);
    if (DEVICES[i].pin2 != 255) { Serial.print(','); Serial.print(DEVICES[i].pin2); }
    switch (DEVICES[i].kind) {
      case DEV_SERVO:   nServo++; break;
      case DEV_MOTOR:   nMotor++; break;
      case DEV_LED:     nLed++;   break;
      case DEV_TONE:    nBuzz++;  break;
      case DEV_ULTRA:   nUltra++; break;
    }
  }
  Serial.println();

  Serial.print(F("[점검] 서보 ")); Serial.print(nServo);
  Serial.print(F(" / 모터 "));     Serial.print(nMotor);
  Serial.print(F(" / LED "));      Serial.print(nLed);
  Serial.print(F(" / 부저 "));     Serial.print(nBuzz);
  Serial.print(F(" / 초음파 "));   Serial.println(nUltra);

  /* 핀 중복 검사 */
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    for (uint8_t j = i + 1; j < DEVICE_COUNT; j++) {
      if (DEVICES[i].pin == DEVICES[j].pin ||
          (DEVICES[i].pin2 != 255 && DEVICES[i].pin2 == DEVICES[j].pin)) {
        Serial.print(F("[경고] "));
        Serial.print(DEVICES[i].pin);
        Serial.print(F("번핀 중복! '"));
        Serial.print(DEVICES[i].name);
        Serial.print(F("' / '"));
        Serial.print(DEVICES[j].name);
        Serial.println(F("'"));
      }
    }
  }

  /* 모터 보조핀 누락 */
  for (uint8_t i = 0; i < DEVICE_COUNT; i++) {
    if (DEVICES[i].kind == DEV_MOTOR && DEVICES[i].pin2 == 255) {
      Serial.print(F("[경고] '"));
      Serial.print(DEVICES[i].name);
      Serial.println(F("' 모터에 보조핀(pin2)이 없습니다 → L9110S 는 2핀 필요"));
    }
  }

  /* 개수 초과 */
  if (DEVICE_COUNT > MAX_DEVICES) {
    Serial.print(F("[오류] 부품이 MAX_DEVICES("));
    Serial.print(MAX_DEVICES);
    Serial.println(F(") 를 초과 → 초과분은 동작하지 않습니다"));
  }
  if (nServo > MAX_SERVO) {
    Serial.print(F("[오류] 서보가 MAX_SERVO("));
    Serial.print(MAX_SERVO);
    Serial.println(F(") 를 초과 → 초과분은 동작하지 않습니다"));
  }
}

void loop() {
  /* ★ 수신을 최우선으로 — 버퍼 오버플로 방지 */
  drainBle();

  /* 동작 진행 */
  stepAction();

  /* LED 깜빡임 진행 (비블로킹) */
  ledTick();
}
