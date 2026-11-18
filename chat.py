"""Chatbot tư vấn. Chọn nhà cung cấp bằng biến môi trường CHAT_PROVIDER:
   gemini  - Google AI Studio (GEMINI_API_KEY hoặc GOOGLE_API_KEY; tùy chọn GEMINI_MODEL)
   claude  - Claude API (ANTHROPIC_API_KEY; tùy chọn CLAUDE_MODEL)
   local   - máy chủ tương thích OpenAI chạy local, vd vLLM/SGLang/Ollama (LOCAL_LLM_URL, LOCAL_MODEL)
   offline - luật đơn giản, không cần mô hình
Bỏ trống: tự chọn theo thứ tự gemini > claude > local nếu có khóa/địa chỉ tương ứng, còn lại offline."""
import json, os, re, threading, time, urllib.error, urllib.request
import db

SYSTEM = """Bạn là trợ lý tư vấn của cửa hàng laptop LaptopS. Trả lời bằng tiếng Việt, thân thiện, tối đa khoảng 120 từ.
Chỉ tư vấn các sản phẩm (laptop và phụ kiện) trong danh mục dưới đây. Không bịa cấu hình, giá hay khuyến mãi; nếu không có máy phù hợp thì nói thẳng.
Khi gợi ý, nêu tên máy và giá, tối đa 3 máy. Mỗi lượt hỏi lại khách không quá một câu.
Mỗi máy trong danh mục có mã dạng [#số].
THÊM VÀO GIỎ: chỉ khi khách nói rõ muốn thêm/bỏ/cho/mua một máy vào giỏ hàng, hãy xác nhận ngắn gọn và kết thúc câu trả lời bằng
một thẻ cho mỗi máy theo đúng cú pháp [[THEM:mã:số_lượng]], ví dụ [[THEM:3:1]]. Không có thẻ thì giỏ hàng không thay đổi.
Không tự thêm khi khách chỉ hỏi hoặc nhờ tư vấn. Nếu chưa rõ khách muốn máy nào, hỏi lại và không kèm thẻ. Không nhắc đến thẻ này với khách.
XÓA KHỎI GIỎ: khi khách nói rõ muốn xóa/bỏ/loại một máy khỏi giỏ, xác nhận ngắn gọn và thêm thẻ [[XOA:mã]] (xóa cả dòng) hoặc
[[XOA:mã:số_lượng]] (chỉ giảm bớt số lượng). Khách muốn làm trống giỏ thì dùng thẻ [[XOA:TATCA]]. Chỉ xóa máy đang có trong "Giỏ hàng hiện tại".
BÁN KÈM: khi khách đã chọn hoặc đang xem một laptop, có thể gợi ý 1-2 phụ kiện phù hợp trong mục Phụ kiện (nêu tên và giá), chỉ một lần
mỗi cuộc trò chuyện, nhẹ nhàng, không ép mua; khách từ chối thì thôi. Phụ kiện cũng thêm vào giỏ bằng thẻ [[THEM:mã:số_lượng]] như laptop.
Khách chỉ đặt hàng được sau khi đăng nhập; bạn chỉ thêm/xóa trong giỏ, không tự đặt hàng.
Danh mục:
{catalog}"""

PRODUCT_CTX = """
Khách đang xem trang chi tiết của máy: {line}
"Máy này", "con này", "nó" nghĩa là máy đó. Hãy đánh giá dựa trên cấu hình ghi ở trên; có thể dùng hiểu biết chung về linh kiện
(ví dụ RTX 4050 là card đồ họa tầm trung phổ thông) nhưng nói rõ đó là nhận định chung. Thông tin không có trong cấu hình
(pin, cổng kết nối, độ sáng màn hình, bảo hành...) thì nói chưa có dữ liệu, không đoán. Nếu máy không hợp nhu cầu của khách,
nói thẳng và gợi ý máy khác trong danh mục."""

