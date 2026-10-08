/* ═══════════════════════════════════════════════════════════════════════════
 *  도리도리 로봇 v5  (서보 2개 + AI 명령 처리 + 난독화 대응 + 오동작 방지)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ★ v5 에서 바뀐 점 ★  ← 이게 핵심입니다
 *    ⓐ 오동작 방지 (v4 의 문제를 고쳤습니다)
 *       · "11NubidaAi" → v4 는 "1Nubida" 가 들어있다고 도리도리를 했습니다.
 *                       v5 는 무시합니다 (번호 자릿수 검사)
 *       · "1" 조각만 와도 → v4 는 로봇이 움직였습니다.
 *                          v5 는 절대 움직이지 않습니다
 *       · 정의되지 않은 4~9번 → v5 는 안내 로그만 남기고 움직이지 않습니다
 *
 *    ⓑ v4 기능은 그대로 유지
 *       · 암호문(난독화) 풀기
 *       · "1NubidaA" 처럼 마지막 글자가 잘려 와도 인식
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  1NubidaAi  →  도리도리   (9번 서보 · 좌우로 흔들기)               │
 *  │  2NubidaAi  →  삐졌어     (9번 서보 · 고개 푹 떨구기)              │
 *  │  3NubidaAi  →  안녕       (7번 서보 · 끄덕끄덕 인사)               │
 *  │  4~99번     →  무시       (정의되지 않은 번호 · 움직이지 않음)     │
 *  ├────────────────────────────────────────────────────────────────────┤
 *  │  AI 명령  →  웹에서 만든 코드를 그대로 보내면 실행됩니다.          │
 *  │    digitalWrite(13,H);      13번 핀 켜기                          │
 *  │    digitalWrite(13,L);      13번 핀 끄기                          │
 *  │    int lamp = 13;           변수(핀) 이름 정하기                  │
 *  │    Serial.print(13);        13번 핀 값 읽어서 보내기              │
 *  │    if(cho < 20)             초음파 20cm 이내면 부저               │
 *  │    if(pos < 90)             모터 앞으로                           │
 *  │    if(pos > 90)             모터 뒤로                             │
 *  │    stop                     정지                                  │
 *  │    tone(8,262);             부저 울리기 (8번 핀)                  │
 *  │    noTone(8);               부저 끄기 (8번 핀)                    │
 *  │    BT.print(t10,e11);       초음파 거리 보내기                    │
 *  │    Piano.mode               초음파 피아노                         │
 *  │    Trash.mode               초음파 거리 재기                      │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ★ 설정은 아래 "설정" 부분 숫자만 바꾸시면 됩니다.
 *  ⚠️ 2번 · 3번 핀은 블루투스 통신 전용입니다.
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>
#include <Servo.h>

/* ═══════════════════════════════════════════════════════════════════════
 *  설정 ─ 여기 숫자만 바꾸시면 됩니다
 * ═══════════════════════════════════════════════════════════════════════ */

/* 서보가 꽂힌 핀 */
#define PIN_HEAD    9      // 도리도리 · 삐졌어 서보
#define PIN_ARM     7      // 안녕 서보
/* 부저가 꽂힌 핀 — 서보(9·7)와 절대 겹치면 안 됩니다 */
#define PIN_BUZZ    8      // 부저 (서보 7번 충돌 방지)

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
 *  ★ 난독화(암호문) 풀기
 *     웹이 보내는 "x1a2b3c..." 를 원래 명령으로 되돌립니다.
 *     ─────────────────────────────────────────────────────────────
 *     규칙 : 'x' + 2글자(열쇠) + [명령글자마다 2글자]
 *            각 2글자를 숫자로 바꾼 뒤 열쇠와 XOR 하면 원래 글자
 *     열쇠 : 0x2F (웹과 같아야 함)
 * ═══════════════════════════════════════════════════════════════════════ */
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
   *     → 버리지 말고 그 1글자만 빼고 계속 (나머지는 정상 복원됨)
   *     예) "1NubidaAi" 가 "1NubidaA" 로 와도 알아봅니다 */
  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  /* (3) 열쇠 꺼내기 */
  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";

  /* (4) 한 글자씩 열쇠와 XOR 해서 원래 글자로
   *     ★ 한글은 1글자가 3바이트라서, "영문만 남기고 버리면"
   *       한글 명령이 전부 사라집니다. → 한글 바이트도 살립니다 */
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

