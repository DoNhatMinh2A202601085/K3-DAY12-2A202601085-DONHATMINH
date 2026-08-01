"""CHECKPOINT 1 — 12-Factor Config, Health Check & Structured Logging.

Chạy: pytest tests/test_cp1.py -v
File cần sửa: app/config.py, app/logging_utils.py, app/main.py (/health)
"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

# Những chuỗi không bao giờ được xuất hiện trong code cấu hình
FORBIDDEN_SECRETS = ["sk-", "secret-key-123", "password123", "AKIA"]


class TestConfig:
    def test_settings_co_du_cac_truong(self):
        """Settings khai báo đủ 6 trường theo bảng trong app/config.py."""
        from app.config import Settings

        for field in (
            "port",
            "agent_api_key",
            "redis_url",
            "rate_limit_per_minute",
            "monthly_budget_usd",
            "log_level",
        ):
            assert field in Settings.model_fields, f"thiếu trường '{field}'"

    def test_doc_gia_tri_tu_bien_moi_truong(self, monkeypatch):
        """Đổi biến môi trường → cấu hình đổi theo, không cần sửa code."""
        from app.config import Settings

        monkeypatch.setenv("AGENT_API_KEY", "khoa-tu-env")
        monkeypatch.setenv("PORT", "9123")
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "42")
        monkeypatch.setenv("MONTHLY_BUDGET_USD", "3.5")

        settings = Settings(_env_file=None)
        assert settings.agent_api_key == "khoa-tu-env"
        assert settings.port == 9123
        assert settings.rate_limit_per_minute == 42
        assert settings.monthly_budget_usd == pytest.approx(3.5)

    def test_gia_tri_mac_dinh_hop_ly(self, monkeypatch):
        """Các trường không phải secret thì có mặc định dùng được ngay."""
        from app.config import Settings

        monkeypatch.setenv("AGENT_API_KEY", "x")
        for name in ("PORT", "REDIS_URL", "RATE_LIMIT_PER_MINUTE",
                     "MONTHLY_BUDGET_USD", "LOG_LEVEL"):
            monkeypatch.delenv(name, raising=False)

        settings = Settings(_env_file=None)
        assert settings.port == 8000
        assert settings.rate_limit_per_minute == 10
        assert settings.monthly_budget_usd == pytest.approx(10.0)
        assert "redis" in settings.redis_url

    def test_thieu_api_key_thi_fail_fast(self, monkeypatch):
        """Không có AGENT_API_KEY → app phải chết ngay lúc khởi động."""
        from app.config import Settings

        monkeypatch.delenv("AGENT_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_khong_hardcode_secret(self, lab_root):
        """Không có secret nào nằm trong source code."""
        for name in ("config.py", "main.py", "auth.py"):
            path = lab_root / "app" / name
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            for bad in FORBIDDEN_SECRETS:
                assert bad not in source, f"{name} chứa secret hardcode: {bad!r}"


class TestStructuredLogging:
    def test_log_event_tra_ve_json_hop_le(self):
        from app.logging_utils import log_event

        raw = log_event("test_event")
        parsed = json.loads(raw)
        assert parsed["event"] == "test_event"
        assert parsed["level"] == "info"
        assert "timestamp" in parsed

    def test_log_event_gan_them_truong_tuy_y(self):
        from app.logging_utils import log_event

        parsed = json.loads(log_event("ask_completed", user_id="sv01", cost_usd=0.12))
        assert parsed["user_id"] == "sv01"
        assert parsed["cost_usd"] == pytest.approx(0.12)

    def test_level_luon_viet_thuong(self):
        from app.logging_utils import log_event

        assert json.loads(log_event("e", level="ERROR"))["level"] == "error"

    def test_log_ra_stdout_dung_mot_dong(self, capsys):
        """Cloud gom log theo dòng — một event xuống dòng là một log bị vỡ."""
        from app.logging_utils import log_event

        log_event("mot_dong", chi_tiet="a")
        out = capsys.readouterr().out.strip()
        assert out, "log_event phải in ra stdout"
        assert len(out.splitlines()) == 1, "log JSON phải nằm gọn trên 1 dòng"
        json.loads(out)

    def test_timestamp_dung_dinh_dang_iso(self):
        from app.logging_utils import log_event

        stamp = json.loads(log_event("e"))["timestamp"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp), stamp


class TestHealthEndpoint:
    def test_health_tra_ve_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_khong_can_api_key(self, client):
        """Probe của platform không gửi API key — bắt buộc key là tự sát."""
        assert client.get("/health").status_code == 200

    def test_health_khong_phu_thuoc_dependency_nao(self):
        """Redis chết thì /health vẫn phải 200, nếu không cả cụm bị restart.

        Cách kiểm tra: hàm health() không được nhận tham số dependency nào.
        """
        import inspect

        from app.main import health

        params = list(inspect.signature(health).parameters)
        assert not params, f"/health không được phụ thuộc dependency: {params}"
