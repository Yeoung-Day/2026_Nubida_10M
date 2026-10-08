/**
 * 누비다플랫폼 — 우클릭 방지 및 개발자 도구 차단
 * 학생 학습 페이지 보호 (컨텐츠 무단 복사 방지)
 * Version: 1.0.0
 */

(function() {
    'use strict';

    // ===== 1. 우클릭 방지 (context menu) =====
    document.addEventListener('contextmenu', function(e) {
        e.preventDefault();
        return false;
    });

    // body oncontextmenu 대비
    document.addEventListener('DOMContentLoaded', function() {
        document.body.setAttribute('oncontextmenu', 'return false');
    });

    // ===== 2. 키보드 단축키 차단 (F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U) =====
    document.addEventListener('keydown', function(e) {
        // F12
        if (e.key === 'F12' || e.keyCode === 123) {
            e.preventDefault();
            return false;
        }
        // Ctrl+Shift+I (개발자 도구)
        if (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'i' || e.keyCode === 73)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+Shift+J (콘솔)
        if (e.ctrlKey && e.shiftKey && (e.key === 'J' || e.key === 'j' || e.keyCode === 74)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+U (소스 보기)
        if (e.ctrlKey && (e.key === 'U' || e.key === 'u' || e.keyCode === 85)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+C (복사) — 학습 콘텐츠 보호 목적
        if (e.ctrlKey && (e.key === 'c' || e.key === 'C' || e.keyCode === 67)) {
            e.preventDefault();
            return false;
        }
        // Ctrl+S (저장)
        if (e.ctrlKey && (e.key === 's' || e.key === 'S' || e.keyCode === 83)) {
            e.preventDefault();
            return false;
        }
    });

    // ===== 3. 추가 복사 방지 (선택/드래그) =====
    document.addEventListener('copy', function(e) {
        e.preventDefault();
        return false;
    });

    document.addEventListener('cut', function(e) {
        e.preventDefault();
        return false;
    });

    document.addEventListener('dragstart', function(e) {
        e.preventDefault();
        return false;
    });

    document.addEventListener('selectstart', function(e) {
        e.preventDefault();
        return false;
    });

    // ===== 4. 콘솔 경고 메시지 =====
    console.log('%c⚠️ 누비다플랫폼 콘텐츠 보호 안내',
        'font-size:14px; font-weight:bold; color:#dc2626;');
    console.log('%c이 페이지의 콘텐츠는 저작권 보호를 받습니다.',
        'font-size:12px; color:#6b7280;');

})();
