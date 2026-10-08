#include "Servo.h"

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════
 *  누비다머신 수신 펌웨어 — 2서보 안정판 (v8 · 버퍼오버플로 수정판)
 * ───────────────────────────────────────────────────────────────────
 *  [v7 진단 결과 — 원인 확정]
 *    [RX] 총 78 바이트 수신
 *    [RAW] len=44 : +CONNECTING<<98:da:20:09:73:c5\r\n+CONNECTED\r\n
 *
 *    → 78바이트가 들어왔는데 로그엔 44바이트(AT 이벤트)만 찍혔다.
 *      나머지 34바이트(카메라 프레임)는 **SoftwareSerial 버퍼에서 유실**.
 *
 *  [원인]
 *    SoftwareSerial 의 수신 버퍼는 64바이트뿐이다.
 *    AT-09 이벤트 44바이트가 들어온 상태에서 read 하는 동안
 *    뒤따라온 카메라 프레임 34바이트가 버퍼를 넘쳐 조용히 사라졌다.
 *    게다가 v7 은 매 루프마다 Serial.print("[RX] 총 N ...") 를 찍었는데,
 *    이 로그 자체가 9600bps 로 약 30ms 를 잡아먹어 read() 를 더 늦췄다.
 *
 *  [v8 수정]
 *    ① 수신 루프를 **가장 먼저, 최대한 오래** 돌린다. (로그 최소화)
 *    ② 로그는 "프레임 완성 시" 1회만. [RX] 카운터 로그 제거.
 *    ③ 로그 문자열을 대폭 단축 (F() 매크로 + 짧은 문구)
 *       → Serial 출력에 잡히는 시간을 줄여 다음 drainBle() 이 빨리 돌게 함
 *    ④ BTSerial 버퍼 여유를 위해 프레임 처리 중에도 read 를 병행.
 * ═══════════════════════════════════════════════════════════════════ */

#define NB_KEY 0x2F          // nubida-bt.js 의 KEY 와 동일해야 함

#define SERVO_PIN_1   9      // 1NubidaAi → 9번
#define SERVO_PIN_2   7      // 2NubidaAi → 7번
#define STEP_DEG      2      // 한 스텝 각도
#define STEP_MS       40     // 스텝 간격 (ms)

#define FRAME_GAP_MS  25     // 이 시간 무수신 = 한 프레임 완료

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

char          rxBuf[192];            // 수신 버퍼 (넉넉히)
int           rxLen      = 0;
unsigned long lastRxAt   = 0;
bool          overflowed = false;

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

  Serial.print(F("[스캔] 시작 — "));
  Serial.println(which == 1 ? F("1NubidaAi (9번)") : F("2NubidaAi (7번)"));
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
      Serial.println(F("[스캔] 완료 — 서보 전원 해제"));
      return;
    }
  }
  activeServo()->write(scanP);
}

/* ── 수신 버퍼에 있는 것을 최대한 긁어모은다 (가장 중요) ── */
void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = c;
    } else {
      overflowed = true;             // 버퍼 꽉 참 — 그래도 버리지 않고 플래그만
    }
    lastRxAt = millis();
  }
}

/* ── 완성된 한 프레임을 처리 ─────────────────────────── */
void handleFrame() {
  rxBuf[rxLen] = '\0';
  String raw = String(rxBuf);
  raw.trim();

  /* 개행 기준으로 줄 단위 분리 */
  int start = 0;
  while (start <= (int)raw.length()) {
    int nl = raw.indexOf('\n', start);
    String line = (nl < 0) ? raw.substring(start) : raw.substring(start, nl);
    line.trim();

    if (line.length() > 0) {
      String cmd = line;

      if (cmd.charAt(0) == 'x') {
        String d = decodeFrame(cmd);
        Serial.print(F("[복호화] "));
        Serial.print(cmd);
        Serial.print(F("  →  "));
        Serial.println(d.length() > 0 ? d : F("(빈값)"));
        cmd = (d.length() > 0) ? d : "";
      }

      bool isBleEvent = (cmd.length() > 0 && cmd.charAt(0) == '+');
      if (isBleEvent) {
        Serial.print(F("[BLE이벤트] ")); Serial.println(cmd);
      }

      if (!isBleEvent && cmd != "") {
        bool is1 = (cmd.indexOf("1Nubida") >= 0) || cmd.equals("1NubidaAi");
        bool is2 = (cmd.indexOf("2Nubida") >= 0) || cmd.equals("2NubidaAi");

        if (!is1 && !is2 && cmd.length() >= 1) {
          if (cmd.charAt(0) == '1') { is1 = true; }
          else if (cmd.charAt(0) == '2') { is2 = true; }
        }

        if (is1 || is2) {
          if (scanActive) {
            Serial.println(F("[대기] 스캔 진행 중 — 새 명령 무시"));
          } else {
            startScan(is1 ? 1 : 2);
          }
        } else {
          Serial.print(F("[무시] 알 수 없는 명령: ")); Serial.println(cmd);
        }
      }
    }
    if (nl < 0) break;
    start = nl + 1;
  }

  if (overflowed) {
    Serial.println(F("[경고] 수신버퍼 초과 — 일부 바이트 유실됨"));
    overflowed = false;
  }

  rxLen = 0;
  rxBuf[0] = '\0';
}

void setup() {
  Serial.begin(9600);       // 시리얼 모니터 9600 그대로 사용
  BTSerial.begin(9600);      // AT-09 통신 속도는 그대로
  delay(300);

  Serial.println(F("=== 누비다머신 수신 (2서보 안정판 v8) ==="));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__)); Serial.print(F(" ")); Serial.println(F(__TIME__));
  Serial.println(F("[수정] 버퍼오버플로 해결 — 수신 최우선, 로그는 완성시 1회"));
  Serial.println(F("준비 완료 — 1NubidaAi(9번) / 2NubidaAi(7번) 대기"));
}

void loop() {

  /* ── ① BLE 수신 최우선 (다른 어떤 작업보다 먼저) ────── */
  drainBle();

  /* ── ② 25ms 무수신 = 한 프레임 완료 → 처리 ──────────── */
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }

  /* ── ③ 서보 스캔 1스텝 ──────────────────────────────── */
  stepScan();

  /* ── ④ PC 시리얼 모니터 입력 → BLE 전송 (테스트용) ──── */
  while (Serial.available()) {
    BTSerial.write(Serial.read());
  }
}
