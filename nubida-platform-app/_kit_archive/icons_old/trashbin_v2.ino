/* ═══════════════════════════════════════════════════════════════════════════
 *  스마트 휴지통  v2  (서보모터 3개 · 캔 / 플라스틱 / 일반 분리)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★ v2 에서 바뀐 점 ★  ← 이게 핵심입니다
 *
 *    웹앱(누비다플랫폼)은 명령을 그냥 보내지 않고
 *    "xa1bfc0fbece7eaefcfe" 처럼 암호처럼 바꿔서(난독화) 보냅니다.
 *
 *    v1 까지는 이 암호문을 그대로 읽어서
 *      [명령] xa1bfc0fbece7eaefcfe
 *      [무시] xa1bfc0fbece7eaefcfe     ← 그래서 동작이 안 됐습니다
 *
 *    v2 는 암호문을 풀어서 원래 명령(캔, 플라스틱 ...)을 알아냅니다.
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
 *  │                                                                    │
 *  │  ★ 누비다머신 AI 명령도 그대로 쓸 수 있습니다                     │
 *  │       1NubidaAi → 캔    2NubidaAi → 플라스틱   3NubidaAi → 일반   │
 *  │       4NubidaAi → 열기  5NubidaAi → 닫기       6NubidaAi → 홈     │
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
 *  ★ 순서대로 확인하세요 (동작이 안 될 때)
 *      ① 시리얼 모니터(9600) 를 열고 전원을 켠다
 *         → "스마트 휴지통 v2" + "[빌드] 날짜" 가 보이는가?
 *           (안 보이면 업로드가 안 된 것입니다 → 시리얼 모니터 닫고 다시 업로드)
 *      ② 캔 명령을 보낸다
 *         → "[복호화] → [캔]" 이 보이는가?
 *         → "[동작] 캔 분리" 가 보이는가?
 *      ③ "[동작]" 은 보이는데 서보가 안 움직이면 → 배선/전원 문제
 *      ④ 서보가 떨리거나 힘이 없으면 → 서보 전원을 외부 5V 로
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

  /* (1) 쓸 수 있는 16진수 글자만 모은다 */
  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  /* (2) 글자 수가 홀수면 마지막 1글자가 잘린 것
   *     → 버리지 말고 그 1글자만 빼고 계속 (나머지는 정상 복원됨) */
  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  /* (3) 열쇠 꺼내기 */
  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";

  /* (4) 한 글자씩 열쇠와 XOR 해서 원래 글자로
   *     ★ 한글은 1글자가 3바이트라서, "영문만 남기고 버리면"
   *       한글 명령(캔·일반 등)이 전부 사라집니다. → 한글 바이트도 살립니다 */
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

  /* ══════════════════════════════════════════════════════════════════════
   *  ★ 누비다머신 AI 명령이 오면 휴지통 동작으로 연결합니다
   *     ★ 마지막 글자(i)가 잘려서 "1NubidaA" 로 와도 알아봅니다.
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.length() >= 7 && cmd.charAt(0) >= '1' && cmd.charAt(0) <= '6'
      && cmd.indexOf("Nubida") >= 0) {
    char n = cmd.charAt(0);
    Serial.print(F("[AI명령] ")); Serial.print(n); Serial.println(F("번 → 휴지통 동작"));

    if (n == '1') { sortTrash(GATE_CAN);     return true; }
    if (n == '2') { sortTrash(GATE_PLASTIC); return true; }
    if (n == '3') { sortTrash(GATE_NORMAL);  return true; }
    if (n == '4') { lidOpen();               return true; }
    if (n == '5') { lidClose();              return true; }
    if (n == '6') { goHome();                return true; }
  }

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
  else if (cmd.equals("열기") || cmd.equals("open") || cmd.equals("4")) {
    Serial.println(F("[동작] 뚜껑 열기"));
    lidOpen();
    return true;
  }

  /* ── 뚜껑만 닫기 ── */
  else if (cmd.equals("닫기") || cmd.equals("close") || cmd.equals("5")) {
    Serial.println(F("[동작] 뚜껑 닫기"));
    lidClose();
    return true;
  }

  /* ── 홈 (처음 위치) ── */
  else if (cmd.equals("홈") || cmd.equals("home") ||
           cmd.equals("reset") || cmd.equals("6")) {
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

        /* ── ★ 여기가 v2 의 핵심 ──
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
  Serial.println(F("  스마트 휴지통 v2  (난독화 대응)"));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));      Serial.println(F(__TIME__));
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
