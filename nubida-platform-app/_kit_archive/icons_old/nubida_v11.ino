#include "Servo.h"

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다머신 통합 펌웨어 (v11 · AI분기 if/else if 형)
 * ───────────────────────────────────────────────────────────────────────────
 *  [설계 목표]
 *    ① AI 값 처리를 **if / else if 문**으로 — 한눈에 읽히게
 *    ② 기존 문법도 if / else if 체인으로 — 원본과 같은 형식
 *    ③ 두 가지가 한 코드에서 동시에 동작
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ AI 값 추가하는 법 — aiDispatch() 의 else if 를 한 줄 복사
 *  ─────────────────────────────────────────────────────────────────────────
 *
 *    else if (cmd.equals("3NubidaAi") || cmd.startsWith("3Nubida")) {
 *      aiServo3.attach(5);            // ← 새 서보 핀 (원하는 핀)
 *      aiServo3.write(10);            // ← 시작 각도
 *      aiScanWhich = 3;               // ← 스캔 번호 (아래 표 참고)
 *      aiScan = true; aiLast = millis(); aiPhase = 0;
 *      aiP = 10; aiDir = 1; aiStart = 10; aiEnd = 160;
 *      Serial.println(F("[AI] 3NubidaAi — 5번 스캔 시작"));
 *      return;
 *    }
 *
 *    → 이 블록 하나만 추가하면 끝. 다른 곳은 손댈 필요 없음.
 *
 *  ★ 스캔 번호별 방향 (홀수는 160→10, 짝수는 10→160 — 기존 관례)
 *      aiScanWhich = 1 → 160 → 10   (원래 1NubidaAi 동작)
 *      aiScanWhich = 2 →  10 → 160  (원래 2NubidaAi 동작)
 *      aiScanWhich = 3 → 160 → 10
 *      aiScanWhich = 4 →  10 → 160
 *    → 홀수/짝수만 맞추면 됨. 시작/끝 각도는 블록에서 직접 지정.
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ 기존 문법 추가하는 법 — handleLegacyCommand() 의 else if 를 복사
 *  ─────────────────────────────────────────────────────────────────────────
 *    ① cmd 에서 값을 뽑고 (indexOf + substring)
 *    ② if 체인에 블록 추가 + return true;
 *    → 원본 nubida_machine_receiver.ino 와 완전히 같은 형식.
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 하위 호환: 원본의 모든 문장 그대로 지원
 *    Piano.mode / Trash.mode / digitalWrite / tone / noTone /
 *    if(cho < N) / if(pos < N) / if(pos > N) / pos.write(mN,N) /
 *    BT.print(tN,eN) / int a = b; / Serial.print(N); / stop
 * ═══════════════════════════════════════════════════════════════════════════ */

#define NB_KEY       0x2F    // nubida-bt.js 의 KEY 와 동일해야 함
#define STEP_DEG     2       // AI 스캔 한 스텝 각도
#define STEP_MS      40      // AI 스캔 스텝 간격(ms)
#define FRAME_GAP_MS 30      // 이 시간 무수신 = 한 프레임 완료
#define MAX_RX       256     // 수신 버퍼 크기

/* ═══════════════════════════════════════════════════════════════════════════
 *  [1] 서보 객체 — AI 값이 쓰는 서보들
 *      ★ AI 값을 늘릴 때 여기에 Servo 를 하나 추가한다
 * ═══════════════════════════════════════════════════════════════════════════ */
Servo aiServo1;    // 1NubidaAi → 9번
Servo aiServo2;    // 2NubidaAi → 7번
Servo aiServo3;    // 3NubidaAi → 5번   (▼ 사용 안 하면 이 줄 지워도 됨)
Servo aiServo4;    // 4NubidaAi → 6번   (▼ 사용 안 하면 이 줄 지워도 됨)

// 기존 문장 전용 서보 (Piano.mode / Trash.mode / pos.write 등)
Servo myServo;

/* ═══════════════════════════════════════════════════════════════════════════
 *  [2] 기존 문법 변수 (원본 유지)
 * ═══════════════════════════════════════════════════════════════════════════ */
