/* ═══════════════════════════════════════════════════════════════════════════
 *  스마트 휴지통  (서보모터 3개 · 캔 / 플라스틱 / 일반 분리)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  서보 3개 역할                                                     │
 *  │                                                                    │
 *  │    5번 서보  →  뚜껑 (열고 닫기)                                   │
 *  │    7번 서보  →  분리대 (좌우로 돌려 길을 바꿈)                     │
 *  │    9번 서보  →  밀대 (쓰레기를 밀어 넣기)                          │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  명령어 (블루투스로 보내면 동작)                                   │
 *  │                                                                    │
 *  │    캔      →  뚜껑 열고 → 분리대 캔쪽 → 밀대 → 뚜껑 닫기          │
 *  │    플라스틱→  뚜껑 열고 → 분리대 플라스틱쪽 → 밀대 → 뚜껑 닫기    │
 *  │    일반     →  뚜껑 열고 → 분리대 일반쪽 → 밀대 → 뚜껑 닫기        │
 *  │    열기     →  뚜껑만 열기                                        │
 *  │    닫기     →  뚜껑만 닫기                                        │
 *  │    홈       →  모든 서보 처음 위치로                                │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 배선
 *
 *      서보 5번 (뚜껑)      신호선(주황) → 5번
 *      서보 7번 (분리대)    신호선(주황) → 7번
 *      서보 9번 (밀대)      신호선(주황) → 9번
 *      서보 전원(빨강)      →  5V (서보 3개면 외부 5V 권장)
 *      서보 접지(갈색)      →  GND
 *
 *      ⚠️ 서보 3개를 한꺼번에 움직이면 전류가 많이 필요합니다.
 *         힘이 약하거나 떨리면 서보 전원을 따로 넣어 주세요.
 *      ⚠️ 2번·3번 핀은 블루투스 전용입니다.
 * ─────────────────────────────────────────────────────────────────────────
 *
 *  ★ 각도는 아래 "설정" 부분만 바꾸면 됩니다.
 *    서보를 처음 붙였을 때 각도가 안 맞으면, 그 숫자만 고쳐 주세요.
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>
#include <Servo.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  설정 ─ 여기 숫자만 바꾸시면 됩니다
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 서보가 꽂힌 핀 ── */
#define PIN_LID     5      // 뚜껑 서보
#define PIN_GATE    7      // 분리대 서보
#define PIN_PUSH    9      // 밀대 서보

/* ── ① 뚜껑 각도 ── */
#define LID_CLOSE   10     // 닫힌 상태
#define LID_OPEN    95     // 열린 상태

/* ── ② 분리대 각도 (길을 바꾸는 부분) ── */
#define GATE_CAN    15     // 캔 통로
#define GATE_PLASTIC 90    // 플라스틱 통로
#define GATE_NORMAL 165    // 일반쓰레기 통로

/* ── ③ 밀대 각도 (쓰레기를 밀어 넣는 부분) ── */
#define PUSH_HOME   30     // 원래 위치 (대기)
#define PUSH_GO     130    // 밀어 넣기

/* ── 움직이는 속도 (숫자가 클수록 천천히) ── */
#define MS_FAST     300
#define MS_NORMAL   500
#define MS_SLOW     700

/* ── 동작 사이 쉬는 시간 (밀대가 밀고 돌아올 시간) ── */
#define WAIT_PUSH   700

/* ═══════════════════════════════════════════════════════════════════════════
 *  블루투스 (BLE)  RX=2 / TX=3
 * ═══════════════════════════════════════════════════════════════════════════ */
SoftwareSerial BTSerial(2, 3);

/* ═══════════════════════════════════════════════════════════════════════════
 *  서보 3개 기억장치
 *    ※ 함수 밖에 있어야 합니다 (안에 만들면 각도가 풀립니다)
 * ═══════════════════════════════════════════════════════════════════════════ */
Servo srv[3];
int   srvPin[3] = { PIN_LID,   PIN_GATE,    PIN_PUSH };
int   srvCur[3] = { LID_CLOSE, GATE_CAN,    PUSH_HOME };

/* ═══════════════════════════════════════════════════════════════════════════
 *  서보를 부드럽게 움직이는 함수
 *    pin : 서보 핀   deg : 목표 각도(0~180)   ms : 걸리는 시간
 *
 *  서보는 "천천히 가"라는 명령이 없어서, 3도씩 나눠서 조금씩 보냅니다.
 * ═══════════════════════════════════════════════════════════════════════════ */
