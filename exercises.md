# Phiếu Phản Ánh — K3 Ngày 12

> **Bài làm cá nhân.** Trả lời bằng lời của chính bạn, dựa trên những gì bạn
> quan sát được khi chạy code — không sao chép đáp án của người khác.
>
> Cách trả lời: thay dòng có dấu `> *` ở cuối mỗi câu hỏi bằng câu trả lời của bạn.
> `grade.py` đếm số câu đã trả lời (15 điểm cho 10 câu).
>
> Họ và tên: Đỗ Nhật Minh  Mã học viên: 2A202601085

---

### Câu 1 — Fail fast (CP1)

Trong `Settings`, `agent_api_key` không có giá trị mặc định nên app chết ngay
khi khởi động nếu thiếu biến môi trường. Hãy mô tả một tình huống cụ thể mà
việc "chết sớm" này cứu bạn, so với việc để mặc định `"changeme"`.

> **Tình huống cụ thể:**
> Bạn deploy lên Railway nhưng quên set `AGENT_API_KEY` trong dashboard.
> - **Nếu có default `"changeme"`:** App khởi động bình thường → user có thể gọi API với key `"changeme"` → AI agent chạy, gọi LLM → **bạn trả tiền cho người lạ dùng API của mình**. Bạn chỉ biết khi nhìn hóa đơn $50.
> - **Nếu KHÔNG có default (code trong repo của tôi):** App không khởi động được, Railway health check fail → container restart liên tục → **bạn thấy ngay lỗi khi đang deploy**, biết là thiếu biến môi trường → set lại → xong.
>
> Chết sớm = phát hiện lỗi khi bạn còn đang theo dõi. Chết muộn (với default) = phát hiện khi đã mất tiền.

---

### Câu 2 — Log cho máy đọc (CP1)

Chạy service và gọi `/ask` vài lần. Dán một dòng log JSON bạn thu được, rồi
nêu **hai** việc bạn làm được với dòng log đó mà `print("đã trả lời xong")`
không làm được.

> **Log JSON thu được:**
> ```json
> {"event":"ask_completed","level":"info","timestamp":"2026-08-10T07:43:46.479747+00:00","user_id":"sv01","tokens_in":3,"tokens_out":41,"cost_usd":0.00002505}
> ```
>
> **Hai việc `print()` không làm được:**
> 1. **Đếm/tính toán:** Query "user nào tiêu nhiều tiền nhất tuần này?" — log JSON parse được bằng SQL/Elasticsearch, còn `print()` thì máy không đọc được nội dung.
> 2. **Cảnh báo tự động:** Cloud (Datadog, Grafana) đọc JSON → alert khi `level:error` hoặc `cost_usd > 1` → không thể làm với `print()` vì không phân biệt được level hay extract được field.

---

### Câu 3 — Kích thước image (CP2)

Build cả hai phiên bản và ghi lại số đo thật:

| Bản | Dung lượng |
|-----|-----------|
| 1 stage (bản đầu) | 1730 MB (1.73 GB) |
| Multi-stage | 270 MB |

Giải thích: phần dung lượng chênh lệch đó là những gì?

> **Kết quả đo được:**
> - 1 stage (bản gốc `FROM python:3.11`): **1730 MB**
> - Multi-stage (bản đã sửa): **270 MB**
> - Chênh lệch: **~1.46 GB** (~84% nhẹ hơn)
>
> **Giải thích:** Bản 1 stage chứa toàn bộ Python image đầy đủ (~900MB base) cộng thêm compiler (build-essential, pip cache) và các file không cần thiết. Multi-stage dùng `python:3.11-slim` làm base image nhẹ hơn nhiều, và quan trọng hơn — stage `builder` (chứa compiler để biên dịch dependencies) bị **DISCARD** hoàn toàn sau khi copy kết quả sang runtime stage. Chỉ có `/usr/local` (thư viện đã cài) và source code mới sang stage cuối.

---

### Câu 4 — Thứ tự lệnh trong Dockerfile (CP2)

Sửa một ký tự trong `app/main.py` rồi build lại. Với Dockerfile của bạn, những
layer nào được dùng lại từ cache, layer nào phải chạy lại? Nếu bạn đặt
`COPY . .` lên trước `RUN pip install` thì kết quả khác thế nào?

