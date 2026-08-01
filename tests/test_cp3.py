"""CHECKPOINT 3 — API Security: authentication, rate limiting, cost guard.

Chạy: pytest tests/test_cp3.py -v
File cần sửa: app/auth.py, app/rate_limiter.py, app/cost_guard.py, app/main.py (/ask)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


class TestAuthentication:
    def test_khong_co_key_thi_401(self, client):
        response = client.post("/ask", json={"question": "Xin chào"})
        assert response.status_code == 401

    def test_sai_key_thi_401(self, client):
        response = client.post(
            "/ask",
            json={"question": "Xin chào"},
            headers={"X-API-Key": "khoa-bia-dat"},
        )
        assert response.status_code == 401

    def test_dung_key_thi_200(self, client, auth_headers):
        response = client.post(
            "/ask", json={"question": "Docker là gì?"}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"]

    def test_tra_ve_dung_user_id(self, client, api_key):
        response = client.post(
            "/ask",
            json={"question": "Hi"},
            headers={"X-API-Key": api_key, "X-User-Id": "sv-123"},
        )
        assert response.json()["user_id"] == "sv-123"

    def test_khong_gui_user_id_thi_thanh_anonymous(self, client, api_key):
        from app.auth import ANONYMOUS_USER

        response = client.post(
            "/ask", json={"question": "Hi"}, headers={"X-API-Key": api_key}
        )
        assert response.json()["user_id"] == ANONYMOUS_USER

    def test_so_sanh_key_chong_timing_attack(self, lab_root):
        """Phải GỌI secrets.compare_digest, không chỉ nhắc tới trong comment."""
        import ast

        tree = ast.parse((lab_root / "app" / "auth.py").read_text(encoding="utf-8"))
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert "compare_digest" in called, (
            "so sánh API key bằng secrets.compare_digest(a, b), không dùng =="
        )


class TestRateLimiter:
    def test_trong_han_muc_thi_cho_qua(self, fake_redis):
        from app.rate_limiter import RateLimiter

        limiter = RateLimiter(fake_redis, limit_per_minute=3)
        for i in range(3):
            limiter.check("u1", now=1000.0 + i)

    def test_vuot_han_muc_thi_429(self, fake_redis):
        from app.rate_limiter import RateLimiter

        limiter = RateLimiter(fake_redis, limit_per_minute=3)
        for i in range(3):
            limiter.check("u1", now=1000.0 + i)

        with pytest.raises(HTTPException) as err:
            limiter.check("u1", now=1002.5)
        assert err.value.status_code == 429

    def test_cua_so_truot_qua_thi_duoc_goi_lai(self, fake_redis):
        from app.rate_limiter import RateLimiter

        limiter = RateLimiter(fake_redis, limit_per_minute=2)
        limiter.check("u1", now=1000.0)
        limiter.check("u1", now=1001.0)
        with pytest.raises(HTTPException):
            limiter.check("u1", now=1002.0)

        limiter.check("u1", now=1065.0)  # 2 request cũ đã ra khỏi cửa sổ 60s

    def test_moi_user_mot_han_muc_rieng(self, fake_redis):
        from app.rate_limiter import RateLimiter

        limiter = RateLimiter(fake_redis, limit_per_minute=1)
        limiter.check("u1", now=1000.0)
        limiter.check("u2", now=1000.0)  # user khác không bị ảnh hưởng

    def test_dem_dung_so_request(self, fake_redis):
        from app.rate_limiter import RateLimiter

        limiter = RateLimiter(fake_redis, limit_per_minute=10)
        for i in range(4):
            limiter.check("u1", now=2000.0 + i)
        assert limiter.hit_count("u1", now=2004.0) == 4

    def test_qua_http_thi_tra_429(self, client_factory, auth_headers):
        client = client_factory(rate_limit=3)
        for _ in range(3):
            assert client.post(
                "/ask", json={"question": "x"}, headers=auth_headers
            ).status_code == 200

        blocked = client.post("/ask", json={"question": "x"}, headers=auth_headers)
        assert blocked.status_code == 429

    def test_401_duoc_kiem_tra_truoc_429(self, client_factory):
        """Request không có key phải dừng ở 401, không tiêu quota của ai cả."""
        client = client_factory(rate_limit=1)
        for _ in range(5):
            assert client.post("/ask", json={"question": "x"}).status_code == 401


class TestCostGuard:
    def test_chua_tieu_gi_thi_spent_bang_0(self, fake_redis):
        from app.cost_guard import CostGuard

        assert CostGuard(fake_redis, 10.0).spent("u1") == pytest.approx(0.0)

    def test_record_cong_don(self, fake_redis):
        from app.cost_guard import CostGuard

        guard = CostGuard(fake_redis, 10.0)
        guard.record("u1", 0.5)
        guard.record("u1", 0.25)
        assert guard.spent("u1") == pytest.approx(0.75)

    def test_con_ngan_sach_thi_cho_qua(self, fake_redis):
        from app.cost_guard import CostGuard

        guard = CostGuard(fake_redis, 1.0)
        guard.record("u1", 0.9)
        guard.check("u1", estimated_cost=0.05)

    def test_vuot_ngan_sach_thi_402(self, fake_redis):
        from app.cost_guard import CostGuard

        guard = CostGuard(fake_redis, 1.0)
        guard.record("u1", 0.9)
        with pytest.raises(HTTPException) as err:
            guard.check("u1", estimated_cost=0.5)
        assert err.value.status_code == 402

    def test_moi_user_mot_ngan_sach_rieng(self, fake_redis):
        from app.cost_guard import CostGuard

        guard = CostGuard(fake_redis, 1.0)
        guard.record("u1", 5.0)
        guard.check("u2", estimated_cost=0.5)

    def test_qua_http_thi_tra_402(self, client, fake_redis, auth_headers):
        """Đã tiêu quá ngân sách → /ask trả 402 Payment Required."""
        from app.cost_guard import CostGuard

        fake_redis.set(CostGuard._key("sv-test"), "999")
        response = client.post("/ask", json={"question": "x"}, headers=auth_headers)
        assert response.status_code == 402

    def test_ask_ghi_nhan_chi_phi(self, client, fake_redis, auth_headers):
        from app.cost_guard import CostGuard

        client.post("/ask", json={"question": "Chi phí bao nhiêu?"}, headers=auth_headers)
        assert CostGuard(fake_redis, 10.0).spent("sv-test") > 0, (
            "/ask phải gọi guard.record() sau khi trả lời, nếu không ngân sách "
            "không bao giờ tăng và cost guard trở nên vô dụng"
        )


class TestAskResponse:
    def test_tra_du_cac_truong(self, client, auth_headers):
        body = client.post(
            "/ask", json={"question": "Kubernetes là gì?"}, headers=auth_headers
        ).json()
        for field in ("answer", "user_id", "history_length", "cost_usd", "tokens"):
            assert field in body, f"response thiếu trường {field!r}"

    def test_cau_hoi_rong_thi_422(self, client, auth_headers):
        response = client.post("/ask", json={"question": ""}, headers=auth_headers)
        assert response.status_code == 422
