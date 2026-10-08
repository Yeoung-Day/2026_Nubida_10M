#include "Servo.h"

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════
 *  누비다머신 수신 펌웨어 — 2서보 안정판 (v5)
 * ───────────────────────────────────────────────────────────────────
 *  [배선]  ★ 두 서보 모두 VCC/S/GND 3핀에 올바로 꽂혀야 한다.
 *      서보 A (1NubidaAi) : 주황(S) → D9
 *      서보 B (2NubidaAi) : 주황(S) → D7
 *      빨강(+) → 5V (또는 외부 5~6V) / 갈색(-) → GND
 *
 *  [★★ 이 버전의 핵심 — 두 서보를 절대 동시에 돌리지 않는다 ★★]
 *    전원이 하나뿐이라 두 서보가 함께 움직이면 순간 전류가 2배가 되어
 *    나노가 브라운아웃 리셋된다. 따라서
 *      · 1NubidaAi 가 오면 → 9번 서보만 스캔 (7번은 detach = 무전류)
 *      · 2NubidaAi 가 오면 → 7번 서보만 스캔 (9번은 detach = 무전류)
 *    스캔이 끝나면 해당 서보를 즉시 detach 해서 힘을 뺀다.
 *
 *  [안정화]
 *    1) 비블로킹(millis) 스캔 — loop 가 계속 살아 통신이 안 끊긴다
 *    2) 스텝 2도 / 40ms — 한 번에 적은 전류만 소모
 *    3) 스캔 중 새 명령은 무시 (재트리거 폭주 방지)
 *    4) 스캔 완료 후 서보 detach → 대기 전류 0 (리셋 여유 확보)
 *
 *  ★ 9V 사각 배터리를 서보에 직결하면 안 된다 (과전압 + 전류부족).
 *    되도록 5~6V 2A 어댑터 + 1000µF 커패시터를 권장.
 * ═══════════════════════════════════════════════════════════════════ */

#define NB_KEY 0x2F          // nubida-bt.js 의 KEY 와 동일해야 함

#define SERVO_PIN_1   9      // 1NubidaAi → 9번
#define SERVO_PIN_2   7      // 2NubidaAi → 7번
#define STEP_DEG      2      // 한 스텝 각도 (작을수록 전류 분산)
#define STEP_MS       40     // 스텝 간격 (ms)

Servo servo1;                // 9번
Servo servo2;                // 7번

/* ── 비블로킹 서보 스캔 상태 ──────────────────────────────
 *  scanActive : 스캔 진행 중인가
 *  scanWhich  : 1 = 9번 서보, 2 = 7번 서보
 *  scanP      : 현재 각도
 *  scanDir    : +1 / -1
 *  scanPhase  : 0 = 1차, 1 = 2차 → 2가 되면 종료
 * ──────────────────────────────────────────────────────── */
bool          scanActive = false;
int           scanWhich  = 0;
int           scanP      = 10;
int           scanDir    = 1;
int           scanPhase  = 0;
int           scanStart  = 10;
int           scanEnd    = 160;
unsigned long scanLast   = 0;

String myString = "";

/* ── HEX 문자 → 값 ─────────────────────────────────────── */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* ── 난독화 프레임("x...") → 평문 복원 ─────────────────── */
String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  /* ★ [2026-09-13 파싱 실패 수정]
   *   AT-09 는 청크 경계에서 '\r' 이나 잔여 제어문자를 섞어 보내는 경우가 있다.
   *   기존 코드는 hex 문자열에 그런 문자가 하나라도 끼면 hexVal() 이 -1 을 돌려
   *   즉시 return "" 하여, 화면에 "[복호화] x... → (빈값)" 이 찍히고
   *   그 결과 [무시] 알 수 없는 명령이 되었다.
   *   → 'x' 이후 문자 중 "유효한 hex 문자만" 골라 새 문자열을 만든다.
   *     (제어문자·공백·CR/LF 를 원천 제거)
   */
  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;      // 0-9 a-f A-F 만 수집
  }
  if (hexs.length() < 4) return "";

  /* 홀수 길이 = 마지막 1글자 유실(청크 경계) → 마지막 글자를 버리고 진행한다.
   * 프레임은 [seed 2글자] + [바이트당 2글자] 구조이므로,
   * 1글자가 모자라면 그 바이트(원문 마지막 글자)만 잃고 나머지는 정상 복원된다.
   * 예: "xbba6dae1f6fdf0f5d5f"(19자) → 18자로 줄여 "2NubidaA" 복원
   *     → 아래 명령 판정에서 접두어 부분일치로 정상 인식된다.
   */
  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";
  String out = "";
  for (unsigned int i = 2; i + 1 < hexs.length(); i += 2) {
    int h1 = hexVal(hexs.charAt(i));
    int h2 = hexVal(hexs.charAt(i + 1));
    if (h1 < 0 || h2 < 0) continue;      // 방어: 남은 이상 문자는 건너뛴다
    char c = (char)((h1 * 16 + h2) ^ seed);
    if (c != '\0' && c >= 32 && c < 127) out += c;   // 출력 가능한 ASCII 만
  }
  out.trim();
  return out;
}

