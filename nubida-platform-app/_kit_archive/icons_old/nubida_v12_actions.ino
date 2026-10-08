#include "Servo.h"

#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3); //(RX, TX)

/* ═══════════════════════════════════════════════════════════════════════════
 *  누비다머신 통합 펌웨어 (v12 · 동작 이름표 방식)
 * ───────────────────────────────────────────────────────────────────────────
 *  [v12 에서 쉬워진 점]
 *    ★ 동작을 추가하려면 아래 [동작표] ACTIONS[] 에 **한 줄만** 추가하면 된다.
 *      (v11 은 서보객체/attach/aiWhich/각도/로그 5곳을 고쳐야 했다)
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★★ 동작 추가하는 법 (딱 한 줄)
 *  ─────────────────────────────────────────────────────────────────────────
 *
 *    // 머리 흔들기(9번) 를 "고개젓기" 로 추가하고 싶다면:
 *    { "4NubidaAi", 9, ACT_SHAKE, 60, 120, 3, "고개젓기" },
 *       ↑해시명     ↑핀  ↑동작종류  ↑a  ↑b  ↑횟수  ↑설명
 *
 *    → ACTIONS[] 에 이 한 줄만 넣으면 끝.
 *      서보 객체도, aiWhich 도, 로그도 손댈 필요 없다.
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 동작 종류 3가지 (필요하면 여기에 새 종류를 추가)
 *      ACT_FOLD   : a° 로 갔다가 b° 로 숙임        (삐졌어)
 *      ACT_SHAKE  : a° ↔ b° 를 n회 왕복            (도리도리)
 *      ACT_WAVE   : a° → b° → 중간 → 원위치 n회    (안녕)
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 현재 등록된 동작
 *      1NubidaAi → 9번 · 삐졌어   (90 → 160 숙임)
 *      2NubidaAi → 9번 · 도리도리 (60 ↔ 120, 3회)
 *      3NubidaAi → 7번 · 안녕     (90 → 160 → 60, 3회)
 *
 *      ※ 1번과 2번이 같은 9번 핀을 쓴다 → 충돌 방지를 위해
 *        동작은 **한 번에 하나씩 순서대로** 실행된다(큐 방식).
 *
 *  ─────────────────────────────────────────────────────────────────────────
 *  ★ 하위 호환: 원본의 모든 문장 그대로 지원
 *    Piano.mode / Trash.mode / digitalWrite / tone / noTone /
 *    if(cho < N) / if(pos < N) / if(pos > N) / pos.write(mN,N) /
 *    BT.print(tN,eN) / int a = b; / Serial.print(N); / stop
 * ═══════════════════════════════════════════════════════════════════════════ */

#define NB_KEY       0x2F    // nubida-bt.js 의 KEY 와 동일해야 함
#define STEP_DEG     3       // 동작 스텝 각도 (클수록 빠름)
#define STEP_MS      25      // 동작 스텝 간격(ms)
#define FRAME_GAP_MS 30      // 이 시간 무수신 = 한 프레임 완료
#define MAX_RX       256     // 수신 버퍼 크기

/* ═══════════════════════════════════════════════════════════════════════════
 *  [1] 서보 객체
 * ═══════════════════════════════════════════════════════════════════════════ */
Servo servo9;      // 9번 — 삐졌어 · 도리도리
Servo servo7;      // 7번 — 안녕
Servo myServo;     // 기존 문장 전용 (Piano.mode / Trash.mode / pos.write 등)

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

/* ═══════════════════════════════════════════════════════════════════════════
 *  [3] ★★ 동작표 — 여기 한 줄 추가하면 새 동작이 생긴다
 *      필드: { 명령어, 서보핀, 동작종류, a각도, b각도, 반복, 설명 }
 * ═══════════════════════════════════════════════════════════════════════════ */
#define ACT_FOLD   0    // a 로 갔다가 b 로 숙임 (삐졌어)
#define ACT_SHAKE  1    // a ↔ b 왕복 (도리도리)
#define ACT_WAVE   2    // a → b → 중간 n회 (안녕)