> **Câu trả lời:**
> Dockerfile hiện tại có thứ tự đúng:
> ```
> COPY requirements.txt .        # layer 1
> RUN pip install --prefix=/install -r requirements.txt  # layer 2
> COPY app ./app                  # layer 3
> COPY utils ./utils              # layer 4
> ```
> Khi sửa 1 ký tự trong `app/main.py`:
> - **CACHED (giữ nguyên):** Layer 1 và Layer 2 — vì `requirements.txt` không thay đổi, Docker dùng lại cache
> - **PHẢI REBUILD:** Layer 3 (`COPY app ./app`) — vì file trong `app/` đã thay đổi
> - **CACHED hoặc REBUILD tùy:** Layer 4 (`COPY utils ./utils`) — chỉ rebuild nếu `utils/` cũng thay đổi
>
> Chỉ ~2 layer chạy lại → build nhanh (vài giây).
>
> Nếu đặt `COPY . .` **trước** `RUN pip install`:
> - Mỗi lần sửa bất kỳ file nào trong `app/`, `utils/`, hay `requirements.txt` → layer `COPY . .` thay đổi → **Layer pip install BỊ HUỶ CACHE và chạy lại toàn bộ** → mất vài phút mỗi lần build
> - Thêm vấn đề: các file không cần thiết (`.env`, `__pycache__`, `.git`) cũng được copy vào image

---

### Câu 5 — Vì sao không chạy bằng root (CP2)

Container mặc định chạy bằng root. Mô tả chuỗi sự kiện dẫn từ "một lỗ hổng
trong code Python của bạn" tới "kẻ tấn công có quyền cao trên máy host", và
lệnh `USER` cắt đứt chuỗi đó ở chỗ nào.

> **Chuỗi sự kiện nếu container chạy root:**
> 1. Container chạy với **UID 0 (root)** bên trong
> 2. Code Python có lỗ hổng (ví dụ: command injection, path traversal, deserialization)
> 3. Attacker gửi payload khai thác lỗ hổng đó
> 4. Attacker **đã là root bên trong container** — có thể: tạo user mới, sửa file hệ thống, cài thêm tool
> 5. Attacker leo thang sang host qua **container escape** (vd: mount host filesystem, dirty pipe, privileged container)
> 6. Kẻ tấn công **có quyền root trên máy host** → toàn bộ hệ thống bị kiểm soát
>
> **Lệnh `USER` cắt đứt ở bước 4:**
> ```
> RUN useradd --create-home --uid 10001 appuser
> USER appuser
> ```
> Container chạy với UID 10001 (user thường), không phải root. Nếu attacker khai thác được lỗ hổng trong code Python, họ chỉ có quyền của user `appuser` — **không có quyền root** và **không thể thoát container** để leo lên host.

---

### Câu 6 — Cửa sổ trượt (CP3)

Rate limit của bạn dùng sliding window 60 giây. Nếu thay bằng cách đếm theo
phút đồng hồ (reset lúc giây 00), một người dùng có thể gửi tối đa bao nhiêu
request trong 2 giây liên tiếp khi hạn mức là 10/phút? Giải thích cách đạt được
con số đó.

> **Trả lời: Tối đa 20 request trong 2 giây.**
>
> **Cách đạt được:**
> - Giả sử hạn mức 10/phút, reset lúc giây :00 mỗi phút
> - Lúc **10:00:59** — gửi 10 request → đầy quota phút thứ 1
> - Lúc **10:01:01** (sang phút mới, quota reset) — gửi 10 request → đầy quota phút thứ 2
> - **Tổng: 20 request trong ~2 giây** (từ :59 của phút này đến :01 của phút sau)
>
> **Lý do:** Reset đồng hồ tạo "kẽ hở" — hai phút liền kề mỗi phút có 10 quota riêng, user khai thác được khoảng cách ~2 giây giữa hai lần reset.
>
> **Sliding window trong repo của bạn không có lỗ hở này:** Code dùng Redis ZSET với `zremrangebyscore(key, 0, now - 60)` — mọi request đều nằm trong cùng một cửa sổ 60 giây trượt, không có reset theo phút đồng hồ.

---

### Câu 7 — Rate limit và cost guard (CP3)

Hai cơ chế này khác nhau ở điểm nào? Cho một tình huống mà rate limit cho qua
nhưng cost guard phải chặn, và một tình huống ngược lại.

> **Khác nhau:**
> - **Rate limit** (rate_limiter.py): giới hạn **số lượng request** trong 60 giây
> - **Cost guard** (cost_guard.py): giới hạn **số tiền** tổng chi tiêu tháng
>
> **Rate limit cho qua, cost guard chặn:**
> Một user gửi 5 request/phút (dưới rate limit 10/phút), nhưng mỗi request có context lịch sử hội thoại rất dài → mỗi response trả về ~50,000 tokens. Sau 20 request, đã tiêu ~$5 USD — vượt ngân sách $10/tháng → cost guard chặn ở request thứ 21 dù rate limit vẫn còn quota.
>
> **Cost guard cho qua, rate limit chặn:**
> Một user gửi 20 request rất ngắn (mỗi response chỉ 10 tokens, tốn ~$0.001). Tổng chi tiêu chỉ ~$0.02 — cách xa ngân sách $10. Nhưng nếu user gửi nhanh 15 request trong 5 giây → vượt rate limit 10/phút → rate limit chặn, dù cost guard hoàn toàn cho qua.

