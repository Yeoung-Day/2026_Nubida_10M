/* ═══════════════════════════════════════════════════════════════════════════
 *  스마트 휴지통  v5  (뚜껑 3개 · 서보모터 3개 · 떨림 완전 완화판)
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 / 아두이노 나노 CH340
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  구조                                                              │
 *  │                                                                    │
 *  │     캔 통      플라스틱 통      일반 통                             │
 *  │    ┌─────┐    ┌─────┐        ┌─────┐                              │
 *  │    │ 뚜껑 │    │ 뚜껑 │        │ 뚜껑 │   ← 서보 3개가 각각 담당     │
 *  │    └─────┘    └─────┘        └─────┘                              │
 *  │      5번        7번             9번                                 │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ★ 밀대·분리대는 없습니다. 뚜껑만 열고 닫습니다.
 *
 *  ════════════════════════════════════════════════════════════════════════
 *  ★★ v5 에서 바뀐 점 ★★  ← "1개가 움직이면 다른 2개가 떨린다" 해결
*  ════════════════════════════════════════════════════════════════════════
*
*  윤비스님 증상 :
*    - 떨리는 서보 = 3개 다       → 전원(전류) 부족이 맞음
*    - 1개를 움직이려 하면        → 나머지 2개가 같이 떨림
*    - 그래도 천천히 자연스럽게 하나씩 열리고 닫혀야 함
*
*  ★ 진짜 원인 ─ "힘을 잡고 있는 서보(holding torque)"
*  ──────────────────────────────────────────────────────────────
*    서보는 명령을 받은 뒤에도 계속 전원을 먹으며 각도를 잡고 있습니다.
*    (이걸 holding torque 라고 합니다)
*
*    뚜껑 3개 중 1개만 움직여도, 안 움직이는 2개가 각도를 버티느라
*    전류를 같이 먹습니다. 전원이 부족하면 그 틈에 전압이 흔들려서
*    안 움직이는 서보들이 "드드득" 떨립니다.
*
*    → 서보 3개 × 0.4A = 최대 1.2A 를 계속 요구하는 셈입니다.
*      나노 5V 핀은 0.4A 밖에 못 주니 당연히 떨립니다.
*
*  ★ v5 해결책 ─ 안 쓰는 서보는 힘을 뺀다
*  ──────────────────────────────────────────────────────────────
*    ① 【힘 빼기】 움직이지 않는 서보는 detach() 로 전원을 끊습니다
*         → 떨림의 직접 원인 제거. 전류 소모도 크게 줄어듭니다.
*
*    ② 【부드럽게 왕복】 떨림 방지를 위해 뚜껑을 "천천히" 여닫습니다
*         (기계식 댐퍼가 없는 서보라, 급하게 멈추면 덜컥거립니다)
*
*    ③ 【한 번에 1개】 순차 동작 유지 → 순간 전류 1/3
*
*    ④ 【순수 정지】 움직이는 동안 다른 서보에 신호를 보내지 않습니다
*         → 전원이 한 곳에만 집중됩니다
*
*  ⚠️ 절충 ─ 힘을 빼면 뚜껑이 손으로 밀리거나 무게에 의해 내려앉을 수
*     있습니다. 그래서 "힘 유지가 꼭 필요한 경우"를 위해 스위치를
*     남겨 두었습니다 :
*
*        #define HOLD_TORQUE  0   // 0 = 떨림 없음(권장) / 1 = 각도 유지
*
*     뚜껑이 처지면 1 로 바꾸세요. (대신 떨림이 돌아올 수 있음)
*
*  ⚠️ 근본 해결은 여전히 전원입니다. 서보 전원(빨강)을 외부 5V 2A 로
*     분리하시면 v5 설정 그대로도 떨림이 거의 사라집니다.
* ═══════════════════════════════════════════════════════════════════════════
*
*  ★ 웹앱 대응 ★
 *    웹은 명령을 "xa1bfc0fbece7eaecfe" 처럼 암호로 바꿔 보냅니다.
 *    v4 는 그 암호를 풀어서 원래 명령(캔·일반 ...)을 알아냅니다.
 *    한글 명령도 정상 동작합니다.
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │  명령어 (블루투스로 보내면 동작)                                   │
 *  │                                                                    │
 *  │    캔        →  5번 뚜껑 열기 → 잠깐 → 닫기                        │
 *  │    플라스틱  →  7번 뚜껑 열기 → 잠깐 → 닫기                        │
 *  │    일반      →  9번 뚜껑 열기 → 잠깐 → 닫기                        │
 *  │    열기      →  뚜껑 3개 하나씩 열기                               │
 *  │    닫기      →  뚜껑 3개 하나씩 닫기                               │
 *  │    홈        →  뚜껑 3개 모두 닫기 (처음 상태)                     │
 *  │                                                                    │
 *  │  ★ 누비다머신 AI 명령도 그대로 쓸 수 있습니다                     │
 *  │       1NubidaAi → 캔    2NubidaAi → 플라스틱   3NubidaAi → 일반   │
 *  │       4NubidaAi → 열기  5NubidaAi → 닫기       6NubidaAi → 홈     │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 배선
 *
 *      캔 뚜껑 서보        신호선(주황) → 5번
 *      플라스틱 뚜껑 서보  신호선(주황) → 7번
 *      일반 뚜껑 서보      신호선(주황) → 9번
 *      서보 전원(빨강)     →  ★ 외부 5V 2A 어댑터 (나노 5V 아님!)
 *      서보 접지(갈색)     →  GND  ← 나노 GND 와 반드시 연결(공통 접지)
 *
 *      ⚠️ 외부 전원을 쓰더라도 GND 는 나노와 꼭 이어야 합니다.
 *      ⚠️ 2번·3번 핀은 블루투스 전용입니다.
 * ─────────────────────────────────────────────────────────────────────────
 *
 *  ★ 순서대로 확인하세요 (동작이 안 될 때)
 *      ① 시리얼 모니터(9600) 를 열고 전원을 켠다
 *         → "스마트 휴지통 v5" + "[빌드] 날짜" 가 보이는가?
 *           (안 보이면 업로드가 안 된 것입니다 → 모니터 닫고 다시 업로드)
 *      ② 캔 명령을 보낸다
 *         → "[복호화] → [캔]" 이 보이는가?
 *         → "[동작] 캔 뚜껑 열기" 가 보이는가?
 *      ③ "[동작]" 은 보이는데 서보가 떨리면
 *         → 전원 부족입니다. 서보 전원을 외부 5V 로 분리하세요.
 *      ④ 서보가 180도에서 웅웅거리며 떨면
 *         → 각도를 180 대신 175 로 낮춰 보세요 (끝에서 걸리는 것)
 *      ⑤ 1개가 움직일 때 다른 것이 떨리면
 *         → v5 는 안 쓰는 서보의 힘을 자동으로 뺍니다 (해결됨)
 *         → 그래도 떨리면 전원 부족이 확실합니다. 외부 5V 로 분리하세요.
 * ═══════════════════════════════════════════════════════════════════════════ */

