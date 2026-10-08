// 데이터 로드
let users = JSON.parse(localStorage.getItem('users')) || [];
let products = JSON.parse(localStorage.getItem('products')) || [];
let reviews = JSON.parse(localStorage.getItem('reviews')) || [];
let currentUser = JSON.parse(sessionStorage.getItem('currentUser')) || null;

// 네비게이션 바 동적 생성
function renderNavbar() {
    const navbar = `
    <nav class="bg-blue-600 text-white p-4 shadow-lg sticky top-0 z-50">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl font-bold cursor-pointer" onclick="location.href='index.html'">🎓 학생 창업 마켓</h1>
            <div class="space-x-4 flex items-center">
                <a href="index.html">메인</a>
                ${currentUser ? 
                    `<span>💰 ${currentUser.points.toLocaleString()}P</span>
                     <a href="myshop.html" class="text-yellow-300 font-bold">${currentUser.shopName}</a>
                     <button onclick="logout()" class="text-red-200">로그아웃</button>` : 
                    `<a href="login.html">로그인</a>
                     <a href="signup.html">회원가입</a>`
                }
            </div>
        </div>
    </nav>`;
    document.body.insertAdjacentHTML('afterbegin', navbar);
}

function logout() {
    sessionStorage.removeItem('currentUser');
    location.href = 'index.html';
}

// 데이터 저장 함수들
function saveUsers() { localStorage.setItem('users', JSON.stringify(users)); }
function saveProducts() { localStorage.setItem('products', JSON.stringify(products)); }
function saveReviews() { localStorage.setItem('reviews', JSON.stringify(reviews)); }