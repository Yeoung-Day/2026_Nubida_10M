/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다 블루투스카  v2  (DC 모터 2개 · 모터드라이버 4핀)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★ v2 에서 바뀐 점 ★
 *    v1 은 "명령이 오는 동안만" 움직였습니다.
 *    → 버튼을 한 번 누르면 0.8초만 가고 멈춰서, 동작이 안 되는 것처럼 보였습니다.
 *
 *    v2 는 "한 번 누르면 정해진 시간만큼 스스로 갑니다."
 *    → 전진 누르면 1.5초 동안 전진하고 자동으로 섭니다.
 *    → 계속 가게 하려면 시간을 늘리거나 0(무한)으로 바꾸세요.
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  명령어 (블루투스로 보내면 동작)                                   │
 *  │                                                                    │
 *  │    전진   ( f / F / go / forward / 전진 / 앞 )                     │
 *  │    후진   ( b / B / back / 후진 / 뒤 )                             │
 *  │    좌회전 ( l / L / left / 좌회전 / 좌 )                            │
 *  │    우회전 ( r / R / right / 우회전 / 우 )                           │
 *  │    정지   ( s / S / stop / 정지 / 멈춤 )                            │
 *  │                                                                    │
 *  │    ★ 한 번 누르면 MOVE_MS 만큼 움직이고 자동으로 섭니다.           │
 *  │    ★ 계속 가려면 정지 명령을 보낼 때까지 계속 가게 할 수 있습니다. │
 *  │       (MOVE_MS 를 0 으로 바꾸면 무한)                              │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 배선 (L9110S 모터드라이버 2개 기준 — 가장 흔한 구성)
 *
 *      왼쪽 모터                아두이노 나노         오른쪽 모터
 *      ──────────               ─────────────         ──────────
 *        IA  ───────────────────  4번  ─────────────── IA
 *        IB  ───────────────────  5번  ─────────────── IB
 *                                6번  ─────────────── IA
 *                                7번  ─────────────── IB
 *        VCC ───────────────────  5V(VIN)
 *        GND ───────────────────  GND
 *
 *      ⚠️ 모터 전원은 배터리(9V 등)를 VIN 에 넣어야 힘이 좋습니다.
 *      ⚠️ 2번·3번 핀은 블루투스 전용이라 쓰지 마세요.
 * ─────────────────────────────────────────────────────────────────────────
 *
 *  ★ 순서대로 확인하세요 (동작이 안 될 때)
 *      ① 시리얼 모니터(9600) 를 열고 전원을 켠다
 *         → "누비다 블루투스카" 목록이 보이는가?
 *      ② 전진 명령을 보낸다
 *         → "[동작] 전진" 이 보이는가?
 *      ③ "[동작] 전진" 은 보이는데 바퀴가 안 돌면 → 배선/전원 문제
 *      ④ "[무시]" 가 보이면 → 명령 글자가 안 맞는 것 (아래 명령어 확인)
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  설정 ─ 여기 숫자만 바꾸시면 됩니다
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 왼쪽 모터 (모터드라이버 A) ── */
#define LEFT_A      4      // 왼쪽 모터 제어 1
#define LEFT_B      5      // 왼쪽 모터 제어 2

/* ── 오른쪽 모터 (모터드라이버 B) ── */
#define RIGHT_A     6      // 오른쪽 모터 제어 1
#define RIGHT_B     7      // 오른쪽 모터 제어 2

/* ── 속도 (0 ~ 100) ── */
#define SPEED_GO    70     // 직진 속도
#define SPEED_TURN  60     // 회전 속도

/* ── 한 번 누르면 움직이는 시간 (밀리초) ──
 *    1500 = 1.5초
 *    0    = 정지 명령을 받을 때까지 계속 (무한)                        */
#define MOVE_MS     1500

/* ═══════════════════════════════════════════════════════════════════════════
 *  블루투스 (BLE)  RX=2 / TX=3
 * ═══════════════════════════════════════════════════════════════════════════ */
SoftwareSerial BTSerial(2, 3);

/* ═══════════════════════════════════════════════════════════════════════════
 *  모터 제어
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 모터 한 개 ──
 *    speed : -100 ~ 100  ( + 앞 / - 뒤 / 0 정지 )
 */
void motorOne(int pinA, int pinB, int speed) {

  if (speed > 100)  speed = 100;
  if (speed < -100) speed = -100;

  int mag = abs(speed);
  int pwm = map(mag, 0, 100, 0, 255);

  if (speed > 0) {
    analogWrite(pinA, pwm); digitalWrite(pinB, LOW);      // 앞으로
  } else if (speed < 0) {
    digitalWrite(pinA, LOW); analogWrite(pinB, pwm);      // 뒤로
  } else {
    digitalWrite(pinA, LOW); digitalWrite(pinB, LOW);     // 정지
  }
}