Servo *activeServo() {
  return (scanWhich == 1) ? &servo1 : &servo2;
}

/* ── 스캔 시작 (비블로킹) ─────────────────────────────────
 *  which : 1 → 9번(1NubidaAi, 160→10→160), 2 → 7번(2NubidaAi, 10→160→10)
 * ─────────────────────────────────────────────────────── */
void startScan(int which) {
  scanWhich = which;
  scanActive = true;
  scanLast = millis();
  scanPhase = 0;

  if (which == 1) {                 // 9번 : 160 → 10 → 160
    servo1.attach(SERVO_PIN_1);
    scanP = 160; scanStart = 160; scanEnd = 10; scanDir = -1;
    servo1.write(scanP);
  } else {                          // 7번 : 10 → 160 → 10
    servo2.attach(SERVO_PIN_2);
    scanP = 10; scanStart = 10; scanEnd = 160; scanDir = 1;
    servo2.write(scanP);
  }

  Serial.print("[스캔] 시작 — ");
  Serial.print(which == 1 ? "1NubidaAi (9번, 160→10→160)" : "2NubidaAi (7번, 10→160→10)");
  Serial.print(" / 스텝 ");
  Serial.print(STEP_DEG);
  Serial.print("도, ");
  Serial.print(STEP_MS);
  Serial.println("ms");
}

/* ── 스캔 1스텝 진행 (loop 에서 매번 호출) ─────────────── */
void stepScan() {
  if (!scanActive) return;
  if (millis() - scanLast < (unsigned long)STEP_MS) return;
  scanLast = millis();

  scanP += scanDir * STEP_DEG;

  if ((scanDir > 0 && scanP >= scanEnd) || (scanDir < 0 && scanP <= scanEnd)) {
    scanP = scanEnd;
    scanDir = -scanDir;
    int tmp = scanStart; scanStart = scanEnd; scanEnd = tmp;   // 목표 교체
    scanPhase++;

    if (scanPhase >= 2) {                 // 왕복 2회 완료 → 종료
      activeServo()->write(scanP);
      delay(120);                          // 마지막 위치 도달 대기
      // ★ 서보 힘 빼기 — 대기 전류 0 → 리셋 여유 확보
      if (scanWhich == 1) servo1.detach(); else servo2.detach();
      scanActive = false;
      Serial.print("[스캔] 완료 (");
      Serial.print(scanWhich == 1 ? "9번" : "7번");
      Serial.print(", 끝 각도 ");
      Serial.print(scanP);
      Serial.println("도) — 서보 전원 해제");
      return;
    }
  }
  activeServo()->write(scanP);
}

void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);
  delay(300);
  Serial.println("=== 누비다머신 수신 (2서보 안정판 v3) ===");
  Serial.println("준비 완료 — 1NubidaAi(9번) / 2NubidaAi(7번) 대기");
}