struct ActionDef {
  const char* token;    // BLE 명령 (해시 복호화 결과)
  uint8_t     pin;      // 서보 신호 핀
  uint8_t     kind;     // ACT_FOLD / ACT_SHAKE / ACT_WAVE
  uint8_t     a;        // 각도 A
  uint8_t     b;        // 각도 B
  uint8_t     repeat;   // 반복 횟수
  const char* label;    // 시리얼 로그용 이름
};

const ActionDef ACTIONS[] = {
  { "1NubidaAi", 9, ACT_FOLD,   90, 160, 1, "삐졌어"   },
  { "2NubidaAi", 9, ACT_SHAKE,  60, 120, 3, "도리도리" },
  { "3NubidaAi", 7, ACT_WAVE,   90, 160, 3, "안녕"     },
  /* ▼▼▼ 새 동작은 여기에 한 줄만 추가 ▼▼▼
  { "4NubidaAi", 5, ACT_WAVE,   90, 160, 3, "박수"     },
  */
};
const uint8_t ACTION_COUNT = sizeof(ACTIONS) / sizeof(ACTIONS[0]);

/* ═══════════════════════════════════════════════════════════════════════════
 *  [4] 동작 실행기 — 동작종류별로 각도를 계산해 스텝마다 한 칸씩 움직인다
 *      (블로킹 delay 금지: loop() 가 계속 돌아 수신을 못 막는다)
 * ═══════════════════════════════════════════════════════════════════════════ */

/* 진행 상태 */
long          actIdx   = -1;    // 실행 중인 ACTIONS 인덱스 (-1 = 없음)
int           actFrom  = 0;     // 현재 출발 각도
int           actTo    = 0;     // 현재 목표 각도
int           actCur   = 90;    // 현재 각도
int           actRep   = 0;     // 남은 반복
int           actStep  = 0;     // 현재 동작 내 단계
unsigned long actLast  = 0;

/* 한 번에 하나만: 대기 큐 (최대 4개) */
int           qIdx[4];
uint8_t       qHead = 0;
uint8_t       qTail = 0;

bool qEmpty() { return qHead == qTail; }
void qPush(int v) {
  uint8_t n = (uint8_t)((qTail + 1) % 4);
  if (n == qHead) return;          // 가득 참 → 버림
  qIdx[qTail] = v;
  qTail = n;
}
int qPop() {
  if (qEmpty()) return -1;
  int v = qIdx[qHead];
  qHead = (uint8_t)((qHead + 1) % 4);
  return v;
}

/* 실행할 서보 얻기 (핀 번호로) */
Servo* servoForPin(uint8_t pin) {
  if (pin == 9) return &servo9;
  if (pin == 7) return &servo7;
  return &myServo;
}

/* 전방 선언 — stepAction() 이 먼저 정의되어도 finishAction() 을 쓸 수 있게 */
void finishAction();

/* 동작 시작 — 동작표에서 상태를 초기화한다 */
void startAction(int idx) {
  const ActionDef& d = ACTIONS[idx];
  actIdx  = idx;
  actCur  = d.a;
  actFrom = d.a;
  actTo   = d.b;
  actRep  = d.repeat;
  actStep = 0;
  actLast = millis();

  Servo* sv = servoForPin(d.pin);
  sv->attach(d.pin);
  sv->write(actCur);

  Serial.print(F("[동작] "));
  Serial.print(d.label);
  Serial.print(F(" — "));
  Serial.print(d.pin);
  Serial.println(F("번 시작"));
}