/* ═══════════════════════════════════════════════════════════════════════
 *  서보 2개 기억장치
 *    ※ 함수 밖에 있어야 합니다 (안에 만들면 각도가 풀립니다)
 * ═══════════════════════════════════════════════════════════════════════ */
Servo srv[2];
int   srvPin[2] = { PIN_HEAD, PIN_ARM };
int   srvCur[2] = { CENTER,   CENTER   };

/* ═══════════════════════════════════════════════════════════════════════
 *  서보를 부드럽게 움직이는 함수
 *    pin : 서보 핀   deg : 목표 각도(0~180)   ms : 걸리는 시간
 * ═══════════════════════════════════════════════════════════════════════ */
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

/* ═══════════════════════════════════════════════════════════════════════
 *  함수 미리 알리기 (전방 선언)
 *    C++ 는 위에서 아래로 읽기 때문에, 아래에 정의된 함수를 위에서 쓰려면
 *    "이런 함수가 있다"고 미리 알려줘야 합니다.
 * ═══════════════════════════════════════════════════════════════════════ */
bool handleAiCommand(String cmd);

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
  servoTo(PIN_HEAD, SAD_DOWN, MS_SLOW);
  delay(800);
  servoTo(PIN_HEAD, CENTER,   MS_NORMAL);
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
 *
 *  ★ v5 에서 바뀐 점 (오동작 방지)
 *    ① 두 자릿수 번호를 한 자리로 오인하지 않습니다.
 *         v4 : "11NubidaAi" → "1Nubida" 가 들어있어서 도리도리 (오동작!)
 *         v5 : "Nubida" 위치가 정확히 1번째일 때만 인정 → 무시
 *    ② 번호 뒤에는 반드시 "Nubida" 가 와야 합니다.
 *         BLE 는 긴 명령을 잘라 보냅니다. 그래서 "1NubidaAi" 가
 *         "1" + "NubidaAi" 로 나뉘어 도착할 수 있습니다.
 *         v4 : "1" 만 와도 로봇이 움직였습니다 (오동작!)
 *         v5 : "1" 단독으로는 절대 움직이지 않습니다
 *    ③ AI 명령(1~3번) 구역에 들어오면 무조건 그 안에서 끝냅니다.
 *         아래 평문 명령 검사로 흘러가지 않습니다.
 *    ④ "1NubidaA" 처럼 마지막 글자가 잘려 와도 인식합니다 (v4 기능 유지).
 * ═══════════════════════════════════════════════════════════════════════ */
