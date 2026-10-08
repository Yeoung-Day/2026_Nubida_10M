/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다머신 통합 펌웨어 (v22 · 한 곳에서 다 보이는 방식)
 * ───────────────────────────────────────────────────────────────────────────
 *
 *  [v22 에서 바뀐 점]
 *    ★ 부품표(DEVICES[]) · 신호표(SIG_*) 를 전부 없앴습니다.
 *    ★ 이제 actionDispatch() 안에서 배선·동작을 전부 볼 수 있습니다.
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ 동작 추가하는 법
 *  ─────────────────────────────────────────────────────────────────────────
 *
 *    actionDispatch() 안에 한 덩어리만 추가하면 끝입니다.
 *
 *      else if (cmd.equals("8NubidaAi") || cmd.equals("8Nubida") || cmd.equals("8")) {
 *        servoTo(9, 90, 600);        // 9번 서보를 90도로 (0.6초에 걸쳐)
 *        servoTo(9, 160, 600);       // 160도로
 *        servoTo(9, 90, 400);        // 복귀
 *        return true;
 *      }
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ 쓸 수 있는 동작 (한 줄씩)
 *  ─────────────────────────────────────────────────────────────────────────
 *
 *    servoTo(핀, 각도, 시간)          서보를 각도로 부드럽게 이동 (0~180)
 *    motorGo(핀A, 핀B, 속도, 초)      모터 회전 (속도 0~100, 초 단위)
 *    motorGo(핀A, 핀B, -속도, 초)     반대로 회전
 *    motorStop(핀A, 핀B)              모터 정지
 *    ledOn(핀, 색)                    LED 켜기 (0xFF0000 = 빨강)
 *    ledOff(핀)                       LED 끄기
 *    ledBlink(핀, 색, 횟수, 간격ms)   LED 깜빡임
 *    beep(핀, 주파수, 시간ms)         부저 소리
 *    beepOff(핀)                      부저 끄기
 *    wait(시간ms)                     대기
 *    dist(trig핀, echo핀)             초음파 거리(cm) 반환
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ 동시에 움직이려면 (융합)
 *  ─────────────────────────────────────────────────────────────────────────
 *
 *    servoTo(9, 160, 600, false);     // ★ 마지막 false = "기다리지 마"
 *    motorGo(5, 4, 70, 0);            // 0초 = 계속
 *    ledOn(3, 0x0000FF);
 *    beep(6, 1046, 600);
 *    wait(600);                       // 여기서 한꺼번에 진행
 *    motorStop(5, 4);
 *
 *  ─────────────────────────────────────────────────────────────────────────
 */

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3);   // BLE (RX=2, TX=3)

#include <Servo.h>
Servo srv[12];                   // 서보 객체 (최대 12개)


/* ══════════════════════════════════════════════════════════════════════════
 *  도우미 함수들 — 여기는 건드리지 않아도 됩니다
 * ══════════════════════════════════════════════════════════════════════════ */

/* ── 서보 ── */
int  srvPin[12];                  // 서보가 붙은 핀 (-1 = 미사용)
int  srvCur[12];                  // 현재 각도
int  srvIdx = 0;                  // 다음에 쓸 서보 칸

int srvFind(int pin) {
  for (int i = 0; i < 12; i++) if (srvPin[i] == pin) return i;
  return -1;
}

/* 서보 준비 (attach + 현재각도 기록) — servoTo 안에서만 씀 */
int srvPrep(int pin) {
  int i = srvFind(pin);
  if (i >= 0) return i;
  if (srvIdx >= 12) { Serial.println(F("[경고] 서보 12개 초과")); return -1; }
  i = srvIdx++;
  srvPin[i] = pin;
  srvCur[i] = 90;
  srv[i].attach(pin);
  delay(15);
  return i;
}

/* servoTo(핀, 각도, 시간)  —  부드럽게 이동
 *   시간 ms 동안 각도까지 조금씩 움직인다.
 *   기다리기=false 면 목표만 정하고 바로 돌아온다(동시동작용) */
void servoTo(int pin, int deg, int ms, bool block = true) {
  if (deg < 0)   deg = 0;
  if (deg > 180) deg = 180;

  int i = srvPrep(pin);
  if (i < 0) return;

  int from = srvCur[i];
  if (from == deg) return;

  if (ms <= 0) {                       // 즉시
    srvCur[i] = deg;
    srv[i].write(deg);
    return;
  }

  /* 3도씩 나눠서 이동 */
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
    srvCur[i] = cur;
    if (block) delay(tick);
  }
  srvCur[i] = deg;
  srv[i].write(deg);

  Serial.print(F("[서보] ")); Serial.print(pin);
  Serial.print(F("번 → ")); Serial.print(deg); Serial.println(F("도"));
}