def provider():
    p = os.getenv("CHAT_PROVIDER", "").lower()
    if p in ("gemini", "claude", "local", "offline"):
        return p
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"): return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"): return "claude"
    return "local" if os.getenv("LOCAL_LLM_URL") else "offline"

def money(n):
    return f"{n:,}".replace(",", ".") + "đ"

def line(p, needs):
    return f"{p['brand']} {p['name']} | {money(p['price'])} | {p['spec']} | {', '.join(needs[t] for t in p['tags'])}"

def build_system(product=None, cart=None):
    needs = db.needs()
    rows = lambda cat: "\n".join(f"- [#{p['id']}] " + line(p, needs) for p in db.search(category=cat))
    s = SYSTEM.format(catalog="Laptop:\n" + rows("laptop") + "\nPhụ kiện:\n" + rows("accessory"))
    s += (PRODUCT_CTX.format(line=f"[#{product['id']}] " + line(product, needs)) if product else "")
    held = db.by_ids([int(i) for i in cart]) if cart else {}
    return s + "\nGiỏ hàng hiện tại: " + (", ".join(f"[#{i}] {held[int(i)]['brand']} {held[int(i)]['name']} × {q}"
                                              for i, q in cart.items() if int(i) in held) or "trống")

# ---- Thêm / xóa sản phẩm trong giỏ qua chatbot ----
# Hành động: ("add", mã, số lượng) | ("remove", mã, số lượng hoặc None = xóa cả dòng) | ("clear",)
MAX_QTY = 20
TAG_RE = re.compile(r"\[\[\s*(THEM|XOA)\s*:\s*(\d+|TATCA)\s*(?::\s*(\d+))?\s*\]\]", re.I)

def parse_actions(text):
    """Tách thẻ [[THEM:mã:sl]], [[XOA:mã(:sl)]], [[XOA:TATCA]] khỏi câu trả lời của mô hình -> (văn bản sạch, [hành động]).
    Mã sai sẽ bị bỏ ở bước kiểm tra phía server."""
    acts = []
    for m in TAG_RE.finditer(text):
        kind, ref, n = m[1].upper(), m[2].upper(), m[3]
        qty = min(MAX_QTY, max(1, int(n))) if n else None
        if kind == "THEM" and ref.isdigit():
            acts.append(("add", int(ref), qty or 1))
        elif kind == "XOA":
            acts.append(("clear",) if ref == "TATCA" else ("remove", int(ref), qty))
    return TAG_RE.sub("", text).strip(), acts[:5]

ADD_INTENT = re.compile(r"\b(thêm|bỏ|cho|đặt|mua|lấy|nhét|add)\b.*\bgiỏ\b|\bgiỏ\b.*\b(thêm|bỏ|cho|đặt|mua|lấy|add)\b")
# "xóa/loại/gỡ/hủy ... giỏ", "bỏ/lấy/bớt ... ra khỏi giỏ", "bớt 1 cái ..."; (khác với "bỏ ... vào giỏ" = thêm)
REMOVE_INTENT = re.compile(r"\b(xóa|xoá|loại|gỡ|hủy|huỷ|dọn)\b|\b(bỏ|lấy|bớt)\b.*\b(khỏi|ra khỏi)\b.*\bgiỏ\b|\bbớt\b|\blàm trống\b")
CLEAR_ALL = re.compile(r"\b(hết|tất cả|toàn bộ|sạch)\b|làm trống|dọn.*giỏ|giỏ.*\b(trống|sạch)\b")
NUM_WORDS = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5}

def match_products(t, product=None, pool=None):
    """Tìm các máy được nhắc tới trong câu: khớp tên đầy đủ hoặc tên dòng máy (từ đầu của tên: "zenbook", "nitro", "rog"...)."""
    word = lambda w: re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t)
    hit = [p for p in (pool if pool is not None else db.search()) if word(p["name"].lower()) or word(p["name"].lower().split()[0])]
    if not hit and product and re.search(r"\b(này|nó)\b", t):
        hit = [product]
    return hit[:5]

