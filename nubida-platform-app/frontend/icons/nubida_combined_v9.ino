#include "Servo.h"
Servo myServo;                 // 9번 — 기존 로직(Piano.mode, Trash.mode 등) + AI값 1
Servo servo7;                  // 7번 — AI값 2 전용

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다머신 통합 펌웨어 (v9 · 기존문장 + AI값 동시 지원)
 * ───────────────────────────────────────────────────────────────────────────
 *  [요구사항]
 *    ① 기존 문장을 그대로 읽어서 동작 (Piano.mode 처럼)
 *    ② 해시값(난독화 프레임)이 들어오면 AI 값도 동작
 *    ③ 두 가지가 한 코드에서 동시에 동작
 *
 *  [입력 경로]
 *    A) BLE(AT-09, 2·3번) — 웹에서 오는 난독화 프레임("x..") + 평문
 *    B) PC 시리얼 모니터(9600) — 기존 문장 직접 타이핑 테스트
 *       → B 로 들어온 문장은 BT 로도 그대로 중계(투명 프록시)
 *
 *  [AI 값 매핑]
 *    "1NubidaAi"  → myServo(9번)  스캔  (160 → 10 → 160)
 *    "2NubidaAi"  → servo7(7번)   스캔  ( 10 → 160 → 10)
 *
 *  [기존 문장 처리 — 원본 nubida_machine_receiver.ino 로직 그대로]
 *    Piano.mode / Trash.mode / digitalWrite(_,H|L); / tone(f,d); / noTone(p);
 *    if(cho < N) / if(pos < N) / if(pos > N) / pos.write(mN,N); / BT.print(tN,eN);
 *    int a = b; / Serial.print(N); / stop
 *
 *  [v8 에서 가져온 안정화]
 *    - SoftwareSerial 64바이트 버퍼 오버플로 대응(수신 최우선, char 버퍼)
 *    - 로그는 "프레임 완성 시" 1회만 → read() 지연 최소화
 *    - 수신 조각 붙이기 대기(청크 2개 도착 대응)
 *    - loop() 안에 return; 금지 → 플래그로 건너뛰기
 * ═══════════════════════════════════════════════════════════════════════════ */

#define NB_KEY 0x2F          // nubida-bt.js 의 KEY 와 동일해야 함

#define AI_SERVO_1   9       // 1NubidaAi → 9번
#define AI_SERVO_2   7       // 2NubidaAi → 7번
#define STEP_DEG     2       // AI 스캔 한 스텝 각도
#define STEP_MS      40      // AI 스캔 스텝 간격(ms)
#define FRAME_GAP_MS 30      // 이 시간 무수신 = 한 프레임 완료

/* ── 기존 문장용 변수 (원본 유지) ─────────────────────────────── */
int piezo;
int buzzer;
int buzzer1;
int SeRe;
int pwm;
int cho;
int pos1;
int pos2;
int pos = 0;
int Servopin;
int Servopos;
int serial;
int trig5;
int echo5;
int trig;
int echo;
int digitalHIGH;
int digitalLOW;

int  scanActive = 0;         // 0=없음 1=servo9 2=servo7

/* ── 수신 버퍼 (SoftwareSerial 64B 함정 대응, 넉넉히) ────────── */
char          rxBuf[256];
int           rxLen      = 0;
unsigned long lastRxAt   = 0;
bool          rxOverflow = false;

/* ── AI 스캔 상태 ────────────────────────────────────────────── */
bool          aiScan     = false;
int           aiWhich    = 0;     // 1=9번, 2=7번
int           aiP        = 10;
int           aiDir      = 1;
int           aiPhase    = 0;
int           aiStart    = 10;
int           aiEnd      = 160;
unsigned long aiLast     = 0;

/* ── HEX 문자 → 값 ──────────────────────────────────────────── */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* ── 난독화 프레임("x...") → 평문 복원 ───────────────────────── */
String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  // 홀수 길이 = 청크 경계에서 1글자 유실 → 마지막 1글자만 잘라 진행
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

