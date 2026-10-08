#include "Servo.h"

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════
 *  누비다머신 수신 펌웨어 — 2서보 안정판 (v7 · 진단강화판)
 * ───────────────────────────────────────────────────────────────────
 *  [v7 의 목적]  "카메라 값이 안 간다" 의 원인을 **완전히 확정**한다.
 *
 *    v6 까지의 로그는 "뭔가 도착했을 때만" 출력했다.
 *    그래서 데이터가 아예 안 오면 로그가 하나도 안 떠서
 *    "안 오는 건지 / 왔는데 버리는 건지" 구분이 불가능했다.
 *
 *    v7 은 다음을 **무조건** 출력한다.
 *      ① [연결] 상태 변화
 *      ② [RX] 수신 바이트 수 — 매 루프, 값이 늘면 그때마다 출력
 *      ③ [RAW] 실제로 받은 원시 문자열 (제어문자는 \xNN 형태로)
 *      ④ [프레임] 30ms 무수신 = 한 프레임 완료로 보고 확정
 *
 *    ★ 진단 후에는 ②③ 로그를 지우고 v6 로 돌아가도 된다.
 * ═══════════════════════════════════════════════════════════════════ */

#define NB_KEY 0x2F          // nubida-bt.js 의 KEY 와 동일해야 함

#define SERVO_PIN_1   9      // 1NubidaAi → 9번
#define SERVO_PIN_2   7      // 2NubidaAi → 7번
#define STEP_DEG      2      // 한 스텝 각도
#define STEP_MS       40     // 스텝 간격 (ms)

Servo servo1;                // 9번
Servo servo2;                // 7번

bool          scanActive = false;
int           scanWhich  = 0;
int           scanP      = 10;
int           scanDir    = 1;
int           scanPhase  = 0;
int           scanStart  = 10;
int           scanEnd    = 160;
unsigned long scanLast   = 0;

String myString = "";

/* ── [v7] 진단용 ─────────────────────────────────────── */
unsigned long rxTotal     = 0;      // 누적 수신 바이트
unsigned long rxShown     = 0;      // 마지막으로 로그에 찍은 수신 바이트
unsigned long lastRxAt    = 0;      // 마지막 수신 시각
bool          frameDone   = false;  // 프레임 확정 플래그

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

  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

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
    if (h1 < 0 || h2 < 0) continue;
    char c = (char)((h1 * 16 + h2) ^ seed);
    if (c != '\0' && c >= 32 && c < 127) out += c;
  }
  out.trim();
  return out;
}

Servo *activeServo() {
  return (scanWhich == 1) ? &servo1 : &servo2;
}

void startScan(int which) {
  scanWhich = which;
  scanActive = true;
  scanLast = millis();
  scanPhase = 0;

  if (which == 1) {
    servo1.attach(SERVO_PIN_1);
    scanP = 160; scanStart = 160; scanEnd = 10; scanDir = -1;
    servo1.write(scanP);
  } else {
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

void stepScan() {
  if (!scanActive) return;
  if (millis() - scanLast < (unsigned long)STEP_MS) return;
  scanLast = millis();

  scanP += scanDir * STEP_DEG;

  if ((scanDir > 0 && scanP >= scanEnd) || (scanDir < 0 && scanP <= scanEnd)) {
    scanP = scanEnd;
    scanDir = -scanDir;
    int tmp = scanStart; scanStart = scanEnd; scanEnd = tmp;
    scanPhase++;

    if (scanPhase >= 2) {
      activeServo()->write(scanP);
      delay(120);
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

/* ── [v7] 원시 문자열을 안전하게 출력 (\r \n 등은 \xNN) ── */
void printRaw(String s) {
  Serial.print("[RAW] len=");
  Serial.print(s.length());
  Serial.print(" : ");
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c >= 32 && c < 127) {
      Serial.print(c);
    } else {
      Serial.print("\\x");
      if ((unsigned char)c < 16) Serial.print("0");
      Serial.print((unsigned char)c, HEX);
    }
  }
  Serial.println();
}

void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);
  delay(300);

  Serial.println(F("=== 누비다머신 수신 (2서보 안정판 v7 · 진단강화) ==="));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__)); Serial.print(F(" ")); Serial.println(F(__TIME__));
  Serial.println(F("[기능] 수신바이트 카운터 + RAW 덤프 + 30ms 프레임확정"));
  Serial.println(F("준비 완료 — 1NubidaAi(9번) / 2NubidaAi(7번) 대기"));
  Serial.println(F("[안내] 이 화면에 [RX] 로그가 뜨면 데이터가 오는 것입니다."));
}

void loop() {

  /* ── ① 블루투스 수신 ─────────────────────────────────
   *   [v7] 대기(블로킹) 방식을 버리고, **들어오는 즉시** 버퍼에 쌓는다.
   *        프레임 확정은 "30ms 동안 새 데이터가 없으면" 으로 판단한다.
   *        → 22바이트가 20+2 로 쪼개져 와도 정상적으로 한 덩어리가 된다.
   * ──────────────────────────────────────────────────── */
  while (BTSerial.available()) {
    myString += (char)BTSerial.read();
    rxTotal++;
    lastRxAt = millis();
  }

  /* ── [v7] 수신량 변화 로그 (데이터가 오는지 눈으로 확인) ── */
  if (rxTotal != rxShown) {
    Serial.print("[RX] 총 ");
    Serial.print(rxTotal);
    Serial.println(" 바이트 수신");
    rxShown = rxTotal;
  }

  /* ── [v7] 30ms 무수신 = 프레임 완료로 확정 ───────────── */
  if (myString.length() > 0 && lastRxAt > 0 && (millis() - lastRxAt) > 30) {
    frameDone = true;
  }

  if (frameDone) {
    frameDone = false;

    printRaw(myString);                 // ★ 원시 수신 내용 그대로 출력

    myString.trim();                    // \r \n 제거
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

      bool isBleEvent = (cmd.length() > 0 && cmd.charAt(0) == '+');
      if (isBleEvent) {
        Serial.print("[BLE이벤트] "); Serial.println(cmd);
      }

      if (!isBleEvent && cmd != "") {
        Serial.print("[명령] '");
        Serial.print(cmd);
        Serial.print("'  len=");
        Serial.println(cmd.length());

        bool is1 = (cmd.indexOf("1Nubida") >= 0) || cmd.equals("1NubidaAi");
        bool is2 = (cmd.indexOf("2Nubida") >= 0) || cmd.equals("2NubidaAi");

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