int piezo, buzzer, buzzer1, SeRe, pwm, cho, pos1, pos2, pos;
int Servopin, Servopos, serial;
int trig5, echo5, trig, echo, digitalHIGH, digitalLOW;

/* ── 수신 버퍼 (SoftwareSerial 64B 함정 대응) ─────────────────── */
char          rxBuf[MAX_RX];
int           rxLen      = 0;
unsigned long lastRxAt   = 0;
bool          rxOverflow = false;

/* ── AI 스캔 상태 ──────────────────────────────────────────── */
bool          aiScan  = false;
int           aiWhich = 0;      // 1=aiServo1, 2=aiServo2, 3=aiServo3, 4=aiServo4
int           aiP     = 10;
int           aiDir   = 1;
int           aiPhase = 0;
int           aiStart = 10;
int           aiEnd   = 160;
unsigned long aiLast  = 0;

/* ═══════════════════════════════════════════════════════════════════════════
 *  [3] 유틸
 * ═══════════════════════════════════════════════════════════════════════════ */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* 난독화 프레임("x...") → 평문 복원 */
String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  // 홀수 = 청크 경계 1글자 유실 → 마지막 1글자만 잘라 진행
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

/* ═══════════════════════════════════════════════════════════════════════════
 *  [4] AI 스캔 실행 — aiWhich 에 따라 서보 선택
 * ═══════════════════════════════════════════════════════════════════════════ */