/* ══════════════════════════════════════════════════════════════
 *  AI 값 동작 — 비블로킹 스캔 (v8 방식)
 * ══════════════════════════════════════════════════════════════ */
void startAiScan(int which) {
  aiWhich = which;
  aiScan  = true;
  aiLast  = millis();
  aiPhase = 0;

  if (which == 1) {                       // 9번 : 160 → 10
    myServo.attach(AI_SERVO_1);
    aiP = 160; aiStart = 160; aiEnd = 10; aiDir = -1;
    myServo.write(aiP);
    Serial.println(F("[AI] 1NubidaAi — 9번 스캔 시작"));
  } else {                                // 7번 : 10 → 160
    servo7.attach(AI_SERVO_2);
    aiP = 10; aiStart = 10; aiEnd = 160; aiDir = 1;
    servo7.write(aiP);
    Serial.println(F("[AI] 2NubidaAi — 7번 스캔 시작"));
  }
}

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

    if (aiPhase >= 2) {                   // 왕복 2회 → 종료
      if (aiWhich == 1) { myServo.write(aiP); delay(120); myServo.detach(); }
      else              { servo7.write(aiP);  delay(120); servo7.detach();  }
      aiScan = false;
      Serial.println(F("[AI] 스캔 완료 — 서보 전원 해제"));
      return;
    }
  }
  if (aiWhich == 1) myServo.write(aiP);
  else              servo7.write(aiP);
}

/* ══════════════════════════════════════════════════════════════
 *  기존 문장 처리 — 원본 nubida_machine_receiver.ino 파서 그대로
 *  ★ cmd 에 대해 파싱하고, 매칭되면 true 반환
 * ══════════════════════════════════════════════════════════════ */
