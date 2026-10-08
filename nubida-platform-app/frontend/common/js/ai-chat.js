/**
 * 누비다 AI — 채팅 어시스턴트 (확정설계안 v2)
 *
 * 두 가지 모드:
 *  1) 플로팅 위젯 (기본) — 페이지에 <script src="/common/js/ai-chat.js"> 포함 시 우하단 버튼
 *  2) 전체 페이지  — <body data-ai-mode="full"> + <div id="aiChatRoot"></div> 포함 시 전체 화면
 *
 * 기능: 질문 → 2~5줄 요약 답변 / [✅ 해결][⚠️ 부족] 버튼 / ⚠️ 부족 시 attempt+1 재질문
 * 원칙: 정답 직접 제공 금지(백엔드 이중 방어), 학생 쿼터(50회/일) 안내
 */
(function () {
  'use strict';

  var MODE = document.body.getAttribute('data-ai-mode') === 'full' ? 'full' : 'floating';
  var MAX_ATTEMPT = 4;

  // 강좌 컨텍스트: URL ?course_id= 또는 window.AI_COURSE_ID
  var courseId = new URLSearchParams(window.location.search).get('course_id') || (window.AI_COURSE_ID || null);

  var pending = { question: null, attempt: 1 };   // ⚠️ 부족 재질문용
  var busy = false;
  var rootEl = null;
  var msgListEl = null;
  var inputEl = null;
  var sendBtnEl = null;

  /* ---------- DOM 구성 ---------- */
  function buildWidget() {
    var panel = document.createElement('div');
    panel.className = 'ai-chat-panel';
    panel.innerHTML =
      '<div class="ai-chat-header">' +
        '<div class="ai-chat-title">' +
          '<span class="ai-chat-logo">🤖</span>' +
          '<div><div class="ai-chat-name">누비다 AI</div><div class="ai-chat-sub">정답 대신 해결방법을 안내해 드려요</div></div>' +
        '</div>' +
        '<button class="ai-chat-close" id="aiChatClose" aria-label="닫기">✕</button>' +
      '</div>' +
      '<div class="ai-chat-messages" id="aiChatMessages">' +
        '<div class="ai-chat-bubble ai-chat-bubble-assistant">' +
          '안녕하세요! 🤖 코딩/공부 중 궁금한 점을 물어보세요.<br>' +
          '스스로 해결할 수 있도록 <b>해결방법</b>을 알려드릴게요.' +
        '</div>' +
      '</div>' +
      '<div class="ai-chat-input-row">' +
        '<textarea id="aiChatInput" class="ai-chat-input" rows="1" placeholder="궁금한 점을 입력하세요 (한국어)" maxlength="1000"></textarea>' +
        '<button class="ai-chat-send" id="aiChatSend">전송</button>' +
      '</div>';

    if (MODE === 'full') {
      rootEl = document.getElementById('aiChatRoot');
      if (!rootEl) return;
      rootEl.appendChild(panel);
      panel.classList.add('ai-chat-mode-full');
    } else {
      var wrap = document.createElement('div');
      wrap.className = 'ai-chat-widget';
      wrap.appendChild(panel);
      var fab = document.createElement('button');
      fab.className = 'ai-chat-fab';
      fab.id = 'aiChatFab';
      fab.setAttribute('aria-label', '누비다 AI 열기');
      fab.innerHTML = '🤖';
      wrap.appendChild(fab);
      document.body.appendChild(wrap);
      panel.classList.add('ai-chat-mode-floating');
    }
  }

  function bindEvents() {
    inputEl = document.getElementById('aiChatInput');
    sendBtnEl = document.getElementById('aiChatSend');
    msgListEl = document.getElementById('aiChatMessages');

    var fab = document.getElementById('aiChatFab');
    var close = document.getElementById('aiChatClose');
    var panel = document.querySelector('.ai-chat-panel');

    if (fab) {
      fab.addEventListener('click', function () {
        panel.classList.add('ai-chat-open');
        fab.style.display = 'none';
        if (inputEl) inputEl.focus();
        loadHistory();
      });
    }
    if (close) {
      close.addEventListener('click', function () {
        panel.classList.remove('ai-chat-open');
        if (fab) fab.style.display = 'flex';
      });
    }
    if (sendBtnEl) sendBtnEl.addEventListener('click', function () { submitQuestion(); });
    if (inputEl) {
      inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitQuestion(); }
      });
      inputEl.addEventListener('input', function () {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
      });
    }
    if (MODE === 'full') loadHistory();
  }

  /* ---------- 렌더링 ---------- */

  // 🔍 마크다운 → 형광펜 HTML 렌더링 (XSS 방지 포함)
  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  // 마크다운을 안전한 HTML로 변환 + 형광펜 강조
  function renderMarkdown(text) {
    var lines = (text || '').split('\n');
    var html = '';
    var inCode = false;
    var inSvg = false;
    var codeBuf = []; // 코드블록 안 줄들 수집 (ASCII 다이어그램 판별용)

    function isAsciiDiagram(buf) {
      // 박스 다이어그램 판별:
      // - 박스 테두리 줄: +----+ 로 시작/끝
      // - 라벨 줄: | ... |로 둘러싸여 있음
      // - 흐름 줄: | / v / ^ / <-- / --> 를 포함
      // 코드블록 전체에서 '|' 를 포함하거나 '+-' 로 시작하는 줄이 충분히 많으면 다이어그램으로 판정
      var total = 0, boxLike = 0;
      for (var i = 0; i < buf.length; i++) {
        var s = buf[i].trim();
        if (!s) continue;
        total++;
        if (s.indexOf('|') !== -1 || /^\+-+/.test(s) || /^\+[+=]+$/.test(s)) boxLike++;
      }
      // '|' 나 '+---' 가 최소 2줄 이상이면서 절반 이상을 차지하면 다이어그램
      return boxLike >= 2 && (boxLike / total) >= 0.5;
    }

    lines.forEach(function (line, i) {
      var t = line;

      // [SVG] 다이어그램 블록 처리
      if (/^\[\/?SVG\]/.test(t.trim())) {
        if (t.trim() === '[/SVG]') { html += '</div>'; inSvg = false; }
        else { html += '<div class="ai-svg-diagram">'; inSvg = true; }
        return;
      }
      if (inSvg) {
        // SVG 코드 삽입 — 보안: <script>, on* 이벤트, javascript: URL 제거
        var sanitized = line
          .replace(/<script[\s\S]*?<\/script>/gi, '')
          .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
          .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
          .replace(/javascript:/gi, '');
        html += sanitized + '\n';
        return;
      }

      // 코드 블록 처리 (``` ... ```)
      if (t.trim().startsWith('```')) {
        if (inCode) {
          // 닫힘 — 빈 블록(내용없음)이면 렌더링 생략
          if (codeBuf.length === 0) {
            html += '</div>'; // .ai-code-block 닫기
          } else {
            var isAscii = isAsciiDiagram(codeBuf);
            if (isAscii) {
              // ASCII 다이어그램은 .ai-code-block(어두운 배경) 바깥에, 밝은 배경으로 렌더링
              html += '</div>'; // .ai-code-block 닫기
              html += '<div class="ai-ascii-diagram"><pre>' + codeBuf.map(escapeHtml).join('\n') + '</pre></div>';
            } else {
              // 일반 코드블록: 어두운 배경 + <pre> 안에 내용
              html += '<pre>' + codeBuf.map(escapeHtml).join('\n') + '</pre></div>';
            }
          }
          codeBuf = [];
          inCode = false;
        } else {
          html += '<div class="ai-code-block">';
          inCode = true;
        }
        return;
      }
      if (inCode) {
        // 코드블록 라인 수집 (아직 html엔 안 넣음)
        codeBuf.push(t);
        return;
      }
      if (t.trim() === '') { html += '<br>'; return; }

      // ## 제목 → 형광펜 스타일
      if (/^#{1,3}\s+/.test(t)) {
        t = t.replace(/^#{1,3}\s+/, '');
        html += '<div class="ai-hl-title">' + formatInline(t) + '</div>';
        return;
      }

      // - 목록
      if (/^[-*]\s+/.test(t) && i < lines.length - 1) {
        t = t.replace(/^[-*]\s+/, '');
        html += '<div class="ai-list-item">• ' + formatInline(t) + '</div>';
        return;
      }

      // > 인용구 → 부드러운 배경
      if (t.trim().startsWith('>')) {
        t = t.trim().replace(/^>\s?/, '');
        html += '<div class="ai-quote">💡 ' + formatInline(t) + '</div>';
        return;
      }

      // 일반 라인
      html += '<div class="ai-line">' + formatInline(t) + '</div>';
    });

    // 닫히지 않고 끝난 코드블록/SVG 처리
    if (inCode) {
      var isAsciiEnd = isAsciiDiagram(codeBuf);
      if (isAsciiEnd) {
        html += '</div>'; // .ai-code-block 닫기
        html += '<div class="ai-ascii-diagram"><pre>' + codeBuf.map(escapeHtml).join('\n') + '</pre></div>';
      } else {
        html += '<pre>' + codeBuf.map(escapeHtml).join('\n') + '</pre></div>';
      }
    }
    if (inSvg) html += '</div>';
    return html;
  }

  // 인라인 형광펜 처리 (**텍스트** → mark, `코드` → code, *기울임* → em)
  function formatInline(s) {
    s = escapeHtml(s);
    // **중요내용** → 형광펜 (가장 먼저 처리)
    s = s.replace(/\*\*([^*]+)\*\*/g, '<mark>$1</mark>');
    // `코드` → code 스타일
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    return s;
  }

  function addBubble(role, text, meta) {
    var row = document.createElement('div');
    row.className = 'ai-chat-row ai-chat-row-' + role;

    var bubble = document.createElement('div');
    bubble.className = 'ai-chat-bubble ai-chat-bubble-' + role;
    if (role === 'assistant') {
      bubble.innerHTML = renderMarkdown(text); // 안전 렌더링
    } else {
      bubble.textContent = text; // 사용자 메시지는 textContent로 안전하게
    }
    row.appendChild(bubble);

    if (role === 'assistant') {
      var actions = document.createElement('div');
      actions.className = 'ai-chat-actions';
      var hasMeta = !!(meta && meta.messageId);
      var btns =
        '<button class="ai-btn ai-btn-copy" type="button">📋 복사</button>';
      if (hasMeta) {
        btns +=
          '<button class="ai-btn ai-btn-solve" data-msgid="' + meta.messageId + '">✅ 해결</button>' +
          '<button class="ai-btn ai-btn-lack" data-msgid="' + meta.messageId + '">⚠️ 부족</button>' +
          (meta.attemptLabel ? '<span class="ai-attempt-tag">힌트 ' + meta.attemptLabel + '</span>' : '');
      }
      actions.innerHTML = btns;
      actions.querySelector('.ai-btn-copy').addEventListener('click', function () {
        copyToClipboard(text, this);
      });
      if (hasMeta) {
        actions.querySelector('.ai-btn-solve').addEventListener('click', function () {
          sendFeedback(meta.messageId, 1, this);
        });
        actions.querySelector('.ai-btn-lack').addEventListener('click', function () {
          sendFeedback(meta.messageId, -1, this);
        });
      }
      row.appendChild(actions);
    }
    msgListEl.appendChild(row);
    msgListEl.scrollTop = msgListEl.scrollHeight;
  }

  // 응답 원문(마크다운/코드 포함)을 클립보드에 복사
  function copyToClipboard(text, btnEl) {
    function done(ok) {
      if (btnEl) {
        var label = ok ? '✅ 복사됨' : '❌ 실패';
        var oldText = btnEl.textContent;
        var oldDisabled = btnEl.disabled;
        btnEl.textContent = label;
        btnEl.disabled = true;
        setTimeout(function () {
          btnEl.textContent = oldText;
          btnEl.disabled = oldDisabled;
        }, 1600);
      }
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); })
        .catch(function () { fallbackCopy(text); done(true); });
    } else {
      fallbackCopy(text);
      done(true);
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  function addSystem(text) {
    var row = document.createElement('div');
    row.className = 'ai-chat-row ai-chat-row-system';
    row.innerHTML = '<div class="ai-chat-bubble ai-chat-bubble-system">' + text + '</div>';
    msgListEl.appendChild(row);
    msgListEl.scrollTop = msgListEl.scrollHeight;
  }

  function setBusy(on) {
    busy = on;
    if (sendBtnEl) {
      sendBtnEl.disabled = on;
      sendBtnEl.textContent = on ? '···' : '전송';
    }
  }

  /* ---------- API ---------- */
  function submitQuestion() {
    if (busy) return;
    var text = (inputEl.value || '').trim();
    if (!text) return;
    addBubble('user', text, null);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    pending = { question: text, attempt: 1 };
    requestAnswer(text, 1);
  }

  function requestAnswer(question, attempt) {
    setBusy(true);
    addSystem('생각하는 중...');

    // 스트리밍용 진행 말풍선 생성
    var live = createLiveBubble();

    var gotText = false;
    streamChat('/ai/chat/stream', { course_id: courseId, message: question, attempt: attempt }, {
      onDelta: function (text) {
        if (!gotText) { gotText = true; removeSystemLoading(); }
        live.append(text);
      },
      onMeta: function (meta) {
        pending = { question: question, attempt: meta.attempt || attempt };
        live.finish(meta.final || '', {
          messageId: meta.message_id,
          attemptLabel: meta.attempt,
        });
        if (meta.allow_more === false) {
          addSystem('⚠️ 최대 힌트 단계까지 안내했어요. 이제 직접 해결해 보세요!');
        }
      },
      onError: function (detail) {
        removeSystemLoading();
        live.remove();
        addSystem('⚠️ ' + detail);
      },
      onDone: function () {
        removeSystemLoading();
        live.done();
      },
      onFallback: function () {
        // 스트리밍 미지원 환경 → 기존 방식으로 재시도
        live.remove();
        requestAnswerFallback(question, attempt);
      },
    });
  }

  // 스트리밍 실패/미지원 시 기존 단일 응답 방식 (안전망)
  function requestAnswerFallback(question, attempt) {
    apiPost('/ai/chat', { course_id: courseId, message: question, attempt: attempt })
      .then(function (res) {
        removeSystemLoading();
        var data = (res && res.data) || {};
        pending = { question: question, attempt: data.attempt || attempt };
        addBubble('assistant', data.reply || '답변을 준비하지 못했어요. 다시 시도해 주세요.', {
          messageId: data.message_id,
          attemptLabel: data.attempt,
        });
        if (data.allow_more === false) {
          addSystem('⚠️ 최대 힌트 단계까지 안내했어요. 이제 직접 해결해 보세요!');
        }
      })
      .catch(function (err) {
        removeSystemLoading();
        var raw = (err && err.message) || '';
        if ((err && err.name === 'AbortError') || /abort/i.test(raw)) {
          addSystem('⏱️ 답변 생성이 예상보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
          return;
        }
        var msg = raw || '오류가 발생했어요.';
        if (msg.includes('한도')) {
          addSystem('📌 ' + msg);
        } else if (msg.includes('준비 중')) {
          addSystem('📌 누비다 AI 서버가 아직 연결되지 않았어요. 잠시 후 다시 시도해 주세요.');
        } else {
          addSystem('⚠️ ' + msg);
        }
      })
      .finally(function () { setBusy(false); });
  }

  /* ---------- SSE 스트리밍 수신 ---------- */
  function streamChat(path, body, handlers) {
    var base = (window.location.protocol === 'https:' ? 'https:' : 'http:') +
               '//' + window.location.host + '/api/v1';
    var token = localStorage.getItem('token') || localStorage.getItem('access_token');
    var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var timedOut = false;
    var timer = null;
    if (ctrl) {
      // 전체 240초 (백엔드 LLM 180초 + 여유)
      timer = setTimeout(function () { timedOut = true; ctrl.abort(); }, 240000);
    }

    // 스트리밍 미지원 → 폴백
    if (typeof fetch !== 'function' || typeof ReadableStream === 'undefined') {
      if (handlers.onFallback) handlers.onFallback();
      return;
    }

    fetch(base + path, {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {}),
      body: JSON.stringify(body),
      signal: ctrl ? ctrl.signal : undefined,
    })
      .then(function (res) {
        if (res.status === 401) {
          localStorage.removeItem('token');
          localStorage.removeItem('access_token');
          localStorage.removeItem('user');
          window.location.href = '/pages/login.html';
          throw new Error('로그인이 필요합니다.');
        }
        if (res.status === 429) {
          return res.json().then(function (j) {
            throw new Error(j.detail || '오늘 질문 한도를 모두 사용했어요.');
          });
        }
        if (res.status === 403) {
          throw new Error('접근 권한이 없습니다.');
        }
        if (!res.ok || !res.body) {
          // SSE 불가 → 폴백
          if (handlers.onFallback) { handlers.onFallback(); return null; }
          throw new Error('오류 발생 (' + res.status + ')');
        }

        var reader = res.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var buffer = '';

        // SSE 블록 파싱: 'event:'/'data:' 라인을 모아 빈 줄에서 1개 이벤트 확정
        function handleBlock(block) {
          var evName = 'message', dataStr = '';
          block.split('\n').forEach(function (line) {
            if (line.indexOf('event:') === 0) evName = line.slice(6).trim();
            else if (line.indexOf('data:') === 0) dataStr += line.slice(5).trim();
          });
          if (!dataStr) return;
          var payload;
          try { payload = JSON.parse(dataStr); } catch (e) { return; }
          if (evName === 'delta' && handlers.onDelta) handlers.onDelta(payload.text || '');
          else if (evName === 'meta' && handlers.onMeta) handlers.onMeta(payload);
          else if (evName === 'error' && handlers.onError) {
            handlers.onError(payload.detail || '답변 생성 중 문제가 발생했어요.');
          }
        }

        function pump() {
          return reader.read().then(function (r) {
            if (r.done) {
              if (timer) clearTimeout(timer);
              // 남은 버퍼 처리 (마지막 이벤트가 개행 없이 끝난 경우)
              var rest = buffer.trim();
              if (rest) {
                rest.split(/\n\n+/).forEach(function (b) {
                  if (b.trim()) handleBlock(b);
                });
              }
              if (handlers.onDone) handlers.onDone();
              return;
            }
            buffer += decoder.decode(r.value, { stream: true });
            // '\n\n' 뿐 아니라 '\r\n\r\n' 도 처리
            var norm = buffer.replace(/\r\n/g, '\n');
            var blocks = norm.split('\n\n');
            buffer = blocks.pop();
            blocks.forEach(function (b) { if (b.trim()) handleBlock(b); });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        if (timer) clearTimeout(timer);
        if (timedOut || (err && err.name === 'AbortError')) {
          if (handlers.onError) {
            handlers.onError('답변 생성이 예상보다 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
          }
          return;
        }
        if (handlers.onError) handlers.onError((err && err.message) || '오류가 발생했어요.');
      });
  }

  /* ---------- 스트리밍 진행 말풍선 ---------- */
  function createLiveBubble() {
    var row = document.createElement('div');
    row.className = 'ai-chat-row ai-chat-row-assistant ai-chat-row-live';

    var bubble = document.createElement('div');
    bubble.className = 'ai-chat-bubble ai-chat-bubble-assistant';
    bubble.innerHTML = '<span class="ai-live-cursor">▊</span>';
    row.appendChild(bubble);

    var actions = document.createElement('div');
    actions.className = 'ai-chat-actions';
    actions.style.display = 'none';
    row.appendChild(actions);

    msgListEl.appendChild(row);
    msgListEl.scrollTop = msgListEl.scrollHeight;

    var raw = '';
    var finished = false;

    return {
      append: function (text) {
        if (finished || !text) return;
        raw += text;
        bubble.innerHTML = renderMarkdown(raw) + '<span class="ai-live-cursor">▊</span>';
        msgListEl.scrollTop = msgListEl.scrollHeight;
      },
      finish: function (finalText, meta) {
        if (finished) return;
        finished = true;
        raw = finalText || raw;
        bubble.innerHTML = renderMarkdown(raw);
        row.classList.remove('ai-chat-row-live');

        var hasMeta = !!(meta && meta.messageId);
        var btns = '<button class="ai-btn ai-btn-copy" type="button">📋 복사</button>';
        if (hasMeta) {
          btns +=
            '<button class="ai-btn ai-btn-solve" data-msgid="' + meta.messageId + '">✅ 해결</button>' +
            '<button class="ai-btn ai-btn-lack" data-msgid="' + meta.messageId + '">⚠️ 부족</button>' +
            (meta.attemptLabel ? '<span class="ai-attempt-tag">힌트 ' + meta.attemptLabel + '</span>' : '');
        }
        actions.innerHTML = btns;
        actions.style.display = '';
        actions.querySelector('.ai-btn-copy').addEventListener('click', function () {
          copyToClipboard(raw, this);
        });
        if (hasMeta) {
          actions.querySelector('.ai-btn-solve').addEventListener('click', function () {
            sendFeedback(meta.messageId, 1, this);
          });
          actions.querySelector('.ai-btn-lack').addEventListener('click', function () {
            sendFeedback(meta.messageId, -1, this);
          });
        }
        msgListEl.scrollTop = msgListEl.scrollHeight;
      },
      remove: function () { try { row.remove(); } catch (e) {} },
      done: function () {
        if (!finished) {
          // meta 없이 끝난 경우(이벤트 유실) → 커서 제거하고 내용 보존
          finished = true;
          row.classList.remove('ai-chat-row-live');
          bubble.innerHTML = renderMarkdown(raw);
          setBusy(false);
        } else {
          setBusy(false);
        }
      },
    };
  }

  function removeSystemLoading() {
    var rows = msgListEl.querySelectorAll('.ai-chat-row-system');
    if (rows.length) rows[rows.length - 1].remove();
  }

  function sendFeedback(messageId, helpful, btnEl) {
    if (!messageId) return;
    if (btnEl) { btnEl.disabled = true; btnEl.classList.add('ai-btn-done'); }
    apiPost('/ai/feedback', { message_id: messageId, helpful: helpful })
      .then(function () {
        if (helpful === 1) {
          addSystem('🎉 해결됐다니 다행이에요! 이 답변이 다른 친구들에게도 도움이 되도록 저장할게요.');
        } else {
          addSystem('💡 더 자세한 힌트를 준비할게요...');
          var next = Math.min((pending.attempt || 1) + 1, MAX_ATTEMPT);
          if (pending.question) requestAnswer(pending.question, next);
          else addSystem('⚠️ 이전 질문을 찾을 수 없어요. 새로 질문해 주세요.');
        }
      })
      .catch(function (err) {
        addSystem('⚠️ 피드백 저장에 실패했어요: ' + ((err && err.message) || ''));
      });
  }

  function loadHistory() {
    apiGet('/ai/history' + (courseId ? '?course_id=' + encodeURIComponent(courseId) : ''))
      .then(function (res) {
        var items = (res && res.data) || [];
        if (!items.length) return;
        // 첫 안내 버블은 유지하고, 이어서 렌더링
        items.forEach(function (m) {
          if (m.role === 'user') { addBubble('user', m.content, null); }
          else if (m.role === 'assistant') {
            addBubble('assistant', m.content, { messageId: m.id, attemptLabel: m.attempt });
            pending = { question: null, attempt: m.attempt || 1 };
          }
        });
      })
      .catch(function () { /* 히스토리 실패는 무시 */ });
  }

  /* ---------- 시작 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    buildWidget();
    bindEvents();
  });
})();
