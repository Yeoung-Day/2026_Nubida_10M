/**
 * Nubida 공통 비밀번호 해시 유틸리티 (Node.js 표준 crypto 만 사용)
 *
 * 형식: pbkdf2_sha256$<iterations>$<base64_salt>$<base64_hash>
 *  - salt: 16바이트 난수 (매번 새로 생성)
 *  - iterations: 260,000
 *  - 하위 호환: 기존 평문도 검증 가능 → 로그인 시 자동 업그레이드
 */
const crypto = require('crypto');

const ITERATIONS = 260000;
const ALGO = 'pbkdf2_sha256';
const KEYLEN = 32;
const DIGEST = 'sha256';

function hashPassword(password) {
    const salt = crypto.randomBytes(16);
    const dk = crypto.pbkdf2Sync(String(password), salt, ITERATIONS, KEYLEN, DIGEST);
    return [ALGO, ITERATIONS, salt.toString('base64'), dk.toString('base64')].join('$');
}

function verifyPassword(plain, stored) {
    if (!stored) return false;
    stored = String(stored);

    // 1) PBKDF2 형식
    if (stored.startsWith(ALGO + '$')) {
        try {
            const parts = stored.split('$');
            const iters = parseInt(parts[1], 10);
            const salt = Buffer.from(parts[2], 'base64');
            const expected = Buffer.from(parts[3], 'base64');
            const dk = crypto.pbkdf2Sync(String(plain), salt, iters, expected.length, DIGEST);
            return crypto.timingSafeEqual(dk, expected);
        } catch (e) {
            return false;
        }
    }

    // 2) 기존 SHA-256 (64자 hex)
    if (stored.length === 64 && /^[0-9a-f]{64}$/i.test(stored)) {
        const legacy = crypto.createHash('sha256').update(String(plain)).digest('hex');
        return crypto.timingSafeEqual(Buffer.from(legacy), Buffer.from(stored));
    }

    // 3) 평문 (기존 데이터)
    const a = Buffer.from(String(plain));
    const b = Buffer.from(stored);
    if (a.length !== b.length) return false;
    return crypto.timingSafeEqual(a, b);
}

function needsRehash(stored) {
    return !String(stored || '').startsWith(ALGO + '$');
}

module.exports = { hashPassword, verifyPassword, needsRehash };