/* ── 모터 ── */
/* motorGo(핀A, 핀B, 속도, 초)
 *   속도  1~100 = 앞으로,  -1~-100 = 뒤로,  0 = 정지
 *   초    0 = 계속 돌림 (멈추려면 motorStop) */
void motorGo(int pinA, int pinB, int speed, float secs) {
  pinMode(pinA, OUTPUT);
  pinMode(pinB, OUTPUT);

  int mag = abs(speed);
  if (mag > 100) mag = 100;
  int pwm = map(mag, 0, 100, 0, 255);

  if (speed > 0) {
    analogWrite(pinA, pwm); digitalWrite(pinB, LOW);
  } else if (speed < 0) {
    digitalWrite(pinA, LOW); analogWrite(pinB, pwm);
  } else {
    digitalWrite(pinA, LOW); digitalWrite(pinB, LOW);
    return;
  }

  Serial.print(F("[모터] ")); Serial.print(pinA); Serial.print(F(","));
  Serial.print(pinB); Serial.print(F(" 속도 ")); Serial.print(speed);
  Serial.println(F("%"));

  if (secs > 0) {
    delay((int)(secs * 1000));
    digitalWrite(pinA, LOW); digitalWrite(pinB, LOW);
  }
}

void motorStop(int pinA, int pinB) {
  pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
  digitalWrite(pinA, LOW);  digitalWrite(pinB, LOW);
  Serial.print(F("[모터] ")); Serial.print(pinA); Serial.print(F(","));
  Serial.print(pinB); Serial.println(F(" 정지"));
}

/* ── LED (라이브러리 없이 ON/OFF + 밝기) ── */
void ledOn(int pin, unsigned long color) {
  pinMode(pin, OUTPUT);
  if (color == 0) { digitalWrite(pin, LOW); return; }
  uint8_t bright = (uint8_t)((color >> 16) & 0xFF);
  if (bright == 0) bright = 255;
  if (pin == 3 || pin == 5 || pin == 6 || pin == 9 || pin == 10 || pin == 11)
    analogWrite(pin, bright);
  else
    digitalWrite(pin, HIGH);

  Serial.print(F("[LED] ")); Serial.print(pin);
  Serial.print(F("번 색 0x"));
  { char hb[9]; snprintf(hb, sizeof(hb), "%06X", (unsigned int)(color & 0xFFFFFF));
    Serial.println(hb); }
}

void ledOff(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  Serial.print(F("[LED] ")); Serial.print(pin); Serial.println(F("번 끔"));
}

void ledBlink(int pin, unsigned long color, int times, int gapMs) {
  for (int i = 0; i < times; i++) {
    ledOn(pin, color);  delay(gapMs / 2);
    ledOff(pin);        delay(gapMs / 2);
  }
}

/* ── 부저 ── */
void beep(int pin, int freq, int ms) {
  pinMode(pin, OUTPUT);
  tone(pin, freq, ms);
  Serial.print(F("[부저] ")); Serial.print(pin);
  Serial.print(F("번 ")); Serial.print(freq); Serial.println(F("Hz"));
}

void beepOff(int pin) {
  pinMode(pin, OUTPUT);
  noTone(pin);
  Serial.print(F("[부저] ")); Serial.print(pin); Serial.println(F("번 끔"));
}

/* ── 대기 ── */
void wait(int ms) { delay(ms); }

/* ── 초음파 거리(cm) ── */
float dist(int trigPin, int echoPin) {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  digitalWrite(trigPin, LOW);  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH); delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  unsigned long dur = pulseIn(echoPin, HIGH, 30000);
  float cm = dur / 58.0;
  Serial.print(F("[초음파] ")); Serial.print((int)cm); Serial.println(F("cm"));
  return cm;
}

/* ── 전부 정지/정리 ── */
void allStop() {
  for (int i = 0; i < srvIdx; i++) {
    srv[i].write(srvCur[i]);
    delay(20);
    srv[i].detach();
  }
}

/* ══════════════════════════════════════════════════════════════════════════
 *  ★★★ 여기서부터 동작 ★★★  — 이 함수 안만 고치면 됩니다
 *
 *    · 배선(핀 번호)은 아래 "내 배선" 에 적습니다.
 *    · 동작은 cmd.equals(...) 로 하나씩 추가합니다.
 * ══════════════════════════════════════════════════════════════════════════ */

