import functools, os, re, secrets
from datetime import datetime, timedelta
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

def load_env(path):
    """Nạp biến môi trường từ file .env (dạng KEY=VALUE) nằm cạnh app.py, để không phải gõ lại mỗi lần chạy.
    Biến đã đặt sẵn trong terminal ($env:...) được ưu tiên, không bị .env ghi đè."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip().removeprefix("export ").strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k:
                    os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass

load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import chat, db, paypal

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "doi-khoa-bi-mat-nay-khi-deploy")
app.config.update(MAX_CONTENT_LENGTH=3 * 1024 * 1024,  # ảnh upload tối đa 3MB
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
db.init_db()

# ---- Tài khoản Admin mặc định (chỉ tạo khi CSDL chưa có admin nào) ----
# Đặt ADMIN_EMAIL / ADMIN_PASSWORD (biến môi trường) để dùng thông tin riêng.
ADMIN_NAME, DEFAULT_ADMIN_PW = "Quản trị viên", "Admin@123"
if not db.admin_exists():
    _email = os.getenv("ADMIN_EMAIL", "admin@laptops.local").strip().lower()
    _pw = os.getenv("ADMIN_PASSWORD") or DEFAULT_ADMIN_PW
    db.create_user(ADMIN_NAME, _email, generate_password_hash(_pw), "admin")
    print(f"[LaptopS] Đã tạo tài khoản Admin: {_email}")
    if _pw == DEFAULT_ADMIN_PW:
        print("[LaptopS] CẢNH BÁO: đang dùng mật khẩu Admin mặc định, hãy đặt ADMIN_PASSWORD khi deploy!")

# ---------- Xác thực & phân quyền ----------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FORM_ENDPOINTS = {"login", "register", "logout", "admin_new", "admin_edit", "admin_delete"}

def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = db.user_by_id(uid) if uid else None
        if uid and not g.user:
            session.pop("uid", None)
    return g.user

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]

@app.before_request
def verify_csrf():
    if request.method == "POST" and request.endpoint in FORM_ENDPOINTS:
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400)

def track(etype, product_id=None, source=None, value=None):
    """Ghi một sự kiện cho phễu chuyển đổi (bỏ qua tài khoản admin để không làm sai số liệu)."""
    u = current_user()
    if u and u["role"] == "admin":
        return
    if "sid" not in session:
        session["sid"] = secrets.token_hex(8)
    db.log_event(session["sid"], etype, product_id, source, value)

@app.before_request
def track_visit():
    if request.method == "GET" and request.endpoint in ("index", "product"):
        track("visit")
        if request.endpoint == "product":
            track("product_view", (request.view_args or {}).get("pid"))

@app.post("/api/event")
def api_event():
    """Sự kiện phía trình duyệt (chỉ cho phép một danh sách nhỏ, không nhận dữ liệu tùy ý)."""
    etype = (request.get_json(silent=True) or {}).get("type")
    if etype in ("chat_open",):
        track(etype)
    return jsonify(ok=True)

@app.context_processor
def inject_globals():
    return {"me": current_user(), "csrf_token": csrf_token, "pay_badge": pay_badge,
            "paypal_client_id": paypal.client_id() if paypal.configured() else ""}

def start_session(uid):
    """Đăng nhập: làm mới session (chống session fixation) nhưng giữ lại giỏ hàng."""
    cart, sid = session.get("cart"), session.get("sid")
    session.clear()
    session["uid"] = uid
    if cart:
        session["cart"] = cart
    if sid:
        session["sid"] = sid   # giữ mã phiên để phễu chuyển đổi không bị đứt khi khách đăng nhập

def safe_next(url):
    """Chỉ cho chuyển hướng tới đường dẫn nội bộ (chống open redirect)."""
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else url_for("index")

def login_required(view):
    @functools.wraps(view)
    def wrapper(*a, **k):
        if not current_user():
            flash("Vui lòng đăng nhập để xem đơn hàng", "err")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*a, **k)
    return wrapper

def login_required_api(view):
    """API: bắt buộc đăng nhập mới được đặt hàng. Chưa đăng nhập -> 401 (JS sẽ chuyển tới trang đăng nhập)."""
    @functools.wraps(view)
    def wrapper(*a, **k):
        if not current_user():
            return jsonify(error="Vui lòng đăng nhập để đặt hàng", login=True), 401
        return view(*a, **k)
    return wrapper

def pay_badge(o, admin=False):
    """(nội dung, màu) của nhãn thanh toán cho một đơn hàng."""
    if o["payment_method"] == "cod":
        return "COD - thanh toán khi nhận hàng", "gray"
    return {"paid": ("Đã thanh toán qua PayPal", "ok"),
            "pending": ("PayPal: chờ thanh toán / xác nhận", "warn"),
            "failed": ("PayPal: thanh toán không thành công", "err"),
            "review": ("PayPal: cần kiểm tra thủ công" if admin else "Đang kiểm tra thanh toán", "warn"),
            }.get(o["payment_status"], (o["payment_status"], "gray"))

@app.template_filter("dt")
def fmt_dt(s):
    """CSDL lưu giờ UTC; hiển thị theo giờ Việt Nam (UTC+7)."""
    try:
        return (datetime.strptime(s, "%Y-%m-%d %H:%M:%S") + timedelta(hours=7)).strftime("%H:%M %d/%m/%Y")
    except (TypeError, ValueError):
        return s or ""

def admin_required(view):
    @functools.wraps(view)
    def wrapper(*a, **k):
        u = current_user()
        if not u:
            flash("Vui lòng đăng nhập để tiếp tục", "err")
            nxt = request.full_path.rstrip("?") if request.method == "GET" else ""
            return redirect(url_for("login", next=nxt))
        if u["role"] != "admin":
            abort(403)
        return view(*a, **k)
    return wrapper

@app.get("/")
def index():
    return render_template("index.html", brands=db.brands("laptop"), needs=db.needs())

@app.template_filter("vnd")
def vnd(n):
    return f"{n:,}".replace(",", ".") + " ₫"

@app.get("/product/<int:pid>")
def product(pid):
    p = db.by_ids([pid]).get(pid)
    if not p:
        abort(404)
    acc = db.accessories_for(p) if p["category"] == "laptop" else []
    return render_template("product.html", p=p, specs=db.specs(p["spec"], p["category"]), related=db.related(p), acc=acc,
                           needs=db.needs(), pct=round(100 - p["price"] / p["old"] * 100))

@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html"), 403

@app.get("/api/products")
def products():
    a = request.args
    return jsonify(db.search(a.get("brand", ""), a.get("need", ""), int(a.get("min") or 0),
                             int(a.get("max") or 0) or 10**12, a.get("q", "").strip(), a.get("sort", ""),
                             a.get("cat", "") if a.get("cat") in ("laptop", "accessory") else ""))

def cart_items():
    cart = session.get("cart", {})
    found = db.by_ids([int(i) for i in cart])
    return [dict(found[int(i)], qty=q) for i, q in cart.items() if int(i) in found]

def cart_view():
    items = cart_items()
    total = sum(i["price"] * i["qty"] for i in items)
    return jsonify(items=items, count=sum(i["qty"] for i in items), total=total,
                   usd=paypal.vnd_to_usd(total) if total and paypal.configured() else None,
                   rate=int(paypal.usd_rate()))

@app.get("/api/cart")
def cart_get():
    return cart_view()

@app.post("/api/cart")
def cart_set():
    """JSON: {id, delta} cộng/trừ số lượng; {id, remove:true} xóa."""
    d = request.get_json(force=True)
    pid = int(d.get("id", 0))
    if pid not in db.by_ids([pid]):
        return jsonify(error="Sản phẩm không tồn tại"), 404
    cart, key = session.get("cart", {}), str(pid)
    if d.get("remove"):
        cart.pop(key, None)
    else:
        cart[key] = cart.get(key, 0) + int(d.get("delta", 1))
        if int(d.get("delta", 1)) > 0:
            track("add_to_cart", pid, "button")
        if cart[key] <= 0:
            cart.pop(key)
    session["cart"] = cart
    return cart_view()

def buyer_info(d):
    name, phone = str(d.get("name") or "").strip()[:80], str(d.get("phone") or "").strip()[:20]
    return (name, phone) if name and len(phone) >= 9 else None

@app.post("/api/checkout")
@login_required_api
def checkout():
    d = request.get_json(force=True)
    items = cart_items()
    if not items:
        return jsonify(error="Giỏ hàng đang trống"), 400
    buyer = buyer_info(d)
    if not buyer:
        return jsonify(error="Vui lòng nhập họ tên và số điện thoại"), 400
    track("checkout_start", source="cod")
    oid = db.create_order(*buyer, items, user_id=current_user()["id"])
    track("order_placed", source="cod", value=sum(i["price"] * i["qty"] for i in items))
    session["cart"] = {}
    return jsonify(ok=True, message=f"Đặt hàng thành công, mã đơn #{oid}")

@app.post("/api/chat")
def chat_api():
    data = request.get_json(force=True)
    msgs = [{"role": m["role"], "content": str(m["content"])[:500]}
            for m in (data.get("messages") or [])[-10:]
            if m.get("role") in ("user", "assistant") and m.get("content")]
    while msgs and msgs[0]["role"] == "assistant":  # lịch sử phải mở đầu bằng tin của khách
        msgs.pop(0)
    if not msgs or msgs[-1]["role"] != "user":
        return jsonify(error="Tin nhắn trống"), 400
    pid = str(data.get("product_id") or "")
    product = db.by_ids([int(pid)]).get(int(pid)) if pid.isdigit() else None
    cart = dict(session.get("cart", {}))
    track("chat_message", product["id"] if product else None)
    text, acts = chat.reply(msgs, product, cart)
    # Hành động do chatbot/mô hình đưa ra đều được kiểm tra lại với CSDL và giỏ hiện tại trước khi đụng tới giỏ hàng.
    valid = db.by_ids([a[1] for a in acts if len(a) > 1]) if acts else {}
    changed, rejected = False, 0
    for a in acts:
        if a[0] == "clear":
            changed |= bool(cart); cart = {}
        elif a[1] not in valid:
            rejected += 1
        elif a[0] == "add":
            cart[str(a[1])] = min(20, cart.get(str(a[1]), 0) + a[2]); changed = True
            track("add_to_cart", a[1], "chat")
        elif a[0] == "remove" and str(a[1]) in cart:
            left = cart[str(a[1])] - a[2] if a[2] else 0
            cart.pop(str(a[1])) if left <= 0 else cart.__setitem__(str(a[1]), left); changed = True
        else:
            rejected += 1
    if changed:
        session["cart"] = cart
    if rejected and not changed:
        text = (text + "\n" if text else "") + "(Mình không thực hiện được thay đổi này vì máy không có trong cửa hàng hoặc giỏ hàng.)"
    res = dict(reply=text, provider=chat.provider())
    if changed:
        res["cart"] = cart_view().get_json()
    return jsonify(res)


# ================= Đăng ký / Đăng nhập / Đăng xuất =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("index"))
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email")}
        form["email"] = form["email"].lower()
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        errs = []
        if not 2 <= len(form["name"]) <= 60: errs.append("Họ tên phải từ 2 đến 60 ký tự")
        if not EMAIL_RE.match(form["email"]) or len(form["email"]) > 120: errs.append("Email không hợp lệ")
        if len(pw) < 8: errs.append("Mật khẩu phải có ít nhất 8 ký tự")
        elif pw != pw2: errs.append("Mật khẩu nhập lại không khớp")
        if not errs:
            uid = db.create_user(form["name"], form["email"], generate_password_hash(pw))
            if uid:
                start_session(uid)
                flash("Đăng ký thành công, chào mừng bạn đến với LaptopS!", "ok")
                return redirect(url_for("index"))
            errs.append("Email này đã được đăng ký")
        for e in errs: flash(e, "err")
    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = request.values.get("next", "")
    if current_user():
        return redirect(safe_next(nxt))
    form = {}
    if request.method == "POST":
        form["email"] = request.form.get("email", "").strip().lower()
        u = db.user_by_email(form["email"])
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            start_session(u["id"])
            return redirect(safe_next(nxt))
        flash("Email hoặc mật khẩu không đúng", "err")
    return render_template("login.html", form=form, next=nxt)

@app.post("/logout")
def logout():
    session.clear()
    flash("Bạn đã đăng xuất", "ok")
    return redirect(url_for("index"))

# ================= Quản lý sản phẩm (chỉ Admin) =================
IMG_DIR = os.path.join(app.static_folder, "img", "products")
UPLOADED_IMG = re.compile(r"^/static/img/products/[0-9a-f]{16}\.(png|jpg|webp)$")  # chỉ xóa ảnh do Admin upload

def image_ext(file):
    """Nhận diện loại ảnh theo nội dung thật của file (không tin vào đuôi file). SVG bị từ chối vì có thể chứa script."""
    head = file.stream.read(12)
    file.stream.seek(0)
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return "png"
    if head.startswith(b"\xff\xd8\xff"): return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP": return "webp"
    return None

def save_image(file, ext):
    name = f"{secrets.token_hex(8)}.{ext}"
    file.save(os.path.join(IMG_DIR, name))
    return f"/static/img/products/{name}"

def remove_image(url):
    if url and UPLOADED_IMG.match(url):
        try: os.remove(os.path.join(IMG_DIR, url.rsplit("/", 1)[1]))
        except OSError: pass

def read_product_form(needs):
    f = request.form
    v = {k: f.get(k, "").strip() for k in ("brand", "name", "spec", "price", "old", "category")}
    if v["category"] not in ("laptop", "accessory"): v["category"] = "laptop"
    tags = [t for t in f.getlist("tags") if t in needs]
    errs = []
    for k, label, mx in (("brand", "Hãng", 40), ("name", "Tên sản phẩm", 80), ("spec", "Cấu hình", 300)):
        if not v[k]: errs.append(f"Vui lòng nhập {label.lower()}")
        elif len(v[k]) > mx: errs.append(f"{label} tối đa {mx} ký tự")
    try:
        price, old = int(v["price"]), int(v["old"])
        if price <= 0 or old <= 0: errs.append("Giá phải lớn hơn 0")
        elif old < price: errs.append("Giá gốc phải lớn hơn hoặc bằng giá bán")
        elif max(price, old) > 10**10: errs.append("Giá quá lớn")
    except ValueError:
        price = old = 0
        errs.append("Giá bán và giá gốc phải là số nguyên")
    if not tags and v["category"] == "laptop": errs.append("Hãy chọn ít nhất một nhu cầu")
    img, ext = request.files.get("image"), None
    if img and img.filename:
        ext = image_ext(img)
        if not ext: errs.append("Ảnh phải là PNG, JPG hoặc WEBP")
    else:
        img = None
    return v, dict(price=price, old=old), tags, img, ext, errs

def product_form(pid=None):
    needs = db.needs()
    p = db.by_ids([pid]).get(pid) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        v, n, tags, img, ext, errs = read_product_form(needs)
        if not errs:
            image = save_image(img, ext) if img else None
            db.save_product(pid, v["brand"], v["name"], v["spec"], n["price"], n["old"], image, tags, v["category"])
            if pid and image: remove_image(p["image"])
            flash("Đã cập nhật sản phẩm" if pid else "Đã thêm sản phẩm mới", "ok")
            return redirect(url_for("admin_products"))
        for e in errs: flash(e, "err")
        p = dict(p or {}, brand=v["brand"], name=v["name"], spec=v["spec"], price=v["price"], old=v["old"], tags=tags, category=v["category"])
    return render_template("admin_form.html", p=p, needs=needs)

@app.get("/admin")
@admin_required
def admin_products():
    return render_template("admin_products.html", items=db.search(), needs=db.needs())

@app.get("/admin/funnel")
@admin_required
def admin_funnel():
    return render_template("admin_funnel.html", s=db.funnel_stats())

@app.route("/admin/product/new", methods=["GET", "POST"])
@admin_required
def admin_new():
    return product_form()

@app.route("/admin/product/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit(pid):
    return product_form(pid)

@app.post("/admin/product/<int:pid>/delete")
@admin_required
def admin_delete(pid):
    p = db.by_ids([pid]).get(pid)
    if not p:
        abort(404)
    if db.delete_product(pid):
        remove_image(p["image"])
        flash(f"Đã xóa {p['brand']} {p['name']}", "ok")
    else:
        flash("Không thể xóa: sản phẩm này đã có trong đơn hàng", "err")
    return redirect(url_for("admin_products"))

# ================= Xem đơn hàng =================
@app.get("/orders")
@login_required
def my_orders():
    if current_user()["role"] == "admin":      # Admin không mua hàng qua trang này: đưa thẳng tới danh sách toàn bộ đơn
        return redirect(url_for("admin_orders"))
    return render_template("orders.html", orders=db.orders_for_user(current_user()["id"]))

@app.get("/orders/<int:oid>")
@login_required
def order_view(oid):
    o, u = db.order_detail(oid), current_user()
    # Khách chỉ xem được đơn của mình; Admin xem được mọi đơn. Đơn của người khác trả 404 (không lộ là có tồn tại).
    if not o or (u["role"] != "admin" and o["user_id"] != u["id"]):
        abort(404)
    return render_template("order_detail.html", o=o)

ORDERS_PER_PAGE = 15

@app.get("/admin/orders")
@admin_required
def admin_orders():
    pay, q = request.args.get("pay", ""), request.args.get("q", "").strip()[:60]
    page = max(1, request.args.get("page", 1, type=int))
    rows, total = db.all_orders(pay, q, page, ORDERS_PER_PAGE)
    pages = max(1, -(-total // ORDERS_PER_PAGE))
    if page > pages:
        return redirect(url_for("admin_orders", pay=pay, q=q, page=pages))
    return render_template("admin_orders.html", orders=rows, total=total, page=page, pages=pages, pay=pay, q=q)

# ================= Thanh toán PayPal (sandbox) =================
# Luồng: nút PayPal (trình duyệt) -> /create-order (server tính tiền từ giỏ hàng + tạo đơn PayPal)
#        -> khách đăng nhập & đồng ý trên PayPal -> /capture-order (server thu tiền, đối chiếu rồi mới đánh dấu "đã thanh toán").
# Số tiền luôn do server tính từ CSDL, trình duyệt không thể sửa giá.
def paypal_off():
    return jsonify(error="Thanh toán PayPal chưa được cấu hình"), 503

@app.post("/api/paypal/create-order")
@login_required_api
def paypal_create():
    if not paypal.configured():
        return paypal_off()
    d = request.get_json(silent=True) or {}
    items = cart_items()
    if not items:
        return jsonify(error="Giỏ hàng đang trống"), 400
    buyer = buyer_info(d)
    if not buyer:
        return jsonify(error="Vui lòng nhập họ tên và số điện thoại"), 400
    usd = paypal.vnd_to_usd(sum(i["price"] * i["qty"] for i in items))
    track("checkout_start", source="paypal")
    oid = db.create_order(*buyer, items, method="paypal", status="pending", usd=usd,
                          user_id=current_user()["id"])
    try:
        pp = paypal.create_order(usd, oid, f"create-{oid}")
    except paypal.PayPalError as e:
        app.logger.error("PayPal create-order lỗi (đơn #%s): %s", oid, e)
        db.set_payment(oid, "failed")
        return jsonify(error="Không kết nối được PayPal, vui lòng thử lại"), 502
    db.set_paypal_order(oid, pp["id"])
    session["pp_pending"] = (session.get("pp_pending", []) + [pp["id"]])[-5:]
    return jsonify(id=pp["id"])

@app.post("/api/paypal/capture-order")
@login_required_api
def paypal_capture():
    if not paypal.configured():
        return paypal_off()
    pid = str((request.get_json(silent=True) or {}).get("orderID", ""))
    if pid not in session.get("pp_pending", []):      # chỉ capture đơn do chính phiên này tạo
        return jsonify(error="Giao dịch không hợp lệ"), 400
    o = db.order_by_paypal(pid)
    if not o:
        return jsonify(error="Không tìm thấy đơn hàng"), 404
    if o["payment_status"] != "paid":
        try:
            res = paypal.capture_order(pid)
        except paypal.PayPalError as e:
            app.logger.error("PayPal capture lỗi (đơn #%s): %s", o["id"], e)
            if e.issue == "INSTRUMENT_DECLINED":
                return jsonify(error="PayPal từ chối phương thức thanh toán này, hãy chọn phương thức khác",
                               code=e.issue), 422
            if e.issue == "ORDER_ALREADY_CAPTURED":   # đã thu tiền ở lần gọi trước -> đọc lại trạng thái
                try: res = paypal.get_order(pid)
                except paypal.PayPalError:
                    return jsonify(error="Chưa xác nhận được thanh toán, vui lòng thử lại"), 502
            elif e.status == 0 or e.status >= 500:   # không rõ kết quả: giữ "pending", gọi lại an toàn nhờ PayPal-Request-Id
                return jsonify(error="Chưa xác nhận được thanh toán, vui lòng thử lại (đừng thanh toán lại)"), 502
            else:
                db.set_payment(o["id"], "failed")
                return jsonify(error="Thanh toán không thành công, vui lòng thử lại"), 422
        state, cap_id = paypal.check_capture(res, o["total_usd"], o["id"])
        db.set_payment(o["id"], state if state != "mismatch" else "review", cap_id)
        if state == "mismatch":
            app.logger.error("PayPal: số tiền/đơn không khớp (đơn #%s, capture %s)", o["id"], cap_id)
            return jsonify(error=f"Thông tin thanh toán không khớp, vui lòng liên hệ cửa hàng (đơn #{o['id']})"), 409
        if state == "failed":
            return jsonify(error="Thanh toán không thành công, vui lòng thử lại"), 422
        o["payment_status"] = state
        if state == "paid":
            track("order_placed", source="paypal", value=o["total"])
    session["cart"] = {}   # giữ pid trong phiên: nếu trình duyệt gọi lại do mất phản hồi, server trả lại kết quả "đã thanh toán"
    msg = (f"Thanh toán PayPal thành công, mã đơn #{o['id']}" if o["payment_status"] == "paid"
           else f"Đơn #{o['id']} đang chờ PayPal xác nhận thanh toán")
    return jsonify(ok=True, message=msg, order=o["id"], status=o["payment_status"])

if __name__ == "__main__":
    app.run(debug=True)