bool handleLegacyCommand(String cmd) {

  /*디지털동작 HIGH부분 */
  int HIGHa = cmd.indexOf("digitalWrite(");
  int HIGHb = cmd.indexOf(",H);");
  String HIGHc = "digitalWrite(";
  String HIGHResult = (HIGHa >= 0 && HIGHb > HIGHa) ? cmd.substring(HIGHa + HIGHc.length(), HIGHb) : "";
  digitalHIGH = HIGHResult.toInt();

  /*디지털동작 LOW부분 */
  int LOWa = cmd.indexOf("digitalWrite(");
  int LOWb = cmd.indexOf(",L);");
  String LOWc = "digitalWrite(";
  String LOWResult = (LOWa >= 0 && LOWb > LOWa) ? cmd.substring(LOWa + LOWc.length(), LOWb) : "";
  digitalLOW = LOWResult.toInt();

  int ifa = cmd.indexOf("if(cho < ");
  int ifb = cmd.indexOf(")");
  String if1 = "if(cho < ";
  String ifResult1 = (ifa >= 0 && ifb > ifa) ? cmd.substring(ifa + if1.length(), ifb) : "";
  cho = ifResult1.toInt();

  int ifposa = cmd.indexOf("if(pos < ");
  int ifposb = cmd.indexOf(")");
  String ifpos1 = "if(pos < ";
  String ifposResult1 = (ifposa >= 0 && ifposb > ifposa) ? cmd.substring(ifposa + ifpos1.length(), ifposb) : "";
  pos1 = ifposResult1.toInt();

  int ifpos2a = cmd.indexOf("if(pos > ");
  int ifpos2b = cmd.indexOf(")");
  String ifpos2 = "if(pos > ";
  String ifposResult2 = (ifpos2a >= 0 && ifpos2b > ifpos2a) ? cmd.substring(ifpos2a + ifpos2.length(), ifpos2b) : "";
  pos2 = ifposResult2.toInt();

  int tonea = cmd.indexOf("tone(");
  int toneb = cmd.indexOf(",");
  int tonec = cmd.indexOf(");");
  String tone1 = "tone(";
  String tone2 = ",";
  String toneResult1 = (tonea >= 0 && toneb > tonea) ? cmd.substring(tonea + tone1.length(), toneb) : "";
  String toneResult2 = (toneb >= 0 && tonec > toneb) ? cmd.substring(toneb + tone2.length(), tonec) : "";
  buzzer = toneResult1.toInt();
  pwm    = toneResult2.toInt();

  int notonea = cmd.indexOf("noTone(");
  int notoneb = cmd.indexOf(");");
  String notone1 = "noTone(";
  String notoneResult1 = (notonea >= 0 && notoneb > notonea) ? cmd.substring(notonea + notone1.length(), notoneb) : "";
  buzzer1 = notoneResult1.toInt();

  int inta = cmd.indexOf("int ");
  int intb = cmd.indexOf(" = ");
  int intc = cmd.indexOf(";");
  String int1 = "int ";
  String int2 = " = ";
  String intResult1 = (inta >= 0 && intb > inta) ? cmd.substring(inta + int1.length(), intb) : "";
  String intResult2 = (intb >= 0 && intc > intb) ? cmd.substring(intb + int2.length(), intc) : "";

  int Seriala = cmd.indexOf("Serial.print(");
  int Serialb = cmd.indexOf(");");
  String Serialc = "Serial.print(";
  String SerialResult = (Seriala >= 0 && Serialb > Seriala) ? cmd.substring(Seriala + Serialc.length(), Serialb) : "";
  SeRe = SerialResult.toInt();

  int cho_modea = cmd.indexOf("BT.print(t");
  int cho_modeb = cmd.indexOf(",e");
  int cho_modec = cmd.indexOf(");");
  String cho_modeRe1 = "BT.print(t";
  String cho_modeRe2 = ",e";
  String cho_modeaResult1 = (cho_modea >= 0 && cho_modeb > cho_modea) ? cmd.substring(cho_modea + cho_modeRe1.length(), cho_modeb) : "";
  String cho_modeaResult2 = (cho_modeb >= 0 && cho_modec > cho_modeb) ? cmd.substring(cho_modeb + cho_modeRe2.length(), cho_modec) : "";
  trig5 = cho_modeaResult1.toInt();
  echo5 = cho_modeaResult2.toInt();

  int Servoa = cmd.indexOf("pos.write(m");
  int Servob = cmd.indexOf(",");
  int Servoc = cmd.indexOf(");");
  String Servod = "pos.write(m";
  String Servoe = ",";
  String ServoResult1 = (Servoa >= 0 && Servob > Servoa) ? cmd.substring(Servoa + Servod.length(), Servob) : "";
  String ServoResult2 = (Servob >= 0 && Servoc > Servob) ? cmd.substring(Servob + Servoe.length(), Servoc) : "";
  Servopin = ServoResult1.toInt();
  Servopos = ServoResult2.toInt();

  int Piano_modea = cmd.indexOf("Piano.mode(t");
  int Piano_modeb = cmd.indexOf(",e");
  int Piano_modec = cmd.indexOf(",m");
  int Piano_moded = cmd.indexOf(");");
  String Piano_modeRe1 = "Piano.mode(t";
  String Piano_modeRe2 = ",e";
  String Piano_modeRe3 = ",m";
  String Piano_modeaResult1 = (Piano_modea >= 0 && Piano_modeb > Piano_modea) ? cmd.substring(Piano_modea + Piano_modeRe1.length(), Piano_modeb) : "";
  String Piano_modeaResult2 = (Piano_modeb >= 0 && Piano_modec > Piano_modeb) ? cmd.substring(Piano_modeb + Piano_modeRe2.length(), Piano_modec) : "";
  String Piano_modeaResult3 = (Piano_modec >= 0 && Piano_moded > Piano_modec) ? cmd.substring(Piano_modec + Piano_modeRe3.length(), Piano_moded) : "";
  trig  = Piano_modeaResult1.toInt();
  echo  = Piano_modeaResult2.toInt();
  piezo = Piano_modeaResult3.toInt();

  /* ── 판정 (원본 순서 유지) ─────────────────────────────────── */
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

    digitalWrite(10, LOW);
    digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH);
    delayMicroseconds(10);
    digitalWrite(10, LOW);

    unsigned long duration1 = pulseIn(11, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);

    if (distance < 11) {
      tone(7, 262);
      myServo.write(170);
      delay(1000);
    } else {
      noTone(7);
      myServo.write(90);
      delay(1000);
    }
    myServo.detach();
    return true;
  }
  else if (cmd.equals("if(pos < " + ifposResult1 + ")")) {
    pinMode(4, OUTPUT);
    pinMode(5, OUTPUT);
    pinMode(6, OUTPUT);
    pinMode(7, OUTPUT);
    myServo.attach(9);

    myServo.write(45);
    digitalWrite(4, HIGH);
    digitalWrite(5, LOW);
    digitalWrite(6, HIGH);
    digitalWrite(7, LOW);
    delay(100);
    return true;
  }
  else if (cmd.equals("stop")) {
    pinMode(4, OUTPUT);
    pinMode(5, OUTPUT);
    pinMode(6, OUTPUT);
    pinMode(7, OUTPUT);
    digitalWrite(4, LOW);
    digitalWrite(5, LOW);
    digitalWrite(6, LOW);
    digitalWrite(7, LOW);
    delay(100);
    return true;
  }
  else if (cmd.equals("if(pos > " + ifposResult2 + ")")) {
    pinMode(4, OUTPUT);
    pinMode(5, OUTPUT);
    pinMode(6, OUTPUT);
    pinMode(7, OUTPUT);
    myServo.attach(9);

    myServo.write(135);
    digitalWrite(4, LOW);
    digitalWrite(6, LOW);
    digitalWrite(7, HIGH);
    delay(100);
    return true;
  }
  else if (cmd.equals("BT.print(t" + cho_modeaResult1 + ",e" + cho_modeaResult2 + ");")) {
    pinMode(trig5, OUTPUT);
    pinMode(echo5, INPUT);

    digitalWrite(trig5, LOW);
    digitalWrite(echo5, LOW);
    delayMicroseconds(2);
    digitalWrite(trig5, HIGH);
    delayMicroseconds(10);
    digitalWrite(trig5, LOW);

    unsigned long duration1 = pulseIn(echo5, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);
    Serial.print(distance);
    Serial.println("cm");

    BTSerial.print(distance);
    BTSerial.println("cm");
    delay(1000);
    return true;
  }
  else if (cmd.equals("tone(" + toneResult1 + "," + toneResult2 + ");")) {
    pinMode(buzzer, OUTPUT);
    tone(buzzer, pwm);
    return true;
  }
  else if (cmd.equals("noTone(" + notoneResult1 + ");")) {
    pinMode(buzzer1, OUTPUT);
    noTone(buzzer1);
    return true;
  }
  else if (cmd.equals("Piano.mode")) {
    pinMode(7, OUTPUT);
    pinMode(10, OUTPUT);
    pinMode(11, INPUT);

    digitalWrite(10, LOW);
    digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH);
    delayMicroseconds(10);
    digitalWrite(10, LOW);

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
    pinMode(10, OUTPUT);
    pinMode(11, INPUT);

    digitalWrite(10, LOW);
    digitalWrite(11, LOW);
    delayMicroseconds(2);
    digitalWrite(10, HIGH);
    delayMicroseconds(10);
    digitalWrite(10, LOW);

    unsigned long duration1 = pulseIn(11, HIGH);
    float distance = duration1 / 29.0 / 2.0;
    delay(10);

    if (distance < 15) {
      myServo.write(180);
      delay(3000);
    } else {
      myServo.write(85);
      delay(1000);
    }
    myServo.detach();
    return true;
  }

  return false;   // 어떤 문장과도 일치하지 않음
}

