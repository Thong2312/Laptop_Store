const $ = s => document.querySelector(s);
const vnd = n => n.toLocaleString("vi-VN") + " ₫";
const U = new URLSearchParams(location.search);
const f = {brand: U.get("brand") || "", need: U.get("need") || "", q: U.get("q") || "", cat: U.get("cat") === "accessory" ? "accessory" : "laptop"};
const nvOn = c => (c.dataset.cat || "laptop") === f.cat && c.dataset.need === f.need;

async function api(url, body) {
  const r = await fetch(url, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  const j = await r.json();
  if (r.status === 401 && j.login) {   // chưa đăng nhập -> chuyển tới trang đăng nhập, quay lại trang hiện tại sau khi xong
    toast(j.error);
    setTimeout(() => location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search), 700);
  }
  return j;
}
function toast(m) {
  const e = $("#toast"); e.textContent = m; e.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove("on"), 1600);
}

async function loadProducts() {
  let lo = +$("#lo").value, hi = +$("#hi").value;
  if (lo > hi) [lo, hi] = [hi, lo];
  const acc = f.cat === "accessory";   // phụ kiện giá thấp: bỏ qua thanh giá (tính theo triệu cho laptop) và bộ lọc hãng laptop
  if (acc) f.brand = "";
  if ($("#brandRow")) $("#brandRow").style.display = acc ? "none" : "";
  $("#plabel").textContent = acc ? "Mọi mức giá" : `${lo} - ${hi} triệu` + (hi === 50 ? "+" : "");
  $("#fill").style.left = (lo - 10) / 40 * 100 + "%";
  $("#fill").style.right = 100 - (hi - 10) / 40 * 100 + "%";
  const p = new URLSearchParams({brand: f.brand, need: f.need, q: f.q, cat: f.cat, sort: $("#sort").value, min: acc ? 0 : lo * 1e6, max: acc || hi === 50 ? 0 : hi * 1e6});
  const list = await api("/api/products?" + p);
  $("#count").textContent = `${list.length} ${acc ? "phụ kiện" : "laptop"}`;
  $("#grid").innerHTML = list.length ? list.map(x => `<div class="card"><a class="img" href="/product/${x.id}"><img src="${x.image}" alt="${x.brand} ${x.name}" loading="lazy"><span class="off">-${Math.round(100 - x.price / x.old * 100)}%</span></a>
    <a class="nm" href="/product/${x.id}">${x.brand} ${x.name}</a><div class="sp">${x.spec}</div>
    <div class="pr">${vnd(x.price)}<span class="old">${vnd(x.old)}</span></div>
    <button class="add" data-id="${x.id}">Thêm vào giỏ</button></div>`).join("")
    : `<div class="empty">Không có sản phẩm phù hợp. Hãy nới bộ lọc giá hoặc chọn hãng khác.</div>`;
}

function drawCart(c) {
  $("#cnt").textContent = c.count; $("#total").textContent = vnd(c.total);
  if ($("#ppnote")) $("#ppnote").textContent = c.usd ? `PayPal tính bằng USD: ≈ $${c.usd} (tỷ giá 1 USD = ${c.rate.toLocaleString("vi-VN")} ₫)` : "";
  $("#items").innerHTML = c.items.length ? c.items.map(i => `<div class="it"><div><b>${i.brand} ${i.name}</b><div class="sp">${vnd(i.price)}</div>
    <div class="q"><button data-id="${i.id}" data-d="-1">−</button><span>${i.qty}</span><button data-id="${i.id}" data-d="1">+</button></div></div>
    <div style="text-align:right"><b>${vnd(i.price * i.qty)}</b><br><button class="rm" data-id="${i.id}" data-rm="1">Xóa</button></div></div>`).join("")
    : `<div class="empty">Giỏ hàng trống. Chọn một chiếc laptop để bắt đầu.</div>`;
}
const openCart = o => { $("#drawer").classList.toggle("on", o); $("#ov").classList.toggle("on", o); };

