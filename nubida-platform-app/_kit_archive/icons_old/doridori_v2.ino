/* ═══════════════════════════════════════════════════════════════════════════
 *  도리도리 로봇  (서보 2개 전용 · 단독 파일)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  1NubidaAi  →  도리도리   (9번 서보 · 좌우로 흔들기)               │
 *  │  2NubidaAi  →  삐졌어     (9번 서보 · 고개 푹 떨구기)              │
 *  │  3NubidaAi  →  안녕       (7번 서보 · 끄덕끄덕 인사)               │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ★ 바꾸실 곳은 맨 아래 "설정" 부분뿐입니다.
 *    핀 번호와 각도 숫자만 바꾸면 됩니다.
 *
 *  ⚠️ 2번 · 3번 핀은 블루투스 통신 전용입니다 (서보 연결 금지)
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>
#include <Servo.h>

/* ═══════════════════════════════════════════════════════════════════════
 *  설정 ─ 여기 숫자만 바꾸시면 됩니다
 * ═══════════════════════════════════════════════════════════════════════ */

/* 서보가 꽂힌 핀 */
#define PIN_HEAD    9      // 도리도리 · 삐졌어 서보
#define PIN_ARM     7      // 안녕 서보

/* 도리도리 각도 */
#define DORI_LEFT   140    // 왼쪽으로
#define DORI_RIGHT   40    // 오른쪽으로

/* 삐졌어 각도 */
#define SAD_DOWN     25    // 고개 푹 떨군 각도

/* 안녕 각도 */
#define HI_UP       135    // 위로 들기
#define HI_DOWN      25    // 아래로 숙이기

/* 가운데(정면) */
#define CENTER       90

/* 움직이는 속도 — 숫자가 클수록 천천히 */
#define MS_FAST     300
#define MS_NORMAL   500
#define MS_SLOW     800

/* ═══════════════════════════════════════════════════════════════════════
 *  블루투스 (BLE)  RX=2 / TX=3
 * ═══════════════════════════════════════════════════════════════════════ */
SoftwareSerial BTSerial(2, 3);

/* ═══════════════════════════════════════════════════════════════════════
 *  서보 2개 기억장치
 *    srv[i]     : 서보 객체
 *    srvPin[i]  : 그 서보가 꽂힌 핀
 *    srvCur[i]  : 그 서보의 현재 각도 (부드럽게 이어가려고 기억)
 *
 *  ※ 이 3줄은 함수 밖에 있어야 합니다.
 *    함수 안에 만들면 함수가 끝날 때 사라져서 각도가 풀립니다.
 * ═══════════════════════════════════════════════════════════════════════ */
Servo srv[2];
int   srvPin[2] = { PIN_HEAD, PIN_ARM };
int   srvCur[2] = { CENTER,   CENTER   };

/* ═══════════════════════════════════════════════════════════════════════
 *  서보를 부드럽게 움직이는 함수
 *
 *    pin : 서보가 꽂힌 핀 번호
 *    deg : 목표 각도 (0 ~ 180)
 *    ms  : 그 각도까지 가는 데 걸리는 시간 (클수록 천천히)
 *
 *  서보는 "천천히 가"라는 명령이 없어서, 3도씩 나눠서 조금씩 보냅니다.
 * ═══════════════════════════════════════════════════════════════════════ */
void servoTo(int pin, int deg, int ms) {

  /* 0~180 밖으로 나가지 않게 막기 */
  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  /* 이 핀의 서보를 찾기 (없으면 새로 등록) */
  int i = -1;
  for (int k = 0; k < 2; k++) {
    if (srvPin[k] == pin) { i = k; break; }
  }
  if (i < 0) return;                 // 등록 안 된 핀은 무시

  int from = srvCur[i];
  if (from == deg) return;           // 이미 그 자리면 아무것도 안 함

  /* 몇 걸음으로 나눌지 (3도씩) */
  int total = abs(deg - from);
  int steps = total / 3;
  if (steps < 1) steps = 1;

  /* 한 걸음에 쉬는 시간 */
  int tick = ms / steps;
  if (tick < 5) tick = 5;            // 너무 빠르면 서보가 떨려서 최소 5ms

  int dir = (deg > from) ? 3 : -3;
  int cur = from;

  for (int s = 1; s <= steps; s++) {
    cur += dir;
    if (dir > 0 && cur > deg) cur = deg;
    if (dir < 0 && cur < deg) cur = deg;
    srv[i].write(cur);
    delay(tick);
  }

  /* 마지막에 목표 각도에 정확히 오지 않았으면 한 번 더 */
  if (cur != deg) srv[i].write(deg);
  srvCur[i] = deg;
}

/* ═══════════════════════════════════════════════════════════════════════
 *  동작 만들기
 * ═══════════════════════════════════════════════════════════════════════ */

