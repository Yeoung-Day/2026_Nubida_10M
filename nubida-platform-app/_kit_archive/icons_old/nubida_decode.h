/* ===========================================================================
 *  nubida_decode.h  -  난독화(암호문) 풀기
 *  ---------------------------------------------------------------------------
 *  누비다플랫폼 웹앱이 명령을 그냥 보내지 않고 암호처럼 바꿔서 보냅니다.
 *  이 파일이 그 암호문("x1a2b3c...")을 원래 명령으로 되돌립니다.
 *
 *  ★ 이 파일은 건드리실 필요가 없습니다. (거의 모든 교구가 똑같이 씁니다)
 *
 *  규칙 : 'x' + 2글자(열쇠) + [명령글자마다 2글자]
 *         각 2글자를 숫자로 바꾼 뒤 열쇠와 XOR 하면 원래 글자
 *  열쇠 : 0x2F (웹과 같아야 함)
 * =========================================================================== */

#ifndef NUBIDA_DECODE_H
#define NUBIDA_DECODE_H

#define NB_KEY 0x2F

/* 16진수 글자 1개 -> 숫자   ('a' -> 10, 'F' -> 15, 아니면 -1) */
inline int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/* "x...." 를 원래 명령으로 되돌림. 실패하면 빈 문자열("") */
inline String decodeFrame(String frame) {
  if (frame.length() < 5 || frame.charAt(0) != 'x') return "";

  /* (1) 쓸 수 있는 16진수 글자만 모은다 */
  String hexs = "";
  for (unsigned int i = 1; i < frame.length(); i++) {
    char c = frame.charAt(i);
    if (hexVal(c) >= 0) hexs += c;
  }
  if (hexs.length() < 4) return "";

  /* (2) 글자 수가 홀수면 마지막 1글자가 잘린 것
   *     버리지 말고 그 1글자만 빼고 계속 (나머지는 정상 복원됨)
   *     예) "1NubidaAi" 가 "1NubidaA" 로 와도 알아봅니다 */
  if ((hexs.length() % 2) != 0) {
    hexs = hexs.substring(0, hexs.length() - 1);
    if (hexs.length() < 4) return "";
  }

  /* (3) 열쇠 꺼내기 */
  int seed = (hexVal(hexs.charAt(0)) * 16 + hexVal(hexs.charAt(1))) ^ NB_KEY;
  if (seed == 0) return "";

  /* (4) 한 글자씩 열쇠와 XOR 해서 원래 글자로
   *     한글은 1글자가 3바이트라서 "영문만 남기고 버리면"
   *     한글 명령이 전부 사라집니다. -> 한글 바이트도 살립니다 */
  String out = "";
  for (unsigned int i = 2; i + 1 < hexs.length(); i += 2) {
    int h1 = hexVal(hexs.charAt(i));
    int h2 = hexVal(hexs.charAt(i + 1));
    if (h1 < 0 || h2 < 0) continue;
    char c = (char)((h1 * 16 + h2) ^ seed);
    out += c;                                  /* 거르지 않고 그대로 담음 */
  }
  out.trim();
  return out;
}

#endif  /* NUBIDA_DECODE_H */