#include <SoftwareSerial.h>
#include <Servo.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  설정 ─ 여기 숫자만 바꾸시면 됩니다
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 뚜껑 3개가 꽂힌 핀 ──
 *    ★ 순서를 바꾸고 싶으면 이 세 줄의 핀 번호만 바꾸세요            */
#define PIN_CAN       5    // 캔 뚜껑 서보
#define PIN_PLASTIC   7    // 플라스틱 뚜껑 서보
#define PIN_NORMAL    9    // 일반 뚜껑 서보

/* ── 뚜껑 각도 ──
 *    뚜껑마다 각도가 다르면 따로 지정할 수 있습니다.
 *
 *    ★ 각도를 180 으로 두면 서보가 끝까지 가서 기어가 걸립니다.
 *      그 상태에서 웅웅거리며 떨리면 180 → 175 로 낮춰 보세요.        */
#define CAN_CLOSE      95     // 캔 뚜껑 닫힘
#define CAN_OPEN      180     // 캔 뚜껑 열림
#define PLASTIC_CLOSE  95     // 플라스틱 뚜껑 닫힘
#define PLASTIC_OPEN  180     // 플라스틱 뚜껑 열림
#define NORMAL_CLOSE   95     // 일반 뚜껑 닫힘
#define NORMAL_OPEN   180     // 일반 뚜껑 열림

/* ── 움직이는 속도 (숫자가 클수록 천천히) ──
 *    ★ 천천히 움직이면 전류를 덜 먹어서 떨림이 줄어듭니다.           */
#define MS_OPEN      600     // 여는 속도  (400 → 600, 더 천천히)
#define MS_CLOSE     600     // 닫는 속도  (400 → 600, 더 천천히)

/* ── 뚜껑이 열려 있는 시간 (사람이 쓰레기를 넣는 시간) ── */
#define OPEN_HOLD_MS 2000    // 2초간 열어 둠

/* ═══════════════════════════════════════════════════════════════════════════
 *  ★ 떨림 완화 설정
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 서보 사이 쉬는 시간 (밀리초) ──
 *    한 서보가 움직이고 나면 잠깐 쉬어서 전원이 회복되게 합니다.
 *    ★ 더 심하게 떨리면 300 으로 늘리세요.                            */