/* ── 도리도리 ── 좌우로 흔들기 (9번 서보) */
void doDoriDori() {
  servoTo(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  servoTo(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  servoTo(PIN_HEAD, DORI_LEFT,  MS_NORMAL);
  servoTo(PIN_HEAD, DORI_RIGHT, MS_NORMAL);
  servoTo(PIN_HEAD, CENTER,     MS_FAST);
}

/* ── 삐졌어 ── 고개 푹 떨구기 (9번 서보) */
void doSajin() {
  servoTo(PIN_HEAD, CENTER,   MS_FAST);
  servoTo(PIN_HEAD, SAD_DOWN, MS_SLOW);   // 천천히 푹
  delay(800);                             // 잠깐 그대로 (삐진 척)
  servoTo(PIN_HEAD, CENTER,   MS_NORMAL); // 다시 올림
}

/* ── 안녕 ── 끄덕끄덕 인사 (7번 서보) */
void doHello() {
  servoTo(PIN_ARM, HI_UP,   MS_FAST);
  servoTo(PIN_ARM, HI_DOWN, MS_NORMAL);
  servoTo(PIN_ARM, HI_UP,   MS_NORMAL);
  servoTo(PIN_ARM, HI_DOWN, MS_NORMAL);
  servoTo(PIN_ARM, CENTER,  MS_FAST);
}

/* ═══════════════════════════════════════════════════════════════════════
 *  명령 처리 ─ 한 줄을 받아서 알맞은 동작 실행
 * ═══════════════════════════════════════════════════════════════════════ */
bool runCommand(String cmd) {

  /* ── 1NubidaAi ─ 도리도리 ── */
  if (cmd.equals("1NubidaAi") || cmd.equals("1Nubida") || cmd.equals("1")) {
    Serial.println(F("[동작] 도리도리"));
    doDoriDori();
    return true;
  }

  /* ── 2NubidaAi ─ 삐졌어 ── */
  if (cmd.equals("2NubidaAi") || cmd.equals("2Nubida") || cmd.equals("2")) {
    Serial.println(F("[동작] 삐졌어"));
    doSajin();
    return true;
  }

  /* ── 3NubidaAi ─ 안녕 ── */
  if (cmd.equals("3NubidaAi") || cmd.equals("3Nubida") || cmd.equals("3")) {
    Serial.println(F("[동작] 안녕"));
    doHello();
    return true;
  }

  /* ── 정지 ── */
  if (cmd.equals("stop") || cmd.equals("STOP")) {
    Serial.println(F("[동작] 정지"));
    servoTo(PIN_HEAD, CENTER, MS_FAST);
    servoTo(PIN_ARM,  CENTER, MS_FAST);
    return true;
  }

  return false;    // 모르는 명령
}

/* ═══════════════════════════════════════════════════════════════════════
 *  블루투스 수신
 * ═══════════════════════════════════════════════════════════════════════ */
char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;

#define FRAME_GAP_MS 60     // 마지막 글자 후 이만큼 지나면 한 줄 끝으로 봄

/* 블루투스에 온 글자를 전부 꺼내 버퍼에 쌓기 */
void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    lastRxAt = millis();
  }
}

/* 버퍼에 쌓인 글자를 줄 단위로 잘라서 처리 */
void handleFrame() {
  if (rxLen == 0) return;
  rxBuf[rxLen] = '\0';
  String block(rxBuf);
  rxLen = 0;

  int start = 0;
  for (int i = 0; i <= (int)block.length(); i++) {
    bool cut = (i == (int)block.length()) ||
               block.charAt(i) == '\n' || block.charAt(i) == '\r';
    if (!cut) continue;
    if (i > start) {
      String one = block.substring(start, i);
      one.trim();
      if (one.length() > 0) {
        Serial.print(F("[명령] "));
        Serial.println(one);
        if (!runCommand(one)) {
          Serial.print(F("[무시] "));
          Serial.println(one);
        }
      }
    }
    start = i + 1;
  }
}

/* ═══════════════════════════════════════════════════════════════════════
 *  setup ─ 전원 켤 때 1번
 * ═══════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  /* 서보 2개 준비 */
  for (int i = 0; i < 2; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(CENTER);
    srvCur[i] = CENTER;
  }
  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  도리도리 로봇"));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  도리도리 · 삐졌어  →  "));
  Serial.print(PIN_HEAD); Serial.println(F("번 서보"));
  Serial.print(F("  안녕               →  "));
  Serial.print(PIN_ARM);  Serial.println(F("번 서보"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  1NubidaAi → 도리도리"));
  Serial.println(F("  2NubidaAi → 삐졌어"));
  Serial.println(F("  3NubidaAi → 안녕"));
  Serial.println(F("  stop      → 정지"));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
}

/* ═══════════════════════════════════════════════════════════════════════
 *  loop ─ 계속 반복
 * ═══════════════════════════════════════════════════════════════════════ */
void loop() {
  drainBle();
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }
}