bool actionDispatch(String cmd) {

  /* ─────────── 내 배선 (여기 숫자만 바꾸면 됩니다) ─────────── */
  const int PIN_HEAD  = 9;    // 머리 서보
  const int PIN_ARM   = 7;    // 팔 서보
  const int PIN_ML_A  = 5;    // 바퀴L  (L9110S IA)
  const int PIN_ML_B  = 4;    // 바퀴L  (L9110S IB)
  const int PIN_LED   = 3;    // 눈 LED
  const int PIN_BUZZ  = 6;    // 부저
  const int PIN_TRIG  = 10;   // 초음파 TRIG
  const int PIN_ECHO  = 11;   // 초음파 ECHO
  /* ─────────────────────────────────────────────────────────── */


  /* ══ 1NubidaAi — 머리 숙이기 ══ */
  if (cmd.equals("1NubidaAi") || cmd.equals("1Nubida") || cmd.equals("1")) {
    servoTo(PIN_HEAD,  90, 400);
    servoTo(PIN_HEAD, 160, 600);
    servoTo(PIN_HEAD,  90, 400);
    return true;
  }

  /* ══ 2NubidaAi — 인사 (팔 안녕) ══ */
  else if (cmd.equals("2NubidaAi") || cmd.equals("2Nubida") || cmd.equals("2")) {
    servoTo(PIN_ARM,  90, 300);
    servoTo(PIN_ARM, 160, 500);
    servoTo(PIN_ARM,  60, 500);
    servoTo(PIN_ARM, 160, 500);
    servoTo(PIN_ARM,  60, 500);
    servoTo(PIN_ARM,  90, 300);
    return true;
  }

  /* ══ 3NubidaAi — 앞으로 (바퀴) ══ */
  else if (cmd.equals("3NubidaAi") || cmd.equals("3Nubida") || cmd.equals("3")) {
    motorGo(PIN_ML_A, PIN_ML_B, 80, 1.2);
    return true;
  }

  /* ══ 4NubidaAi — 불 켜기 (눈 LED) ══ */
  else if (cmd.equals("4NubidaAi") || cmd.equals("4Nubida") || cmd.equals("4")) {
    ledOn(PIN_LED, 0xFF0000);
    wait(400);
    ledBlink(PIN_LED, 0x00FF00, 3, 300);
    ledOff(PIN_LED);
    return true;
  }

  /* ══ 5NubidaAi — 삐삐 (부저) ══ */
  else if (cmd.equals("5NubidaAi") || cmd.equals("5Nubida") || cmd.equals("5")) {
    beep(PIN_BUZZ, 880, 150);  wait(100);
    beep(PIN_BUZZ, 880, 150);
    return true;
  }

  /* ══ 6NubidaAi — 출발 (★융합: 서보+모터+LED+부저 동시) ══ */
  else if (cmd.equals("6NubidaAi") || cmd.equals("6Nubida") || cmd.equals("6")) {
    servoTo(PIN_HEAD,  90, 300, false);   // false = 기다리지 마 (동시 진행)
    servoTo(PIN_HEAD, 160, 600, false);
    motorGo(PIN_ML_A, PIN_ML_B, 70, 0);   // 0 = 계속
    ledOn(PIN_LED, 0x0000FF);
    beep(PIN_BUZZ, 1046, 600);
    wait(600);                            // 여기서 한꺼번에 진행
    servoTo(PIN_HEAD,  90, 400, false);
    motorStop(PIN_ML_A, PIN_ML_B);
    ledOff(PIN_LED);
    return true;
  }

  /* ══ 7NubidaAi — 장애물 감지하면 멈추기 ══ */
  else if (cmd.equals("7NubidaAi") || cmd.equals("7Nubida") || cmd.equals("7")) {
    motorGo(PIN_ML_A, PIN_ML_B, 70, 0);   // 앞으로 출발
    float cm = dist(PIN_TRIG, PIN_ECHO);
    if (cm < 20) {
      motorStop(PIN_ML_A, PIN_ML_B);
      beep(PIN_BUZZ, 440, 400);
    }
    motorStop(PIN_ML_A, PIN_ML_B);
    return true;
  }

  return false;
}