def qty_in(t):
    m = re.search(r"(\d+)\s*(?:cái|chiếc|máy|con|bộ)\b", t) or re.search(r"\b(" + "|".join(NUM_WORDS) + r")\s*(?:cái|chiếc|máy|con|bộ)\b", t)
    return min(MAX_QTY, max(1, NUM_WORDS.get(m[1]) or int(m[1]))) if m else None

SEG_SPLIT = re.compile(r"\s*(?:,|;|\+|&|\bvà\b|\bvới\b|\bcùng với\b|\bcộng\b)\s*")
QTY_UNIT = r"(?:cái|chiếc|máy|con|bộ)"

def seg_qty(seg):
    """Số lượng trong một đoạn câu: "3 chiếc nitro", "hai cái zenbook", "victus x2". Số đứng trơn sau tên không tính ("vivobook 15" là tên máy)."""
    m = (re.search(rf"(?<!\w)(\d+)\s*{QTY_UNIT}(?!\w)", seg) or re.search(r"(?<!\w)[x×]\s*(\d+)(?!\w)", seg)
         or re.search(rf"(?<!\w)({'|'.join(NUM_WORDS)})\s*{QTY_UNIT}(?!\w)", seg))
    return min(MAX_QTY, max(1, NUM_WORDS.get(m[1]) or int(m[1]))) if m else None

def items_in(t, product=None, pool=None):
    """Các máy được nhắc tới kèm số lượng riêng của từng máy: [(máy, số lượng hoặc None)].
    Câu được tách theo dấu phẩy/"và"/"+"; "mỗi máy 2 cái" áp dụng cho tất cả máy trong câu."""
    each = re.search(rf"\b(?:mỗi|từng)\s+(?:máy|loại|con|cái|chiếc)?\s*(\d+)\s*{QTY_UNIT}?", t)
    out = {}
    for seg in SEG_SPLIT.split(t):
        for p in match_products(seg, None, pool):
            out[p["id"]] = (p, seg_qty(seg) or (min(MAX_QTY, int(each[1])) if each else None))
    if not out:
        for p in match_products(t, product, pool):   # "máy này", "nó"
            out[p["id"]] = (p, qty_in(t))
    return list(out.values())[:5]

def cart_request(text, product=None, cart=None):
    """Nhận diện yêu cầu thêm/xóa giỏ bằng luật (không cần AI). Trả về None nếu không phải yêu cầu về giỏ hàng, hoặc
    (câu trả lời, [hành động])."""
    t, cart = text.lower(), cart or {}
    if REMOVE_INTENT.search(t):
        # "loại"/"dọn"... cũng có nghĩa khác trong câu tư vấn thường ("loại nào tốt?"), nên cần có "giỏ", hoặc nhắc máy đang có trong giỏ,
        # hoặc đang xem trang một máy và nói "xóa máy này".
        in_cart = db.by_ids([int(i) for i in cart]).values()
        if "giỏ" in t or match_products(t, None, in_cart) or (product and re.search(r"\b(này|nó)\b", t)):
            return remove_request(t, product, cart)
    if ADD_INTENT.search(t):
        its = items_in(t, product)
        if not its:
            return "Bạn muốn thêm máy nào vào giỏ? Hãy cho mình tên máy (ví dụ: Asus Zenbook 14 OLED).", []
        its = [(p, q or 1) for p, q in its]
        return ("Đã thêm vào giỏ hàng: " + ", ".join(f"{q} × {p['brand']} {p['name']}" for p, q in its) + ". Bạn cần đăng nhập để đặt hàng nhé.",
                [("add", p["id"], q) for p, q in its])
    return None