void stepAiScan() {
  if (!aiScan) return;
  if (millis() - aiLast < (unsigned long)STEP_MS) return;
  aiLast = millis();

  aiP += aiDir * STEP_DEG;

  if ((aiDir > 0 && aiP >= aiEnd) || (aiDir < 0 && aiP <= aiEnd)) {
    aiP = aiEnd;
    aiDir = -aiDir;
    int tmp = aiStart; aiStart = aiEnd; aiEnd = tmp;
    aiPhase++;

    if (aiPhase >= 2) {                        // 왕복 2회 → 종료
      if      (aiWhich == 1) { aiServo1.write(aiP); delay(120); aiServo1.detach(); }
      else if (aiWhich == 2) { aiServo2.write(aiP); delay(120); aiServo2.detach(); }
      else if (aiWhich == 3) { aiServo3.write(aiP); delay(120); aiServo3.detach(); }
      else if (aiWhich == 4) { aiServo4.write(aiP); delay(120); aiServo4.detach(); }
      aiScan = false;
      Serial.println(F("[AI] 스캔 완료 — 서보 전원 해제"));
      return;
    }
  }

  if      (aiWhich == 1) aiServo1.write(aiP);
  else if (aiWhich == 2) aiServo2.write(aiP);
  else if (aiWhich == 3) aiServo3.write(aiP);
  else if (aiWhich == 4) aiServo4.write(aiP);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [5] ★★ AI 값 분기 — 여기에 else if 를 복사해서 AI 값을 늘린다
 *      반환값 true = AI 값으로 처리됨
 * ═══════════════════════════════════════════════════════════════════════════ */
bool aiDispatch(String cmd) {

  // ── 1NubidaAi → 9번 서보 (160 → 10) ─────────────────────────
  if (cmd.equals("1NubidaAi") || cmd.startsWith("1Nubida") || cmd.equals("1")) {
    aiServo1.attach(9);
    aiWhich = 1;
    aiScan = true; aiLast = millis(); aiPhase = 0;
    aiP = 160; aiDir = -1; aiStart = 160; aiEnd = 10;
    aiServo1.write(aiP);
    Serial.println(F("[AI] 1NubidaAi — 9번 스캔 시작"));
    return true;
  }
  // ── 2NubidaAi → 7번 서보 (10 → 160) ─────────────────────────
  else if (cmd.equals("2NubidaAi") || cmd.startsWith("2Nubida") || cmd.equals("2")) {
    aiServo2.attach(7);
    aiWhich = 2;
    aiScan = true; aiLast = millis(); aiPhase = 0;
    aiP = 10; aiDir = 1; aiStart = 10; aiEnd = 160;
    aiServo2.write(aiP);
    Serial.println(F("[AI] 2NubidaAi — 7번 스캔 시작"));
    return true;
  }
  /* ─────────────────────────────────────────────────────────────
   *  ▼▼▼ AI 값을 늘리려면 아래 블록을 복사해서 주석을 풀면 된다 ▼▼▼
   *
   *  // ── 3NubidaAi → 5번 서보 (160 → 10) ─────────────────────
   *  else if (cmd.equals("3NubidaAi") || cmd.startsWith("3Nubida") || cmd.equals("3")) {
   *    aiServo3.attach(5);                    // ← 새 서보 핀
   *    aiWhich = 3;                           // ← 스캔 번호 (3)
   *    aiScan = true; aiLast = millis(); aiPhase = 0;
   *    aiP = 160; aiDir = -1; aiStart = 160; aiEnd = 10;
   *    aiServo3.write(aiP);
   *    Serial.println(F("[AI] 3NubidaAi — 5번 스캔 시작"));
   *    return true;
   *  }
   *
   *  // ── 4NubidaAi → 6번 서보 (10 → 160) ──────────────────────
   *  else if (cmd.equals("4NubidaAi") || cmd.startsWith("4Nubida") || cmd.equals("4")) {
   *    aiServo4.attach(6);                    // ← 새 서보 핀
   *    aiWhich = 4;                           // ← 스캔 번호 (4)
   *    aiScan = true; aiLast = millis(); aiPhase = 0;
   *    aiP = 10; aiDir = 1; aiStart = 10; aiEnd = 160;
   *    aiServo4.write(aiP);
   *    Serial.println(F("[AI] 4NubidaAi — 6번 스캔 시작"));
   *    return true;
   *  }
   * ───────────────────────────────────────────────────────────── */

  return false;   // AI 값 아님
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [6] 기존 문법 파서 — 원본 nubida_machine_receiver.ino 그대로
 *      ★ 새 문장은 아래 else if 체인에 블록을 추가한다
 * ═══════════════════════════════════════════════════════════════════════════ */
bool handleLegacyCommand(String cmd) {

  /*디지털동작 HIGH부분 */
  int HIGHa = cmd.indexOf("digitalWrite(");
  int HIGHb = cmd.indexOf(",H);");
  String HIGHResult = (HIGHa >= 0 && HIGHb > HIGHa) ? cmd.substring(HIGHa + 11, HIGHb) : "";
  digitalHIGH = HIGHResult.toInt();

  /*디지털동작 LOW부분 */
  int LOWa = cmd.indexOf("digitalWrite(");
  int LOWb = cmd.indexOf(",L);");
  String LOWResult = (LOWa >= 0 && LOWb > LOWa) ? cmd.substring(LOWa + 11, LOWb) : "";
  digitalLOW = LOWResult.toInt();

  int ifa = cmd.indexOf("if(cho < ");
  int ifb = cmd.indexOf(")");
  String ifResult1 = (ifa >= 0 && ifb > ifa) ? cmd.substring(ifa + 9, ifb) : "";
  cho = ifResult1.toInt();

  int ifposa = cmd.indexOf("if(pos < ");
  int ifposb = cmd.indexOf(")");
  String ifposResult1 = (ifposa >= 0 && ifposb > ifposa) ? cmd.substring(ifposa + 9, ifposb) : "";
  pos1 = ifposResult1.toInt();

  int ifpos2a = cmd.indexOf("if(pos > ");
  int ifpos2b = cmd.indexOf(")");
  String ifposResult2 = (ifpos2a >= 0 && ifpos2b > ifpos2a) ? cmd.substring(ifpos2a + 9, ifpos2b) : "";
  pos2 = ifposResult2.toInt();

  int tonea = cmd.indexOf("tone(");
  int toneb = cmd.indexOf(",");
  int tonec = cmd.indexOf(");");
  String toneResult1 = (tonea >= 0 && toneb > tonea) ? cmd.substring(tonea + 5, toneb) : "";
  String toneResult2 = (toneb >= 0 && tonec > toneb) ? cmd.substring(toneb + 1, tonec) : "";
  buzzer = toneResult1.toInt();
  pwm    = toneResult2.toInt();

  int notonea = cmd.indexOf("noTone(");
  int notoneb = cmd.indexOf(");");
  String notoneResult1 = (notonea >= 0 && notoneb > notonea) ? cmd.substring(notonea + 7, notoneb) : "";
  buzzer1 = notoneResult1.toInt();

  int inta = cmd.indexOf("int ");
  int intb = cmd.indexOf(" = ");
  int intc = cmd.indexOf(";");
  String intResult1 = (inta >= 0 && intb > inta) ? cmd.substring(inta + 4, intb) : "";
  String intResult2 = (intb >= 0 && intc > intb) ? cmd.substring(intb + 3, intc) : "";

  int Seriala = cmd.indexOf("Serial.print(");
  int Serialb = cmd.indexOf(");");
  String SerialResult = (Seriala >= 0 && Serialb > Seriala) ? cmd.substring(Seriala + 13, Serialb) : "";
  SeRe = SerialResult.toInt();

  int cho_modea = cmd.indexOf("BT.print(t");
  int cho_modeb = cmd.indexOf(",e");
  int cho_modec = cmd.indexOf(");");
  String cho_modeaResult1 = (cho_modea >= 0 && cho_modeb > cho_modea) ? cmd.substring(cho_modea + 10, cho_modeb) : "";
  String cho_modeaResult2 = (cho_modeb >= 0 && cho_modec > cho_modeb) ? cmd.substring(cho_modeb + 2, cho_modec) : "";
  trig5 = cho_modeaResult1.toInt();
  echo5 = cho_modeaResult2.toInt();

  int Servoa = cmd.indexOf("pos.write(m");
  int Servob = cmd.indexOf(",");
  int Servoc = cmd.indexOf(");");
  String ServoResult1 = (Servoa >= 0 && Servob > Servoa) ? cmd.substring(Servoa + 11, Servob) : "";
  String ServoResult2 = (Servob >= 0 && Servoc > Servob) ? cmd.substring(Servob + 1, Servoc) : "";
  Servopin = ServoResult1.toInt();
  Servopos = ServoResult2.toInt();

  int Piano_modea = cmd.indexOf("Piano.mode(t");
  int Piano_modeb = cmd.indexOf(",e");
  int Piano_modec = cmd.indexOf(",m");
  int Piano_moded = cmd.indexOf(");");
  String Piano_modeaResult1 = (Piano_modea >= 0 && Piano_modeb > Piano_modea) ? cmd.substring(Piano_modea + 12, Piano_modeb) : "";
  String Piano_modeaResult2 = (Piano_modeb >= 0 && Piano_modec > Piano_modeb) ? cmd.substring(Piano_modeb + 2, Piano_modec) : "";
  String Piano_modeaResult3 = (Piano_modec >= 0 && Piano_moded > Piano_modec) ? cmd.substring(Piano_modec + 2, Piano_moded) : "";
  trig  = Piano_modeaResult1.toInt();
  echo  = Piano_modeaResult2.toInt();
  piezo = Piano_modeaResult3.toInt();

  /* ── 판정 (원본 순서 그대로) ─────────────────────────────── */
  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
    pinMode(digitalHIGH, OUTPUT);
    digitalWrite(digitalHIGH, HIGH);
    delay(100);
    return true;
  }
  else if (cmd.equals("digitalWrite(" + LOWResult + ",L);")) {
    pinMode(digitalLOW, OUTPUT);
    digitalWrite(digitalLOW, LOW);
    delay(100);
    return true;
  }
  else if (cmd.equals("int " + intResult1 + " = " + intResult2 + ";")) {
    BTSerial.println(intResult1 + "의 변수명은 " + intResult2 + "번의 핀을 사용합니다.");
    delay(100);
    return true;
  }
  else if (cmd.equals("Serial.print(" + SerialResult + ");")) {
    int Result;
    pinMode(SeRe, INPUT);
    Result = digitalRead(SeRe);
    BTSerial.println(Result);
    delay(100);
    return true;
  }
  else if (cmd.equals("if(cho < " + ifResult1 + ")")) {
    pinMode(7, OUTPUT);
    myServo.attach(9);
    pinMode(10, OUTPUT);
    pinMode(11, INPUT);

    digitalWrite(10, LOW);  digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);

    unsigned long duration1 = pulseIn(11, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);

    if (distance < 11) { tone(7, 262); myServo.write(170); delay(1000); }
    else               { noTone(7);    myServo.write(90);  delay(1000); }
    myServo.detach();
    return true;
  }
  else if (cmd.equals("if(pos < " + ifposResult1 + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    myServo.attach(9);
    myServo.write(45);
    digitalWrite(4, HIGH); digitalWrite(5, LOW);
    digitalWrite(6, HIGH); digitalWrite(7, LOW);
    delay(100);
    return true;
  }
  else if (cmd.equals("stop")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    digitalWrite(4, LOW); digitalWrite(5, LOW);
    digitalWrite(6, LOW); digitalWrite(7, LOW);
    delay(100);
    return true;
  }
  else if (cmd.equals("if(pos > " + ifposResult2 + ")")) {
    pinMode(4, OUTPUT); pinMode(5, OUTPUT); pinMode(6, OUTPUT); pinMode(7, OUTPUT);
    myServo.attach(9);
    myServo.write(135);
    digitalWrite(4, LOW); digitalWrite(6, LOW); digitalWrite(7, HIGH);
    delay(100);
    return true;
  }
  else if (cmd.equals("BT.print(t" + cho_modeaResult1 + ",e" + cho_modeaResult2 + ");")) {
    pinMode(trig5, OUTPUT); pinMode(echo5, INPUT);
    digitalWrite(trig5, LOW); digitalWrite(echo5, LOW);
    delayMicroseconds(2);
    digitalWrite(trig5, HIGH); delayMicroseconds(10); digitalWrite(trig5, LOW);

    unsigned long duration1 = pulseIn(echo5, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);
    Serial.print(distance); Serial.println("cm");
    BTSerial.print(distance); BTSerial.println("cm");
    delay(1000);
    return true;
  }
  else if (cmd.equals("tone(" + toneResult1 + "," + toneResult2 + ");")) {
    pinMode(buzzer, OUTPUT); tone(buzzer, pwm);
    return true;
  }
  else if (cmd.equals("noTone(" + notoneResult1 + ");")) {
    pinMode(buzzer1, OUTPUT); noTone(buzzer1);
    return true;
  }
  else if (cmd.equals("Piano.mode")) {
    pinMode(7, OUTPUT); pinMode(10, OUTPUT); pinMode(11, INPUT);
    digitalWrite(10, LOW);  digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);

    unsigned long duration1 = pulseIn(11, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);

    if (distance < 4)         { tone(7, 262, 1000); delay(100); }
    else if (distance < 6.9)  { tone(7, 294, 1000); delay(100); }
    else if (distance < 9.8)  { tone(7, 330, 1000); delay(100); }
    else if (distance < 12.5) { tone(7, 349, 1000); delay(100); }
    else if (distance < 14.6) { tone(7, 392, 1000); delay(100); }
    else if (distance < 16)   { tone(7, 440, 1000); delay(100); }
    else if (distance < 18)   { tone(7, 494, 1000); delay(100); }
    else if (distance < 20.1) { tone(7, 523, 1000); delay(100); }
    else                      { noTone(7); delay(100); }
    return true;
  }
  else if (cmd.equals("pos.write(m" + ServoResult1 + "," + ServoResult2 + ");")) {
    myServo.attach(Servopin);
    myServo.write(Servopos);
    delay(100);
    return true;
  }
  else if (cmd.equals("Trash.mode")) {
    myServo.attach(9);
    pinMode(10, OUTPUT); pinMode(11, INPUT);
    digitalWrite(10, LOW);  digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH); delayMicroseconds(10); digitalWrite(10, LOW);

    unsigned long duration1 = pulseIn(11, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);

    if (distance < 15) { myServo.write(180); delay(3000); }
    else               { myServo.write(85);  delay(1000); }
    myServo.detach();
    return true;
  }

  /* ▼▼▼ 새 기존문장은 여기에 else if 블록을 추가 ▼▼▼ */

  return false;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [7] 한 줄 처리 — ① 복호화 → ② BLE 이벤트 → ③ AI값 → ④ 기존문법
 * ═══════════════════════════════════════════════════════════════════════════ */
