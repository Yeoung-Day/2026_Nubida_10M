/* ══════════════════════════════════════════════════════════════════════════
 *  [기존 문법 13개]  handleLegacyCommand()
 *
 *  예전에 쓰던 명령 형식을 그대로 살려 둔 부분입니다.
 *  새로 만든 1~7 번호와 겹치지 않게, 블루투스로 "글자 그대로" 오는 명령을
 *  알아서 구분해서 처리합니다.
 *
 *    digitalWrite(핀,H);          → 그 핀을 HIGH 로
 *    digitalWrite(핀,L);          → 그 핀을 LOW 로
 *    int 이름 = 값;               → 변수 저장
 *    Serial.print(내용);          → 시리얼로 출력
 *    if(cho < 값) / if(pos < 값) / if(pos > 값)
 *    stop                         → 전부 정지
 *    tone(핀,주파수);             → 부저 울리기
 *    noTone(핀);                  → 부저 끄기
 *    BT.print(t값,e값);           → 블루투스로 문자열 전송
 *    Piano.mode / Trash.mode      → 모드 전환
 *
 *  ★ 이 함수는 여러 명령이 "공통으로 거쳐가는 길"이라서 안에 펼치지 않습니다.
 *    (부품을 움직이는 코드는 위 actionDispatch() 안에 전부 들어 있습니다)
 * ═══════════════════════════════════════════════════════════════════════════
 *  누비다머신 펌웨어  v25
 *  ─────────────────────────────────────────────────────────────────────────
 *  누비다플랫폼 (xn--od1bqqv8i85hml3aulb.kr) / 아두이노 나노 CH340
 *
 *  ★ 이 파일의 목표 ★
 *    1. 번호(1~7)와 부품을 분리한다.  →  2번에 서보를 넣어도 되고 모터를 넣어도 됨
 *    2. 각 번호 블록을 "그 블록만 복사"해도 단독으로 동작하게 만든다.
 *    3. 동작 코드는 전부 actionDispatch() 안에 "펼쳐서" 넣는다.
 *       (motorGo / ledOn / srvTo 같은 도우미 함수 호출 없음)
 *
 *  ★★ 남은 함수 4개 (외부에 있어야만 하는 것) ★★
 *    · setup()            — 전원이 켜질 때 1번 실행. 시리얼(9600) 준비.       [아두이노 필수]
 *    · loop()             — 계속 반복 실행. 블루투스 수신 확인.               [아두이노 필수]
 *    · actionDispatch()   — 1~7 번호 명령이 들어오면 동작 실행.
 *    · handleLegacyCommand() — 기존 13개 문법(digitalWrite 등) 처리.
 *    · processLine/drainBle/handleFrame/decodeFrame/hexVal
 *                         — 블루투스로 글자 받아서 명령으로 바꾸는 통신 담당.
 *
 *    ※ 이 함수들은 "여러 명령이 공통으로 거쳐가는 길"이라서 안에 펼칠 수 없습니다.
 *      대신 하나하나 주석을 달아 두었습니다.
 *      부품을 움직이는 코드(서보·모터·LED·부저·초음파)는
 *      전부 actionDispatch() 안에 있으니 그 부분만 보시면 됩니다.
 *
 *  ═════════════════════════════════════════════════════════════════════════
 *  ★★★ 부품별 복사용 코드 (이걸 그대로 가져다 쓰면 됩니다) ★★★
 *  ═════════════════════════════════════════════════════════════════════════
 *
 *  ┌─ [서보]  pin=핀번호  deg=각도(0~180)  ms=움직이는시간(ms)
 *  │
 *  │    { int pin = 9, deg = 90, ms = 400;
 *  │      int i = -1;
 *  │      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
 *  │      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
 *  │                   srv[i].attach(pin); delay(15); }
 *  │      int from = srvCur[i];
 *  │      if (from != deg) {
 *  │        int total = abs(deg - from);
 *  │        int steps = total / 3; if (steps < 1) steps = 1;
 *  │        int tick  = ms / steps; if (tick < 5) tick = 5;
 *  │        int dir   = (deg > from) ? 3 : -3, cur = from;
 *  │        for (int s = 1; s <= steps; s++) {
 *  │          cur += dir;
 *  │          if (dir > 0 && cur > deg) cur = deg;
 *  │          if (dir < 0 && cur < deg) cur = deg;
 *  │          srv[i].write(cur); srvCur[i] = cur; delay(tick);
 *  │        }
 *  │        srvCur[i] = deg; srv[i].write(deg);
 *  │      } }
 *  │
 *  │    ※ 한 줄만 바꾸면 다른 서보:  { int pin = 7, deg = 45, ms = 500; ...
 *  │    ※ 서보는 최대 4개까지 동시에 기억합니다 (srv[4]).
 *  │
 *  ├─ [모터]  pinA/pinB=두 개의 제어핀  speed=-100~100  secs=돌리는시간(초)
 *  │
 *  │    { int pinA = 5, pinB = 4, speed = 80; float secs = 1.2;
 *  │      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
 *  │      int mag = abs(speed); if (mag > 100) mag = 100;
 *  │      int pwm = map(mag, 0, 100, 0, 255);
 *  │      if (speed > 0)      { analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }
 *  │      else if (speed < 0) { digitalWrite(pinA, LOW); analogWrite(pinB, pwm); }
 *  │      else                { digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
 *  │      if (secs > 0) { delay((int)(secs * 1000));
 *  │                      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
 *  │    }
 *  │
 *  │    ※ speed 가 + 면 정회전, - 면 역회전, 0 이면 정지.
 *  │    ※ secs = 0 이면 계속 돌립니다(멈추려면 speed=0 블록을 따로).
 *  │
 *  ├─ [LED]  pin=핀번호  color=0xRRGGBB
 *  │
 *  │    { int pin = 3; unsigned long color = 0xFF0000;
 *  │      pinMode(pin, OUTPUT);
 *  │      uint8_t bright = (uint8_t)((color >> 16) & 0xFF);
 *  │      if (bright == 0) bright = 255;
 *  │      if (pin == 3 || pin == 5 || pin == 6 || pin == 9 ||
 *  │          pin == 10 || pin == 11) analogWrite(pin, bright);
 *  │      else digitalWrite(pin, HIGH);
 *  │    }
 *  │
 *  │    ※ color=0x000000 → 끄기 (digitalWrite(pin, LOW))
 *  │    ※ 밝기 조절(PWM) 가능 핀: 3, 5, 6, 9, 10, 11
 *  │
 *  ├─ [부저]  pin=핀번호  freq=주파수(Hz)  ms=울리는시간(ms)
 *  │
 *  │    { int pin = 6, freq = 1000, ms = 200;
 *  │      pinMode(pin, OUTPUT);
 *  │      tone(pin, freq, ms);
 *  │      delay(ms); noTone(pin);
 *  │    }
 *  │
 *  └─ [초음파]  trig=TRIG핀  echo=ECHO핀  →  거리(cm)를 dist 변수에 저장
 *
 *       { int trig = 10, echo = 11; float dist = 0;
 *         pinMode(trig, OUTPUT); pinMode(echo, INPUT);
 *         digitalWrite(trig, LOW);  delayMicroseconds(2);
 *         digitalWrite(trig, HIGH); delayMicroseconds(10);
 *         digitalWrite(trig, LOW);
 *         unsigned long us = pulseIn(echo, HIGH, 30000UL);
 *         if (us > 0) dist = us / 58.0; }
 *
 *       ※ dist 가 10.0 보다 작으면 뭔가 가까이 있음 (단위 cm)
 *
 *  ═════════════════════════════════════════════════════════════════════════
 *  ⚠️ 2번 · 3번 핀은 블루투스(BLE) 통신 전용입니다 (SoftwareSerial)
 *     → 2·3번 핀에는 LED·모터·부저 등 다른 부품을 연결하면 통신이 끊깁니다.
 *     ※ 기본 예제에서 LED 를 3번 핀에 쓰고 있는데, 실제 배선이 바뀌면
 *       그 숫자를 배선에 맞게 고쳐 주세요.
 *  ═════════════════════════════════════════════════════════════════════════
 */