def remove_request(t, product, cart):
    if not cart:
        return "Giỏ hàng của bạn đang trống.", []
    held = db.by_ids([int(i) for i in cart])
    inside = [p for p in held.values()]
    if CLEAR_ALL.search(t) and not match_products(t, None, inside):
        return "Đã xóa toàn bộ sản phẩm khỏi giỏ hàng.", [("clear",)]
    its = items_in(t, product, inside)
    if not its:   # có thể khách nhắc máy không có trong giỏ, hoặc chưa nêu tên
        named = items_in(t, product)
        if named:
            return ", ".join(f"{p['brand']} {p['name']}" for p, _ in named) + " hiện không có trong giỏ hàng của bạn.", []
        return ("Bạn muốn xóa máy nào? Trong giỏ đang có: " + ", ".join(f"{p['brand']} {p['name']}" for p in inside) + "."), []
    out, acts = [], []
    for p, n in its:
        cur, name = cart.get(str(p["id"]), 0), f"{p['brand']} {p['name']}"
        # "bớt" hoặc có nêu số lượng ("xóa 2 cái nitro") -> chỉ giảm; còn lại xóa cả dòng
        if (n or "bớt" in t) and (n or 1) < cur:
            n = n or 1
            acts.append(("remove", p["id"], n)); out.append(f"giảm {n} × {name} (còn {cur - n})")
        else:
            acts.append(("remove", p["id"], None)); out.append(f"xóa {name}")
    named_out = [p for p, _ in items_in(t, product)]
    miss = [f"{p['brand']} {p['name']}" for p in named_out if str(p["id"]) not in cart]
    return "Đã " + ", ".join(out) + " trong giỏ hàng." + (f" ({', '.join(miss)} không có trong giỏ.)" if miss else ""), acts

