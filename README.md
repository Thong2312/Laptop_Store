# LaptopS - Website bán laptop (Flask + SQLite)

## Chạy dự án

pip install -r requirements.txt
python app.py

http://127.0.0.1:5000

## Tài khoản & phân quyền
- **Đăng ký / Đăng nhập / Đăng xuất**: /register, /login.
- **Admin**: admin@laptops.local / Admin@123


## Quản lý sản phẩm (chỉ Admin)
Đăng nhập Admin -> bấm "Quản trị":
- Thêm: /admin/product/new
- Sửa: /admin/product/<id>/edit
- Xóa: nút **Xóa** trong danh sách. Sản phẩm đã có trong đơn hàng sẽ không xóa được để giữ lịch sử đơn.

Quyền được kiểm tra ở phía server; người dùng thường truy cập các trang này nhận lỗi 403.

## Thanh toán PayPal (Sandbox)
Giỏ hàng có 2 cách đặt hàng: **COD** (thanh toán khi nhận hàng) và **PayPal**.
PAYPAL_USD_VND_RATE (mặc định "25000", tức 1 USD = 25.000 đ).
### Cách hoạt động
- PayPal **không hỗ trợ VND**, nên server quy đổi tổng tiền sang **USD** theo tỷ giá trên.
- Số tiền do **server** tính từ giỏ hàng và CSDL, trình duyệt không sửa được giá.
- Đơn hàng được lưu với payment_method = paypal; trạng thái payment_status:
  pending (đang chờ) -> paid (đã thanh toán) | failed (thất bại) | review (số tiền không khớp, cần kiểm tra thủ công).

## Xem đơn hàng

- **Khách hàng** (đã đăng nhập): menu **Đơn hàng** để xem danh sách đơn của mình và chi tiết từng đơn (/orders/<mã đơn>): sản phẩm, số lượng, tổng tiền, trạng thái thanh toán, mã giao dịch PayPal. Khách chỉ xem được đơn của chính mình, đơn của người khác trả về 404.
- **Admin**: /admin/orders (tab **Đơn hàng** trong trang Quản trị) xem "tất cả" đơn, có lọc theo hình thức/trạng thái thanh toán, tìm theo mã đơn / tên / SĐT / email. Admin mở được chi tiết mọi đơn, kèm tài khoản đặt hàng và mã đơn PayPal.
- Đơn được gắn với tài khoản khi khách đặt hàng.

## Chatbot thêm/xóa sản phẩm vào giỏ
Khách có thể nhắn cho trợ lý, ví dụ: "thêm Asus Zenbook 14 OLED vào giỏ", "cho mình 2 chiếc Nitro V vào giỏ", hoặc "thêm máy này vào giỏ" khi đang xem trang chi tiết.
- Yêu cầu rõ ràng được xử lý bằng luật trong chat.py (cart_request), không tốn lượt gọi AI. Các câu nói tự nhiên hơn do mô hình AI xử lý: mô hình kết thúc câu trả lời bằng thẻ [[THEM:mã:số_lượng]], server tách thẻ, kiểm tra mã sản phẩm với CSDL rồi mới thêm vào giỏ.
- Xóa khỏi giỏ: "xóa Nitro khỏi giỏ", "bỏ Victus ra khỏi giỏ", "bớt 1 cái Nitro V trong giỏ", "xóa máy này khỏi giỏ", "xóa hết giỏ hàng". Mô hình dùng thẻ [[XOA:mã]], [[XOA:mã:số_lượng]] hoặc [[XOA:TATCA]]; chỉ xóa được máy đang có trong giỏ.
- Nhiều máy trong một câu, mỗi máy một số lượng riêng: "thêm 3 chiếc Nitro V, 2 cái Zenbook và Victus vào giỏ", "Aspire 5 x2", "mỗi máy 2 cái"; tương tự khi xóa/bớt: "bớt 2 cái Nitro V và 1 cái Zenbook trong giỏ".
- Chatbot chỉ thêm/xóa trong giỏ; việc đặt hàng vẫn bắt buộc đăng nhập.

## Phụ kiện công nghệ và bán kèm (cross-sell)
- Bảng products có cột category (laptop | accessory). 9 phụ kiện mẫu (chuột, bàn phím, sạc, tai nghe, balo, hub, đế tản nhiệt, SSD). Ảnh dùng placeholder, thay trong Quản trị.
- Trang chủ có mục **Phụ kiện công nghệ** (/?cat=accessory). Trang laptop có mục "Phụ kiện đi kèm", xếp theo nhóm nhu cầu trùng với máy.
- Chatbot gợi ý 1-2 phụ kiện phù hợp khi khách đã chọn laptop, và thêm phụ kiện vào giỏ như laptop.

## Phễu chuyển đổi (Admin: /admin/funnel)
- Bảng events ghi: visit, product_view, chat_open, chat_message, add_to_cart (nguồn button | chat), checkout_start, order_placed. Không ghi phiên của admin.
- Phễu: Visit -> Add to cart -> Checkout started -> Order placed, so sánh phiên "có dùng chat" và "không dùng chat", kèm chỉ số chat.