void servoTo(int pin, int deg, int ms) {

  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  int i = -1;
  for (int k = 0; k < 3; k++) if (srvPin[k] == pin) { i = k; break; }
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

/* ═══════════════════════════════════════════════════════════════════════════
 *  기본 동작
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 뚜껑 열기 ── */
void lidOpen() {
  servoTo(PIN_LID, LID_OPEN, MS_NORMAL);
}

/* ── 뚜껑 닫기 ── */
void lidClose() {
  servoTo(PIN_LID, LID_CLOSE, MS_NORMAL);
}

/* ── 분리대를 원하는 통로로 ── */
void gateTo(int angle) {
  servoTo(PIN_GATE, angle, MS_NORMAL);
}

/* ── 밀대로 밀어 넣기 (밀고 → 잠깐 → 돌아오기) ── */
void pushOnce() {
  servoTo(PIN_PUSH, PUSH_GO,   MS_FAST);    // 밀기
  delay(WAIT_PUSH);                          // 밀린 쓰레기가 떨어질 시간
  servoTo(PIN_PUSH, PUSH_HOME, MS_NORMAL);  // 원위치
}

/* ── 모든 서보 처음 위치로 ── */
void goHome() {
  servoTo(PIN_PUSH, PUSH_HOME, MS_NORMAL);
  servoTo(PIN_GATE, GATE_CAN,  MS_NORMAL);
  servoTo(PIN_LID,  LID_CLOSE, MS_NORMAL);
}

/* ── 쓰레기 하나 분리하기 ──
 *    gateAngle : 분리대가 갈 통로 각도
 */
void sortTrash(int gateAngle) {

  /* 1. 뚜껑 열기 */
  lidOpen();
  delay(200);

  /* 2. 분리대를 그 통로로 돌리기 */
  gateTo(gateAngle);
  delay(200);

  /* 3. 밀대로 밀어 넣기 */
  pushOnce();

  /* 4. 뚜껑 닫기 */
  delay(200);
  lidClose();
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  명령 처리
 * ═══════════════════════════════════════════════════════════════════════════ */
bool runCommand(String cmd) {

  /* ── 캔 ── */
  if (cmd.equals("캔") || cmd.equals("can") || cmd.equals("1")) {
    Serial.println(F("[동작] 캔 분리"));
    sortTrash(GATE_CAN);
    return true;
  }

  /* ── 플라스틱 ── */
  else if (cmd.equals("플라스틱") || cmd.equals("plastic") || cmd.equals("2")) {
    Serial.println(F("[동작] 플라스틱 분리"));
    sortTrash(GATE_PLASTIC);
    return true;
  }

  /* ── 일반 ── */
  else if (cmd.equals("일반") || cmd.equals("일반쓰레기") ||
           cmd.equals("normal") || cmd.equals("3")) {
    Serial.println(F("[동작] 일반쓰레기 분리"));
    sortTrash(GATE_NORMAL);
    return true;
  }

  /* ── 뚜껑만 열기 ── */
  else if (cmd.equals("열기") || cmd.equals("open")) {
    Serial.println(F("[동작] 뚜껑 열기"));
    lidOpen();
    return true;
  }

  /* ── 뚜껑만 닫기 ── */
  else if (cmd.equals("닫기") || cmd.equals("close")) {
    Serial.println(F("[동작] 뚜껑 닫기"));
    lidClose();
    return true;
  }

  /* ── 홈 (처음 위치) ── */
  else if (cmd.equals("홈") || cmd.equals("home") || cmd.equals("reset")) {
    Serial.println(F("[동작] 처음 위치"));
    goHome();
    return true;
  }

  return false;    // 모르는 명령
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  블루투스 수신
 * ═══════════════════════════════════════════════════════════════════════════ */
char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;

#define FRAME_GAP_MS 60     // 마지막 글자 후 이만큼 지나면 한 줄 끝으로 봄

void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    lastRxAt = millis();
  }
}

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

/* ═══════════════════════════════════════════════════════════════════════════
 *  setup ─ 전원 켤 때 1번
 * ═══════════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  /* 서보 3개 준비 */
  for (int i = 0; i < 3; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(srvCur[i]);
  }
  delay(300);

  /* 처음 위치로 */
  servoTo(PIN_LID,  LID_CLOSE, MS_FAST);
  servoTo(PIN_GATE, GATE_CAN,  MS_FAST);
  servoTo(PIN_PUSH, PUSH_HOME, MS_FAST);
  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  스마트 휴지통"));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  뚜껑   →  ")); Serial.print(PIN_LID);
  Serial.print(F("번   (닫힘 ")); Serial.print(LID_CLOSE);
  Serial.print(F(" / 열림 "));   Serial.print(LID_OPEN);
  Serial.println(F(")"));
  Serial.print(F("  분리대 →  ")); Serial.print(PIN_GATE);
  Serial.print(F("번   (캔 "));  Serial.print(GATE_CAN);
  Serial.print(F(" / 플라스틱 ")); Serial.print(GATE_PLASTIC);
  Serial.print(F(" / 일반 "));   Serial.print(GATE_NORMAL);
  Serial.println(F(")"));
  Serial.print(F("  밀대   →  ")); Serial.print(PIN_PUSH);
  Serial.print(F("번   (대기 ")); Serial.print(PUSH_HOME);
  Serial.print(F(" / 밀기 "));    Serial.print(PUSH_GO);
  Serial.println(F(")"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  캔 / 플라스틱 / 일반"));
  Serial.println(F("  열기 / 닫기 / 홈"));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  loop ─ 계속 반복
 * ═══════════════════════════════════════════════════════════════════════════ */
void loop() {
  drainBle();
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }
}