/* ══════════════════════════════════════════════════════════════
 *  한 줄(line) 처리 — AI 값 우선, 없으면 기존 문장
 * ══════════════════════════════════════════════════════════════ */
void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  String cmd = line;

  /* ① 난독화 프레임이면 복호화 (해시값) */
  if (cmd.charAt(0) == 'x') {
    String d = decodeFrame(cmd);
    Serial.print(F("[복호화] "));
    Serial.print(cmd);
    Serial.print(F("  →  "));
    Serial.println(d.length() > 0 ? d : F("(빈값)"));
    if (d.length() == 0) return;
    cmd = d;
  }

  /* ② BLE 이벤트(+CONNECTED 등)는 로그만, 동작 안 함 */
  if (cmd.charAt(0) == '+') {
    Serial.print(F("[BLE이벤트] "));
    Serial.println(cmd);
    return;
  }

  /* ③ AI 값 판정 — 관대한 매칭(마지막 글자 유실 대응) */
  bool is1 = (cmd.indexOf("1Nubida") >= 0) || cmd.equals("1NubidaAi");
  bool is2 = (cmd.indexOf("2Nubida") >= 0) || cmd.equals("2NubidaAi");

  if (!is1 && !is2 && cmd.length() >= 1) {
    if (cmd.charAt(0) == '1')      { is1 = true; Serial.println(F("[보정] 앞자리 1만 수신")); }
    else if (cmd.charAt(0) == '2') { is2 = true; Serial.println(F("[보정] 앞자리 2만 수신")); }
  }

  if (is1 || is2) {
    Serial.print(F("[판정] AI값 = "));
    Serial.println(is1 ? F("1NubidaAi") : F("2NubidaAi"));

    if (aiScan) {
      Serial.println(F("[대기] 스캔 진행 중 — 새 AI 명령 무시"));
    } else {
      startAiScan(is1 ? 1 : 2);
    }
    return;
  }

  /* ④ 기존 문장 처리 */
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