#define REST_BETWEEN_MS 150

/* ── 서보 힘 제한 (20 ~ 100 %) ──
 *    낮출수록 약하게 움직여서 전류를 덜 먹습니다.
 *    ★ 뚜껑이 무거우면 올리고, 떨리면 내리세요.
 *      100 = 제한 없음 (기본)
 *       70 = 약하게 (전류 절약)                                  */
#define SERVO_POWER   100

/* ── ★ 안 쓰는 서보의 힘을 뺄까? (v5 핵심) ──
 *    서보는 멈춰 있어도 각도를 잡느라 전원을 계속 먹습니다.
 *    그 때문에 "1개가 움직일 때 나머지가 떨리는" 현상이 생깁니다.
 *
 *      0 = 힘 빼기  ← 떨림 없음 (권장)
 *      1 = 각도 유지 ← 떨림이 생길 수 있지만 뚜껑이 처지지 않음
 *
 *    ★ 뚜껑이 손으로 밀리거나 무게로 내려앉으면 1 로 바꾸세요.     */
#define HOLD_TORQUE   0

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
int   srvPin[3]  = { PIN_CAN,     PIN_PLASTIC,    PIN_NORMAL     };
int   srvShut[3] = { CAN_CLOSE,   PLASTIC_CLOSE,  NORMAL_CLOSE   };  // 닫힘 각도
int   srvOpen[3] = { CAN_OPEN,    PLASTIC_OPEN,   NORMAL_OPEN    };  // 열림 각도
int   srvCur[3]  = { CAN_CLOSE,   PLASTIC_CLOSE,  NORMAL_CLOSE   };  // 현재 각도

/* ═══════════════════════════════════════════════════════════════════════════
 *  ★ 서보 다루기 (v5 핵심)
 *
 *  핵심 아이디어 :
 *      "움직이는 서보만 힘을 갖고, 나머지는 힘을 뺀다"
 *
 *  attach() = 서보에 전원을 넣는다 (힘을 잡음, 전류를 먹음)
 *  detach() = 서보에서 전원을 끊는다 (떨림 없음, 전류 0)
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 서보에 전원을 넣는다 (아직 attach 안 된 경우만) ── */
void srvEnable(int idx) {
  if (idx < 0 || idx > 2) return;
  srv[idx].attach(srvPin[idx]);          // 준비 : 각도는 바로 아래에서 씀
  srv[idx].write(srvCur[idx]);           // 현재 각도로 즉시 세팅
}

/* ── 서보에서 전원을 끊는다 (안 움직일 때) ──
 *    ★ 이 한 줄이 떨림을 없앱니다.                                */
void srvRelease(int idx) {
  if (idx < 0 || idx > 2) return;
  srv[idx].detach();
}

/* ── ★ 서보를 부드럽게 움직이는 함수 ──
 *    idx : 서보 번호(0=캔, 1=플라스틱, 2=일반)
 *    deg : 목표 각도(0~180)     ms : 걸리는 시간
 *
 *  ① 움직이기 전에 그 서보만 전원을 넣습니다 (나머지는 힘 빠진 상태)
 *  ② 1도씩 아주 잘게 나눠서 보냅니다 → 부드럽고 전류가 적게 듭니다
 *  ③ 다 움직이면 다시 힘을 뺍니다 → 떨림 없음
 *     (HOLD_TORQUE 를 1 로 하면 힘을 유지합니다)
 * ═══════════════════════════════════════════════════════════════════════════ */