document.addEventListener("click", async e => {
  const t = e.target;
  if (t.matches(".add")) { drawCart(await api("/api/cart", {id: +t.dataset.id, delta: t.dataset.detail ? Math.min(20, Math.max(1, +$("#qty").value || 1)) : 1})); toast("Đã thêm vào giỏ hàng"); if (t.dataset.buy) openCart(true); }
  else if (t.closest("#items") && t.dataset.id) drawCart(await api("/api/cart", t.dataset.rm ? {id: +t.dataset.id, remove: true} : {id: +t.dataset.id, delta: +t.dataset.d}));
  else if (t.matches(".chip")) { f.brand = t.dataset.brand; document.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", c === t)); loadProducts(); }
  else if (t.matches(".nv")) { f.need = t.dataset.need; f.cat = t.dataset.cat || "laptop"; document.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", c.dataset.brand === f.brand)); document.querySelectorAll(".nv").forEach(c => c.classList.toggle("on", c === t)); loadProducts(); }
  else if (t.closest("#cartBtn")) openCart(true);
  else if (t.id === "close" || t.id === "ov") openCart(false);
});
$("#co").onclick = async () => {
  const r = await api("/api/checkout", {name: $("#cname").value, phone: $("#cphone").value}); toast(r.message || r.error);
  if (r.ok) { drawCart(await api("/api/cart")); openCart(false); }
};
["#lo", "#hi", "#sort"].forEach(s => $(s) && ($(s).oninput = loadProducts));
$("#searchForm").onsubmit = e => {
  e.preventDefault(); f.q = $("#q").value;
  if ($("#grid")) loadProducts(); else location.href = "/?q=" + encodeURIComponent(f.q);
};
document.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", c.dataset.brand === f.brand));
document.querySelectorAll(".nv").forEach(c => c.classList.toggle("on", nvOn(c)));
$("#q").value = f.q;
if ($("#qty")) {
  const q = $("#qty");
  $("#qm").onclick = () => q.value = Math.max(1, (+q.value || 1) - 1);
  $("#qp").onclick = () => q.value = Math.min(20, (+q.value || 1) + 1);
}
if ($("#grid")) loadProducts();
api("/api/cart").then(drawCart);

// ---- Thanh toán PayPal (sandbox). Server tính tiền, trình duyệt chỉ hiện nút và chuyển tiếp mã đơn.
let ppShown = false;
function ppFail(msg) { ppShown = true; toast(msg); throw new Error(msg); }
if ($("#paypal-buttons") && window.paypal) {
  paypal.Buttons({
    style: {layout: "vertical", shape: "rect", label: "pay"},
    async createOrder() {
      ppShown = false;
      const r = await api("/api/paypal/create-order", {name: $("#cname").value, phone: $("#cphone").value});
      if (!r.id) ppFail(r.error || "Không tạo được đơn PayPal");
      return r.id;
    },
    async onApprove(data, actions) {
      ppShown = false;
      const r = await api("/api/paypal/capture-order", {orderID: data.orderID});
      if (r.code === "INSTRUMENT_DECLINED") return actions.restart();   // cho khách chọn phương thức khác
      if (!r.ok) ppFail(r.error || "Thanh toán không thành công");
      toast(r.message); drawCart(await api("/api/cart")); openCart(false);
    },
    onCancel() { toast("Bạn đã hủy thanh toán PayPal"); },
    onError() { if (!ppShown) toast("Có lỗi với PayPal, vui lòng thử lại"); ppShown = false; }
  }).render("#paypal-buttons");
}

// ---- Chatbot
const chatEl = $("#chat"), pid = +chatEl.dataset.product || null, pname = chatEl.dataset.name || "";
let hist = [];
try { hist = JSON.parse(sessionStorage.getItem("chat") || "[]"); } catch (e) {}
const saveHist = () => { try { sessionStorage.setItem("chat", JSON.stringify(hist.slice(-20))); } catch (e) {} };
const addMsg = (role, text) => { const d = document.createElement("div"); d.className = "m " + (role === "user" ? "me" : "bot"); d.textContent = text; $("#msgs").append(d); $("#msgs").scrollTop = 1e9; return d; };
hist.forEach(m => addMsg(m.role, m.content));
const openChat = o => {
  chatEl.classList.toggle("on", o); $("#chatFab").style.display = o ? "none" : "";
  if (o) {
    fetch("/api/event", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({type: "chat_open"})}).catch(() => {});
    if (!$("#msgs").children.length) addMsg("assistant", pname ? `Bạn đang xem ${pname}. Bạn muốn hỏi gì về máy này?` : "Xin chào! Bạn cần laptop để làm gì và ngân sách khoảng bao nhiêu? Mình sẽ gợi ý máy và phụ kiện phù hợp.");
    $("#chatIn").focus();
  }
};
$("#chatFab").onclick = () => openChat(true); $("#chatClose").onclick = () => openChat(false);
$("#chatForm").onsubmit = async e => {
  e.preventDefault(); const t = $("#chatIn").value.trim(); if (!t) return;
  $("#chatIn").value = ""; addMsg("user", t); hist.push({role: "user", content: t}); saveHist();
  const w = addMsg("assistant", "Đang soạn câu trả lời...");
  try { const r = await api("/api/chat", {messages: hist, product_id: pid}); w.textContent = r.reply || r.error; if (r.cart) { drawCart(r.cart); toast("Đã cập nhật giỏ hàng"); } hist.push({role: "assistant", content: w.textContent}); }
  catch { w.textContent = "Không kết nối được trợ lý. Bạn thử lại sau nhé."; hist.pop(); }
  saveHist();
};
