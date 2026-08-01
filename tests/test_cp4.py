"""CHECKPOINT 4 — Scaling & Reliability: stateless, readiness, graceful shutdown.

Chạy: pytest tests/test_cp4.py -v
File cần sửa: app/store.py, app/lifecycle.py, app/main.py (/ready, /health, /ask)
"""

from __future__ import annotations

import re
import signal

import pytest


class TestConversationStore:
    def test_luu_va_doc_lai_duoc(self, fake_redis):
        from app.store import ConversationStore

        store = ConversationStore(fake_redis)
        store.append("u1", "user", "Xin chào")
        store.append("u1", "assistant", "Chào bạn")

        history = store.get_history("u1")
        assert [turn["role"] for turn in history] == ["user", "assistant"]
        assert history[0]["content"] == "Xin chào"

    def test_chua_co_gi_thi_tra_list_rong(self, fake_redis):
        from app.store import ConversationStore

        assert ConversationStore(fake_redis).get_history("nguoi-la") == []

    def test_moi_user_mot_lich_su_rieng(self, fake_redis):
        from app.store import ConversationStore

        store = ConversationStore(fake_redis)
        store.append("u1", "user", "cua u1")
        store.append("u2", "user", "cua u2")
        assert len(store.get_history("u1")) == 1
        assert store.get_history("u2")[0]["content"] == "cua u2"

    def test_cat_bot_lich_su_qua_dai(self, fake_redis):
        """Lịch sử không được phình vô hạn — prompt dài = tiền token nhiều."""
        from app.store import ConversationStore, HISTORY_MAX_MESSAGES

        store = ConversationStore(fake_redis)
        for i in range(HISTORY_MAX_MESSAGES + 10):
            store.append("u1", "user", f"tin nhan {i}")

        history = store.get_history("u1")
        assert len(history) == HISTORY_MAX_MESSAGES
        assert history[-1]["content"] == f"tin nhan {HISTORY_MAX_MESSAGES + 9}", (
            "phải giữ các tin nhắn MỚI NHẤT, không phải cũ nhất"
        )

    def test_co_dat_han_su_dung(self, fake_redis):
        from app.store import ConversationStore

        store = ConversationStore(fake_redis)
        store.append("u1", "user", "hi")
        assert fake_redis.ttl(ConversationStore._key("u1")) > 0, (
            "phải đặt TTL cho key lịch sử, nếu không Redis đầy dần theo thời gian"
        )

    def test_ping_bao_dung_trang_thai(self, fake_redis):
        from app.store import ConversationStore

        assert ConversationStore(fake_redis).ping() is True

    def test_ping_khong_nem_loi_khi_redis_chet(self):
        """Redis chết → ping trả False, KHÔNG được để exception thoát ra."""
        from app.store import ConversationStore

        class RedisChet:
            def ping(self):
                raise ConnectionError("Redis không phản hồi")

        assert ConversationStore(RedisChet()).ping() is False

    def test_fake_url_tra_ve_redis_gia(self):
        from app.store import get_redis_client

        client = get_redis_client("fake://")
        client.set("k", "v")
        assert client.get("k") == "v"


class TestStateless:
    def test_state_khong_nam_trong_process(self, fake_redis):
        """Hai instance store khác nhau (mô phỏng 2 container) phải thấy
        cùng một dữ liệu, vì state nằm ở Redis chứ không nằm trong object."""
        from app.store import ConversationStore

        container_a = ConversationStore(fake_redis)
        container_b = ConversationStore(fake_redis)

        container_a.append("u1", "user", "câu hỏi gửi vào container A")
        history = container_b.get_history("u1")

        assert len(history) == 1, (
            "container B không thấy dữ liệu container A ghi — state đang bị "
            "giữ trong RAM của từng instance"
        )

    def test_khong_co_bien_toan_cuc_giu_state(self, lab_root):
        """Quét source tìm dict/list toàn cục dùng làm bộ nhớ hội thoại."""
        pattern = re.compile(
            r"^(?!\s)(\w*(history|conversation|session|cache|memory|store)\w*)"
            r"\s*(:\s*[^=]+)?=\s*(\{\}|\[\]|dict\(\)|list\(\))",
            re.IGNORECASE | re.MULTILINE,
        )
        for name in ("main.py", "store.py"):
            path = lab_root / "app" / name
            if not path.exists():
                continue
            found = pattern.findall(path.read_text(encoding="utf-8"))
            assert not found, (
                f"app/{name} có biến toàn cục giữ state: {[f[0] for f in found]}. "
                "Khi scale ra nhiều instance, mỗi instance có RAM riêng → agent "
                "mất trí nhớ. Đưa state sang Redis."
            )

    def test_lich_su_duoc_dung_lai_giua_cac_request(self, client_real_store, auth_headers):
        first = client_real_store.post(
            "/ask", json={"question": "Câu hỏi thứ nhất"}, headers=auth_headers
        )
        assert first.status_code == 200, first.text
        assert first.json()["history_length"] == 0

        second = client_real_store.post(
            "/ask", json={"question": "Câu hỏi thứ hai"}, headers=auth_headers
        )
        assert second.json()["history_length"] == 2, (
            "lượt hỏi thứ hai phải thấy 2 message trước đó (user + assistant)"
        )