/* ══════════════════════════════════════════════════════════════════════════
 *  기존문법 (AI 가 만든 코드) — digitalWrite / tone / 초음파 등
 *
 *  ★ 추가하는 법 (딱 2단계)
 *    【1단계】 아래 "값 꺼내기" 에 위치 계산 한 줄 추가
 *    【2단계】 아래 "실행" 에 else if (...) { ... } 한 덩어리 추가
 * ══════════════════════════════════════════════════════════════════════════ */

bool handleLegacyCommand(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  【1단계】 값 꺼내기 — 명령에서 숫자를 뽑아 변수에 담습니다
   * ══════════════════════════════════════════════════════════════════════ */

  /* digitalWrite(13,H); 에서 13 뽑기 */
  int HIGH_a = cmd.indexOf("digitalWrite(");
  int HIGH_b = cmd.indexOf(",H);");
  String HIGHResult = (HIGH_a >= 0 && HIGH_b > HIGH_a)
                      ? cmd.substring(HIGH_a + 13, HIGH_b) : "";

  /* digitalWrite(13,L); 에서 13 뽑기 */
  int LOW_a = cmd.indexOf("digitalWrite(");
  int LOW_b = cmd.indexOf(",L);");
  String LOWResult = (LOW_a >= 0 && LOW_b > LOW_a)
                     ? cmd.substring(LOW_a + 13, LOW_b) : "";

  /* int lamp = 13; 에서 변수명과 13 뽑기 */
  int INT_a = cmd.indexOf("int ");
  int INT_b = cmd.indexOf(" = ");
  int INT_c = cmd.indexOf(";");
  String INTResult1 = (INT_a >= 0 && INT_b > INT_a)
                      ? cmd.substring(INT_a + 4, INT_b) : "";
  String INTResult2 = (INT_b > 0 && INT_c > INT_b)
                      ? cmd.substring(INT_b + 3, INT_c) : "";

  /* Serial.print(13); 에서 13 뽑기 */
  int SR_a = cmd.indexOf("Serial.print(");
  int SR_b = cmd.indexOf(");");
  String SRResult = (SR_a >= 0 && SR_b > SR_a)
                    ? cmd.substring(SR_a + 13, SR_b) : "";

  /* tone(7,262); 에서 7 과 262 뽑기 */
  int TN_a = cmd.indexOf("tone(");
  int TN_c = cmd.indexOf(",");
  int TN_b = cmd.indexOf(");");
  String TNResult1 = (TN_a >= 0 && TN_c > TN_a)
                     ? cmd.substring(TN_a + 5, TN_c) : "";
  String TNResult2 = (TN_c > 0 && TN_b > TN_c)
                     ? cmd.substring(TN_c + 1, TN_b) : "";

  /* noTone(7); 에서 7 뽑기 */
  int NT_a = cmd.indexOf("noTone(");
  int NT_b = cmd.indexOf(");");
  String NTResult = (NT_a >= 0 && NT_b > NT_a)
                    ? cmd.substring(NT_a + 7, NT_b) : "";

  /* if(cho < 20) 에서 20 뽑기 */
  int CHO_a = cmd.indexOf("if(cho <");
  String CHOResult = "";
  if (CHO_a >= 0) {
    String t = cmd.substring(CHO_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) CHOResult = t.substring(0, e);
  }

  /* if(pos < 90) 에서 90 뽑기 */
  int POSL_a = cmd.indexOf("if(pos <");
  String POSLResult = "";
  if (POSL_a >= 0) {
    String t = cmd.substring(POSL_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSLResult = t.substring(0, e);
  }

  /* if(pos > 90) 에서 90 뽑기 */
  int POSG_a = cmd.indexOf("if(pos >");
  String POSGResult = "";
  if (POSG_a >= 0) {
    String t = cmd.substring(POSG_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSGResult = t.substring(0, e);
  }

  /* BT.print(t10,e11); 에서 10 과 11 뽑기 */
  int BP_a = cmd.indexOf("BT.print(t");
  int BP_c = cmd.indexOf(",e");
  int BP_b = cmd.indexOf(");");
  String BPResult1 = (BP_a >= 0 && BP_c > BP_a)
                     ? cmd.substring(BP_a + 10, BP_c) : "";
  String BPResult2 = (BP_c > 0 && BP_b > BP_c)
                     ? cmd.substring(BP_c + 2, BP_b) : "";


  /* ══════════════════════════════════════════════════════════════════════
   *  【2단계】 실행 — 여기에 if 문으로 추가
   *
   *   예)  13번 핀 켜기
   *     else if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
   *       pinMode(13, OUTPUT); digitalWrite(13, HIGH); delay(100); return true;
   *     }
   * ══════════════════════════════════════════════════════════════════════ */

/* ── ① digitalWrite(13,H);  →  13번 핀 켜기 ─────────────────────────── */
  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
    int pin = HIGHResult.toInt();
    pinMode(pin, OUTPUT); digitalWrite(pin, HIGH); delay(100); return true;
  }

/* ── ② digitalWrite(13,L);  →  13번 핀 끄기 ─────────────────────────── */
  else if (cmd.equals("digitalWrite(" + LOWResult + ",L);")) {
    int pin = LOWResult.toInt();
    pinMode(pin, OUTPUT); digitalWrite(pin, LOW); delay(100); return true;
  }

/* ── ③ int lamp = 13;  →  13번 핀을 변수로 쓰기 ─────────────────────── */
  else if (cmd.equals("int " + INTResult1 + " = " + INTResult2 + ";")) {
    BTSerial.println(INTResult1 + "의 변수명은 " + INTResult2 + "번의 핀을 사용합니다.");
    delay(100); return true;
  }

/* ── ④ Serial.print(13);  →  13번 핀 읽어서 보내기 ──────────────────── */
  else if (cmd.equals("Serial.print(" + SRResult + ");")) {
    int pin = SRResult.toInt();
    pinMode(pin, INPUT);
    BTSerial.println(digitalRead(pin));
    delay(100); return true;
  }

/* ── ⑤ if(cho < 20)  →  초음파 20cm 이내면 부저 ─────────────────────── */
  else if (cmd.equals("if(cho < " + CHOResult + ")")) {
    int limit = CHOResult.toInt();
    float cm = dist(10, 11);
    if (cm < limit) { beep(7, 262, 1000); }
    else            { noTone(7); }
    delay(1000);
    return true;
  }

/* ── ⑥ if(pos < 90)  →  모터 앞으로 ─────────────────────────────────── */
  else if (cmd.equals("if(pos < " + POSLResult + ")")) {
    motorGo(4, 5, 70, 0);
    return true;
  }

/* ── ⑦ if(pos > 90)  →  모터 뒤로 ───────────────────────────────────── */
  else if (cmd.equals("if(pos > " + POSGResult + ")")) {
    motorGo(4, 5, -70, 0);
    return true;
  }

/* ── ⑧ stop  →  모터 정지 ───────────────────────────────────────────── */
  else if (cmd.equals("stop")) {
    motorStop(4, 5);
    return true;
  }

/* ── ⑨ tone(7,262);  →  7번 부저에 262 주파수 ───────────────────────── */
  else if (cmd.equals("tone(" + TNResult1 + "," + TNResult2 + ");")) {
    beep(TNResult1.toInt(), TNResult2.toInt(), 1000);
    return true;
  }

/* ── ⑩ noTone(7);  →  7번 부저 끄기 ─────────────────────────────────── */
  else if (cmd.equals("noTone(" + NTResult + ");")) {
    beepOff(NTResult.toInt());
    return true;
  }

/* ── ⑪ BT.print(t10,e11);  →  초음파 거리 측정해서 보내기 ───────────── */
  else if (cmd.equals("BT.print(t" + BPResult1 + ",e" + BPResult2 + ");")) {
    float cm = dist(BPResult1.toInt(), BPResult2.toInt());
    Serial.println(cm);
    BTSerial.println(cm);
    delay(500);
    return true;
  }

/* ── ⑫ Piano.mode  →  초음파 피아노 ─────────────────────────────────── */
  else if (cmd.equals("Piano.mode")) {
    float cm = dist(10, 11);
    int f = 0;
    if      (cm < 4)    f = 262;
    else if (cm < 6.9)  f = 294;
    else if (cm < 9.8)  f = 330;
    else if (cm < 12.5) f = 349;
    else if (cm < 14.6) f = 392;
    else if (cm < 16)   f = 440;
    else if (cm < 18)   f = 494;
    else if (cm < 20.1) f = 523;
    if (f) { beep(7, f, 300); } else { noTone(7); }
    return true;
  }

/* ── ⑬ Trash.mode  →  초음파 쓰레기통 (거리 출력) ───────────────────── */
  else if (cmd.equals("Trash.mode")) {
    float cm = dist(10, 11);
    Serial.println(cm);
    BTSerial.println(cm);
    delay(500);
    return true;
  }

  return false;
}


/* ══════════════════════════════════════════════════════════════════════════
 *  프레임 처리 (난독화 복호화) — 건드리지 않아도 됩니다
 * ══════════════════════════════════════════════════════════════════════════ */

char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;
#define FRAME_GAP_MS 30

int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  int h0 = hexVal(hexs.charAt(0));
  int h1 = hexVal(hexs.charAt(1));
  int seed = (h0 * 16 + h1) ^ 0x2F;

  String out = "";
  for (unsigned int i = 2; i + 1 < hexs.length(); i += 2) {
    int a = hexVal(hexs.charAt(i));
    int b = hexVal(hexs.charAt(i + 1));
    if (a < 0 || b < 0) break;
    char ch = (char)(((a * 16 + b) ^ seed) & 0xFF);
    out += ch;
  }
  out.trim();
  return out;
}