---

### Câu 8 — /health khác /ready (CP4)

Nếu gộp hai endpoint làm một và cho nó kiểm tra Redis, chuyện gì xảy ra với cụm
3 container khi Redis mất kết nối 30 giây? Trả lời theo đúng thứ tự sự kiện.

> **Trả lời:**
>
> Code `/health` trong repo của bạn (main.py:76-92) **không gọi Redis** — chỉ kiểm tra `lifecycle.shutting_down`.
> Code `/ready` trong repo của bạn (main.py:95-114) **CÓ gọi `store.ping()`** — kiểm tra Redis.
>
> Nếu gộp hai endpoint làm một (sai) và cho nó kiểm tra Redis:
> 1. Redis mất kết nối 30 giây
> 2. Container A gọi health check → Redis chết → trả **503**
> 3. Container B gọi health check → Redis chết → trả **503**
> 4. Container C gọi health check → Redis chết → trả **503**
> 5. **Orchestrator nhận 503 → restart cả 3 container cùng lúc** (vì health check lúc này kiểm tra Redis — và container chết = process không sống)
> 6. Khi Redis quay lại sau 30 giây → **không còn container nào đang chạy** để phục vụ request
> 7. Hệ thống sập hoàn toàn
>
> **Tách ra đúng như repo của bạn:**
> - `/health` chỉ trả lời "process còn sống không?" → Redis chết, container vẫn sống → **200** → không restart
> - `/ready` kiểm tra Redis → Redis chết → **503** → load balancer ngừng gửi request vào, nhưng **không restart container** → khi Redis quay lại, container vẫn đó và tự phục vụ tiếp

---

### Câu 9 — Stateless (CP4)

Chạy `docker compose up --scale agent=3` rồi gọi `/ask` nhiều lần với cùng một
`X-User-Id`. Quan sát `history_length` trong response. Nếu lịch sử được lưu
trong một dict Python thay vì Redis, bạn sẽ thấy con số đó thay đổi thế nào?

> **Trả lời:**
>
> Với **code đúng trong repo của bạn** (store.py dùng Redis):
> - 3 container cùng nhìn vào **một Redis duy nhất**
> - Gọi `/ask` lần 1 → history_length = 0
> - Gọi `/ask` lần 2 → history_length = 2 (user + assistant)
> - Gọi `/ask` lần 3 → history_length = 4
> - **Luôn tăng dần**, bất kể request vào container nào
>
> Nếu dùng **dict Python trong RAM** (sai — ví dụ `conversation_history = {}` trong main.py hoặc store.py):
> - Container A nhận câu 1: `history_length = 0`
> - Container B nhận câu 2: `history_length = 0` (vì dict của B là rỗng!)
> - Container A nhận câu 3: `history_length = 2` (B không ghi vào A)
> - Container C nhận câu 4: `history_length = 0` (dict của C cũng rỗng)
> - **history_length dao động ngẫu nhiên: 0, 0, 2, 0...** — agent "mất trí nhớ" tùy container

---

### Câu 10 — Deploy thật (CP5)

Ghi lại **một** lỗi bạn gặp khi deploy lên cloud (build fail, health check
timeout, sai REDIS_URL, app không đọc `$PORT`...): thông báo lỗi là gì, bạn
tìm ra nguyên nhân bằng cách nào, và sửa ra sao?

> **Lỗi gặp phải: `/ready` trả 503 — Redis không kết nối được**
>
> **Thông báo lỗi:**
> ```
> Status: 503
> Response: {"status":"not ready","redis":false}
> ```
>
> **Nguyên nhân:**
> Sau khi deploy thành công, `/health` trả 200 nhưng `/ready` trả 503. Điều này nghĩa là app chạy được nhưng không kết nối được Redis.
>
> Kiểm tra bằng `railway variables` → thấy `REDIS_URL` bị set nhưng giá trị là `redis://` (không có host/username/password) — không phải giá trị đầy đủ.
>
> **Cách tìm ra:**
> - Chạy `railway logs` xem app logs
> - Dùng `railway variables` xem giá trị biến thực tế
> - So sánh với Redis credentials trong dashboard
>
> **Cách sửa:**
> - Lấy `REDIS_URL` đầy đủ từ Railway: `redis://default:<PASSWORD>@redis.railway.internal:6379`
> - Set lại: `railway variables --set REDIS_URL="redis://default:QPKDbDfbpLpqpzVbPaeqgYhqobEFyspI@redis.railway.internal:6379"`
> - Redeploy: `railway redeploy --yes`
> - Kết quả: `/ready` trả 200, Redis connected ✅
