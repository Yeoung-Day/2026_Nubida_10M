import os, time, json
import mysql.connector
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sys
sys.path.insert(0, '/app')
from password_hash import hash_password, verify_password, needs_rehash
from werkzeug.utils import secure_filename

app = Flask(__name__)
import os
app.secret_key = os.environ.get('SESSION_SECRET', 'mp2bh81vFVL_bvZItLBJPXfmaWayTdPkYwS9RsFYoJng7SmvCOASElj7H9XlTd-T')

# 설정
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- DB 연결 함수 ---
def get_db_connection():
    return mysql.connector.connect(
        host="music-db",  # Docker Compose의 서비스명
        user="nubiapp",
        password="Mi9qEZGvEaE^g9nhzoILrvT=",
        database="shop_db",
        charset="utf8mb4"
    )

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_admin():
    if not session.get('user'):
        return False
    # admin 이거나 adj29089 이면 관리자로 판단
    return session['user']['id'] in ['admin', 'adj29089']

# --- 라우트 ---

@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    conn.close()
    return render_template('index.html', products=products, user=session.get('user'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        uid = request.form['id']
        pw = request.form['pw']
        name = request.form['name']
        shopName = request.form['shopName']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (uid,))
        if cursor.fetchone():
            flash("이미 존재하는 아이디입니다.")
            conn.close()
            return redirect(url_for('signup'))
            
        cursor.execute("INSERT INTO users (id, pw, name, shopName, points) VALUES (%s, %s, %s, %s, 50000)",
                       (uid, hash_password(pw), name, shopName))
        conn.commit()
        conn.close()
        flash("가입 완료! 50,000P가 지급되었습니다.")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    # 세션에서 유저 정보를 제거합니다.
    session.pop('user', None)
    # 메인 페이지로 돌아갑니다.
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid, upw = request.form['id'], request.form['pw']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))
        u = cursor.fetchone()

        # 비밀번호 검증 (PBKDF2 / 기존 평문/구형 해시 하위 호환)
        if not u or not verify_password(upw, u.get('pw', '')):
            conn.close()
            flash("로그인 정보가 틀립니다.")
            return render_template('login.html')
        session['user'] = u
        # 구형(평문/무염) 해시면 로그인 시점에 자동으로 PBKDF2 로 교체
        if needs_rehash(u.get('pw', '')):
            try:
                newh = hash_password(upw)
                c2 = conn.cursor()
                c2.execute("UPDATE users SET pw = %s WHERE id = %s", (newh, uid))
                conn.commit()
                u['pw'] = newh
                c2.close()
            except Exception:
                pass
        conn.close()

        if u:
            session['user'] = u
            # 아이디가 admin이거나 adj29089인 경우 관리자 페이지로 이동
            if is_admin():
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash("로그인 정보가 틀립니다.")
    return render_template('login.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        # 변수를 미리 초기화해서 NameError 방지
        img_url = "/static/uploads/default.jpg"
        det_url = ""
        
        img = request.files.get('img_file')
        det = request.files.get('detail_img_file')
        
        if img and allowed_file(img.filename):
            fn = f"t_{int(time.time())}_{secure_filename(img.filename)}"
            img.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
            img_url = f"/static/uploads/{fn}"
        
        if det and allowed_file(det.filename):
            dfn = f"d_{int(time.time())}_{secure_filename(det.filename)}"
            det.save(os.path.join(app.config['UPLOAD_FOLDER'], dfn))
            det_url = f"/static/uploads/{dfn}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        # 컬럼명을 DB와 동일하게 언더바(_) 형식으로 수정
        sql = """INSERT INTO products (id, seller_id, seller_shop, name, price, stock, img, detail_img, `desc`) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        cursor.execute(sql, (int(time.time()), session['user']['id'], session['user']['shopName'], 
                             request.form['name'], int(request.form['price']), int(request.form['stock']), 
                             img_url, det_url, request.form['desc']))
        conn.commit()
        conn.close()
        return redirect(url_for('shop_view', seller_id=session['user']['id']))
    return render_template('upload.html', user=session.get('user'))

@app.route('/product/<int:p_id>')
def detail(p_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # products 테이블에서 seller_id 컬럼이 포함되어 있는지 확인
    cursor.execute("SELECT * FROM products WHERE id = %s", (p_id,))
    p = cursor.fetchone()
    conn.close()
    
    if not p:
        return "상품을 찾을 수 없습니다.", 404
        
    return render_template('detail.html', p=p, user=session.get('user'))

@app.route('/product/edit/<int:p_id>', methods=['GET', 'POST'])
def edit_product(p_id):
    if 'user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        name = request.form['name']
        price = int(request.form['price'])
        stock = int(request.form['stock'])
        desc = request.form['desc']
        
        img = request.files.get('img_file')
        if img and img.filename != '':
            fn = f"t_{int(time.time())}_{secure_filename(img.filename)}"
            img.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
            img_url = f"/static/uploads/{fn}"
            cursor.execute("UPDATE products SET name=%s, price=%s, stock=%s, `desc`=%s, img=%s WHERE id=%s",
                           (name, price, stock, desc, img_url, p_id))
        else:
            cursor.execute("UPDATE products SET name=%s, price=%s, stock=%s, `desc`=%s WHERE id=%s",
                           (name, price, stock, desc, p_id))
        
        conn.commit()
        conn.close()
        flash("수정이 완료되었습니다.")
        return redirect(url_for('detail', p_id=p_id))

    cursor.execute("SELECT * FROM products WHERE id = %s", (p_id,))
    product = cursor.fetchone()
    conn.close()
    return render_template('edit.html', p=product, user=session.get('user'))

@app.route('/buy/<int:p_id>')
def buy(p_id):
    if 'user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM products WHERE id = %s", (p_id,))
    p = cursor.fetchone()
    
    if not p:
        flash("상품을 찾을 수 없습니다.")
        conn.close()
        return redirect(url_for('index'))

    # [수정] 본인 상품 구매 방지 로직 추가
    if p['seller_id'] == session['user']['id']:
        flash("본인의 상품은 구매할 수 없습니다.")
        conn.close()
        return redirect(url_for('detail', p_id=p_id))

    if p['stock'] <= 0:
        flash("품절된 상품입니다.")
        conn.close()
        return redirect(url_for('detail', p_id=p_id))

    # 구매자 포인트 확인
    cursor.execute("SELECT points FROM users WHERE id = %s", (session['user']['id'],))
    buyer_points = cursor.fetchone()['points']
    
    if buyer_points < p['price']:
        flash("포인트가 부족합니다.")
        conn.close()
        return redirect(url_for('detail', p_id=p_id))

    try:
        # 결제 처리
        cursor.execute("UPDATE users SET points = points - %s WHERE id = %s", (p['price'], session['user']['id']))
        cursor.execute("UPDATE users SET points = points + %s WHERE id = %s", (p['price'], p['seller_id']))
        cursor.execute("UPDATE products SET stock = stock - 1 WHERE id = %s", (p_id,))
        
        # [수정] 주문 기록 (컬럼명을 prod_img 로 정확히 매칭)
        sql = """INSERT INTO orders (order_id, buyer_id, buyer_name, seller_id, seller_shop, prod_name, prod_img, price, date) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        
        # 데이터가 비어있지 않은지 확인하며 삽입
        cursor.execute(sql, (
            int(time.time()),            # order_id
            session['user']['id'],       # buyer_id
            session['user']['name'],     # buyer_name (이게 빈칸이면 안됨)
            p['seller_id'],              # seller_id
            p['seller_shop'],            # seller_shop
            p['name'],                   # prod_name (이게 빈칸이면 안됨)
            p['img'],                    # prod_img
            p['price'],                  # price
            datetime.now().strftime('%Y-%m-%d %H:%M') # date
        ))
        
        conn.commit()
        # 세션 갱신
        cursor.execute("SELECT * FROM users WHERE id = %s", (session['user']['id'],))
        session['user'] = cursor.fetchone()
        flash("구매 성공!")
    except Exception as e:
        conn.rollback()
        print(f"구매 에러 상세: {e}")
        flash(f"구매 처리 중 오류 발생: {e}")
    finally:
        conn.close()
    return redirect(url_for('my_orders'))

@app.route('/my_sales')
def my_sales():
    if 'user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. 판매 내역 조회 (컬럼명 seller_id 확인)
    cursor.execute("SELECT * FROM orders WHERE seller_id = %s", (session['user']['id'],))
    sales = cursor.fetchall()
    
    # 2. 총 매출 계산 및 데이터 타입 변환 (Decimal -> int)
    cursor.execute("SELECT SUM(price) as rev FROM orders WHERE seller_id = %s", (session['user']['id'],))
    rev_res = cursor.fetchone()
    # DB에서 온 Decimal 타입을 파이썬 int로 강제 변환해야 계산 에러가 안 납니다.
    rev = int(rev_res['rev']) if rev_res['rev'] else 0
    
    cursor.execute("SELECT * FROM taxes WHERE userId = %s", (session['user']['id'],))
    taxes = cursor.fetchall()
    
    conn.close()
    return render_template('my_sales.html', sales=sales, revenue=rev, taxes=taxes, user=session.get('user'))

@app.route('/pay_tax', methods=['POST'])
def pay_tax():
    if 'user' not in session: return redirect(url_for('login'))
    amt = int(request.form['tax_amount'])
    t_type = request.form['tax_type']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 포인트 차감
    cursor.execute("UPDATE users SET points = points - %s WHERE id = %s", (amt, session['user']['id']))
    # 세금 기록
    cursor.execute("INSERT INTO taxes (userId, userName, amount, type, date) VALUES (%s, %s, %s, %s, %s)",
                   (session['user']['id'], session['user']['name'], amt, t_type, datetime.now().strftime('%Y-%m-%d %H:%M')))
    
    conn.commit()
    # 세션 갱신
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user']['id'],))
    session['user'] = cursor.fetchone()
    conn.close()
    return redirect(url_for('my_sales'))

@app.route('/admin')
def admin_dashboard():
    if not is_admin(): return "Forbidden", 403
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    cursor.execute("SELECT * FROM orders")
    orders = cursor.fetchall()
    conn.close()

    # 템플릿이 data.users 형식을 쓰므로 dictionary로 묶어서 전달
    dashboard_data = {
        "users": users,
        "products": products,
        "orders": orders
    }
    return render_template('admin.html', data=dashboard_data, user=session['user'])

@app.route('/admin/user/<target_id>')
def admin_user_detail(target_id):
    if not is_admin(): return "Forbidden", 403
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM users WHERE id = %s", (target_id,))
    t_user = cursor.fetchone()
    
    # seller_id, buyer_id 로 수정
    cursor.execute("SELECT * FROM orders WHERE seller_id = %s", (target_id,))
    sales = cursor.fetchall()
    cursor.execute("SELECT * FROM orders WHERE buyer_id = %s", (target_id,))
    orders = cursor.fetchall()
    
    # 템플릿에서 에러가 났던 total_revenue 계산 및 전달
    rev = sum(int(s['price']) for s in sales)
    
    # 세금 리포트 계산
    cursor.execute("SELECT * FROM taxes WHERE userId = %s", (target_id,))
    taxes = cursor.fetchall()
    
    tax_report = {
        "expected_vat": int(rev * 0.1), 
        "paid_vat": sum(int(t['amount']) for t in taxes if t['type']=='부가가치세'),
        "expected_income": int(rev * 0.05), 
        "paid_income": sum(int(t['amount']) for t in taxes if t['type']=='종합소득세')
    }
    
    conn.close()
    # total_revenue=rev 를 반드시 인자로 넘겨줘야 합니다.
    return render_template('admin_user_detail.html', target=t_user, sales=sales, orders=orders, taxes=taxes, total_revenue=rev, tax_report=tax_report, user=session['user'])

@app.route('/admin/update_points', methods=['POST'])
def admin_update_points():
    if not is_admin(): return "Forbidden", 403
    tid = request.form['target_id']
    amt = int(request.form['amount'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points + %s WHERE id = %s", (amt, tid))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_user_detail', target_id=tid))

@app.route('/my_orders')
def my_orders():
    if 'user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # buyerId를 buyer_id로 수정
    cursor.execute("SELECT * FROM orders WHERE buyer_id = %s", (session['user']['id'],))
    orders = cursor.fetchall()
    conn.close()
    return render_template('my_orders.html', orders=orders, user=session.get('user'))

@app.route('/shop/<seller_id>')
def shop_view(seller_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 판매자 확인
    cursor.execute("SELECT * FROM users WHERE id = %s", (seller_id,))
    seller = cursor.fetchone()
    
    if not seller:
        conn.close()
        return "존재하지 않는 상점입니다.", 404

    # 바뀐 컬럼명인 seller_id 로 조회
    cursor.execute("SELECT * FROM products WHERE seller_id = %s", (seller_id,))
    prods = cursor.fetchall()
    
    conn.close()
    return render_template('shop_view.html', seller=seller, products=prods, user=session.get('user'))

@app.route('/product/delete/<int:p_id>')
def delete_product(p_id):
    if 'user' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    # sellerId -> seller_id 로 수정
    if is_admin():
        cursor.execute("DELETE FROM products WHERE id = %s", (p_id,))
    else:
        cursor.execute("DELETE FROM products WHERE id = %s AND seller_id = %s", (p_id, session['user']['id']))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)