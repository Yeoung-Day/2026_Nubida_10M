/* ===========================================================================
 *  nubida_bt.h  -  블루투스 연결 + 수신
 *  ---------------------------------------------------------------------------
 *  휴대폰(웹앱)과 블루투스로 연결하고, 글자가 도착하면 한 줄씩 잘라서
 *  메인의 runCommand() 로 넘겨줍니다.
 *
 *  ★ 이 파일은 건드리실 필요가 없습니다.
 *
 *  사용법 (메인 .ino 안에서):
 *      nubidaBtBegin();                  <- setup() 에서 한 번
 *      nubidaBtUpdate();                 <- loop() 에서 매번
 *
 *  ⚠️ 이 파일은 decodeFrame() 과 runCommand() 를 사용하므로
 *     반드시 그 둘보다 "뒤에" include 해야 합니다.
 * =========================================================================== */

#ifndef NUBIDA_BT_H
#define NUBIDA_BT_H

/* ⚠️ BTSerial(블루투스 연결 객체)은 메인 .ino 에서 만듭니다.
 *    (AI 명령 파일도 BTSerial 을 쓰기 때문입니다)
 *    그래서 이 파일에는 선언하지 않습니다. */

/* 한 줄이 끝났다고 보는 기준 : 마지막 글자 뒤 이만큼(ms) 조용하면 완성
 *   ⚠️ 2026-09-20 수정 : 60 -> 600
 *      블루투스는 한 줄(21자)을 20자 + 2자 처럼 "조각"으로 나눠 보낼 때가 있습니다.
 *      조각 사이 간격이 60ms 를 넘으면 줄이 반토막 나서 마지막 글자가 사라졌습니다.
 *      -> 안전장치 시간을 넉넉히 늘립니다. (아래 nubidaBtUpdate 참고) */
#define FRAME_GAP_MS 600

/* 받은 글자를 모아두는 곳 */
char          rxBuf[192];
int           rxLen    = 0;
unsigned long lastRxAt = 0;

/* 블루투스 시작 - setup() 에서 부릅니다 */
inline void nubidaBtBegin() {
  BTSerial.begin(9600);
}

/* 도착한 글자를 전부 버퍼에 담기 - loop() 에서 매번 부릅니다 */
inline void drainBle() {
  while (BTSerial.available()) {
    char c = (char)BTSerial.read();
    if (rxLen < (int)sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    lastRxAt = millis();
  }
}

/* ── 2026-09-20 추가 : 조각이 다 모였는지 미리 확인하는 도우미 ──────────────
 *   블루투스는 한 줄을 조각조각 보내므로, "다 모였는지"를 시간이 아니라
 *   내용(길이/줄바꿈)으로 판단하면 훨씬 정확합니다. */

/* 버퍼 안에 줄바꿈(\n 또는 \r)이 있으면 -> 한 줄이 확실히 끝난 것 */
inline bool bufHasNewline() {
  for (int i = 0; i < rxLen; i++) {
    if (rxBuf[i] == '\n' || rxBuf[i] == '\r') return true;
  }
  return false;
}

/* 'x' 로 시작하는 암호문은 길이가 정해져 있습니다 ('x' + 20글자 = 21글자).
 *   그만큼 모였으면 -> 더 기다릴 필요 없이 바로 처리합니다.
 *   (기다리다가 반토막 나는 것을 막아줍니다) */
inline bool bufHasFullFrame() {
  for (int i = 0; i < rxLen; i++) {
    if (rxBuf[i] == 'x' && (rxLen - i) >= 21) return true;
  }
  return false;
}

/* 모아둔 글자를 한 줄씩 잘라서 실행 - loop() 에서 부릅니다 */
inline void handleFrame() {
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

        /* -- 여기가 핵심 --
         *    'x' 로 시작하면 암호문 -> 풀어서 원래 명령으로 바꿉니다
         *    웹앱은 명령을 그냥 보내지 않고 암호처럼 바꿔 보냅니다. */
        if (one.charAt(0) == 'x') {
          String plain = decodeFrame(one);
          Serial.print(F("[복호화] -> ["));
          Serial.print(plain);
          Serial.println(F("]"));
          if (plain.length() == 0) {
            Serial.println(F("[무시] 복호화 실패 (조각일 수 있음)"));
            continue;
          }
          one = plain;                      /* 이제 원래 명령이 됨 */
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

/* loop() 에서 부르는 한 줄짜리 통합 함수
 *   ⚠️ 2026-09-20 수정 : 시간(60ms)만 보고 자르던 것을 -> 내용을 보고 자르게 변경
 *     ① 줄바꿈이 왔다        -> 명령이 끝난 게 확실하니 바로 처리
 *     ② 'x' 21자가 모였다    -> 조각이 다 모였으니 바로 처리   ★ 핵심
 *     ③ 600ms 넘게 조용하다  -> 안전장치 (줄바꿈도 없이 멈춘 경우)
 */
inline void nubidaBtUpdate() {
  drainBle();
  if (rxLen == 0) return;

  if (bufHasNewline()) {                        /* ① */
    handleFrame();
    return;
  }

  if (bufHasFullFrame()) {                      /* ② */
    handleFrame();
    return;
  }

  if ((millis() - lastRxAt) > FRAME_GAP_MS) {   /* ③ */
    handleFrame();
  }
}

#endif  /* NUBIDA_BT_H */