/* ─────────────────────────────────────────────────────────────────────────
 *  [1] 블루투스(BLE) 통신
 *      SoftwareSerial BTSerial(RX, TX) →  RX=2번, TX=3번
 *      ⚠️ 이 두 핀은 다른 부품에 쓰면 안 됩니다.
 * ───────────────────────────────────────────────────────────────────────── */
#include <SoftwareSerial.h>
SoftwareSerial BTSerial(2, 3);   // BLE (RX=2, TX=3)

/* ─────────────────────────────────────────────────────────────────────────
 *  [2] 서보 기억장치  ★ 이 4줄은 "함수 밖"에 있어야만 합니다 ★
 *
 *      왜?  Servo 객체(srv[i])를 함수 안에서 만들면
 *           함수가 끝나는 순간 사라져서 서보에 힘이 안 들어갑니다.
 *           (각도가 90도로 돌아가 버림)
 *
 *      그래서 "서보 4개를 기억하는 상자"만 여기 위에 두고,
 *      실제 움직이는 코드는 아래 actionDispatch() 안에 전부 들어 있습니다.
 *
 *      srv[i]     : 서보 객체 (실제로 서보를 움직이는 것)
 *      srvPin[i]  : 그 서보가 꽂힌 핀 번호 (-1 = 아직 안 씀)
 *      srvCur[i]  : 그 서보의 현재 각도 (부드럽게 움직이려고 기억해 둠)
 *      srvCnt     : 지금까지 등록된 서보 개수
 * ───────────────────────────────────────────────────────────────────────── */