/* ── 두 모터 한꺼번에 ── */
void drive(int left, int right) {
  motorOne(LEFT_A,  LEFT_B,  left);
  motorOne(RIGHT_A, RIGHT_B, right);
}

void goForward()  { drive( SPEED_GO,   SPEED_GO); }   // 전진
void goBack()     { drive(-SPEED_GO,  -SPEED_GO); }   // 후진
void turnLeft()   { drive(-SPEED_TURN, SPEED_TURN); } // 좌회전 (왼 뒤 + 오른 앞)
void turnRight()  { drive( SPEED_TURN,-SPEED_TURN); } // 우회전 (왼 앞 + 오른 뒤)
void stopAll()    { drive(0, 0); }                    // 정지

/* ═══════════════════════════════════════════════════════════════════════════
 *  명령 처리
 * ═══════════════════════════════════════════════════════════════════════════ */

/* 움직임 상태 기억 */
unsigned long moveStart  = 0;      // 움직이기 시작한 시각
bool          isMoving   = false;  // 지금 움직이는 중인가

/* ── 움직임 시작 ── */
void startMove() {
  moveStart = millis();
  isMoving  = true;
}

/* ── 명령 하나 처리 ── */
bool runCommand(String cmd) {

  /* ── 전진 ── */
  if (cmd.equals("전진") || cmd.equals("앞") ||
      cmd.equals("f") || cmd.equals("F") ||
      cmd.equals("go") || cmd.equals("forward")) {
    Serial.println(F("[동작] 전진"));
    goForward();
    startMove();
    return true;
  }

  /* ── 후진 ── */
  else if (cmd.equals("후진") || cmd.equals("뒤") ||
           cmd.equals("b") || cmd.equals("B") ||
           cmd.equals("back")) {
    Serial.println(F("[동작] 후진"));
    goBack();
    startMove();
    return true;
  }

  /* ── 좌회전 ── */
  else if (cmd.equals("좌회전") || cmd.equals("좌") || cmd.equals("왼쪽") ||
           cmd.equals("l") || cmd.equals("L") || cmd.equals("left")) {
    Serial.println(F("[동작] 좌회전"));
    turnLeft();
    startMove();
    return true;
  }

  /* ── 우회전 ── */
  else if (cmd.equals("우회전") || cmd.equals("우") || cmd.equals("오른쪽") ||
           cmd.equals("r") || cmd.equals("R") || cmd.equals("right")) {
    Serial.println(F("[동작] 우회전"));
    turnRight();
    startMove();
    return true;
  }

  /* ── 정지 ── */
  else if (cmd.equals("정지") || cmd.equals("멈춤") || cmd.equals("스톱") ||
           cmd.equals("s") || cmd.equals("S") || cmd.equals("stop")) {
    Serial.println(F("[동작] 정지"));
    stopAll();
    isMoving = false;
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

#define FRAME_GAP_MS 60

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

  /* 모터 4핀 준비 + 처음엔 정지 */
  pinMode(LEFT_A,  OUTPUT); pinMode(LEFT_B,  OUTPUT);
  pinMode(RIGHT_A, OUTPUT); pinMode(RIGHT_B, OUTPUT);
  stopAll();

  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  누비다 블루투스카 v2"));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  왼쪽 모터  →  "));
  Serial.print(LEFT_A);  Serial.print(F(",")); Serial.println(LEFT_B);
  Serial.print(F("  오른쪽 모터 →  "));
  Serial.print(RIGHT_A); Serial.print(F(",")); Serial.println(RIGHT_B);
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  전진 f / 후진 b / 좌회전 l / 우회전 r / 정지 s"));
  Serial.print(F("  한 번에 "));
  if (MOVE_MS > 0) { Serial.print(MOVE_MS / 1000.0, 1); Serial.println(F("초 이동")); }
  else             { Serial.println(F("계속 이동 (정지 명령까지)")); }
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

  /* ── 정해진 시간이 지나면 자동 정지 ──
   *    MOVE_MS = 0 이면 이 부분은 동작하지 않습니다 (정지 명령까지 계속) */
  if (MOVE_MS > 0 && isMoving && (millis() - moveStart) >= (unsigned long)MOVE_MS) {
    Serial.println(F("[자동정지] 이동 시간 끝"));
    stopAll();
    isMoving = false;
  }
}
