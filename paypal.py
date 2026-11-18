"""Thanh toán PayPal (Orders v2, intent CAPTURE). Mặc định chạy ở môi trường SANDBOX.

Biến môi trường:
  PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET   Lấy ở https://developer.paypal.com > Apps & Credentials > Sandbox
  PAYPAL_MODE                              "sandbox" (mặc định) hoặc "live"
  PAYPAL_USD_VND_RATE                      Tỷ giá quy đổi, mặc định 25000 (1 USD = 25.000 ₫)

PayPal không hỗ trợ VND nên số tiền được quy đổi sang USD ở phía server.
Khóa bí mật (SECRET) chỉ nằm ở server, không bao giờ gửi xuống trình duyệt.
"""
import base64, json, os, threading, time, urllib.error, urllib.parse, urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TIMEOUT = 15
_lock = threading.Lock()
_token = {"value": None, "exp": 0.0}


class PayPalError(Exception):
    def __init__(self, status, issue="", message="", debug_id=""):
        super().__init__(f"PayPal {status} {issue}: {message} (debug_id={debug_id})")
        self.status, self.issue, self.debug_id = status, issue, debug_id


def client_id():
    return os.getenv("PAYPAL_CLIENT_ID", "").strip()

def configured():
    return bool(client_id() and os.getenv("PAYPAL_CLIENT_SECRET", "").strip())

def base_url():
    return "https://api-m.paypal.com" if os.getenv("PAYPAL_MODE", "sandbox").lower() == "live" \
        else "https://api-m.sandbox.paypal.com"

def usd_rate():
    try:
        r = Decimal(os.getenv("PAYPAL_USD_VND_RATE", "25000"))
        return r if r > 0 else Decimal(25000)
    except InvalidOperation:
        return Decimal(25000)

def vnd_to_usd(vnd):
    """Quy đổi VND -> chuỗi USD 2 chữ số thập phân (PayPal yêu cầu dạng chuỗi, vd '1299.60')."""
    usd = (Decimal(int(vnd)) / usd_rate()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(max(usd, Decimal("0.01")))


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        detail = (body.get("details") or [{}])[0]
        raise PayPalError(e.code, detail.get("issue") or body.get("name", ""),
                          body.get("message", ""), body.get("debug_id", "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PayPalError(0, "NETWORK", str(e)) from None


def access_token():
    with _lock:
        if _token["value"] and time.time() < _token["exp"] - 60:
            return _token["value"]
        cred = base64.b64encode(f"{client_id()}:{os.getenv('PAYPAL_CLIENT_SECRET', '').strip()}".encode()).decode()
        req = urllib.request.Request(base_url() + "/v1/oauth2/token",
                                     data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
                                     headers={"Authorization": "Basic " + cred,
                                              "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        d = _send(req)
        _token.update(value=d["access_token"], exp=time.time() + int(d.get("expires_in", 300)))
        return _token["value"]


def _api(method, path, body=None, request_id=None):
    headers = {"Authorization": "Bearer " + access_token(), "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id   # chống tạo/capture trùng khi gọi lại
    data = json.dumps(body).encode() if body is not None else None
    return _send(urllib.request.Request(base_url() + path, data=data, headers=headers, method=method))


def create_order(usd, local_id, request_id):
    return _api("POST", "/v2/checkout/orders", {
        "intent": "CAPTURE",
        "purchase_units": [{"reference_id": str(local_id), "custom_id": str(local_id),
                            "description": f"LaptopS - don hang #{local_id}",
                            "amount": {"currency_code": "USD", "value": usd}}],
    }, request_id=request_id)

def capture_order(paypal_id):
    return _api("POST", f"/v2/checkout/orders/{urllib.parse.quote(paypal_id, safe='')}/capture", {},
                request_id=f"capture-{paypal_id}")

def get_order(paypal_id):
    return _api("GET", f"/v2/checkout/orders/{urllib.parse.quote(paypal_id, safe='')}")


def check_capture(result, expected_usd, local_id):
    """Đối chiếu kết quả PayPal với đơn hàng trong CSDL.
    Trả về (trạng thái, capture_id): paid | pending | failed | mismatch."""
    try:
        unit = (result.get("purchase_units") or [{}])[0]
        cap = ((unit.get("payments") or {}).get("captures") or [None])[0]
        if not cap:
            return "failed", None
        amount = cap.get("amount") or {}
        if (str(unit.get("reference_id")) != str(local_id) or amount.get("currency_code") != "USD"
                or Decimal(amount.get("value", "")) != Decimal(expected_usd)):
            return "mismatch", cap.get("id")
    except (InvalidOperation, AttributeError, TypeError):
        return "failed", None
    status = cap.get("status")
    if status == "COMPLETED" and result.get("status") == "COMPLETED":
        return "paid", cap.get("id")
    if status == "PENDING":
        return "pending", cap.get("id")
    return "failed", cap.get("id")