bool runCommand(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  ★ 1단계 ─ AI 명령(난독화를 푼 명령)인지 먼저 확인
   *     "Nubida" 라는 글자가 있으면 AI 명령으로 봅니다.
   * ══════════════════════════════════════════════════════════════════════ */
  int np = cmd.indexOf("Nubida");

  if (np >= 0) {

    /* (1) 번호는 반드시 맨 앞 한 글자여야 합니다.
     *     "11NubidaAi" → "Nubida" 가 2번째 → 자릿수가 맞지 않음 → 무시
     *     "31NubidaAi" → "Nubida" 가 2번째 → 자릿수가 맞지 않음 → 무시 */
    if (np != 1) {
      Serial.print(F("[무시] 번호 자릿수가 맞지 않습니다 → "));
      Serial.println(cmd);
      return true;      // ★ 여기서 끝. 아래로 흘러가지 않습니다.
    }

    char n = cmd.charAt(0);

    /* (2) 맨 앞이 숫자가 아니면 무시 */
    if (n < '0' || n > '9') {
      Serial.print(F("[무시] 번호가 아닙니다 → "));
      Serial.println(cmd);
      return true;
    }

    /* (3) 1~3번 ─ 정해진 동작 실행 */
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

    /* ══════════════════════════════════════════════════════════════════
     *  ★★ 6번에 동작을 추가하려면 여기에 넣으시면 됩니다 ★★
     *
     *      6번에 "춤추기" 를 넣고 싶다면 아래 두 줄의 // 를 지우세요.
     *
     *      if (n == '6') {
     *        Serial.println(F("[동작] 춤추기"));
     *        doHello();          // ← 원하는 동작 함수 이름으로 바꾸세요
     *        return true;
     *      }
     *
     *  ⚠️ return true; 를 꼭 남겨두세요. 빼면 아래 평문 검사로
     *     흘러가서 엉뚱한 동작이 실행될 수 있습니다.
     * ══════════════════════════════════════════════════════════════════════ */

    /* (4) 그 외 번호(0, 4~9) ─ 이 로봇에 정의되지 않은 번호입니다.
     *     움직이지 않고 안내만 합니다.
     *     (10 이상은 위 (1) 에서 이미 걸러졌습니다) */
    Serial.print(F("[무시] "));
    Serial.print(n);
    Serial.println(F("번 ─ 이 로봇에 정의되지 않은 번호입니다 (움직이지 않습니다)"));
    return true;        // ★ 여기서 끝. 평문 검사로 흘러가지 않습니다.
  }

  /* ══════════════════════════════════════════════════════════════════════
   *  ★ 2단계 ─ AI 가 만들어 준 코드 명령 (digitalWrite, tone 등)
   * ══════════════════════════════════════════════════════════════════════ */
  if (handleAiCommand(cmd)) return true;

  /* ══════════════════════════════════════════════════════════════════════
   *  ★ 3단계 ─ 그 밖의 평문 명령
   *     ⚠️ 숫자 한 글자("1","2","3")는 절대 여기에 넣지 마세요.
   *        블루투스가 명령을 잘라 보낼 때 그 조각만 도착해서
   *        로봇이 저절로 움직이는 원인이 됩니다.
   * ══════════════════════════════════════════════════════════════════════ */

  return false;    // 모르는 명령
}

/* ═══════════════════════════════════════════════════════════════════════
 *  ★★★ AI 명령 처리 ★★★
 *
 *  웹(누비다플랫폼)에서 AI가 만들어 준 코드를 그대로 받아서 실행합니다.
 *
 *  [1단계] 값 꺼내기
 *      "digitalWrite(13,H);"  →  HIGHResult = "13"
 *      "int lamp = 13;"       →  INTResult1="lamp", INTResult2="13"
 *      이렇게 명령 안에서 숫자·이름만 뽑아냅니다.
 *
 *  [2단계] 실행
 *      뽑아낸 값으로 실제 부품을 움직입니다.
 *
 *  [중요] 모든 조건은 if / else if 로 연결했습니다.
 *         그래서 위에서 하나 걸리면 아래는 확인하지 않습니다.
 * ═══════════════════════════════════════════════════════════════════════ */