/* ══════════════════════════════════════════════════════════════
 *  수신 버퍼 → 개행 단위 줄 분리
 * ══════════════════════════════════════════════════════════════ */
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

/* ── BLE 수신 최우선 긁어모으기 ─────────────────────────────── */
void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    else                                rxOverflow = true;
    lastRxAt = millis();
  }
}

/* ── PC 시리얼(9600) → 그대로 처리 + BLE 중계 ───────────────── */
void drainPcSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    /* PC 에서 직접 친 기존 문장도 동일하게 처리 */
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    else                                rxOverflow = true;
    lastRxAt = millis();

    /* BLE 로도 중계 (원본 투명 프록시 동작 보존) */
    BTSerial.write(c);
  }
}

void setup() {
  Serial.begin(9600);        // 시리얼 모니터 9600 그대로
  BTSerial.begin(9600);      // AT-09 통신 속도 그대로
  delay(300);

  Serial.println(F("=== 누비다머신 통합 (기존문장 + AI값) v9 ==="));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__)); Serial.print(F(" ")); Serial.println(F(__TIME__));
  Serial.println(F("[기능] 난독화 복호화 + 기존문장 파서 + AI값 2서보"));
  Serial.println(F("[AI] 1NubidaAi=9번  2NubidaAi=7번"));
  Serial.println(F("[기존] Piano.mode / Trash.mode / digitalWrite / tone 등"));
  Serial.println(F("준비 완료"));
}

void loop() {

  /* ── ① BLE 수신 최우선 ─────────────────────────────── */
  drainBle();

  /* ── ② PC 시리얼 입력도 수신 ───────────────────────── */
  drainPcSerial();

  /* ── ③ 무수신 FRAME_GAP_MS = 한 프레임 완료 → 처리 ── */
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }

  /* ── ④ AI 스캔 1스텝 (비블로킹) ────────────────────── */
  stepAiScan();
}