def via_gemini(msgs, system):
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in msgs],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.7,
                                 "thinkingConfig": {"thinkingLevel": os.getenv("GEMINI_THINKING", "low")}}}

    def post(b):
        req = urllib.request.Request(url, json.dumps(b).encode(), {"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=int(os.getenv("AI_TIMEOUT", "240"))) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Gemini HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")

    try:
        data = post(body)
    except RuntimeError as e:
        if "HTTP 400" not in str(e): raise
        body["generationConfig"].pop("thinkingConfig")  # model không hỗ trợ thinkingLevel: thử lại không có
        data = post(body)
    parts = data["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise ValueError("Gemini trả về nội dung rỗng")
    return text

def via_claude(msgs, system):
    import anthropic
    r = anthropic.Anthropic().messages.create(model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
                                              max_tokens=500, system=system, messages=msgs)
    return r.content[0].text

def via_local(msgs, system):
    url = os.getenv("LOCAL_LLM_URL", "http://localhost:1235/v1").rstrip("/") + "/chat/completions"
    body = {"model": os.getenv("LOCAL_MODEL", "Qwen/Qwen3.8-27B"), "max_tokens": 500, "temperature": 0.7,
            "messages": [{"role": "system", "content": system}] + msgs,
            "chat_template_kwargs": {"enable_thinking": False}}  # tắt chế độ suy nghĩ để trả lời nhanh
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        text = json.load(r)["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

def budget(t):
    """Trả về (giá thấp nhất, giá cao nhất) tính bằng đồng; 0 nghĩa là không giới hạn."""
    t = t.replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:triệu|tr)?\s*(?:-|–|—|đến|tới)\s*(\d+(?:\.\d+)?)\s*(?:triệu|tr)\b", t)
    if m:
        a, b = sorted((float(m[1]), float(m[2])))
        return int(a * 1e6), int(b * 1e6)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:triệu|tr)\b", t)
    if not m: return 0, 0
    v = int(float(m[1]) * 1e6)
    if re.search(r"\b(trên|từ|hơn|ít nhất)\b", t) and not re.search(r"\b(dưới|tối đa|không quá)\b", t):
        return v, 0
    return 0, v

KEYS = {"gaming": "game", "game": "game", "đồ họa": "game", "ai": "ai", "sinh viên": "student",
        "văn phòng": "student", "mỏng": "slim", "nhẹ": "slim", "doanh nhân": "biz"}

def offline(msgs, product=None):
    t = msgs[-1]["content"].lower()
    need = next((v for k, v in KEYS.items() if re.search(rf"\b{k}\b", t)), "")
    if product and re.search(r"\bnày\b", t):
        needs, name = db.needs(), f"{product['brand']} {product['name']}"
        if need:
            ok = need in product["tags"]
            return (f"{name} {'thuộc' if ok else 'không thuộc'} nhóm {needs[need]} của cửa hàng. Cấu hình: {product['spec']}."
                    + ("" if ok else f" Bạn có thể xem các máy nhóm này ở trang chủ (mục {needs[need]})."))
        return f"{name} giá {money(product['price'])}, cấu hình {product['spec']}, phù hợp: {', '.join(needs[x] for x in product['tags'])}. Bạn muốn biết máy này hợp với nhu cầu nào?"
    brand = next((b for b in db.brands("laptop") if b.lower() in t), "")
    lo, hi = budget(t)
    found = db.search(brand, need, lo, hi or 10**12, "", "asc", "laptop")[:3]
    if not (need or brand or lo or hi):
        return "Bạn cho mình biết nhu cầu (gaming, sinh viên, mỏng nhẹ...), hãng yêu thích hoặc ngân sách nhé, mình sẽ gợi ý máy phù hợp."
    if not found:
        return "Hiện chưa có máy nào khớp đủ các điều kiện bạn nêu. Bạn thử nới khoảng giá hoặc bỏ bớt điều kiện nhé."
    return "Mình gợi ý:\n" + "\n".join(f"- {p['brand']} {p['name']} ({money(p['price'])}): {p['spec']}" for p in found)

_calls, _lock = [], threading.Lock()

def allowed():
    """Chặn gọi AI quá hạn mức. Mặc định cho Gemini: 4 lượt/phút, 18 lượt/ngày (gói miễn phí hiện là 5/phút, 20/ngày
    cho gemini-3.6-flash). Đổi bằng AI_MAX_PER_MIN / AI_MAX_PER_DAY, 0 là không giới hạn. Bộ đếm nằm trong bộ nhớ,
    chỉ mang tính ước lượng và reset khi khởi động lại server."""
    g = provider() == "gemini"
    per_min, per_day = int(os.getenv("AI_MAX_PER_MIN", "4" if g else "0")), int(os.getenv("AI_MAX_PER_DAY", "18" if g else "0"))
    now = time.time()
    with _lock:
        _calls[:] = [t for t in _calls if now - t < 86400]
        if (per_min and sum(now - t < 60 for t in _calls) >= per_min) or (per_day and len(_calls) >= per_day):
            return False
        _calls.append(now)
        return True

def reply(msgs, product=None, cart=None):
    """Trả về (câu trả lời, [hành động giỏ hàng]); cart là giỏ hiện tại {"id": số lượng} của khách."""
    req = cart_request(msgs[-1]["content"], product, cart)   # yêu cầu rõ ràng: xử lý bằng luật, nhanh và không tốn lượt AI
    if req:
        return req
    text = _reply(msgs, product, cart)
    return parse_actions(text) if provider() in ("gemini", "claude", "local") else (text, [])

def _reply(msgs, product=None, cart=None):
    p = provider()
    fn = {"gemini": via_gemini, "claude": via_claude, "local": via_local}.get(p)
    if not fn:
        return offline(msgs, product)
    if not allowed():
        return offline(msgs, product) + "\n(Đã tạm dừng gọi AI để tránh vượt giới hạn lượt miễn phí, đây là gợi ý tự động.)"
    try:
        return fn(msgs, build_system(product, cart))
    except Exception as e:
        print("chatbot error:", repr(e))
        why = ("đã chạm giới hạn lượt gọi AI" if "429" in str(e) else
               "AI phản hồi quá chậm" if "timed out" in str(e) else "Trợ lý AI đang gặp sự cố")
        return offline(msgs, product) + f"\n({why}, đây là gợi ý tự động.)"