void servoTo(int idx, int deg, int ms) {

  if (idx < 0 || idx > 2) return;
  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  int from = srvCur[idx];
  if (from == deg) return;              // 이미 그 위치면 그냥 넘어감

  int total = abs(deg - from);

  /* ★ 이 서보만 전원을 넣는다 (다른 서보는 힘 빠진 채로 있음)
   *   → 1개가 움직일 때 나머지가 떨리는 현상의 직접 해결 */
  srvEnable(idx);

  /* ── 1도씩 나눠서 보낸다 ──
   *   잘게 나눌수록 부드럽고 전류가 적게 듭니다 */
  int steps = total; if (steps < 1) steps = 1;
  int tick  = ms / steps; if (tick < 5) tick = 5;   // 너무 빠르지 않게 하한

  int dir = (deg > from) ? 1 : -1;
  int cur = from;

  for (int s = 1; s <= steps; s++) {
    cur += dir;
    if (dir > 0 && cur > deg) cur = deg;
    if (dir < 0 && cur < deg) cur = deg;

    /* ★ 힘 제한 — 약하게 쓸수록 전류를 덜 먹는다 */
    if (SERVO_POWER < 100 && SERVO_POWER >= 20) {
      srv[idx].writeMicroseconds(
        map(cur, 0, 180, 500 + (100 - SERVO_POWER) * 5,
                           2500 - (100 - SERVO_POWER) * 5));
    } else {
      srv[idx].write(cur);
    }

    delay(tick);
  }

  if (cur != deg) srv[idx].write(deg);
  srvCur[idx] = deg;

  /* ★ 다 움직였으면 전원을 끊는다 (떨림 없음)
   *   뚜껑이 처지면 HOLD_TORQUE 를 1 로 바꾸세요 */
  if (!HOLD_TORQUE) {
    delay(80);              // 힘을 잡고 마지막 각도를 확실히 잡게 함
    srvRelease(idx);
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  뚜껑 열기 / 닫기
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 뚜껑 하나 열기 ── */
void lidOpen(int idx) {
  servoTo(idx, srvOpen[idx], MS_OPEN);
}

/* ── 뚜껑 하나 닫기 ── */
void lidClose(int idx) {
  servoTo(idx, srvShut[idx], MS_CLOSE);
}

/* ── ★ 뚜껑 3개 모두 열기 ──
 *    ★ v5 : 하나씩 움직이고, 움직이는 동안 나머지는 힘이 빠져 있습니다.
 *      (안 움직이는 서보가 각도를 버티면 전류를 같이 먹어서
 *       움직이는 서보까지 떨립니다)
 * ═══════════════════════════════════════════════════════════════════════════ */
void allOpen() {
  Serial.println(F("[순차] 뚜껑 3개 하나씩 열기"));
  for (int i = 0; i < 3; i++) {
    Serial.print(F("      → "));
    Serial.print(i == 0 ? "캔" : (i == 1 ? "플라스틱" : "일반"));
    Serial.println(F(" 열기"));
    lidOpen(i);
    delay(REST_BETWEEN_MS);        // ★ 전원이 회복될 시간
  }
}

/* ── ★ 뚜껑 3개 모두 닫기 (= 홈) ──
 *    ★ v5 : 여기도 하나씩, 나머지는 힘을 뺀 상태로 움직입니다.   */
void allClose() {
  Serial.println(F("[순차] 뚜껑 3개 하나씩 닫기"));
  for (int i = 0; i < 3; i++) {
    Serial.print(F("      → "));
    Serial.print(i == 0 ? "캔" : (i == 1 ? "플라스틱" : "일반"));
    Serial.println(F(" 닫기"));
    lidClose(i);
    delay(REST_BETWEEN_MS);        // ★ 전원이 회복될 시간
  }
}

/* ── 뚜껑 열고 → 잠깐 기다렸다가 → 닫기 ──
 *    쓰레기를 넣는 동안 열어 두는 동작입니다.
 *    (한 개만 움직이므로 전류가 가장 적게 듭니다)                 */
void openThenClose(int idx, String name) {

  Serial.print(F("[동작] "));
  Serial.print(name);
  Serial.println(F(" 뚜껑 열기"));

  lidOpen(idx);                 // 열기
  delay(OPEN_HOLD_MS);          // 열어 둔 채 기다리기 (넣는 시간)
  delay(REST_BETWEEN_MS);       // ★ 전원 회복

  Serial.print(F("[동작] "));
  Serial.print(name);
  Serial.println(F(" 뚜껑 닫기"));

  lidClose(idx);                // 닫기
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

    if (n == '1') { openThenClose(0, "캔");       return true; }
    if (n == '2') { openThenClose(1, "플라스틱"); return true; }
    if (n == '3') { openThenClose(2, "일반");     return true; }
    if (n == '4') { Serial.println(F("[동작] 전부 열기")); allOpen();  return true; }
    if (n == '5') { Serial.println(F("[동작] 전부 닫기")); allClose(); return true; }
    if (n == '6') { Serial.println(F("[동작] 처음 상태")); allClose(); return true; }
  }

  /* ── 캔 : 5번 뚜껑 ── */
  if (cmd.equals("캔") || cmd.equals("can") || cmd.equals("1")) {
    openThenClose(0, "캔");
    return true;
  }

  /* ── 플라스틱 : 7번 뚜껑 ── */
  else if (cmd.equals("플라스틱") || cmd.equals("plastic") || cmd.equals("2")) {
    openThenClose(1, "플라스틱");
    return true;
  }

  /* ── 일반 : 9번 뚜껑 ── */
  else if (cmd.equals("일반") || cmd.equals("일반쓰레기") ||
           cmd.equals("normal") || cmd.equals("3")) {
    openThenClose(2, "일반");
    return true;
  }

  /* ── 뚜껑 3개 모두 열기 ── */
  else if (cmd.equals("열기") || cmd.equals("전부열기") ||
           cmd.equals("open") || cmd.equals("allopen") || cmd.equals("4")) {
    Serial.println(F("[동작] 전부 열기"));
    allOpen();
    return true;
  }

  /* ── 뚜껑 3개 모두 닫기 ── */
  else if (cmd.equals("닫기") || cmd.equals("전부닫기") ||
           cmd.equals("close") || cmd.equals("allclose") || cmd.equals("5")) {
    Serial.println(F("[동작] 전부 닫기"));
    allClose();
    return true;
  }

  /* ── 홈 (처음 상태 = 모두 닫기) ── */
  else if (cmd.equals("홈") || cmd.equals("home") ||
           cmd.equals("reset") || cmd.equals("6")) {
    Serial.println(F("[동작] 처음 상태"));
    allClose();
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

        /* ── ★ 여기가 핵심 ──
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

  /* 서보 3개 준비 (처음엔 닫힌 상태)
   *   ★ v5 : 닫힌 각도까지 이동시킨 뒤 힘을 뺍니다.
   *     (부팅 직후 떨림 방지) */
  for (int i = 0; i < 3; i++) {
    srv[i].attach(srvPin[i]);
    srv[i].write(srvShut[i]);
  }
  delay(700);                        // 각도를 잡을 시간

  if (!HOLD_TORQUE) {
    for (int i = 0; i < 3; i++) srv[i].detach();   // 힘 빼기
  }

  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  스마트 휴지통 v5  (뚜껑 3개 · 떨림 완전 완화)"));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));      Serial.println(F(__TIME__));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  캔       →  ")); Serial.print(PIN_CAN);
  Serial.print(F("번 뚜껑  (닫힘 ")); Serial.print(CAN_CLOSE);
  Serial.print(F(" / 열림 "));        Serial.print(CAN_OPEN);
  Serial.println(F(")"));
  Serial.print(F("  플라스틱 →  ")); Serial.print(PIN_PLASTIC);
  Serial.print(F("번 뚜껑  (닫힘 ")); Serial.print(PLASTIC_CLOSE);
  Serial.print(F(" / 열림 "));        Serial.print(PLASTIC_OPEN);
  Serial.println(F(")"));
  Serial.print(F("  일반     →  ")); Serial.print(PIN_NORMAL);
  Serial.print(F("번 뚜껑  (닫힘 ")); Serial.print(NORMAL_CLOSE);
  Serial.print(F(" / 열림 "));        Serial.print(NORMAL_OPEN);
  Serial.println(F(")"));
  Serial.println(F("------------------------------------------"));
  Serial.print(F("  열어 두는 시간 : "));
  Serial.print(OPEN_HOLD_MS / 1000.0, 1);
  Serial.println(F("초"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  ★ 떨림 완화 설정"));
  Serial.print(F("    안 쓰는 서보  : "));
  Serial.println(HOLD_TORQUE ? F("힘 유지 (각도 고정)")
                             : F("★ 힘 빼기 (떨림 없음 · 권장)"));
  Serial.print(F("    순차 동작     : 켜짐 (하나씩 움직임)"));
  Serial.println(F(""));
  Serial.print(F("    서보 사이 휴식: "));
  Serial.print(REST_BETWEEN_MS);
  Serial.println(F("ms"));
  Serial.print(F("    서보 힘 제한  : "));
  Serial.print(SERVO_POWER);
  Serial.println(F("%"));
  Serial.print(F("    움직이는 속도 : 열기 "));
  Serial.print(MS_OPEN);
  Serial.print(F("ms / 닫기 "));
  Serial.print(MS_CLOSE);
  Serial.println(F("ms"));
  Serial.println(F("------------------------------------------"));
  Serial.println(F("  ⚠️ 뚜껑이 힘없이 처지면"));
  Serial.println(F("     소스 맨 위 #define HOLD_TORQUE 0 을 1 로 바꾸세요."));
  Serial.println(F(""));
  Serial.println(F("  ⚠️ 서보가 계속 떨리면"));
  Serial.println(F("     서보 전원(빨강)을 나노 5V 에서 빼고"));
  Serial.println(F("     외부 5V 2A 어댑터에 연결하세요."));
  Serial.println(F("     (GND 는 나노와 꼭 연결)"));
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