void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  String cmd = line;

  /* ① 난독화 프레임(해시값)이면 복호화 */
  if (cmd.charAt(0) == 'x') {
    String d = decodeFrame(cmd);
    Serial.print(F("[복호화] "));
    Serial.print(cmd);
    Serial.print(F("  →  "));
    Serial.println(d.length() > 0 ? d : F("(빈값)"));
    if (d.length() == 0) return;
    cmd = d;
  }

  /* ② BLE 이벤트(+CONNECTED 등)는 로그만 */
  if (cmd.charAt(0) == '+') {
    Serial.print(F("[BLE이벤트] "));
    Serial.println(cmd);
    return;
  }

  /* ③ AI 값 판정 — aiDispatch() 의 if 체인 */
  if (aiScan) {
    // 이미 스캔 중이면 새 AI 명령을 무시 (서보 충돌 방지)
    if (cmd.charAt(0) >= '0' && cmd.charAt(0) <= '9') {
      Serial.println(F("[대기] 스캔 진행 중 — 새 AI 명령 무시"));
      return;
    }
  }

  if (aiDispatch(cmd)) {
    return;
  }

  /* ④ 기존 문법 */
  if (handleLegacyCommand(cmd)) {
    Serial.print(F("[동작] "));
    Serial.println(cmd);
    return;
  }

  /* ⑤ 어느 것도 아니면 */
  Serial.print(F("[무시] 알 수 없는 명령: '"));
  Serial.print(cmd);
  Serial.print(F("' len="));
  Serial.println(cmd.length());
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [8] 수신
 * ═══════════════════════════════════════════════════════════════════════════ */