#include <Servo.h>
Servo srv[4];                    // ★ 서보 객체 — 함수 안에 못 넣음
int   srvPin[4] = { -1, -1, -1, -1 };   // 핀 번호 기억 (초기: 비어있음)
int   srvCur[4] = { 90, 90, 90, 90 };   // 현재 각도 기억 (초기: 90도)
int   srvCnt    = 0;                    // 등록된 서보 개수

/* ══════════════════════════════════════════════════════════════════════════
 *  ★★★ 여기서부터 "부품 움직이는 코드" ★★★
 *
 *  [사용법]
 *    · 핀 번호와 각도·시간만 바꾸시면 됩니다.
 *    · 각 블록은 모두 독립된 if 입니다 → 블록 하나만 잘라내도 단독으로 동작.
 *    · 도우미 함수 호출이 없습니다 (pinMode·analogWrite·delay 가 전부 안에 있음).
 *
 *  [번호 목록 — 지금 들어있는 내용]
 *    1NubidaAi → 서보 9번   90 → 160 → 90        (고개 끄덕)
 *    2NubidaAi → 서보 7번   인사 (45 → 135 → 45)
 *    3NubidaAi → 모터 5,4   1.2초 전진
 *    4NubidaAi → LED 3번    빨강 → 초록 깜빡 → 끄기
 *    5NubidaAi → 부저 6번   삐삐
 *    6NubidaAi → 서보+모터+LED+부저 동시
 *    7NubidaAi → 모터 + 초음파(10/11) + 부저
 *
 *  [숫자를 바꾸고 싶을 때]
 *    아래 각 블록 첫 줄의 숫자만 바꾸세요.
 *      서보 : { int pin = 9, deg = 90, ms = 400;
 *      모터 : { int pinA = 5, pinB = 4, speed = 80; float secs = 1.2;
 *      LED  : { int pin = 3; unsigned long color = 0xFF0000;
 *      부저 : { int pin = 6, freq = 1000, ms = 200;
 * ══════════════════════════════════════════════════════════════════════════ */