void loop() {

  /* ── ① 블루투스 수신 (블로킹 최소) ─────────────────── */
  while (BTSerial.available()) {
    myString += (char)BTSerial.read();
  }

  if (!myString.equals("")) {
    // ★ 조각 붙이기 대기 — AT-09 가 20바이트 청크 2개로 보내므로 두 번째 조각이
    //   도착할 시간이 필요하다. 기존 25ms 는 짧아 마지막 조각을 놓치는 경우가 있었고,
    //   그 결과 프레임 끝 1~2글자가 잘려 [무시] 알 수 없는 명령이 되었다.
    //   → 대기 시간을 60ms 로 늘리고, 마지막 수신 후에도 짧게 더 기다린다.
    /* ★ [2026-09-14 v4] 조각 붙이기 대기 강화.
     *   난독화 프레임('x'+20hex = 21자) + '\n' = 22바이트가 BLE 20바이트 청크
     *   2개로 나뉘어 도착한다. 두 번째 조각(2바이트)이 늦게 오는 경우가 있어
     *   기존 60ms 로는 마지막 글자를 놓쳤다(→ 홀수 hex → 복호화 실패).
     *   프레임 시작이 'x' 이고 개행이 아직 없으면 최대 200ms 까지 더 기다린다.
     */
    unsigned long lastRx = millis();
    while (millis() - lastRx < 80) {         // 1차 대기 (청크 2개 대응)
      if (BTSerial.available()) {
        myString += (char)BTSerial.read();
        lastRx = millis();
      }
    }
    // 'x' 로 시작하고 아직 개행이 없으면 = 프레임 미완성 → 마무리 조각 대기
    if (myString.charAt(0) == 'x' && myString.indexOf('\n') < 0) {
      unsigned long t2 = millis();
      while (millis() - t2 < 120) {
        if (BTSerial.available()) {
          myString += (char)BTSerial.read();
          t2 = millis();                     // 문자 올 때마다 타이머 리셋
        }
      }
    }

    myString.trim();
    if (!myString.equals("")) {
      String cmd = myString;

      if (cmd.charAt(0) == 'x') {
        String d = decodeFrame(cmd);
        Serial.print("[복호화] ");
        Serial.print(cmd);
        Serial.print("  →  ");
        Serial.println(d);
        cmd = (d.length() > 0) ? d : "";
      }

      /* ★ [2026-09-14 v4] BLE 모듈 AT 이벤트 무시.
       *   AT-09/HM-10 은 연결/해제 시 "+CONNECTING<<맥주소", "+CONNECTED",
       *   "+DISCONNECTED" 같은 이벤트 문자열을 UART 로 흘린다.
       *   기존 코드는 이를 명령으로 파싱해 "[무시] 알 수 없는 명령" 을 찍었고,
       *   그 사이 실제 프레임 처리가 밀리는 원인이 됐다.
       *   '+' 로 시작하는 줄은 이벤트로 보고 로그만 남기고 버린다.
       */
      /* ★ [2026-09-14 v5] return 금지 — 플래그로 건너뛴다.
       *   loop() 중간에서 return 하면 아래의 잔여버퍼 정리 / stepScan() /
       *   PC 시리얼 프록시가 전부 건너뛰어져 **서보 스캔이 영구 정지**한다.
       *   '+CONNECTING' 같은 이벤트는 이벤트로만 로그하고 명령 처리만 생략한다.
       */
      bool isBleEvent = (cmd.length() > 0 && cmd.charAt(0) == '+');
      if (isBleEvent) {
        Serial.print("[BLE이벤트] "); Serial.println(cmd);   // 참고용 로그
      }

      if (!isBleEvent && cmd != "") {
        Serial.print("[명령] '");
        Serial.print(cmd);
        Serial.print("'  len=");
        Serial.println(cmd.length());

        /* ── 명령 판정 (부분 유실 내성) ────────────────────────────────
         * ★ 문제: 프레임이 23글자(24바이트)라 BLE 20바이트 청크 2개로 나뉘어
         *   전송되고, AT-09 가 두 번째 청크를 받을 때 마지막 1바이트를 흘리는
         *   경우가 있다. 그러면 "1NubidaAi" → "1NubidaA" 로 도착해
         *   indexOf("1NubidaAi") 가 -1 이 되어 [무시] 알 수 없는 명령이 된다.
         *
         * ★ 해결: 접두어 앞부분("1Nubida" / "2Nubida")만 일치해도 인식한다.
         *   클래스 번호(1/2)와 접두어 앞 6글자만 확보되면 명령으로 판정하므로
         *   뒤쪽 몇 글자가 유실돼도 정상 동작한다.
         */
        bool is1 = (cmd.indexOf("1Nubida") >= 0) || cmd.equals("1NubidaAi");
        bool is2 = (cmd.indexOf("2Nubida") >= 0) || cmd.equals("2NubidaAi");

        // 접두어를 아예 못 받은 경우(심한 유실) — 앞 숫자만으로도 보정
        if (!is1 && !is2 && cmd.length() >= 1) {
          if (cmd.charAt(0) == '1') { is1 = true; Serial.println("[보정] 앞자리 1만 수신 → 1로 판정"); }
          else if (cmd.charAt(0) == '2') { is2 = true; Serial.println("[보정] 앞자리 2만 수신 → 2로 판정"); }
        }

        if (is1 || is2) {
          if (scanActive) {
            Serial.println("[대기] 스캔 진행 중 — 새 명령 무시");
          } else {
            startScan(is1 ? 1 : 2);
          }
        } else {
          Serial.println("[무시] 알 수 없는 명령");
        }
      }
    }
    myString = "";
  }

  /* ── ② 서보 스캔 1스텝 진행 ────────────────────────── */
  stepScan();

  /* ── ③ PC 시리얼 모니터 입력 → 블루투스 전송 (테스트용) ── */
  while (Serial.available()) {
    BTSerial.write(Serial.read());
  }
}