/* ── 한 줄 처리 ── */
void processLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  Serial.print(F("[명령] "));
  Serial.println(line);

  String cmd = line;

  if (cmd.charAt(0) == 'x') {
    String d = decodeFrame(cmd);
    Serial.print(F("[복호화] "));
    Serial.println(d.length() > 0 ? d : F("(빈값)"));
    if (d.length() == 0) return;
    cmd = d;
  }

  if (cmd.charAt(0) == '+') {
    Serial.print(F("[BLE이벤트] "));
    Serial.println(cmd);
    return;
  }

  if (actionDispatch(cmd))     return;
  if (handleLegacyCommand(cmd)) return;

  Serial.print(F("[무시] 알 수 없는 명령: "));
  Serial.println(cmd);
}

/* ── 수신 버퍼 처리 ── */
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
    bool cut = (i == (int)block.length()) || block.charAt(i) == '\n' || block.charAt(i) == '\r';
    if (!cut) continue;
    if (i > start) {
      String one = block.substring(start, i);
      one.trim();
      if (one.length() > 0) processLine(one);
    }
    start = i + 1;
  }
}


/* ══════════════════════════════════════════════════════════════════════════
 *  setup / loop
 * ══════════════════════════════════════════════════════════════════════════ */

void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  /* 서보 칸 초기화 */
  for (int i = 0; i < 12; i++) { srvPin[i] = -1; srvCur[i] = 90; }

  delay(200);
  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.print(F("  누비다머신 v22 (한 곳에서 다 보이는 방식)"));
  Serial.println(F(""));
  Serial.print(F("  빌드: ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));        Serial.println(F(__TIME__));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
  Serial.println(F("[동작] 7개 등록됨"));
  Serial.println(F("  1NubidaAi → 머리숙이기"));
  Serial.println(F("  2NubidaAi → 안녕"));
  Serial.println(F("  3NubidaAi → 앞으로"));
  Serial.println(F("  4NubidaAi → 불켜기"));
  Serial.println(F("  5NubidaAi → 삐삐"));
  Serial.println(F("  6NubidaAi → 출발 (융합)"));
  Serial.println(F("  7NubidaAi → 장애물감지"));
  Serial.println(F(""));
  Serial.println(F("[기존문법] digitalWrite / tone / 초음파 등 13개"));

  /* ── 배선 검사 ── */
  Serial.println(F(""));
  Serial.println(F("[배선검사]"));
  int pin[8]   = { 9, 7, 5, 4, 3, 6, 10, 11 };
  const char* nm[8] = { "머리서보","팔서보","바퀴L-A","바퀴L-B","눈LED","부저","초음파TRIG","초음파ECHO" };
  bool bad = false;
  for (int i = 0; i < 8; i++) {
    if (pin[i] == 2 || pin[i] == 3) {
      Serial.print(F("  [충돌] ")); Serial.print(nm[i]);
      Serial.print(F(" = ")); Serial.print(pin[i]);
      Serial.println(F("번 (BLE 통신핀 2,3 과 겹침)"));
      bad = true;
    }
    for (int j = i + 1; j < 8; j++) {
      if (pin[i] == pin[j]) {
        Serial.print(F("  [중복] ")); Serial.print(nm[i]);
        Serial.print(F(" 와 ")); Serial.print(nm[j]);
        Serial.print(F(" 가 같은 ")); Serial.print(pin[i]); Serial.println(F("번"));
        bad = true;
      }
    }
  }
  if (!bad) Serial.println(F("  이상 없음"));

  Serial.println(F("준비 완료"));
  Serial.println(F(""));
}

void loop() {
  drainBle();                                     // ① BLE 수신 최우선

  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();                                // ② 프레임 완성 시 처리
  }
}
