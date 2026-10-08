/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다 블루투스카  v4  (DC 모터 2개 · 모터드라이버 4핀)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★ v3 에서 바뀐 점 ★  ← 이게 핵심입니다
 *
 *    웹앱(누비다플랫폼)은 명령을 그냥 보내지 않고
 *    "xa1bfc0fbece7eaefcfe" 처럼 암호처럼 바꿔서(난독화) 보냅니다.
 *
 *    v2 까지는 이 암호문을 그대로 읽어서
 *      [명령] xa1bfc0fbece7eaefcfe
 *      [무시] xa1bfc0fbece7eaefcfe     ← 그래서 동작이 안 됐습니다
 *
 *    v3 는 암호문을 풀어서 원래 명령(f, 전진 ...)을 알아냅니다.
 *
 *  ★ v4 에서 바뀐 점 ★  (오동작 방지)
 *
 *    ① 두 자리 번호가 1번(전진)으로 오동작하던 것을 막았습니다
 *         "10NubidaAi" → 예전엔 전진 / 이제는 [무시] (움직이지 않음)
 *    ② 6번 이상 번호가 엉뚱한 동작을 하던 것을 막았습니다
 *         6~9 번 → [무시] (모터를 움직이지 않음)
 *    ③ AI 명령은 알아본 순간 무조건 끝냅니다 (평문으로 흘러가지 않음)
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  명령어 (블루투스로 보내면 동작)                                   │
 *  │                                                                    │
 *  │    전진   ( f / F / go / forward / 전진 / 앞 )                     │
 *  │    후진   ( b / B / back / 후진 / 뒤 )                             │
 *  │    좌회전 ( l / L / left / 좌회전 / 좌 )                            │
 *  │    우회전 ( r / R / right / 우회전 / 우 )                           │
 *  │    정지   ( s / S / stop / 정지 / 멈춤 )                           │
 *  │                                                                    │
 *  │    ★ 한 번 누르면 MOVE_MS 만큼 움직이고 자동으로 섭니다.           │
 *  │       (MOVE_MS 를 0 으로 바꾸면 정지 명령까지 계속)                │
 *  │                                                                    │
 *  │  ── AI(ML Studio) 명령 ──                                          │
 *  │    1NubidaAi → 전진   2NubidaAi → 후진   3NubidaAi → 좌회전        │
 *  │    4NubidaAi → 우회전 5NubidaAi → 정지                             │
 *  │    6번 이상 → [무시] (모터를 움직이지 않음)                        │
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
 *         → "누비다 블루투스카 v4" + "[빌드] 날짜" 가 보이는가?
 *           (안 보이면 업로드가 안 된 것입니다 → 시리얼 모니터 닫고 다시 업로드)
 *      ② 전진 명령을 보낸다
 *         → "[복호화] x... → f" 가 보이는가?
 *         → "[동작] 전진" 이 보이는가?
 *      ③ "[동작] 전진" 은 보이는데 바퀴가 안 돌면 → 배선/전원 문제
 *      ④ "[무시]" 가 보이면 → 명령 글자가 안 맞는 것
 *         · "6번은 정의되지 않은 번호입니다" → 정상입니다 (6번 이상은 안 움직임)
 *         · "번호 자릿수가 맞지 않습니다"    → 정상입니다 (10번 이상은 안 움직임)
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
 *  ★ 난독화(암호문) 풀기
 *     웹이 보내는 "x1a2b3c..." 를 원래 명령으로 되돌립니다.
 *     ─────────────────────────────────────────────────────────────
 *     규칙 : 'x' + 2글자(열쇠) + [명령글자마다 2글자]
 *            각 2글자를 숫자로 바꾼 뒤 열쇠와 XOR 하면 원래 글자
 *     열쇠 : 0x2F (웹과 같아야 함)
 * ═══════════════════════════════════════════════════════════════════════════ */
#define NB_KEY 0x2F