/* 동작 1스텝 (loop 에서 매번 호출) */
void stepAction() {
  /* 실행 중인 게 없으면 큐에서 하나 꺼내 시작 */
  if (actIdx < 0) {
    int nx = qPop();
    if (nx >= 0) startAction(nx);
    return;
  }
  if (millis() - actLast < (unsigned long)STEP_MS) return;
  actLast = millis();

  const ActionDef& d = ACTIONS[actIdx];
  Servo* sv = servoForPin(d.pin);

  /* 목표까지 한 칸 이동 */
  if (actCur < actTo)      actCur += STEP_DEG;
  else if (actCur > actTo) actCur -= STEP_DEG;
  if (actCur < 0)   actCur = 0;
  if (actCur > 180) actCur = 180;
  sv->write(actCur);

  if (actCur != actTo) return;      // 아직 이동 중

  /* ── 목표 도착 → 다음 단계 결정 ───────────────────────── */
  if (d.kind == ACT_FOLD) {
    /* a → b 로 한 번 숙이고 끝. 잠깐 유지 후 전원 해제 */
    if (actStep == 0) {
      actStep = 1;
      actTo   = d.a;                // 원래 각도로 복귀
      return;
    }
    finishAction();

  } else if (d.kind == ACT_SHAKE) {
    /* a ↔ b 왕복 n회 */
    actRep--;
    if (actRep <= 0) { finishAction(); return; }
    actTo = (actTo == d.a) ? d.b : d.a;
    actStep++;

  } else { /* ACT_WAVE */
    /* a → b → 중간 → (반복) → b → a */
    if (actStep == 0) {             // a → b 도착
      actStep = 1;
      actTo = (d.a + d.b) / 2;      // 중간으로
      return;
    }
    if (actStep == 1) {             // 중간 도착
      actStep = 2;
      actTo = d.b;                  // 다시 위로
      return;
    }
    /* actStep == 2 : 한 번의 인사 완료 */
    actRep--;
    if (actRep <= 0) {
      actStep = 3;
      actTo = d.a;                  // 원위치
      return;
    }
    actStep = 1;
    actTo = (d.a + d.b) / 2;
  }
}

/* 동작 종료 — 서보 전원 해제 (떨림/소음 방지) */
void finishAction() {
  if (actIdx < 0) return;
  const ActionDef& d = ACTIONS[actIdx];
  Servo* sv = servoForPin(d.pin);
  sv->write(actCur);
  delay(80);
  sv->detach();
  Serial.print(F("[완료] "));
  Serial.println(d.label);
  actIdx = -1;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [5] 유틸
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
 *  [6] ★★ 동작 판정 — 동작표를 순회한다
 *      완전일치 → 포함 → 접두어(마지막 글자 유실) → 앞자리 보정
 *      반환값 true = 동작 명령으로 처리됨
 * ═══════════════════════════════════════════════════════════════════════════ */
bool actionDispatch(String cmd) {
  for (uint8_t i = 0; i < ACTION_COUNT; i++) {
    const char* tok = ACTIONS[i].token;      // 예: "1NubidaAi"
    String full(tok);
    String pre = full.substring(0, full.length() - 2);  // "1Nubida"

    bool hit = false;
    if (cmd.equals(full))            hit = true;   // ① 완전 일치
    else if (cmd.indexOf(pre) >= 0)  hit = true;   // ②③ 부분 일치(유실 내성)
    else if (cmd.length() == 1 &&
             cmd.charAt(0) == tok[0]) hit = true;  // ④ 앞자리만 ("1")

    if (hit) {
      if (actIdx < 0) startAction(i);   // 놀고 있으면 바로
      else            qPush(i);         // 동작 중이면 순서대로 대기
      return true;
    }
  }
  return false;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  [7] 기존 문법 파서 — 원본 nubida_machine_receiver.ino 그대로
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
 *  [8] 한 줄 처리 — ① 복호화 → ② BLE 이벤트 → ③ 동작 → ④ 기존문법
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

  /* ③ 동작 명령 판정 */
  if (actionDispatch(cmd)) {
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
 *  [9] 수신
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

  Serial.println(F("=== 누비다머신 통합 (동작 이름표 v12) ==="));
  Serial.print(F("[빌드] ")); Serial.print(F(__DATE__)); Serial.print(F(" ")); Serial.println(F(__TIME__));
  Serial.print(F("[동작] 총 ")); Serial.print(ACTION_COUNT); Serial.println(F("개 등록됨"));
  for (uint8_t i = 0; i < ACTION_COUNT; i++) {
    Serial.print(F("  "));
    Serial.print(ACTIONS[i].token);
    Serial.print(F(" → "));
    Serial.print(ACTIONS[i].pin);
    Serial.print(F("번 · "));
    Serial.println(ACTIONS[i].label);
  }
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

  stepAction();      // ④ 동작 1스텝 (논블로킹)
}
