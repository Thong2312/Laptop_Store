import os, sqlite3

DB_PATH = os.getenv("SHOP_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, brand TEXT NOT NULL, name TEXT NOT NULL, spec TEXT NOT NULL,
  price INTEGER NOT NULL, old_price INTEGER NOT NULL, image TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'laptop');
CREATE TABLE IF NOT EXISTS needs(tag TEXT PRIMARY KEY, label TEXT NOT NULL, sort INTEGER);
CREATE TABLE IF NOT EXISTS product_tags(
  product_id INTEGER REFERENCES products(id), tag TEXT REFERENCES needs(tag),
  PRIMARY KEY(product_id, tag));
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, total INTEGER NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  payment_method TEXT NOT NULL DEFAULT 'cod', payment_status TEXT NOT NULL DEFAULT 'unpaid',
  total_usd TEXT, paypal_order_id TEXT, paypal_capture_id TEXT, user_id INTEGER);
CREATE TABLE IF NOT EXISTS order_items(
  order_id INTEGER REFERENCES orders(id), product_id INTEGER REFERENCES products(id),
  qty INTEGER NOT NULL, unit_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
-- Nhật ký sự kiện cho phễu chuyển đổi (visit -> add_to_cart -> checkout_start -> order_placed, cùng sự kiện chat)
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT NOT NULL, type TEXT NOT NULL,
  product_id INTEGER, source TEXT, value INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_sid ON events(sid);
"""

PLACEHOLDER_IMG = "/static/img/products/placeholder.svg"

NEEDS = [("ai", "Laptop AI"), ("game", "Gaming - Đồ họa"), ("student", "Sinh viên - Văn phòng"),
         ("slim", "Mỏng nhẹ"), ("biz", "Doanh nhân")]

# id, hãng, tên, cấu hình, giá bán, giá gốc, nhu cầu
SEED = [
    (1, "Asus", "Zenbook 14 OLED", "Core Ultra 5 225H 1.7 GHz | Intel Arc Graphics | 16GB | 512GB | OLED 3K 120HZ", 32490000, 38990000, "ai slim"),
    (2, "Asus", "ROG Strix G16", "Ryzen 9 Gen 8 | RTX 5060 | 16GB | 512GB | 165Hz", 53990000, 55590000, "game"),
    (3, "Asus", "Vivobook 15", "Ryzen 5 | 16GB | 512GB | FHD", 14490000, 16490000, "student"),
    (4, "HP", "Envy x360 14 AI", "Core Ultra 7 | 16GB | 1TB | 2in1", 25990000, 28990000, "ai slim"),
    (5, "HP", "Victus 15", "Ryzen 7 | RTX 4050 | 16GB | 144Hz", 19990000, 22990000, "game"),
    (6, "HP", "EliteBook 840 G11", "Core Ultra 5 | 16GB | 512GB", 32490000, 35990000, "biz slim"),
    (7, "HP", "15s", "Core i5 | 8GB | 512GB | FHD", 11990000, 13490000, "student"),
    (8, "Acer", "Swift Go 14 AI", "Core Ultra 7 | 16GB | 1TB | OLED", 22990000, 25990000, "ai slim"),
    (9, "Acer", "Nitro V 15", "Core i5 | RTX 4050 | 16GB | 144Hz", 21490000, 23990000, "game"),
    (10, "Acer", "Aspire 5", "Core i5 | 16GB | 512GB | FHD", 13290000, 14990000, "student"),
    (11, "Lenovo", "ThinkPad X1 Carbon", "Core Ultra 7 | 32GB | 1TB | 1.1kg", 44990000, 49990000, "biz slim ai"),
    (12, "Lenovo", "LOQ 15", "Ryzen 7 | RTX 4060 | 16GB | 144Hz", 20990000, 23490000, "game"),
    (13, "MSI", "Prestige 14 AI", "Core Ultra 7 | 32GB | 1TB | 1.4kg", 29990000, 33990000, "ai biz slim"),
    (14, "Dell", "Inspiron 14", "Core i5 | 16GB | 512GB | FHD+", 15490000, 16990000, "student"),
]

# Phụ kiện công nghệ: hãng, tên, cấu hình, giá bán, giá gốc, nhu cầu phù hợp (dùng để gợi ý bán kèm theo laptop)
ACCESSORIES = [
    ("Logitech", "MX Master 3S", "Chuột không dây | Bluetooth | 8000 DPI | Pin 70 ngày", 1890000, 2290000, "biz slim ai"),
    ("Logitech", "M331 Silent", "Chuột không dây | Click êm | 1000 DPI | Pin 24 tháng", 290000, 350000, "student"),
    ("Keychron", "K2 V2", "Bàn phím cơ | Bluetooth | Hot-swap | 75%", 1790000, 1990000, "game student"),
    ("Anker", "PowerPort 65W", "Sạc GaN 65W | USB-C | Sạc nhanh laptop", 790000, 990000, "slim biz ai"),
    ("Sony", "WH-1000XM5", "Tai nghe chống ồn | Bluetooth | Pin 30 giờ", 6990000, 8490000, "biz slim ai"),
    ("Targus", "Urban 15.6", "Balo laptop 15.6 inch | Chống nước | Ngăn chống sốc", 590000, 790000, "student biz"),
    ("Ugreen", "Hub 6in1", "Hub USB-C | HDMI 4K | USB 3.0 | Khe thẻ SD", 690000, 890000, "slim ai student"),
    ("Cooler Master", "NotePal X-Slim", "Đế tản nhiệt | 2 quạt | Laptop đến 15.6 inch", 490000, 650000, "game student"),
    ("Samsung", "T7 1TB", "SSD di động | 1TB | USB 3.2 | 1050MB/s", 2490000, 2990000, "game ai biz"),
]

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

ORDER_COLS = {"payment_method": "TEXT NOT NULL DEFAULT 'cod'", "payment_status": "TEXT NOT NULL DEFAULT 'unpaid'",
              "total_usd": "TEXT", "paypal_order_id": "TEXT", "paypal_capture_id": "TEXT", "user_id": "INTEGER"}

def migrate(c):
    """Bổ sung cột thanh toán cho shop.db được tạo từ phiên bản cũ (đơn cũ mặc định là COD / chưa thanh toán)."""
    have = {r[1] for r in c.execute("PRAGMA table_info(orders)")}
    for col, ddl in ORDER_COLS.items():
        if col not in have:
            c.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")
    if "category" not in {r[1] for r in c.execute("PRAGMA table_info(products)")}:
        c.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'laptop'")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_paypal ON orders(paypal_order_id) WHERE paypal_order_id IS NOT NULL")

def init_db():
    """Tạo bảng và nạp dữ liệu mẫu nếu CSDL còn trống."""
    with conn() as c:
        c.executescript(SCHEMA)
        migrate(c)
        if not c.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
            c.executemany("INSERT INTO needs VALUES(?,?,?)", [(t, l, i) for i, (t, l) in enumerate(NEEDS)])
            for i, brand, name, spec, price, old, tags in SEED:
                c.execute("INSERT INTO products(id, brand, name, spec, price, old_price, image) VALUES(?,?,?,?,?,?,?)",
                          (i, brand, name, spec, price, old, f"/static/img/products/{i}.svg"))
                c.executemany("INSERT INTO product_tags VALUES(?,?)", [(i, t) for t in tags.split()])
        if not c.execute("SELECT 1 FROM products WHERE category = 'accessory' LIMIT 1").fetchone():
            for brand, name, spec, price, old, tags in ACCESSORIES:   # CSDL cũ chưa có phụ kiện: bổ sung (ảnh thay trong trang Quản trị)
                pid = c.execute("INSERT INTO products(brand, name, spec, price, old_price, image, category) VALUES(?,?,?,?,?,?,'accessory')",
                                (brand, name, spec, price, old, PLACEHOLDER_IMG)).lastrowid
                c.executemany("INSERT INTO product_tags VALUES(?,?)", [(pid, t) for t in tags.split()])

BASE = ("SELECT p.*, GROUP_CONCAT(t.tag) AS tags FROM products p "
        "LEFT JOIN product_tags t ON t.product_id = p.id")

def as_product(r):
    d = dict(r)
    d["old"] = d.pop("old_price")
    d["tags"] = d["tags"].split(",") if d["tags"] else []
    return d

def search(brand="", need="", lo=0, hi=10**12, q="", sort="", category=""):
    where, args = ["p.price BETWEEN ? AND ?"], [lo, hi]
    if category: where.append("p.category = ?"); args.append(category)
    if brand: where.append("p.brand = ?"); args.append(brand)
    if need: where.append("EXISTS(SELECT 1 FROM product_tags WHERE product_id = p.id AND tag = ?)"); args.append(need)
    if q: where.append("(p.brand || ' ' || p.name) LIKE ?"); args.append(f"%{q}%")
    order = {"asc": "p.price ASC", "desc": "p.price DESC"}.get(sort, "p.id")
    with conn() as c:
        rows = c.execute(f"{BASE} WHERE {' AND '.join(where)} GROUP BY p.id ORDER BY {order}", args).fetchall()
    return [as_product(r) for r in rows]

def by_ids(ids):
    if not ids: return {}
    with conn() as c:
        rows = c.execute(f"{BASE} WHERE p.id IN ({','.join('?' * len(ids))}) GROUP BY p.id", list(ids)).fetchall()
    return {r["id"]: as_product(r) for r in rows}

def brands(category=""):
    with conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT brand FROM products WHERE (? = '' OR category = ?) ORDER BY brand",
                                        (category, category))]

def needs():
    with conn() as c:
        return {r["tag"]: r["label"] for r in c.execute("SELECT * FROM needs ORDER BY sort")}

def create_order(name, phone, items, method="cod", status="unpaid", usd=None, user_id=None):
    total = sum(i["price"] * i["qty"] for i in items)
    with conn() as c:
        oid = c.execute("INSERT INTO orders(name, phone, total, payment_method, payment_status, total_usd, user_id) VALUES(?,?,?,?,?,?,?)",
                        (name, phone, total, method, status, usd, user_id)).lastrowid
        c.executemany("INSERT INTO order_items VALUES(?,?,?,?)", [(oid, i["id"], i["qty"], i["price"]) for i in items])
    return oid

def set_paypal_order(oid, paypal_id):
    with conn() as c:
        c.execute("UPDATE orders SET paypal_order_id = ? WHERE id = ?", (paypal_id, oid))

def order_by_paypal(paypal_id):
    with conn() as c:
        r = c.execute("SELECT * FROM orders WHERE paypal_order_id = ?", (paypal_id,)).fetchone()
    return dict(r) if r else None

def set_payment(oid, status, capture_id=None):
    """Cập nhật trạng thái thanh toán: pending / paid / failed / review."""
    with conn() as c:
        c.execute("UPDATE orders SET payment_status = ?, paypal_capture_id = COALESCE(?, paypal_capture_id) WHERE id = ?",
                  (status, capture_id, oid))

def specs(spec, category="laptop"):
    """Tách chuỗi cấu hình 'Core i5 | RTX 4050 | 16GB | 512GB | FHD' thành các dòng có nhãn (phụ kiện: mỗi phần là một đặc điểm)."""
    import re
    if category != "laptop":
        return [("Đặc điểm", s.strip()) for s in spec.split("|") if s.strip()]
    out, ram = [], False
    for part in [s.strip() for s in spec.split("|") if s.strip()]:
        if re.match(r"^(Core|Ryzen)", part): out.append(("Bộ xử lý", part))
        elif "RTX" in part or "GTX" in part: out.append(("Card đồ họa", part))
        elif re.match(r"^\d+TB$", part): out.append(("Ổ cứng", part))
        elif re.match(r"^\d+GB$", part):
            out.append(("Ổ cứng", part) if ram else ("RAM", part)); ram = True
        else: out.append(("Màn hình / đặc điểm", part))
    return out

def related(p, limit=4):
    """Máy cùng nhu cầu (ưu tiên) hoặc cùng hãng, trừ chính nó."""
    others = [x for x in search(category=p.get("category", "laptop")) if x["id"] != p["id"]]
    score = lambda x: 2 * len(set(x["tags"]) & set(p["tags"])) + (x["brand"] == p["brand"])
    return sorted(others, key=lambda x: (-score(x), abs(x["price"] - p["price"])))[:limit]

def accessories_for(p, limit=4):
    """Phụ kiện bán kèm một laptop: ưu tiên phụ kiện trùng nhóm nhu cầu với máy (cross-sell), rẻ hơn xếp trước khi bằng điểm."""
    score = lambda x: len(set(x["tags"]) & set(p["tags"]))
    return sorted(search(category="accessory"), key=lambda x: (-score(x), x["price"]))[:limit]


# ---------- Nhật ký sự kiện & phễu chuyển đổi ----------
FUNNEL = [("visit", "Visit (xem trang chủ / sản phẩm)"), ("add_to_cart", "Add to cart"),
          ("checkout_start", "Checkout started"), ("order_placed", "Order placed")]

def log_event(sid, etype, product_id=None, source=None, value=None):
    try:
        with conn() as c:
            c.execute("INSERT INTO events(sid, type, product_id, source, value) VALUES(?,?,?,?,?)",
                      (sid, etype, product_id, source, value))
    except sqlite3.Error:
        pass   # ghi nhật ký không bao giờ được làm hỏng luồng mua hàng

def _stages(sessions):
    """Số phiên đạt từng bước của phễu; một phiên chỉ được tính ở bước n nếu đã qua mọi bước trước đó."""
    out, alive = [], set(sessions)
    for key, label in FUNNEL:
        alive = {s for s in alive if key in sessions[s]["types"]}
        out.append({"key": key, "label": label, "n": len(alive)})
    for i, st in enumerate(out):
        st["pct_prev"] = round(100 * st["n"] / out[i - 1]["n"], 1) if i and out[i - 1]["n"] else None
        st["pct_top"] = round(100 * st["n"] / out[0]["n"], 1) if out[0]["n"] else None
    revenue = sum(sessions[s]["revenue"] for s in alive)
    return out, revenue

def funnel_stats():
    """Phễu toàn cửa hàng, so sánh phiên có dùng chatbot với phiên không dùng, và các chỉ số riêng của chat."""
    with conn() as c:
        rows = c.execute("SELECT sid, type, source, value FROM events").fetchall()
    ses = {}
    for r in rows:
        s = ses.setdefault(r["sid"], {"types": set(), "revenue": 0, "chat_adds": 0, "msgs": 0})
        s["types"].add(r["type"])
        if r["type"] == "order_placed": s["revenue"] += r["value"] or 0
        if r["type"] == "add_to_cart" and r["source"] == "chat": s["chat_adds"] += 1
        if r["type"] == "chat_message": s["msgs"] += 1
    chat = {k: v for k, v in ses.items() if "chat_message" in v["types"]}
    plain = {k: v for k, v in ses.items() if "chat_message" not in v["types"]}
    all_st, all_rev = _stages(ses)
    chat_st, chat_rev = _stages(chat)
    plain_st, plain_rev = _stages(plain)
    n = lambda f: sum(1 for v in ses.values() if f(v))
    return {"all": all_st, "all_rev": all_rev, "chat": chat_st, "chat_rev": chat_rev, "plain": plain_st, "plain_rev": plain_rev,
            "sessions": len(ses), "chat_opened": n(lambda v: "chat_open" in v["types"]),
            "chat_engaged": len(chat), "messages": sum(v["msgs"] for v in ses.values()),
            "chat_cart_sessions": n(lambda v: v["chat_adds"] > 0),
            "product_views": n(lambda v: "product_view" in v["types"])}


# ---------- Người dùng ----------
def create_user(name, email, password_hash, role="user"):
    """Trả về id người dùng mới, hoặc None nếu email đã tồn tại."""
    try:
        with conn() as c:
            return c.execute("INSERT INTO users(name, email, password_hash, role) VALUES(?,?,?,?)",
                             (name, email, password_hash, role)).lastrowid
    except sqlite3.IntegrityError:
        return None

def user_by_email(email):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(r) if r else None

def user_by_id(uid):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(r) if r else None

def admin_exists():
    with conn() as c:
        return c.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None

# ---------- Quản lý sản phẩm (Admin) ----------
def save_product(pid, brand, name, spec, price, old, image, tags, category="laptop"):
    """Thêm mới (pid=None) hoặc cập nhật. image=None: giữ ảnh cũ (khi sửa) / dùng ảnh mặc định (khi thêm)."""
    with conn() as c:
        if pid is None:
            pid = c.execute("INSERT INTO products(brand, name, spec, price, old_price, image, category) VALUES(?,?,?,?,?,?,?)",
                            (brand, name, spec, price, old, image or PLACEHOLDER_IMG, category)).lastrowid
        else:
            c.execute("UPDATE products SET brand=?, name=?, spec=?, price=?, old_price=?, image=COALESCE(?, image), category=? WHERE id=?",
                      (brand, name, spec, price, old, image, category, pid))
            c.execute("DELETE FROM product_tags WHERE product_id = ?", (pid,))
        c.executemany("INSERT INTO product_tags VALUES(?,?)", [(pid, t) for t in tags])
    return pid

def delete_product(pid):
    """Xóa sản phẩm. Trả về False nếu sản phẩm đã nằm trong đơn hàng (giữ lại để không mất lịch sử đơn)."""
    with conn() as c:
        if c.execute("SELECT 1 FROM order_items WHERE product_id = ?", (pid,)).fetchone():
            return False
        c.execute("DELETE FROM product_tags WHERE product_id = ?", (pid,))
        c.execute("DELETE FROM products WHERE id = ?", (pid,))
    return True


# ---------- Xem đơn hàng ----------
ORDER_SELECT = ("SELECT o.*, u.name AS user_name, u.email AS user_email, "
                "(SELECT COALESCE(SUM(qty), 0) FROM order_items WHERE order_id = o.id) AS n_items "
                "FROM orders o LEFT JOIN users u ON u.id = o.user_id")

def orders_for_user(uid):
    """Đơn hàng của một khách (mới nhất trước)."""
    with conn() as c:
        return [dict(r) for r in c.execute(f"{ORDER_SELECT} WHERE o.user_id = ? ORDER BY o.id DESC", (uid,))]

def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

def all_orders(pay="", q="", page=1, per=15):
    """Tất cả đơn hàng (Admin). pay: cod | paid | pending | failed | review. q: mã đơn, tên, SĐT hoặc email.
    Trả về (danh sách đơn của trang, tổng số đơn khớp bộ lọc)."""
    where, args = [], []
    if pay == "cod":
        where.append("o.payment_method = 'cod'")
    elif pay in ("paid", "pending", "failed", "review"):
        where.append("o.payment_method = 'paypal' AND o.payment_status = ?"); args.append(pay)
    q = q.strip()
    if q:
        num = q.lstrip("#")
        if num.isdigit() and len(num) < 6:      # số ngắn: chỉ là mã đơn (tránh khớp bừa vào SĐT)
            where.append("o.id = ?"); args.append(int(num))
        elif num.isdigit():                      # số dài: SĐT (hoặc mã đơn)
            where.append("(o.id = ? OR o.phone LIKE ? ESCAPE '\\')"); args += [int(num), _like(num)]
        else:
            where.append("(o.name LIKE ? ESCAPE '\\' OR o.phone LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' OR u.name LIKE ? ESCAPE '\\')")
            args += [_like(q)] * 4
    w = (" WHERE " + " AND ".join(where)) if where else ""
    with conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM orders o LEFT JOIN users u ON u.id = o.user_id{w}", args).fetchone()[0]
        rows = c.execute(f"{ORDER_SELECT}{w} ORDER BY o.id DESC LIMIT ? OFFSET ?",
                         args + [per, max(0, page - 1) * per]).fetchall()
    return [dict(r) for r in rows], total

def order_detail(oid):
    """Một đơn hàng kèm danh sách sản phẩm; None nếu không tồn tại."""
    with conn() as c:
        r = c.execute(f"{ORDER_SELECT} WHERE o.id = ?", (oid,)).fetchone()
        if not r:
            return None
        items = c.execute("SELECT oi.product_id, oi.qty, oi.unit_price, p.brand, p.name, p.image "
                          "FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id "
                          "WHERE oi.order_id = ?", (oid,)).fetchall()
    d = dict(r)
    d["items"] = [dict(i) for i in items]
    return d
