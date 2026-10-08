/* ═══════════════════════════════════════════════════════════════════════════
 *  도리도리 로봇  (서보 1개 전용 · 단독 파일)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★ 이 파일은 "서보 하나"만 쓰는 로봇 전용입니다.
 *    다른 부품(모터·LED·부저) 없이 서보만 움직입니다.
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 바꾸실 곳은 딱 두 군데입니다 (아래 ★ 표시)
 *
 *    ★1  핀 번호    SERVO_PIN  = 9      ← 서보 신호선이 꽂힌 핀
 *    ★2  각도 값     아래 DORI / SAJIN 안의 숫자
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 명령어 (블루투스로 보내면 동작합니다)
 *
 *    1NubidaAi  (또는 1Nubida, 1)   →  도리도리  (좌우로 흔들기)
 *    2NubidaAi  (또는 2Nubida, 2)   →  삐졌어    (고개 푹 떨구기)
 *    3NubidaAi  (또는 3Nubida, 3)   →  인사      (끄덕끄덕)
 *    stop                            →  정지 (90도 중앙)
 *
 *  ⚠️ 2번 · 3번 핀은 블루투스 통신 전용이므로 서보를 꽂으면 안 됩니다.
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>
#include <Servo.h>

/* ══════════════════════════════════════════════════════════════════════
 *  ★1  서보 핀 번호  —  여기 숫자만 바꾸시면 됩니다
 * ══════════════════════════════════════════════════════════════════════ */
#define SERVO_PIN   9

/* 서보 각도 기준값 */
#define ANG_CENTER  90      // 정면 (가운데)
#define ANG_LEFT   140      // 도리도리 왼쪽
#define ANG_RIGHT   40      // 도리도리 오른쪽
#define ANG_SAD     25      // 삐졌어 (푹 떨굼)
#define ANG_UP     135      // 인사 위로

/* ─────────────────────────────────────────────────────────────────────
 *  블루투스 (BLE)  RX=2 / TX=3
 * ───────────────────────────────────────────────────────────────────── */
SoftwareSerial BTSerial(2, 3);

/* ─────────────────────────────────────────────────────────────────────
 *  서보 객체 — 함수 밖에 있어야 합니다 (안에 만들면 각도가 풀립니다)
 * ───────────────────────────────────────────────────────────────────── */
Servo head;

int curAngle = ANG_CENTER;   // 지금 서보가 있는 각도 (기억용)

/* ══════════════════════════════════════════════════════════════════════
 *  서보를 부드럽게 움직이는 함수
 *     deg : 목표 각도
 *     ms  : 그 각도까지 가는 데 걸리는 시간 (클수록 천천히)
 *
 *  서보에 "천천히 가"라고 못 하기 때문에,
 *  3도씩 나눠서 조금씩 보내면서 시간을 맞춥니다.
 * ══════════════════════════════════════════════════════════════════════ */
void servoTo(int deg, int ms) {

  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  int from = curAngle;
  if (from == deg) return;          // 이미 그 자리면 아무것도 안 함

  int total = abs(deg - from);
  int steps = total / 3;
  if (steps < 1) steps = 1;

  int tick = ms / steps;
  if (tick < 5) tick = 5;           // 너무 빠르면 서보가 떨려서 최소 5ms

  int dir = (deg > from) ? 3 : -3;
  int cur = from;

  for (int s = 1; s <= steps; s++) {
    cur += dir;
    if (dir > 0 && cur > deg) cur = deg;
    if (dir < 0 && cur < deg) cur = deg;
    head.write(cur);
    delay(tick);
  }

  // 마지막에 목표 각도에 정확히 오지 않았으면 한 번 더 (각도 오차 없애기)
  if (cur != deg) head.write(deg);
  curAngle = deg;
}

/* ══════════════════════════════════════════════════════════════════════
 *  동작 1 — 도리도리  (좌우로 흔들기)
 * ══════════════════════════════════════════════════════════════════════ */
void doDoriDori() {
  servoTo(ANG_LEFT,  400);
  servoTo(ANG_RIGHT, 700);
  servoTo(ANG_LEFT,  700);
  servoTo(ANG_RIGHT, 700);
  servoTo(ANG_CENTER, 400);
}

/* ══════════════════════════════════════════════════════════════════════
 *  동작 2 — 삐졌어  (고개 푹 떨구기)
 * ══════════════════════════════════════════════════════════════════════ */
void doSajin() {
  servoTo(ANG_CENTER, 200);
  servoTo(ANG_SAD,    900);   // 천천히 푹
  delay(800);                 // 잠깐 그대로 (삐진 척)
  servoTo(ANG_CENTER, 500);   // 다시 올림
}

/* ══════════════════════════════════════════════════════════════════════
 *  동작 3 — 인사  (끄덕끄덕)
 * ══════════════════════════════════════════════════════════════════════ */
void doInsah() {
  servoTo(ANG_UP, 300);
  servoTo(ANG_SAD, 400);
  servoTo(ANG_UP, 400);
  servoTo(ANG_SAD, 400);
  servoTo(ANG_CENTER, 300);
}

/* ══════════════════════════════════════════════════════════════════════
 *  명령 처리  —  한 줄을 받아서 알맞은 동작 실행
 * ══════════════════════════════════════════════════════════════════════ */
bool runCommand(String cmd) {

  if (cmd.equals("1NubidaAi") || cmd.equals("1Nubida") || cmd.equals("1")) {
    Serial.println(F("[동작] 도리도리"));
    doDoriDori();
    return true;
  }

  if (cmd.equals("2NubidaAi") || cmd.equals("2Nubida") || cmd.equals("2")) {
    Serial.println(F("[동작] 삐졌어"));
    doSajin();
    return true;
  }

  if (cmd.equals("3NubidaAi") || cmd.equals("3Nubida") || cmd.equals("3")) {
    Serial.println(F("[동작] 인사"));
    doInsah();
    return true;
  }

  if (cmd.equals("stop") || cmd.equals("STOP")) {
    Serial.println(F("[동작] 정지"));
    servoTo(ANG_CENTER, 300);
    return true;
  }

  return false;
}

/* ─────────────────────────────────────────────────────────────────────
 *  블루투스 수신 버퍼
 * ───────────────────────────────────────────────────────────────────── */
char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;

#define FRAME_GAP_MS 60

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
          Serial.print(F("[무시] 알 수 없는 명령: "));
          Serial.println(one);
        }
      }
    }
    start = i + 1;
  }
}

/* ══════════════════════════════════════════════════════════════════════
 *  setup  —  전원 켤 때 1번
 * ══════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  head.attach(SERVO_PIN);
  curAngle = ANG_CENTER;
  head.write(ANG_CENTER);
  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  도리도리 로봇 (서보 1개 전용)"));
  Serial.print(F("  서보 핀: "));
  Serial.println(SERVO_PIN);
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  1NubidaAi → 도리도리"));
  Serial.println(F("  2NubidaAi → 삐졌어"));
  Serial.println(F("  3NubidaAi → 인사"));
  Serial.println(F("  stop      → 정지"));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
}

/* ══════════════════════════════════════════════════════════════════════
 *  loop  —  계속 반복
 * ══════════════════════════════════════════════════════════════════════ */
void loop() {
  drainBle();
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }
}