class TestReadiness:
    def test_ready_tra_200_khi_redis_song(self, client_real_store):
        response = client_real_store.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_ready_tra_503_khi_redis_chet(self, client_factory):
        class StoreChet:
            def ping(self):
                return False

        client = client_factory(store=StoreChet())
        response = client.get("/ready")
        assert response.status_code == 503, (
            "Redis chết mà /ready vẫn 200 thì load balancer sẽ đẩy traffic vào "
            "một instance không phục vụ được"
        )

    def test_ready_khac_health(self, client_real_store):
        """/health không kiểm tra dependency, /ready thì có."""
        import inspect

        from app.main import ready

        assert inspect.signature(ready).parameters, (
            "/ready phải nhận store làm dependency để kiểm tra kết nối"
        )


class TestGracefulShutdown:
    def test_nhan_tin_hieu_thi_bat_co(self):
        from app.lifecycle import Lifecycle

        life = Lifecycle()
        assert life.shutting_down is False
        life.request_shutdown(signal.SIGTERM, None)
        assert life.shutting_down is True

    def test_dang_ky_handler_cho_sigterm_va_sigint(self):
        from app.lifecycle import Lifecycle

        goc_term = signal.getsignal(signal.SIGTERM)
        goc_int = signal.getsignal(signal.SIGINT)
        try:
            life = Lifecycle()
            life.install()
            assert signal.getsignal(signal.SIGTERM) == life.request_shutdown, (
                "chưa đăng ký handler cho SIGTERM — đây là tín hiệu mà Docker, "
                "Railway, Cloud Run gửi khi deploy phiên bản mới"
            )
            assert signal.getsignal(signal.SIGINT) == life.request_shutdown
        finally:
            signal.signal(signal.SIGTERM, goc_term)
            signal.signal(signal.SIGINT, goc_int)

    def test_nhuong_lai_cho_handler_cu(self):
        """Ghi đè handler của uvicorn thì phải gọi lại nó, nếu không server
        không bao giờ tự tắt và bị SIGKILL sau vài chục giây."""
        from app.lifecycle import Lifecycle

        goc_term = signal.getsignal(signal.SIGTERM)
        goc_int = signal.getsignal(signal.SIGINT)
        da_goi = []
        try:
            signal.signal(signal.SIGTERM, lambda signum, frame: da_goi.append(signum))
            life = Lifecycle()
            life.install()
            life.request_shutdown(signal.SIGTERM, None)

            assert life.shutting_down is True
            assert da_goi == [signal.SIGTERM], (
                "request_shutdown phải gọi lại handler đã đăng ký trước đó — "
                "đó chính là handler dừng server của uvicorn"
            )
        finally:
            signal.signal(signal.SIGTERM, goc_term)
            signal.signal(signal.SIGINT, goc_int)

    def test_health_bao_503_khi_dang_tat(self, client):
        from app.lifecycle import lifecycle

        assert client.get("/health").status_code == 200

        lifecycle.request_shutdown(signal.SIGTERM, None)
        response = client.get("/health")
        assert response.status_code == 503, (
            "đang tắt dần thì /health phải trả 503 để load balancer ngừng gửi "
            "request mới vào instance này"
        )

    def test_ready_bao_503_khi_dang_tat(self, client_real_store):
        from app.lifecycle import lifecycle

        lifecycle.request_shutdown(signal.SIGTERM, None)
        assert client_real_store.get("/ready").status_code == 503