void handleFrame() {
  rxBuf[rxLen] = '\0';
  String raw = String(rxBuf);
  raw.trim();

  int start = 0;
  while (start <= (int)raw.length()) {
    int nl = raw.indexOf('\n', start);
    String line = (nl < 0) ? raw.substring(start) : raw.substring(start, nl);
    processLine(line);
    if (nl < 0) break;
    start = nl + 1;
  }

  if (rxOverflow) {
    Serial.println(F("[경고] 수신버퍼 초과 — 일부 바이트 유실"));
    rxOverflow = false;
  }
  rxLen = 0;
  rxBuf[0] = '\0';
}

/* BLE 수신 최우선 긁어모으기 (SoftwareSerial 64B 함정 대응) */
void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < MAX_RX - 1) rxBuf[rxLen++] = c;
    else                    rxOverflow = true;
    lastRxAt = millis();
  }
}

/* PC 시리얼(9600) → 동일 처리 + BLE 중계 */
void drainPcSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (rxLen < MAX_RX - 1) rxBuf[rxLen++] = c;
    else                    rxOverflow = true;
    lastRxAt = millis();
    BTSerial.write(c);
  }
}

void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);
  delay(300);

  Serial.println(F("=== 누비다머신 통합 (AI분기 if/else if 형) v11 ==="));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__)); Serial.print(F(" ")); Serial.println(F(__TIME__));
  Serial.println(F("[AI] 1NubidaAi → 9번"));
  Serial.println(F("[AI] 2NubidaAi → 7번"));
  Serial.println(F("[기존] Piano.mode / Trash.mode / digitalWrite / tone 등"));
  Serial.println(F("준비 완료"));
}

void loop() {
  drainBle();        // ① BLE 수신 최우선
  drainPcSerial();   // ② PC 시리얼 수신

  // ③ 무수신 FRAME_GAP_MS = 프레임 완료
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }

  stepAiScan();      // ④ AI 스캔 1스텝
}
