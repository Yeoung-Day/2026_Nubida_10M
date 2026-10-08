/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다 블루투스카  (DC 모터 2개 · 모터드라이버 4핀)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  명령어 (블루투스로 보내면 동작)                                   │
 *  │                                                                    │
 *  │    전진  ( f / F / go / forward )   →  앞으로                     │
 *  │    후진  ( b / B / back )           →  뒤로                       │
 *  │    좌회전( l / L / left )           →  왼쪽으로 돌기              │
 *  │    우회전( r / R / right )          →  오른쪽으로 돌기            │
 *  │    정지  ( s / S / stop )           →  멈춤                       │
 *  │                                                                    │
 *  │    ★ 명령을 보내는 동안 계속 움직입니다.                          │
 *  │      (정지 명령을 보내거나, 자동정지 시간이 지나면 멈춤)          │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 배선 (L9110S 모터드라이버 2개 기준 — 가장 흔한 구성)
 *
 *      모터드라이버 A          아두이노 나노         모터드라이버 B
 *      ────────────           ─────────────         ────────────
 *        A-IA  ───────────────  4번  ───────────────  B-IA
 *        A-IB  ───────────────  5번  ───────────────  B-IB
 *        VCC   ───────────────  5V(VIN)
 *        GND   ───────────────  GND
 *        A-OA/B-OA  ─── 왼쪽 모터 (앞/뒤)
 *        A-OB/B-OB  ─── 오른쪽 모터 (앞/뒤)
 *
 *      ⚠️ 모터 전원은 배터리(9V 등)를 VIN 에 넣어야 힘이 좋습니다.
 *      ⚠️ 2번·3번 핀은 블루투스 전용이라 쓰지 마세요.
 * ─────────────────────────────────────────────────────────────────────────
 *
 *  ★ 만약 L298N(4선 + ENA/ENB)을 쓰신다면 → 아래 "설정" 부분 설명 참고
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
#define SPEED_TURN  60     // 회전 속도 (직진보다 살짝 약하게)

/* ── 자동 정지 시간 (밀리초) ──
 *    명령을 받고 이 시간 동안 새 명령이 없으면 자동으로 멈춥니다.
 *    계속 움직이게 하려면 0 으로 바꾸세요.                            */
#define AUTO_STOP_MS  800

/* ═══════════════════════════════════════════════════════════════════════════
 *  블루투스 (BLE)  RX=2 / TX=3
 * ═══════════════════════════════════════════════════════════════════════════ */
SoftwareSerial BTSerial(2, 3);

/* ═══════════════════════════════════════════════════════════════════════════
 *  모터 움직이는 부분
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 모터 한 개 돌리기 ──
 *    pinA/pinB : 그 모터의 두 제어핀
 *    speed     : -100 ~ 100  ( + 앞으로 / - 뒤로 / 0 정지 )
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

/* ── 두 모터 한꺼번에 ──
 *    left  : 왼쪽 모터 속도 (-100~100)
 *    right : 오른쪽 모터 속도 (-100~100)
 */
void drive(int left, int right) {
  motorOne(LEFT_A,  LEFT_B,  left);
  motorOne(RIGHT_A, RIGHT_B, right);
}

/* ── 전진 ── 양쪽 다 앞으로 */
void goForward() {
  drive(SPEED_GO, SPEED_GO);
}

/* ── 후진 ── 양쪽 다 뒤로 */
void goBack() {
  drive(-SPEED_GO, -SPEED_GO);
}

/* ── 좌회전 ── 왼쪽은 뒤로, 오른쪽은 앞으로 (제자리 회전) */
void turnLeft() {
  drive(-SPEED_TURN, SPEED_TURN);
}

/* ── 우회전 ── 왼쪽은 앞으로, 오른쪽은 뒤로 (제자리 회전) */
void turnRight() {
  drive(SPEED_TURN, -SPEED_TURN);
}

/* ── 정지 ── 둘 다 멈춤 */
void stopAll() {
  drive(0, 0);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  명령 처리
 * ═══════════════════════════════════════════════════════════════════════════ */

/* 지금 움직이고 있는 상태 (AUTO_STOP_MS 용) */
unsigned long lastMoveAt = 0;
bool          moving     = false;

bool runCommand(String cmd) {

  /* ── 전진 ── */
  if (cmd.equals("전진") || cmd.equals("f") || cmd.equals("F") ||
      cmd.equals("go")  || cmd.equals("forward") || cmd.equals("앞")) {
    Serial.println(F("[동작] 전진"));
    goForward();
    return true;
  }

  /* ── 후진 ── */
  else if (cmd.equals("후진") || cmd.equals("b") || cmd.equals("B") ||
           cmd.equals("back") || cmd.equals("뒤")) {
    Serial.println(F("[동작] 후진"));
    goBack();
    return true;
  }

  /* ── 좌회전 ── */
  else if (cmd.equals("좌회전") || cmd.equals("l") || cmd.equals("L") ||
           cmd.equals("left")   || cmd.equals("왼쪽") || cmd.equals("좌")) {
    Serial.println(F("[동작] 좌회전"));
    turnLeft();
    return true;
  }

  /* ── 우회전 ── */
  else if (cmd.equals("우회전") || cmd.equals("r") || cmd.equals("R") ||
           cmd.equals("right")   || cmd.equals("오른쪽") || cmd.equals("우")) {
    Serial.println(F("[동작] 우회전"));
    turnRight();
    return true;
  }

  /* ── 정지 ── */
  else if (cmd.equals("정지") || cmd.equals("s") || cmd.equals("S") ||
           cmd.equals("stop") || cmd.equals("멈춤")) {
    Serial.println(F("[동작] 정지"));
    stopAll();
    moving = false;
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

        unsigned long before = moving;   // 명령 전 상태

        if (runCommand(one)) {
          /* 움직이는 명령이면 자동정지 타이머 시작 */
          if (!one.equals("정지") && !one.equals("s") && !one.equals("S") &&
              !one.equals("stop") && !one.equals("멈춤")) {
            moving = true;
          }
          lastMoveAt = millis();
        } else {
          Serial.print(F("[무시] "));
          Serial.println(one);
        }
        (void)before;
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

  /* 모터 4핀 준비 */
  pinMode(LEFT_A,  OUTPUT); pinMode(LEFT_B,  OUTPUT);
  pinMode(RIGHT_A, OUTPUT); pinMode(RIGHT_B, OUTPUT);
  stopAll();                 // 처음엔 멈춘 상태로

  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  누비다 블루투스카"));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  왼쪽 모터  →  "));
  Serial.print(LEFT_A);  Serial.print(F(",")); Serial.println(LEFT_B);
  Serial.print(F("  오른쪽 모터 →  "));
  Serial.print(RIGHT_A); Serial.print(F(",")); Serial.println(RIGHT_B);
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  전진 f / 후진 b / 좌회전 l / 우회전 r / 정지 s"));
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

  /* ── 자동 정지 ──
   *    움직이는 중인데 AUTO_STOP_MS 동안 새 명령이 없으면 멈춥니다.
   *    (블루투스가 끊겨서 차가 혼자 달려가는 것을 막아줍니다)
   */
  if (AUTO_STOP_MS > 0 && moving && (millis() - lastMoveAt) > AUTO_STOP_MS) {
    Serial.println(F("[자동정지] 명령 없음"));
    stopAll();
    moving = false;
  }
}
