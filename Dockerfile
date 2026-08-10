# ═══════════════════════════════════════════════════════════════════
# CP2 — Containerization
#
# Dưới đây là Dockerfile "chạy được nhưng chưa production": một stage,
# chạy bằng user root, không có health check, base image nặng.
#
# NHIỆM VỤ: sửa file này thành bản production-ready. Yêu cầu:
#   [x] Multi-stage build: stage `builder` cài dependency, stage runtime
#       chỉ copy kết quả sang → image nhỏ hơn, không mang theo compiler.
#       Cú pháp: `FROM python:3.11-slim AS builder`
#   [x] Base image slim (hoặc alpine), không dùng `python:3.11` bản đầy đủ
#   [x] COPY requirements.txt và pip install TRƯỚC khi COPY source code
#       (Docker cache theo layer: sửa 1 dòng code không phải cài lại thư viện)
#   [x] Tạo user thường và chuyển sang bằng lệnh `USER` — container chạy
#       root nghĩa là ai thoát được khỏi app cũng thành root trên host
#   [x] Có `HEALTHCHECK` gọi vào endpoint /health
#   [x] Đọc cổng từ biến môi trường PORT (cloud tự gán cổng, không cố định 8000)
#
# Kiểm tra:  pytest tests/test_cp2.py -v
# Build thử: docker build -t day12-agent:prod .
#            docker images day12-agent:prod     # xem dung lượng
# ═══════════════════════════════════════════════════════════════════

# ─── Stage 1: builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: runtime ───────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Tạo user thường, không chạy bằng root
RUN useradd --create-home --uid 10001 appuser

# Copy dependency đã cài từ stage builder
COPY --from=builder /install /usr/local

# Copy source code SAU pip install (để tận dụng cache)
COPY app ./app
COPY utils ./utils

# Chuyển sang user thường
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