bool actionDispatch(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  1NubidaAi  ─  서보 9번을 90도 → 160도 → 90도 (고개 끄덕)
   *
   *   · 첫 줄 숫자만 바꾸면 다른 서보/다른 각도가 됩니다.
   *       int pin = 9    → 서보가 꽂힌 핀
   *       int deg = 90   → 목표 각도 (0~180)
   *       int ms  = 400  → 그 각도까지 움직이는 데 걸리는 시간
   *
   *   · 같은 서보를 다시 움직일 때는 현재 각도(srvCur)에서 이어서 움직입니다.
   *     (그래서 90→160→90 이 자연스럽게 이어집니다)
   *
   *   · 무섭게 튀지 않게 3도씩 나눠서 조금씩 움직입니다 (부드러운 동작).
   *
   *   [전체 명령어]  1NubidaAi = 1Nubida = 1  (세 가지 모두 같은 동작)
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("1NubidaAi") || cmd.equals("1Nubida") || cmd.equals("1")) {

    { int pin = 9, deg = 90, ms = 400;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 9, deg = 160, ms = 600;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 9, deg = 90, ms = 400;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    return true;
  }

  /* ══ 2NubidaAi ══  ← 서보(팔 7번) 90 → 160 → 60 → 160 → 60 → 90 */
  /* ══════════════════════════════════════════════════════════════════════
   *  2NubidaAi  ─  서보 7번으로 인사 (45 → 135 → 45)
   *
   *   ★ 여기에는 원래 "모터"가 들어 있었지만, 지금은 "서보"가 들어 있습니다.
   *     → 이렇게 번호와 부품은 상관없습니다. 원하는 부품 코드를 넣으면 됩니다.
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("2NubidaAi") || cmd.equals("2Nubida") || cmd.equals("2")) {

    { int pin = 7, deg = 90, ms = 300;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 7, deg = 160, ms = 500;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 7, deg = 60, ms = 500;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 7, deg = 160, ms = 500;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 7, deg = 60, ms = 500;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    { int pin = 7, deg = 90, ms = 300;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    return true;
  }

  /* ══ 3NubidaAi ══  ← DC모터(5,4번) 1.2초 앞으로 */
  /* ══════════════════════════════════════════════════════════════════════
   *  3NubidaAi  ─  모터 (5번=정, 4번=역) 80% 속도로 1.2초 전진 후 정지
   *
   *   · speed 가 + 이면 정회전, - 이면 역회전, 0 이면 정지.
   *   · secs 초 동안 돌리고 자동으로 멈춥니다 (secs = 0 이면 계속).
   *   · 100% 를 넘는 speed 는 100 으로 잘립니다 (모터 보호).
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("3NubidaAi") || cmd.equals("3Nubida") || cmd.equals("3")) {

    { int pinA = 5, pinB = 4, speed = 80; float secs = 1.2;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      if (speed > 0)      { analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }
      else if (speed < 0) { digitalWrite(pinA, LOW); analogWrite(pinB, pwm); }
      else                { digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
      Serial.print(F("[모터] ")); Serial.print(pinA); Serial.print(F(","));
      Serial.print(pinB); Serial.print(F(" 속도 ")); Serial.print(speed);
      Serial.println(F("%"));
      if (secs > 0) { delay((int)(secs * 1000));
                      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); } }

    return true;
  }

  /* ══ 4NubidaAi ══  ← LED(3번) 빨강 → 초록 깜빡 3회 → 끄기 */
  /* ══════════════════════════════════════════════════════════════════════
   *  4NubidaAi  ─  LED 3번 : 빨강 켜기 → 초록 깜빡 → 끄기
   *
   *   ⚠️ 3번 핀은 블루투스 TX 핀입니다!
   *      LED 를 다른 핀(예: 8번)에 꽂았다면 아래 숫자를 8 로 바꾸세요.
   *      (지금은 예제라서 3번으로 되어 있습니다)
   *
   *   색 지정 : 0xRRGGBB 형식
   *      0xFF0000 = 빨강      0x00FF00 = 초록      0x0000FF = 파랑
   *      0xFFFFFF = 흰색      0x000000 = 끄기
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("4NubidaAi") || cmd.equals("4Nubida") || cmd.equals("4")) {

    /* 빨강 켜기 */
    { int pin = 3; unsigned long color = 0xFF0000;
      pinMode(pin, OUTPUT);
      if (color != 0) {
        uint8_t bright = (uint8_t)((color >> 16) & 0xFF);
        if (bright == 0) bright = 255;
        if (pin == 3 || pin == 5 || pin == 6 || pin == 9 || pin == 10 || pin == 11)
          analogWrite(pin, bright);
        else
          digitalWrite(pin, HIGH);
      } }

    { int ms = 400; delay(ms); }

    /* 초록 깜빡 3회 */
    for (int n = 0; n < 3; n++) {
      { int pin = 3; unsigned long color = 0x00FF00;
        pinMode(pin, OUTPUT);
        if (color != 0) {
          uint8_t bright = (uint8_t)((color >> 16) & 0xFF);
          if (bright == 0) bright = 255;
          if (pin == 3 || pin == 5 || pin == 6 || pin == 9 || pin == 10 || pin == 11)
            analogWrite(pin, bright);
          else
            digitalWrite(pin, HIGH);
        } }
      { int ms = 150; delay(ms); }
      { int pin = 3; pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
      { int ms = 150; delay(ms); }
    }

    /* 끄기 */
    { int pin = 3; pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }

    return true;
  }

  /* ══ 5NubidaAi ══  ← 부저(6번) 삐삐 2회 */
  /* ══════════════════════════════════════════════════════════════════════
   *  5NubidaAi  ─  부저 6번 : 삐삐 소리
   *
   *   · freq = 소리 높이(Hz).  숫자가 클수록 높은 소리.
   *       저음 262(도) / 중음 523 / 고음 1046
   *   · ms = 소리를 내는 시간(밀리초). 200 = 0.2초
   *   · 소리가 끝나면 noTone() 으로 반드시 꺼 줍니다 (안 그러면 계속 울림).
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("5NubidaAi") || cmd.equals("5Nubida") || cmd.equals("5")) {

    { int pin = 6, freq = 880, ms = 150; pinMode(pin, OUTPUT); tone(pin, freq, ms); }
    { int ms = 100; delay(ms); }
    { int pin = 6, freq = 880, ms = 150; pinMode(pin, OUTPUT); tone(pin, freq, ms); }

    return true;
  }

  /* ══ 6NubidaAi ══  ← 전부 (서보+모터+LED+부저) */
  /* ══════════════════════════════════════════════════════════════════════
   *  6NubidaAi  ─  융합 동작 : 서보 + LED + 부저 + 모터를 한 번에
   *
   *   · 한 명령 안에 여러 부품을 순서대로 넣은 예제입니다.
   *   · 서보·LED·부저는 먼저 준비해 두고, 마지막에 모터로 굴러갑니다.
   *   · 이렇게 한 블록 안에 부품을 몇 개든 넣을 수 있습니다.
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("6NubidaAi") || cmd.equals("6Nubida") || cmd.equals("6")) {

    /* 서보 9번 → 160도 */
    { int pin = 9, deg = 160, ms = 600;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    /* 모터 계속 */
    { int pinA = 5, pinB = 4, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }

    /* LED 파랑 */
    { int pin = 3; unsigned long color = 0x0000FF;
      pinMode(pin, OUTPUT);
      if (color != 0) {
        uint8_t bright = (uint8_t)((color >> 16) & 0xFF);
        if (bright == 0) bright = 255;
        if (pin == 3 || pin == 5 || pin == 6 || pin == 9 || pin == 10 || pin == 11)
          analogWrite(pin, bright);
        else
          digitalWrite(pin, HIGH);
      } }

    /* 부저 */
    { int pin = 6, freq = 1046, ms = 600; pinMode(pin, OUTPUT); tone(pin, freq, ms); }

    /* 기다렸다가 정리 */
    { int ms = 600; delay(ms); }

    /* 서보 9번 → 90도 */
    { int pin = 9, deg = 90, ms = 400;
      int i = -1;
      for (int k = 0; k < 4; k++) if (srvPin[k] == pin) { i = k; break; }
      if (i < 0) { i = srvCnt++; srvPin[i] = pin; srvCur[i] = 90;
                   srv[i].attach(pin); delay(15); }
      int from = srvCur[i];
      if (from != deg) {
        int total = abs(deg - from);
        int steps = total / 3; if (steps < 1) steps = 1;
        int tick  = ms / steps; if (tick < 5) tick = 5;
        int dir   = (deg > from) ? 3 : -3, cur = from;
        for (int s = 1; s <= steps; s++) {
          cur += dir;
          if (dir > 0 && cur > deg) cur = deg;
          if (dir < 0 && cur < deg) cur = deg;
          srv[i].write(cur); srvCur[i] = cur; delay(tick);
        }
        srvCur[i] = deg; srv[i].write(deg);
      } }

    /* 모터 정지 */
    { int pinA = 5, pinB = 4;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }

    /* LED 끄기 */
    { int pin = 3; pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }

    return true;
  }

  /* ══ 7NubidaAi ══  ← 모터 + 초음파 + 부저 */
  /* ══════════════════════════════════════════════════════════════════════
   *  7NubidaAi  ─  모터 + 초음파(TRIG 10 / ECHO 11) + 부저
   *
   *   · 초음파로 앞의 거리를 재서(pulseIn), 가까우면 부저로 경고합니다.
   *   · 거리 계산 : us / 58.0  →  단위 cm
   *       58 은 소리가 1cm 왕복하는 데 걸리는 마이크로초입니다.
   *   · pulseIn(echo, HIGH, 30000) 의 30000 은 최대 대기시간(30ms)
   *       → 너무 멀면 0 이 나오고, 그때는 거리 계산을 건너뜁니다.
   * ══════════════════════════════════════════════════════════════════════ */
  if (cmd.equals("7NubidaAi") || cmd.equals("7Nubida") || cmd.equals("7")) {

    /* 모터 계속 */
    { int pinA = 5, pinB = 4, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }

    /* 초음파 거리 재기 */
    float cm = 0;
    { int trigPin = 10, echoPin = 11;
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      cm = dur / 58.0;
      Serial.print(F("[초음파] ")); Serial.print((int)cm); Serial.println(F("cm")); }

    /* 20cm 이내면 정지 + 부저 */
    if (cm < 20) {
      { int pinA = 5, pinB = 4;
        pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
        digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
      { int pin = 6, freq = 440, ms = 400; pinMode(pin, OUTPUT); tone(pin, freq, ms); }
    }

    /* 모터 정지 */
    { int pinA = 5, pinB = 4;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }

    return true;
  }

  /* ══════════════════════════════════════════════════════════════════
   *  ★ 여기에 새 번호를 추가하세요 (독립된 if, return true 필수)
   *
   *    if (cmd.equals("8NubidaAi") || cmd.equals("8Nubida") || cmd.equals("8")) {
   *
   *      // 서보
   *      { int pin = 5, deg = 150, ms = 500;  ... }
   *
   *      // 모터
   *      { int pinA = 6, pinB = 8, speed = 90; float secs = 1.5; ... }
   *
   *      return true;
   *    }
   * ══════════════════════════════════════════════════════════════════ */

  return false;
}


/* ══════════════════════════════════════════════════════════════════════════
 *  기존문법 (AI 가 만든 코드) — digitalWrite / tone / 초음파 등
 *  ★ 여기도 함수 호출 없이 전부 펼쳐져 있습니다.
 * ══════════════════════════════════════════════════════════════════════════ */

bool handleLegacyCommand(String cmd) {

  /* ══════════════════════════════════════════════════════════════════════
   *  【1단계】 값 꺼내기
   * ══════════════════════════════════════════════════════════════════════ */

  int HIGH_a = cmd.indexOf("digitalWrite(");
  int HIGH_b = cmd.indexOf(",H);");
  String HIGHResult = (HIGH_a >= 0 && HIGH_b > HIGH_a)
                      ? cmd.substring(HIGH_a + 13, HIGH_b) : "";

  int LOW_a = cmd.indexOf("digitalWrite(");
  int LOW_b = cmd.indexOf(",L);");
  String LOWResult = (LOW_a >= 0 && LOW_b > LOW_a)
                     ? cmd.substring(LOW_a + 13, LOW_b) : "";

  int INT_a = cmd.indexOf("int ");
  int INT_b = cmd.indexOf(" = ");
  int INT_c = cmd.indexOf(";");
  String INTResult1 = (INT_a >= 0 && INT_b > INT_a)
                      ? cmd.substring(INT_a + 4, INT_b) : "";
  String INTResult2 = (INT_b > 0 && INT_c > INT_b)
                      ? cmd.substring(INT_b + 3, INT_c) : "";

  int SR_a = cmd.indexOf("Serial.print(");
  int SR_b = cmd.indexOf(");");
  String SRResult = (SR_a >= 0 && SR_b > SR_a)
                    ? cmd.substring(SR_a + 13, SR_b) : "";

  int TN_a = cmd.indexOf("tone(");
  int TN_c = cmd.indexOf(",");
  int TN_b = cmd.indexOf(");");
  String TNResult1 = (TN_a >= 0 && TN_c > TN_a)
                     ? cmd.substring(TN_a + 5, TN_c) : "";
  String TNResult2 = (TN_c > 0 && TN_b > TN_c)
                     ? cmd.substring(TN_c + 1, TN_b) : "";

  int NT_a = cmd.indexOf("noTone(");
  int NT_b = cmd.indexOf(");");
  String NTResult = (NT_a >= 0 && NT_b > NT_a)
                    ? cmd.substring(NT_a + 7, NT_b) : "";

  int CHO_a = cmd.indexOf("if(cho <");
  String CHOResult = "";
  if (CHO_a >= 0) {
    String t = cmd.substring(CHO_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) CHOResult = t.substring(0, e);
  }

  int POSL_a = cmd.indexOf("if(pos <");
  String POSLResult = "";
  if (POSL_a >= 0) {
    String t = cmd.substring(POSL_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSLResult = t.substring(0, e);
  }

  int POSG_a = cmd.indexOf("if(pos >");
  String POSGResult = "";
  if (POSG_a >= 0) {
    String t = cmd.substring(POSG_a + 8);
    t.trim();
    int e = t.indexOf(")");
    if (e > 0) POSGResult = t.substring(0, e);
  }

  int BP_a = cmd.indexOf("BT.print(t");
  int BP_c = cmd.indexOf(",e");
  int BP_b = cmd.indexOf(");");
  String BPResult1 = (BP_a >= 0 && BP_c > BP_a)
                     ? cmd.substring(BP_a + 10, BP_c) : "";
  String BPResult2 = (BP_c > 0 && BP_b > BP_c)
                     ? cmd.substring(BP_c + 2, BP_b) : "";


  /* ══════════════════════════════════════════════════════════════════════
   *  【2단계】 실행 — 전부 펼쳐져 있습니다 (독립된 if)
   * ══════════════════════════════════════════════════════════════════════ */

  /* ── digitalWrite(13,H); → 13번 핀 켜기 ── */
  if (cmd.equals("digitalWrite(" + HIGHResult + ",H);")) {
    { int pin = HIGHResult.toInt();
      pinMode(pin, OUTPUT); digitalWrite(pin, HIGH); }
    { int ms = 100; delay(ms); }
    return true;
  }

  /* ── digitalWrite(13,L); → 13번 핀 끄기 ── */
  if (cmd.equals("digitalWrite(" + LOWResult + ",L);")) {
    { int pin = LOWResult.toInt();
      pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
    { int ms = 100; delay(ms); }
    return true;
  }

  /* ── int lamp = 13; ── */
  if (cmd.equals("int " + INTResult1 + " = " + INTResult2 + ";")) {
    { BTSerial.println(INTResult1 + "의 변수명은 " + INTResult2 + "번의 핀을 사용합니다."); }
    { int ms = 100; delay(ms); }
    return true;
  }

  /* ── Serial.print(13); → 13번 핀 읽어서 보내기 ── */
  if (cmd.equals("Serial.print(" + SRResult + ");")) {
    { int pin = SRResult.toInt();
      pinMode(pin, INPUT);
      BTSerial.println(digitalRead(pin)); }
    { int ms = 100; delay(ms); }
    return true;
  }

  /* ── if(cho < 20) → 초음파 20cm 이내면 부저 ── */
  if (cmd.equals("if(cho < " + CHOResult + ")")) {
    { int limit = CHOResult.toInt();
      int trigPin = 10, echoPin = 11;
      pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
      digitalWrite(trigPin, LOW);  delayMicroseconds(2);
      digitalWrite(trigPin, HIGH); delayMicroseconds(10);
      digitalWrite(trigPin, LOW);
      unsigned long dur = pulseIn(echoPin, HIGH, 30000);
      float cm = dur / 58.0;
      if (cm < limit) {
        { int bp = 7, bf = 262, bm = 1000;
          pinMode(bp, OUTPUT); tone(bp, bf, bm); }
      } else {
        { int bp = 7; pinMode(bp, OUTPUT); noTone(bp); }
      } }
    { int ms = 1000; delay(ms); }
    return true;
  }

  /* ── if(pos < 90) → 모터 앞으로 ── */
  if (cmd.equals("if(pos < " + POSLResult + ")")) {
    { int pinA = 4, pinB = 5, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      analogWrite(pinA, pwm); digitalWrite(pinB, LOW); }
    return true;
  }

  /* ── if(pos > 90) → 모터 뒤로 ── */
  if (cmd.equals("if(pos > " + POSGResult + ")")) {
    { int pinA = 4, pinB = 5, speed = 70;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      int mag = abs(speed); if (mag > 100) mag = 100;
      int pwm = map(mag, 0, 100, 0, 255);
      digitalWrite(pinA, LOW); analogWrite(pinB, pwm); }
    return true;
  }

  /* ── stop → 모터 정지 ── */
  if (cmd.equals("stop")) {
    { int pinA = 4, pinB = 5;
      pinMode(pinA, OUTPUT); pinMode(pinB, OUTPUT);
      digitalWrite(pinA, LOW); digitalWrite(pinB, LOW); }
    return true;
  }

  /* ── tone(7,262); → 부저 ── */
  if (cmd.equals("tone(" + TNResult1 + "," + TNResult2 + ");")) {
    { int pin = TNResult1.toInt(), freq = TNResult2.toInt(), ms = 1000;
      pinMode(pin, OUTPUT); tone(pin, freq, ms); }
    return true;
  }

  /* ── noTone(7); → 부저 끄기 ── */
  if (cmd.equals("noTone(" + NTResult + ");")) {
    { int pin = NTResult.toInt();
      pinMode(pin, OUTPUT); noTone(pin); }
    return true;
  }

  /* ── BT.print(t10,e11); → 초음파 거리 보내기 ── */
  if (cmd.equals("BT.print(t" + BPResult1 + ",e" + BPResult2 + ");")) {
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
    return true;
  }

  /* ── Piano.mode → 초음파 피아노 ── */
  if (cmd.equals("Piano.mode")) {
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
      { int bp = 7;
        pinMode(bp, OUTPUT);
        if (f) { tone(bp, f, 300); } else { noTone(bp); } } }
    return true;
  }

  /* ── Trash.mode → 초음파 거리 출력 ── */
  if (cmd.equals("Trash.mode")) {
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
    return true;
  }

  return false;
}


/* ══════════════════════════════════════════════════════════════════════════
 *  프레임 처리 (난독화 복호화)
 * ══════════════════════════════════════════════════════════════════════════ */

/* ─────────────────────────────────────────────────────────────────────────
 *  [3] 블루투스 수신 버퍼
 *      글자가 한 번에 오지 않고 조각조각 오기 때문에, 잠깐 모아 두었다가
 *      "잠깐(FRAME_GAP_MS) 동안 새 글자가 안 오면" 한 줄이 끝난 것으로 봅니다.
 *
 *      rxBuf    : 받은 글자를 담아 두는 그릇 (최대 191자)
 *      rxLen    : 지금까지 담긴 글자 수
 *      lastRxAt : 마지막으로 글자를 받은 시각 (millis 단위)
 * ───────────────────────────────────────────────────────────────────────── */
char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;
#define FRAME_GAP_MS 30

/* ─────────────────────────────────────────────────────────────────────────
 *  [4] hexVal()  —  16진수 글자 하나('0'~'9','A'~'F')를 숫자로 바꿉니다.
 *        'A' → 10,  'F' → 15.   잘못된 글자면 -1.
 * ───────────────────────────────────────────────────────────────────────── */
int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* ─────────────────────────────────────────────────────────────────────────
 *  [5] decodeFrame()  —  웹에서 "x..." 형태로 보낸 암호문을 원래 명령으로 풉니다.
 *
 *      · 첫 두 글자는 열쇠(seed)이고, 그 뒤부터가 실제 내용입니다.
 *      · 글자 하나하나를 열쇠와 XOR 해서 원래 글자로 되돌립니다.
 *      · 풀어낸 결과가 진짜 명령 (예: 3NubidaAi) 이 됩니다.
 *
 *      ★ 웹페이지와 짝이 맞는 부분이라 고치지 마세요.
 * ───────────────────────────────────────────────────────────────────────── */
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

/* ─────────────────────────────────────────────────────────────────────────
 *  [6] processLine()  —  한 줄(명령 하나)을 받아서 처리하는 곳.
 *
 *      순서:
 *        ① 앞뒤 공백 제거, 빈 줄이면 무시
 *        ② 'x' 로 시작하면 → 암호문이므로 decodeFrame() 으로 풀기
 *        ③ '+' 로 시작하면 → 블루투스 연결 알림이므로 무시
 *        ④ actionDispatch() 에게 물어봄  → 1~7 번호 명령이면 실행
 *        ⑤ handleLegacyCommand() 에게 물어봄 → 기존 문법이면 실행
 *        ⑥ 둘 다 아니면 "[무시] 알 수 없는 명령" 출력
 * ───────────────────────────────────────────────────────────────────────── */
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

  if (actionDispatch(cmd))      return;
  if (handleLegacyCommand(cmd)) return;

  Serial.print(F("[무시] 알 수 없는 명령: "));
  Serial.println(cmd);
}

/* ─────────────────────────────────────────────────────────────────────────
 *  [7] drainBle()  —  블루투스에 도착한 글자를 전부 꺼내 버퍼에 쌓습니다.
 *      loop() 에서 쉬지 않고 계속 호출됩니다.
 * ───────────────────────────────────────────────────────────────────────── */
void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    lastRxAt = millis();
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 *  [8] handleFrame()  —  버퍼에 쌓인 글자를 "줄 단위"로 잘라서 처리합니다.
 *      줄바꿈(
) 또는 캐리지리턴()을 기준으로 자릅니다.
 *      잘린 한 줄은 processLine() 으로 넘깁니다.
 * ───────────────────────────────────────────────────────────────────────── */
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
 *  [9] setup()  —  전원이 켜지면 딱 1번 실행 (아두이노 필수 함수)
 *
 *      · 시리얼(9600) 과 블루투스(9600) 를 준비합니다.
 *      · 준비되었는지 화면에 목록을 출력합니다.
 *      · 이 함수 안에는 부품을 움직이는 코드를 넣지 마세요.
 *        (부품 동작은 위 actionDispatch() 안에 있습니다)
 * ══════════════════════════════════════════════════════════════════════════ */

void setup() {
  Serial.begin(9600);
  BTSerial.begin(9600);

  delay(200);
  Serial.println(F(""));
  Serial.println(F("=========================================="));
  Serial.println(F("  누비다머신 v24 (한 블록 안에 전부)"));
  Serial.print(F("  빌드: ")); Serial.print(F(__DATE__));
  Serial.print(F(" "));        Serial.println(F(__TIME__));
  Serial.println(F("=========================================="));
  Serial.println(F(""));
  Serial.println(F("[동작] 7개 등록됨"));
  Serial.println(F("  1NubidaAi → 서보 9번  90→160→90"));
  Serial.println(F("  2NubidaAi → 서보 7번  인사"));
  Serial.println(F("  3NubidaAi → 모터 5,4  1.2초"));
  Serial.println(F("  4NubidaAi → LED 3번   빨강→초록깜빡→끔"));
  Serial.println(F("  5NubidaAi → 부저 6번  삐삐"));
  Serial.println(F("  6NubidaAi → 전부 동시"));
  Serial.println(F("  7NubidaAi → 모터+초음파+부저"));
  Serial.println(F(""));
  Serial.println(F("[기존문법] 13개"));
  Serial.println(F("준비 완료"));
  Serial.println(F(""));
}

/* ══════════════════════════════════════════════════════════════════════════
 *  [10] loop()  —  전원이 꺼질 때까지 계속 반복 (아두이노 필수 함수)
 *
 *       · 블루투스에 글자가 왔는지 확인(drainBle)
 *       · 마지막 글자에서 잠깐(FRAME_GAP_MS) 지나면 → 한 줄이 끝난 것으로 보고 처리
 * ───────────────────────────────────────────────────────────────────────── */
void loop() {
  drainBle();
  if (rxLen > 0 && (millis() - lastRxAt) > FRAME_GAP_MS) {
    handleFrame();
  }
}
