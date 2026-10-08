/* ===========================================================================
 *  nubida_ai.h  -  AI 명령 처리 (13종)
 *  ---------------------------------------------------------------------------
 *  웹(누비다플랫폼)에서 AI가 만들어 준 코드를 그대로 받아서 실행합니다.
 *
 *  [1단계] 값 꺼내기
 *      "digitalWrite(13,H);"  ->  HIGHResult = "13"
 *      "int lamp = 13;"       ->  INTResult1="lamp", INTResult2="13"
 *      이렇게 명령 안에서 숫자/이름만 뽑아냅니다.
 *
 *  [2단계] 실행
 *      뽑아낸 값으로 실제 부품을 움직입니다.
 *
 *  [중요] 모든 조건은 if / else if 로 연결했습니다.
 *         그래서 위에서 하나 걸리면 아래는 확인하지 않습니다.
 *
 *  ★ 새 AI 명령을 추가하려면 handleAiCommand() 안의
 *    if / else if 블록 하나를 복사해서 고치시면 됩니다.
 * =========================================================================== */

#ifndef NUBIDA_AI_H
#define NUBIDA_AI_H

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


#endif  /* NUBIDA_AI_H */
