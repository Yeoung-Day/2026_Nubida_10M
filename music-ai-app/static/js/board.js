/**
 * board.js - (주)누비다플랫폼 실전 서버용 최종본
 */

// 1. 초기 로드
window.addEventListener('load', () => {
    // 좋아요 구분을 위한 임시 고유 ID 생성 (없을 경우)
    if (!window.STUDIO_USER_ID) {
        window.STUDIO_USER_ID = 'u' + Math.random().toString(36).substring(2, 11);
    }
    loadFolders();
    renderBoard();
});

// ══════════════════════════════════════════════════════════════
// [260919] 학교별 게시판 폴더
//   · 본사에서 만든 폴더를 탭으로 보여준다
//   · 탭을 고르면 그 학교 곡만 보인다
//   · 업로드 시 폴더를 선택하면 그 학교 게시판에 저장된다
// ══════════════════════════════════════════════════════════════
window.BOARD_FOLDERS = [];
window.BOARD_CURRENT_FOLDER = '';   // '' = 전체

async function loadFolders() {
    try {
        const res = await fetch('/api/folders', { cache: 'no-store' });
        if (!res.ok) return;
        const folders = await res.json();
        window.BOARD_FOLDERS = Array.isArray(folders) ? folders : [];

        // 1) 게시판 탭
        const tabs = document.getElementById('board-folder-tabs');
        if (tabs) {
            let html = '<div class="board-folder-tab' +
                (window.BOARD_CURRENT_FOLDER === '' ? ' active' : '') +
                '" data-folder="">전체 보기</div>';
            window.BOARD_FOLDERS.forEach(f => {
                html += '<div class="board-folder-tab' +
                    (window.BOARD_CURRENT_FOLDER === f.id ? ' active' : '') +
                    '" data-folder="' + f.id + '">🏫 ' + escapeHtml(f.name) +
                    '<span class="board-folder-cnt">' + (f.post_count || 0) + '</span></div>';
            });
            if (!window.BOARD_FOLDERS.length) {
                html += '<div class="board-folder-empty">아직 만들어진 학교 게시판이 없습니다.</div>';
            }
            tabs.innerHTML = html;
            tabs.querySelectorAll('.board-folder-tab').forEach(el => {
                el.onclick = () => {
                    window.BOARD_CURRENT_FOLDER = el.dataset.folder || '';
                    tabs.querySelectorAll('.board-folder-tab').forEach(x => x.classList.remove('active'));
                    el.classList.add('active');
                    renderBoard();
                };
            });
        }

        // 2) 업로드용 폴더 선택 (기존 선택 유지)
        const sel = document.getElementById('school-name');
        if (sel) {
            const prev = sel.value;
            let opts = '<option value="">게시판 폴더를 선택하세요</option>';
            window.BOARD_FOLDERS.forEach(f => {
                opts += '<option value="' + f.id + '" data-name="' + escapeHtml(f.name) + '">🏫 ' +
                        escapeHtml(f.name) + '</option>';
            });
            sel.innerHTML = opts;
            if (prev) sel.value = prev;
        }
    } catch (e) { console.warn('폴더 로드 실패', e); }
}

// [260919] AI 노래 결과 카드의 폴더 선택도 같은 목록으로 채운다
async function loadFoldersForSong() {
    try {
        if (!window.BOARD_FOLDERS.length) {
            const res = await fetch('/api/folders', { cache: 'no-store' });
            if (res.ok) {
                const folders = await res.json();
                window.BOARD_FOLDERS = Array.isArray(folders) ? folders : [];
            }
        }
        const sel = document.getElementById('song-school-name');
        if (!sel) return;
        const prev = sel.value;
        let opts = '<option value="">게시판 폴더를 선택하세요</option>';
        window.BOARD_FOLDERS.forEach(f => {
            opts += '<option value="' + f.id + '" data-name="' + escapeHtml(f.name) + '">🏫 ' +
                    escapeHtml(f.name) + '</option>';
        });
        sel.innerHTML = opts;
        if (prev) sel.value = prev;
    } catch (e) { console.warn('노래 페이지 폴더 로드 실패', e); }
}

