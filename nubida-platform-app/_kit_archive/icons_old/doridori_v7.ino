/* ===========================================================================
 *  도리도리 로봇 v7  (깔끔하게 정리한 판)
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

/* ===========================================================================
 *  【설정】 - 여기 숫자만 바꾸시면 됩니다
 * =========================================================================== */

/* 서보가 꽂힌 핀 */
#define PIN_HEAD    9      /* 도리도리 · 삐졌어 서보 */
#define PIN_ARM     7      /* 안녕 서보 */
/* 부저가 꽂힌 핀 - 서보(9 · 7)와 절대 겹치면 안 됩니다 */
#define PIN_BUZZ    8      /* 부저 */

/* 도리도리 각도 */
#define DORI_LEFT   140    /* 왼쪽으로 */
#define DORI_RIGHT   40    /* 오른쪽으로 */

/* 삐졌어 각도 */
#define SAD_DOWN     25    /* 고개 푹 떨군 각도 */

/* 안녕 각도 */
#define HI_UP       135    /* 위로 들기 */
#define HI_DOWN      25    /* 아래로 숙이기 */

/* 가운데(정면) */
#define CENTER       90

/* 움직이는 속도 - 숫자가 클수록 천천히 */
#define MS_FAST     300
#define MS_NORMAL   500
#define MS_SLOW     800

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

/* ===========================================================================
 *  서보를 부드럽게 움직이는 함수
 *    pin : 서보 핀   deg : 목표 각도(0~180)   ms : 걸리는 시간
 * =========================================================================== */
void servoTo(int pin, int deg, int ms) {

  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  int i = -1;
  for (int k = 0; k < 2; k++) if (srvPin[k] == pin) { i = k; break; }
  if (i < 0) return;

  int from = srvCur[i];
  if (from == deg) return;

  int total = abs(deg - from);
  int steps = total / 3; if (steps < 1) steps = 1;
  int tick  = ms / steps; if (tick < 5) tick = 5;

  int dir = (deg > from) ? 3 : -3;
  int cur = from;

  for (int s = 1; s <= steps; s++) {
    cur += dir;
    if (dir > 0 && cur > deg) cur = deg;
    if (dir < 0 && cur < deg) cur = deg;
    srv[i].write(cur);
    delay(tick);
  }

  if (cur != deg) srv[i].write(deg);
  srvCur[i] = deg;
}

/* ===========================================================================
 *  【동작 만들기】 - 새 동작은 여기에 함수를 하나 만드시면 됩니다
 * =========================================================================== */

/* -- 도리도리 -- 좌우로 흔들기 (9번 서보) */
void doDoriDori() {
  servoTo(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  servoTo(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  servoTo(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  servoTo(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  servoTo(PIN_HEAD, CENTER,     MS_FAST);
}

/* -- 삐졌어 -- 고개 푹 떨구기 (9번 서보) */
void doSajin() {
  servoTo(PIN_HEAD, CENTER,   MS_FAST);
  servoTo(PIN_HEAD, SAD_DOWN, MS_SLOW);
  delay(800);
  servoTo(PIN_HEAD, CENTER,   MS_NORMAL);
}

/* -- 안녕 -- 끄덕끄덕 인사 (7번 서보) */
void doHello() {
  servoTo(PIN_ARM, HI_UP,   MS_FAST);
  servoTo(PIN_ARM, HI_DOWN, MS_NORMAL);
  servoTo(PIN_ARM, HI_UP,   MS_NORMAL);
  servoTo(PIN_ARM, HI_DOWN, MS_NORMAL);
  servoTo(PIN_ARM, CENTER,  MS_FAST);
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
  Serial.begin(9600);
  nubidaBtBegin();

  for (int i = 0; i < 2; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(CENTER);
    srvCur[i] = CENTER;
  }
  delay(300);

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
  nubidaBtUpdate();
}