/* 16진수 글자 1개 → 숫자   ('a'→10, 'F'→15, 아니면 -1) */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* "x...." 를 원래 명령으로 되돌림. 실패하면 빈 문자열("") */
String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  /* (1) 쓸 수 있는 16진수 글자만 모은다
   *     (중간에 줄바꿈·공백·이상한 글자가 섞여도 걸러냄) */
  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  /* (2) 글자 수가 홀수면 마지막 1글자가 잘린 것
   *     → 버리지 말고 그 1글자만 빼고 계속 (나머지는 정상 복원됨)
   *     예) 19글자로 와도 "전진" 을 알아낼 수 있습니다 */
  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  /* (3) 열쇠 꺼내기 */
  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";

  /* (4) 한 글자씩 열쇠와 XOR 해서 원래 글자로
   *     ★ 한글은 1글자가 3바이트라서, 예전처럼 "영문만 남기고 버리면"
   *       한글 명령(전진·정지 등)이 전부 사라집니다. → 한글 바이트도 살립니다 */
  String out = "";
  for (unsigned int i = 2; i + 1 < hexs.length(); i += 2) {
    int h1 = hexVal(hexs.charAt(i));
    int h2 = hexVal(hexs.charAt(i + 1));
    if (h1 < 0 || h2 < 0) continue;
    char c = (char)((h1 * 16 + h2) ^ seed);
    out += c;                                  // ★ 거르지 않고 그대로 담음
  }
  out.trim();
  return out;
}

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

  /* ══════════════════════════════════════════════════════════════════════
   *  ★ 누비다머신 AI 명령이 오면 블루투스카 동작으로 연결합니다
   *     (웹앱이 ML Studio 쪽 명령을 보내는 경우가 있어서 넣어둡니다)
   *
   *       1NubidaAi  →  전진
   *       2NubidaAi  →  후진
   *       3NubidaAi  →  좌회전
   *       4NubidaAi  →  우회전
   *       5NubidaAi  →  정지
   *
   *     ★ 마지막 글자(i)가 잘려서 "1NubidaA" 로 와도 알아봅니다.
   * ══════════════════════════════════════════════════════════════════════
   *
   *   ★★★ [2026-09-16 v4] 안전장치 강화 ★★★
   *
   *     v3 까지의 문제 2가지를 고쳤습니다.
   *
   *     ── 문제 ① 두 자리 번호가 1번(전진)으로 오동작 ──
   *        서버(/ml/bt-command)는 클래스 번호를 **1~99 까지** 허용합니다.
   *        v3 는 cmd.charAt(0) 만 봤기 때문에
   *          "10NubidaAi" → charAt(0)='1' → **전진** (오동작!)
   *          "11NubidaAi" → charAt(0)='1' → **전진** (오동작!)
   *        이 되었습니다.
   *        → 'Nubida' 앞에 숫자가 **정확히 한 글자**일 때만 처리합니다.
   *
   *     ── 문제 ② 정의되지 않은 번호가 평문 매칭으로 흘러감 ──
   *        v3 는 6~9 번이 오면 AI 블록을 못 들어가고 그대로 빠져나가
   *        아래 평문 if 문으로 흘러갔습니다. (엉뚱한 동작 위험)
   *        → 번호를 알아본 **순간 무조건 return true** 하여
   *          절대 아래로 흘러가지 않게 막았습니다.
   *
   *     ── 6번 이상은 동작하지 않습니다 (안전) ──
   *        1~5 번만 동작하고, 6번 이상은 [무시] 로그만 남기고
   *        **모터를 움직이지 않습니다** (휴지통 v6 와 동일한 정책).
   *
   *        ★ 6번에 동작을 추가하고 싶으면 아래 "6번 자리" 주석을 보고
   *          if 문 한 줄을 추가하면 됩니다.
   * ══════════════════════════════════════════════════════════════════════ */
  int np = cmd.indexOf("Nubida");       // 'Nubida' 가 시작하는 위치

  if (np >= 0) {
    /* ── (1) 숫자는 'Nubida' 바로 앞에 정확히 1글자여야 한다 ──
     *     np==1 → "1Nubida..."  (정상)
     *     np==2 → "10Nubida..." (두 자리 → 처리하지 않음)
     *     np==0 → "Nubida..."   (숫자 없음 → 처리하지 않음)           */
    if (np != 1) {
      Serial.println(F("[무시] 번호 자릿수가 맞지 않습니다 - 모터를 움직이지 않습니다"));
      return true;                      // ★ AI 명령으로 인식했으므로 아래로 보내지 않음
    }

    char n = cmd.charAt(0);

    /* ── (2) 숫자가 아니면 무시 ── */
    if (n < '0' || n > '9') {
      Serial.println(F("[무시] 번호가 아닙니다 - 모터를 움직이지 않습니다"));
      return true;
    }

    /* ── (3) 정의된 번호(1~5)만 동작 ── */
    if (n >= '1' && n <= '5') {
      Serial.print(F("[AI명령] ")); Serial.print(n); Serial.println(F("번 → 카 동작"));

      if (n == '1') { goForward(); startMove(); return true; }
      if (n == '2') { goBack();    startMove(); return true; }
      if (n == '3') { turnLeft();  startMove(); return true; }
      if (n == '4') { turnRight(); startMove(); return true; }
      if (n == '5') { stopAll();   isMoving = false; return true; }
    }

    /* ── (4) 정의되지 않은 번호 (0, 6~9) ──
     *     ★ 여기서 반드시 return 한다. 아래 평문 if 문으로 흘러가면
     *       "6NubidaAi" 같은 값이 엉뚱한 동작을 만들 수 있다.
     *
     *     ★ 6번에 동작을 추가하려면 위 (3) 블록 안에 이렇게 한 줄 넣으세요:
     *          if (n == '6') { stopAll(); isMoving = false; return true; }   // 6번 = 정지
     *       그리고 아래 n <= '5' 를 n <= '6' 으로 바꾸면 됩니다.        */
    Serial.print(F("[무시] "));
    Serial.print(n);
    Serial.println(F("번은 정의되지 않은 번호입니다 - 모터를 움직이지 않습니다"));
    return true;                        // ★★★ 반드시 return (아래로 흘러가지 않음)
  }

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

        /* ── ★ 여기가 v3 의 핵심 ──
         *    'x' 로 시작하면 암호문 → 풀어서 원래 명령으로 바꿉니다 */
        if (one.charAt(0) == 'x') {
          String plain = decodeFrame(one);
          Serial.print(F("[복호화] → ["));
          Serial.print(plain);
          Serial.println(F("]"));
          if (plain.length() == 0) {
            Serial.println(F("[무시] 복호화 실패 (조각일 수 있음)"));
            continue;
          }
          one = plain;                      // ← 이제 원래 명령이 됨
        }

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
  Serial.println(F("  누비다 블루투스카 v4  (난독화 대응 + 오동작 방지)"));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));      Serial.println(F(__TIME__));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  왼쪽 모터  →  "));
  Serial.print(LEFT_A);  Serial.print(F(",")); Serial.println(LEFT_B);
  Serial.print(F("  오른쪽 모터 →  "));
  Serial.print(RIGHT_A); Serial.print(F(",")); Serial.println(RIGHT_B);
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  전진 f / 후진 b / 좌회전 l / 우회전 r / 정지 s"));
  Serial.println(F("  AI명령 1~5번 동작 / 6번 이상은 무시(안 움직임)"));
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