function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// 2. 게시판 목록 불러오기 (실시간 최적화)
async function renderBoard() {
    const bList = document.getElementById('board-list');
    const rList = document.getElementById('ranking-list');
    if (!bList || !rList) return;

    try {
        // [성과 지표: 캐시 무시] cache: 'no-store'로 서버의 진짜 데이터를 가져옴
        // [260919] 선택된 학교 폴더가 있으면 그 폴더만 조회
        const url = window.BOARD_CURRENT_FOLDER
            ? '/api/posts?folder=' + encodeURIComponent(window.BOARD_CURRENT_FOLDER)
            : '/api/posts';
        const response = await fetch(url, { cache: 'no-store' });
        if (!response.ok) throw new Error("데이터 로드 실패");
        const dbPosts = await response.json();

        // 목록 제목 갱신
        const titleEl = document.getElementById('board-list-title');
        if (titleEl) {
            if (window.BOARD_CURRENT_FOLDER) {
                const f = window.BOARD_FOLDERS.find(x => x.id === window.BOARD_CURRENT_FOLDER);
                titleEl.textContent = (f ? f.name : '학교') + ' 게시판';
            } else {
                titleEl.textContent = '최신 게시물';
            }
        }

        const controlBar = document.createElement('div');
        controlBar.style.cssText = "margin-bottom:20px; display:flex; justify-content:center;";
        controlBar.innerHTML = `
            <button class="btn-stop" onclick="stopAll()" 
                    style="width:100%; max-width:400px; background:#ef4444; color:white; padding:15px; border-radius:12px; font-weight:bold; border:none; cursor:pointer; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                🛑 모든 재생 중지
            </button>
        `;

        bList.innerHTML = '';
        bList.appendChild(controlBar);
        rList.innerHTML = '';

        if (dbPosts.length === 0) {
            bList.innerHTML = '<p class="center" style="color:#64748b; margin-top:20px;">아직 등록된 트랙이 없습니다.</p>';
            return;
        }

        // 3. TOP 3 랭킹 출력
        const sorted = [...dbPosts].sort((a, b) => b.likes - a.likes).slice(0, 3);
        const medals = ["🥇", "🥈", "🥉"];
        sorted.forEach((p, i) => {
            const card = document.createElement('div');
            card.className = `card ranking-card ${i === 0 ? 'top1' : ''}`;
            card.innerHTML = `
                <div style="font-size:24px;">${medals[i]}</div>
                <div style="font-weight:900; margin:10px 0;">${p.title}</div>
                <div style="font-size:12px; color:var(--text-sub);">${p.author}</div>
                <div style="color:var(--p-color); font-weight:bold; font-size:12px; margin-top:5px;">🔥 ${p.likes} Likes</div>
            `;
            rList.appendChild(card);
        });

        // 4. 전체 리스트 출력 (메모리 효율을 위해 데이터 바인딩 개선)
        dbPosts.forEach(p => {
            const card = document.createElement('div');
            card.className = 'card';
            card.style.marginBottom = '25px';
            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--text-sub);">
                    <span>🏫 ${p.school} | 👤 ${p.author}</span>
                    <span onclick="deletePost('${p.id}')" style="cursor:pointer; color:#ef4444; font-weight:bold;">삭제 ✕</span>
                </div>
                <h3 style="margin:10px 0; font-weight:900;">${p.title}</h3>
                <div style="display:flex; gap:10px; margin-bottom:15px;">
                    <button class="btn-main" id="btn-play-${p.id}">▶ 재생하기</button>
                    <button class="btn-sub" onclick="likePostDB('${p.id}')">❤️ ${p.likes}</button>
                </div>
            `;
            bList.appendChild(card);
            
            // 재생 버튼에 직접 데이터 연결 (따옴표 충돌 방지)
            document.getElementById(`btn-play-${p.id}`).onclick = () => {
                // [260919] AI 노래(완성된 mp3)는 그대로 재생, 작업실 곡은 recipe 합성
                const isSongFile = p.mrPath && /\.(mp3|wav|m4a|ogg)(\?|$)/i.test(p.mrPath);
                const hasRecipe = (() => {
                    try {
                        const r = typeof p.recipe === 'string' ? JSON.parse(p.recipe) : p.recipe;
                        return Array.isArray(r) && r.length > 0;
                    } catch (e) { return false; }
                })();

                if (isSongFile && !hasRecipe) {
                    playSongFile(p.mrPath);
                } else if (typeof playRecipe === 'function') {
                    playRecipe(p.recipe, p.singerId, p.mrPath);
                } else {
                    alert("재생 엔진 로딩 중...");
                }
            };
        });
    } catch (e) { console.error("로드 실패:", e); }
}

// 5. 게시판 업로드 (중복 함수 제거 및 통합)
async function uploadToBoard() {
    const titleInput = document.getElementById('song-title-input');
    const pwdInput = document.getElementById('post-password');
    const author = document.getElementById('user-name').value || "무명";

    // [260919] 학교 게시판 폴더 선택 필수
    const sel = document.getElementById('school-name');
    const folderId = sel ? sel.value : '';
    const folderOpt = sel && sel.selectedOptions ? sel.selectedOptions[0] : null;
    const folderName = folderOpt ? (folderOpt.dataset.name || folderOpt.textContent.replace('🏫 ', '').trim()) : '';

    if (!titleInput.value.trim()) return alert("제목을 입력하세요.");
    if (!pwdInput.value.trim()) return alert("삭제 비밀번호를 설정하세요.");
    if (!folderId) return alert("올릴 게시판(학교) 폴더를 선택하세요.");

    const postData = {
        id: 'p' + Date.now(),
        title: filterText(titleInput.value),
        password: pwdInput.value,
        author: author,
        school: folderName || '개인',
        folder_id: folderId,
        singerId: currentSinger,
        singerName: SINGERS[currentSinger].name,
        mrPath: currentSelectedBeat,
        recipe: Array.from(document.querySelectorAll('.lyric-row')).map(r => ({
            text: r.querySelector('.lyric-text').value,
            tune: parseFloat(r.querySelector('.line-tune').value) || 10,
            echo: parseFloat(r.querySelector('.line-echo').value) || 0,
            speed: parseFloat(r.querySelector('.line-speed').value) || 1,
            wait: parseFloat(r.querySelector('.line-wait').value) || 0.3,
            // [수정 260914] 필터/패닝/거칠기 값도 저장 (게시판 재생 시 반영)
            filter: parseFloat(r.querySelector('.line-filter')?.value) || 0,
            pan: parseFloat(r.querySelector('.line-pan')?.value) || 0,
            grit: parseFloat(r.querySelector('.line-grit')?.value) || 0
        }))
    };

    try {
        const res = await fetch('/api/posts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(postData)
        });

        if (res.ok) {
            alert("'" + (folderName || "선택한") + "' 게시판에 업로드되었습니다!");
            titleInput.value = '';
            pwdInput.value = '';
            document.getElementById('result-area').style.display = 'none';
            // 업로드한 학교 게시판으로 이동해서 바로 확인
            window.BOARD_CURRENT_FOLDER = folderId;
            showPage('page-board'); // 페이지 이동 (이 함수 내부에서 renderBoard() 호출됨)
            await loadFolders();
            await renderBoard();    // [성과 수호] 확실하게 한 번 더 목록 갱신
        } else {
            const j = await res.json().catch(() => ({}));
            alert("업로드 실패: " + (j.error || res.status));
        }
    } catch (err) { alert("서버 통신 오류"); }
}

// ══════════════════════════════════════════════════════════════
// [260919] AI 노래 페이지 결과 → 게시판 업로드
//   · song-result-card 안에서 바로 올릴 수 있게 한다
//   · 작업실(result-area)과 달리 가사/가창 설정 없이 '완성된 곡'만 올린다
// ══════════════════════════════════════════════════════════════
async function uploadToBoardFromSong() {
    const sel = document.getElementById('song-school-name');
    const nameInput = document.getElementById('song-user-name');
    const pwdInput = document.getElementById('song-post-password');

    const folderId = sel ? sel.value : '';
    const folderOpt = sel && sel.selectedOptions ? sel.selectedOptions[0] : null;
    const folderName = folderOpt ? (folderOpt.dataset.name ||
        folderOpt.textContent.replace('🏫 ', '').trim()) : '';

    // 곡 제목 = 결과 카드에 표시된 제목 재사용
    const titleEl = document.getElementById('song-result-title');
    const title = titleEl ? titleEl.textContent.trim() : '';

    if (!title || title === 'AI 노래') return alert("곡 제목이 없습니다. 노래를 먼저 만들어 주세요.");
    if (!folderId) return alert("올릴 게시판(학교) 폴더를 선택하세요.");
    if (!pwdInput.value.trim()) return alert("삭제 비밀번호를 설정하세요.");

    // 최종 생성된 음원 경로
    const audioEl = document.getElementById('song-audio');
    const audioSrc = audioEl ? (audioEl.getAttribute('src') || '') : '';
    if (!audioSrc) return alert("음원을 찾을 수 없습니다. 다시 만들어 주세요.");

    const postData = {
        id: 'p' + Date.now(),
        title: filterText(title),
        password: pwdInput.value,
        author: (nameInput.value || '').trim() || '무명',
        school: folderName || '개인',
        folder_id: folderId,
        songPath: audioSrc,          // 완성된 AI 노래 파일
        mrPath: audioSrc,            // [260919] 게시판 재생은 mrPath 를 사용한다
        recipe: [],                  // AI 노래는 가사 recipe 없음 → 파일 그대로 재생
        singerId: (typeof currentSinger !== 'undefined' ? currentSinger : null),
        singerName: (typeof SINGERS !== 'undefined' && SINGERS[currentSinger])
            ? SINGERS[currentSinger].name : 'AI',
        style: (typeof currentStyle !== 'undefined' ? currentStyle : null)
    };

    try {
        const res = await fetch('/api/posts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(postData)
        });

        if (res.ok) {
            alert("'" + (folderName || "선택한") + "' 게시판에 업로드되었습니다!");
            pwdInput.value = '';
            window.BOARD_CURRENT_FOLDER = folderId;
            showPage('page-board');
            await loadFolders();
            await renderBoard();
        } else {
            const j = await res.json().catch(() => ({}));
            alert("업로드 실패: " + (j.error || res.status));
        }
    } catch (err) { alert("서버 통신 오류"); }
}

// ══════════════════════════════════════════════════════════════
// [260919] AI 노래(완성된 mp3) 게시판 재생
//   · 작업실 곡은 recipe 합성이지만, AI 노래는 완성 파일이라 그대로 튼다
// ══════════════════════════════════════════════════════════════
function playSongFile(src) {
    try {
        if (typeof stopAll === 'function') stopAll();
        // 기존에 떠 있는 재생기를 재사용 (없으면 새로 만든다)
        let audio = document.getElementById('board-song-player');
        if (!audio) {
            audio = document.createElement('audio');
            audio.id = 'board-song-player';
            audio.controls = true;
            audio.style.cssText = 'width:100%;margin-top:10px;border-radius:10px;';
            document.body.appendChild(audio);
        }
        // 이미 열려 있으면 닫고 새로 재생
        audio.src = src + (src.includes('?') ? '&' : '?') + 't=' + Date.now();
        audio.style.display = 'block';
        audio.play().catch(() => {
            alert("재생을 시작할 수 없습니다. 다시 눌러주세요.");
        });
    } catch (e) {
        console.error('AI 노래 재생 실패', e);
        alert("재생 중 오류가 발생했습니다.");
    }
}

// 6. 좋아요 기능
async function likePostDB(id) {
    await fetch(`/api/posts/${id}/like`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: window.STUDIO_USER_ID })
    });
    renderBoard(); // 실시간 반영
}

// 7. 삭제 기능
async function deletePost(id) {
    const pwd = prompt("삭제 비밀번호를 입력하세요.");
    if(!pwd) return;

    const res = await fetch(`/api/posts/${id}/delete`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ password: pwd })
    });

    if(res.ok) {
        alert("삭제되었습니다.");
        renderBoard(); // 실시간 반영
    } else {
        alert("비밀번호가 틀렸습니다.");
    }
}

// 8. 금지어 필터링
function filterText(t) {
    if (typeof BANNED_WORDS === 'undefined') return t;
    BANNED_WORDS.forEach(w => {
        const reg = new RegExp(w, 'g');
        t = t.replace(reg, '***');
    });
    return t;
}