bool handleAiCommand(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  【1단계】 값 꺼내기
   *     indexOf()  : 그 글자가 몇 번째에 있는지 찾기 (-1 = 없음)
   *     substring(): 그 위치부터 잘라내기
   * ══════════════════════════════════════════════════════════════════════ */

  /* digitalWrite(13,H);  →  13 뽑기 */
  int HIGH_a = cmd.indexOf("digitalWrite(");
  int HIGH_b = cmd.indexOf(",H);");
  String HIGHResult = (HIGH_a >= 0 && HIGH_b > HIGH_a)
                      ? cmd.substring(HIGH_a + 13, HIGH_b) : "";

  /* digitalWrite(13,L);  →  13 뽑기 */
  int LOW_a = cmd.indexOf("digitalWrite(");
  int LOW_b = cmd.indexOf(",L);");
  String LOWResult = (LOW_a >= 0 && LOW_b > LOW_a)
                     ? cmd.substring(LOW_a + 13, LOW_b) : "";

  /* int lamp = 13;  →  "lamp" 과 "13" 뽑기 */
  int INT_a = cmd.indexOf("int ");
  int INT_b = cmd.indexOf(" = ");
  int INT_c = cmd.indexOf(";");
  String INTResult1 = (INT_a >= 0 && INT_b > INT_a)
                      ? cmd.substring(INT_a + 4, INT_b) : "";
  String INTResult2 = (INT_b > 0 && INT_c > INT_b)
                      ? cmd.substring(INT_b + 3, INT_c) : "";

  /* Serial.print(13);  →  13 뽑기 */
  int SR_a = cmd.indexOf("Serial.print(");
  int SR_b = cmd.indexOf(");");
  String SRResult = (SR_a >= 0 && SR_b > SR_a)
                    ? cmd.substring(SR_a + 13, SR_b) : "";

  /* tone(7,262);  →  "7" 과 "262" 뽑기 */
  int TN_a = cmd.indexOf("tone(");
  int TN_c = cmd.indexOf(",");
  int TN_b = cmd.indexOf(");");
  String TNResult1 = (TN_a >= 0 && TN_c > TN_a)
                     ? cmd.substring(TN_a + 5, TN_c) : "";
  String TNResult2 = (TN_c > 0 && TN_b > TN_c)
                     ? cmd.substring(TN_c + 1, TN_b) : "";

  /* noTone(7);  →  7 뽑기 */
  int NT_a = cmd.indexOf("noTone(");
  int NT_b = cmd.indexOf(");");
  String NTResult = (NT_a >= 0 && NT_b > NT_a)
                    ? cmd.substring(NT_a + 7, NT_b) : "";

  /* if(cho < 20)  →  20 뽑기 */
  int CHO_a = cmd.indexOf("if(cho <");
  String CHOResult = "";
  if (CHO_a >= 0) {
    String t = cmd.substring(CHO_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) CHOResult = t.substring(0, e);
  }

  /* if(pos < 90)  →  90 뽑기 */
  int POSL_a = cmd.indexOf("if(pos <");
  String POSLResult = "";
  if (POSL_a >= 0) {
    String t = cmd.substring(POSL_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSLResult = t.substring(0, e);
  }

  /* if(pos > 90)  →  90 뽑기 */
  int POSG_a = cmd.indexOf("if(pos >");
  String POSGResult = "";
  if (POSG_a >= 0) {
    String t = cmd.substring(POSG_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSGResult = t.substring(0, e);
  }

  /* BT.print(t10,e11);  →  "10" 과 "11" 뽑기 */
  int BP_a = cmd.indexOf("BT.print(t");
  int BP_c = cmd.indexOf(",e");
  int BP_b = cmd.indexOf(");");
  String BPResult1 = (BP_a >= 0 && BP_c > BP_a)
                     ? cmd.substring(BP_a + 10, BP_c) : "";
  String BPResult2 = (BP_c > 0 && BP_b > BP_c)
                     ? cmd.substring(BP_c + 2, BP_b) : "";

  /* ══════════════════════════════════════════════════════════════════════
   *  【2단계】 실행  ─  if / else if 로 전부 연결
   * ══════════════════════════════════════════════════════════════════════ */

  /* ── digitalWrite(13,H);  →  13번 핀 켜기 ── */
  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);") && HIGHResult.length() > 0) {
    { int pin = HIGHResult.toInt();
      if (pin == PIN_HEAD || pin == PIN_ARM) { Serial.println(F("[보호] 서보핀 무시")); return true; }
      pinMode(pin, OUTPUT); digitalWrite(pin, HIGH); }
    { int ms = 100; delay(ms); }
    Serial.println(F("[AI] digitalWrite H"));
    return true;
  }

  /* ── digitalWrite(13,L);  →  13번 핀 끄기 ── */
  else if (cmd.equals("digitalWrite(" + LOWResult + ",L);") && LOWResult.length() > 0) {
    { int pin = LOWResult.toInt();
      if (pin == PIN_HEAD || pin == PIN_ARM) { Serial.println(F("[보호] 서보핀 무시")); return true; }
      pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
    { int ms = 100; delay(ms); }
    Serial.println(F("[AI] digitalWrite L"));
    return true;
  }

  /* ── int lamp = 13;  →  변수(핀) 이름 정하기 ── */
  else if (cmd.equals("int " + INTResult1 + " = " + INTResult2 + ";")
           && INTResult1.length() > 0 && INTResult2.length() > 0) {
    BTSerial.println(INTResult1 + "의 변수명은 " + INTResult2 + "번의 핀을 사용합니다.");
    { int ms = 100; delay(ms); }
    Serial.println(F("[AI] int 변수"));
    return true;
  }

  /* ── Serial.print(13);  →  13번 핀 값 읽어서 보내기 ── */
  else if (cmd.equals("Serial.print(" + SRResult + ");") && SRResult.length() > 0) {
    { int pin = SRResult.toInt();
      pinMode(pin, INPUT);
      BTSerial.println(digitalRead(pin)); }
    { int ms = 100; delay(ms); }
    Serial.println(F("[AI] Serial.print"));
    return true;
  }

  /* ── if(cho < 20)  →  초음파 20cm 이내면 부저 ── */
  else if (cmd.equals("if(cho < " + CHOResult + ")") && CHOResult.length() > 0) {
    { int limit = CHOResult.toInt();
      int trigPin = 10, echoPin = 11;
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      float cm = dur / 58.0;
      if (cm < limit) {
        { int bp = PIN_BUZZ, bf = 262, bm = 1000;
          pinMode(bp, OUTPUT); tone(bp, bf, bm); }
      } else {
        { int bp = PIN_BUZZ; pinMode(bp, OUTPUT); noTone(bp); }
      } }
    { int ms = 1000; delay(ms); }
    Serial.println(F("[AI] 초음파 조건"));
    return true;
  }

  /* ── if(pos < 90)  →  모터 앞으로 ── */
  else if (cmd.equals("if(pos < " + POSLResult + ")") && POSLResult.length() > 0) {
    { int pinA = 4, pinB = 5, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }
    Serial.println(F("[AI] 모터 앞으로"));
    return true;
  }

  /* ── if(pos > 90)  →  모터 뒤로 ── */
  else if (cmd.equals("if(pos > " + POSGResult + ")") && POSGResult.length() > 0) {
    { int pinA = 4, pinB = 5, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      digitalWrite(pinA, LOW); analogWrite(pinB, pwm); }
    Serial.println(F("[AI] 모터 뒤로"));
    return true;
  }

  /* ── stop  →  모터 정지 ── */
  else if (cmd.equals("stop")) {
    { int pinA = 4, pinB = 5;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
    /* 서보도 가운데로 */
    servoTo(PIN_HEAD, CENTER, MS_FAST);
    servoTo(PIN_ARM,  CENTER, MS_FAST);
    Serial.println(F("[AI] 정지"));
    return true;
  }

  /* ── tone(7,262);  →  부저 ── */
  else if (cmd.equals("tone(" + TNResult1 + "," + TNResult2 + ");")
           && TNResult1.length() > 0 && TNResult2.length() > 0) {
    { int pin = TNResult1.toInt(), freq = TNResult2.toInt(), ms = 1000;
      /* 서보 핀(9·7)으로 부저 신호가 가면 서보가 죽습니다 → 부저핀으로 우회 */
      if (pin == PIN_HEAD || pin == PIN_ARM) pin = PIN_BUZZ;
      pinMode(pin, OUTPUT); tone(pin, freq, ms); }
    Serial.println(F("[AI] 부저"));
    return true;
  }

  /* ── noTone(7);  →  부저 끄기 ── */
  else if (cmd.equals("noTone(" + NTResult + ");") && NTResult.length() > 0) {
    { int pin = NTResult.toInt();
      if (pin == PIN_HEAD || pin == PIN_ARM) pin = PIN_BUZZ;
      pinMode(pin, OUTPUT); noTone(pin); }
    Serial.println(F("[AI] 부저 끄기"));
    return true;
  }

  /* ── BT.print(t10,e11);  →  초음파 거리 보내기 ── */
  else if (cmd.equals("BT.print(t" + BPResult1 + ",e" + BPResult2 + ");")
           && BPResult1.length() > 0 && BPResult2.length() > 0) {
    { int trigPin = BPResult1.toInt(), echoPin = BPResult2.toInt();
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      float cm = dur / 58.0;
      Serial.println(cm);
      BTSerial.println(cm); }
    { int ms = 500; delay(ms); }
    Serial.println(F("[AI] 거리 전송"));
    return true;
  }

  /* ── Piano.mode  →  초음파 피아노 ── */
  else if (cmd.equals("Piano.mode")) {
    { int trigPin = 10, echoPin = 11;
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      float cm = dur / 58.0;
      int f = 0;
      if      (cm < 4)    f = 262;
      else if (cm < 6.9)  f = 294;
      else if (cm < 9.8)  f = 330;
      else if (cm < 12.5) f = 349;
      else if (cm < 14.6) f = 392;
      else if (cm < 16)   f = 440;
      else if (cm < 18)   f = 494;
      else if (cm < 20.1) f = 523;
      { int bp = PIN_BUZZ;
        pinMode(bp, OUTPUT);
        if (f) { tone(bp, f, 300); } else { noTone(bp); } } }
    Serial.println(F("[AI] 피아노"));
    return true;
  }

  /* ── Trash.mode  →  초음파 거리 재기 ── */
  else if (cmd.equals("Trash.mode")) {
    { int trigPin = 10, echoPin = 11;
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      float cm = dur / 58.0;
      Serial.println(cm);
      BTSerial.println(cm); }
    { int ms = 500; delay(ms); }
    Serial.println(F("[AI] 거리 측정"));
    return true;
  }

  /* ── 걸리는 명령 없음 ── */
  return false;
}

/* ═══════════════════════════════════════════════════════════════════════
 *  블루투스 수신
 * ═══════════════════════════════════════════════════════════════════════ */
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

        /* ── ★ 여기가 핵심 ──
         *    'x' 로 시작하면 암호문 → 풀어서 원래 명령으로 바꿉니다
         *    웹앱은 명령을 그냥 보내지 않고 암호처럼 바꿔 보냅니다. */
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

/* ═══════════════════════════════════════════════════════════════════════
 *  setup / loop
 * ═══════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  for (int i = 0; i < 2; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(CENTER);
    srvCur[i] = CENTER;
  }
  delay(300);

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  도리도리 로봇 v6  (서보·부저 핀 충돌 해결)"));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));      Serial.println(F(__TIME__));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  도리도리 · 삐졌어  →  "));
  Serial.print(PIN_HEAD); Serial.println(F("번 서보"));
  Serial.print(F("  안녕               →  "));
  Serial.print(PIN_ARM);  Serial.println(F("번 서보"));
  Serial.print(F("  부저               →  "));
  Serial.print(PIN_BUZZ); Serial.println(F("번 핀"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  1NubidaAi → 도리도리"));
  Serial.println(F("  2NubidaAi → 삐졌어"));
  Serial.println(F("  3NubidaAi → 안녕"));
  Serial.println(F("  4~9NubidaAi → 무시 (정의되지 않은 번호)"));
  Serial.println(F("  + AI 명령 13종"));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
}

void loop() {
  drainBle();
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }
}
