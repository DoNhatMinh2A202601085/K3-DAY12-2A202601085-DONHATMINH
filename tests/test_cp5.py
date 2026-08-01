"""CHECKPOINT 5 — Cloud Deployment: service chạy thật, có địa chỉ công khai.

Chạy: pytest tests/test_cp5.py -v
File cần sửa: DEPLOYMENT.md (điền URL thật sau khi deploy)

Test này gọi vào service của bạn qua Internet nên cần kết nối mạng.

Không deploy được lên cloud? Đặt ``LOCAL_FALLBACK=true`` trong .env rồi chạy
``docker compose up`` — điểm CP5 khi đó tối đa 60% (xem grade.py).
"""

from __future__ import annotations

import os
import re

import httpx
import pytest

TIMEOUT = 20.0
LOCAL_URL = os.getenv("LOCAL_BASE_URL", "http://localhost:8000")
PLACEHOLDER_HINTS = ("todo", "your-app", "example.com", "abcxyz", "dien-vao", "<")

# Cloud free tier hay "ngủ đông" — request đầu tiên có thể mất vài chục giây
FIRST_CALL_TIMEOUT = 60.0


def fallback_mode() -> bool:
    return os.getenv("LOCAL_FALLBACK", "false").strip().lower() in ("1", "true", "yes")


def call(method: str, url: str, timeout: float = TIMEOUT, **kwargs):
    """Gọi HTTP và biến lỗi kết nối thành thông báo dễ hiểu thay vì traceback."""
    try:
        return httpx.request(method, url, timeout=timeout, **kwargs)
    except httpx.HTTPError as err:
        pytest.fail(
            f"không gọi được {url}\n"
            f"lý do: {type(err).__name__}: {err}\n"
            "→ kiểm tra URL trong DEPLOYMENT.md, xem service còn sống không, "
            "và mở log trên dashboard của platform."
        )


def read_deployment(repo_root) -> str:
    path = repo_root / "DEPLOYMENT.md"
    assert path.exists(), "thiếu file DEPLOYMENT.md ở gốc repo"
    return path.read_text(encoding="utf-8")


def require_filled(text: str) -> None:
    """Chưa điền xong thì không tính là đạt."""
    assert not re.search(r"\(điền", text), (
        "DEPLOYMENT.md còn chỗ trống '(điền ...)' chưa hoàn thiện"
    )


def extract_url(text: str) -> str | None:
    """URL công khai đầu tiên trong DEPLOYMENT.md, bỏ qua các giá trị mẫu."""
    for url in re.findall(r"https://[^\s`)\]>*]+", text):
        cleaned = url.rstrip("/.,")
        if any(hint in cleaned.lower() for hint in PLACEHOLDER_HINTS):
            continue
        if "github.com" in cleaned or "railway.app/project" in cleaned:
            continue  # link repo hoặc link dashboard, không phải service
        return cleaned
    return None


@pytest.fixture(scope="module")
def deployment_text(repo_root) -> str:
    return read_deployment(repo_root)


@pytest.fixture(scope="module")
def base_url(deployment_text) -> str:
    if fallback_mode():
        return LOCAL_URL
    url = extract_url(deployment_text)
    if not url:
        pytest.fail(
            "Chưa điền Public URL thật vào DEPLOYMENT.md.\n"
            "Nếu bạn dùng phương án dự phòng, đặt LOCAL_FALLBACK=true trong .env."
        )
    return url


class TestDeploymentDoc:
    def test_da_dien_thong_tin_ca_nhan(self, deployment_text):
        require_filled(deployment_text)
        assert "mã học viên" in deployment_text.lower(), (
            "DEPLOYMENT.md phải ghi mã học viên"
        )

    def test_ghi_ro_platform(self, deployment_text):
        require_filled(deployment_text)
        lowered = deployment_text.lower()
        assert any(
            name in lowered
            for name in ("railway", "render", "cloud run", "fly.io", "koyeb")
        ), "DEPLOYMENT.md phải ghi rõ deploy trên platform nào"

    def test_liet_ke_bien_moi_truong(self, deployment_text):
        require_filled(deployment_text)
        for name in ("AGENT_API_KEY", "REDIS_URL"):
            assert name in deployment_text, (
                f"DEPLOYMENT.md phải liệt kê biến môi trường {name} đã set"
            )

    def test_khong_lo_secret_trong_tai_lieu(self, deployment_text):
        """Liệt kê TÊN biến thì được, dán GIÁ TRỊ thật thì không."""
        require_filled(deployment_text)
        for match in re.finditer(
            r"AGENT_API_KEY\s*[:=]\s*([^\s|`]+)", deployment_text, re.IGNORECASE
        ):
            value = match.group(1).strip()
            assert not re.fullmatch(r"[A-Za-z0-9_\-]{12,}", value), (
                f"DEPLOYMENT.md đang lộ giá trị AGENT_API_KEY ({value!r}). "
                "Repo là nơi công khai — chỉ ghi TÊN biến, không ghi giá trị. "
                "Nếu đã lỡ commit, đổi khóa mới ngay."
            )


@pytest.mark.skipif(fallback_mode(), reason="Đang dùng phương án dự phòng LOCAL_FALLBACK")
class TestPublicDeployment:
    def test_url_dung_https(self, base_url):
        assert base_url.startswith("https://"), (
            "service công khai phải chạy trên HTTPS, không phải http://"
        )

    def test_health_tra_ve_200(self, base_url):
        response = call("GET", f"{base_url}/health", timeout=FIRST_CALL_TIMEOUT)
        assert response.status_code == 200, (
            f"{base_url}/health trả {response.status_code}. "
            "Xem log trên dashboard của platform."
        )
        assert response.json().get("status") == "ok"

    def test_ready_tra_ve_200(self, base_url):
        """/ready 200 nghĩa là service đã kết nối được Redis trên cloud."""
        response = call("GET", f"{base_url}/ready")
        assert response.status_code == 200, (
            f"/ready trả {response.status_code} — nhiều khả năng biến REDIS_URL "
            "trên cloud chưa đúng hoặc chưa tạo Redis instance"
        )

    def test_ask_yeu_cau_xac_thuc(self, base_url):
        """Public URL mà không cần key = ai cũng tiêu tiền của bạn được."""
        response = call("POST", f"{base_url}/ask", json={"question": "Hello"})
        assert response.status_code == 401, (
            f"/ask trả {response.status_code} khi không có API key — phải là 401"
        )

    @pytest.mark.skipif(
        not os.getenv("DEPLOY_API_KEY"),
        reason="Chưa đặt DEPLOY_API_KEY trong .env (điểm cộng)",
    )
    def test_ask_hoat_dong_voi_key_that(self, base_url):
        response = call(
            "POST",
            f"{base_url}/ask",
            timeout=FIRST_CALL_TIMEOUT,
            json={"question": "Deploy là gì?"},
            headers={
                "X-API-Key": os.environ["DEPLOY_API_KEY"],
                "X-User-Id": "cp5-test",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"]


@pytest.mark.skipif(
    not fallback_mode(), reason="Chỉ chạy khi LOCAL_FALLBACK=true"
)
class TestLocalFallback:
    """Phương án dự phòng: stack chạy bằng docker compose ở máy + screenshot."""

    def test_stack_dang_chay(self, base_url):
        response = call("GET", f"{base_url}/health")
        assert response.status_code == 200

    def test_ready_ket_noi_duoc_redis(self, base_url):
        assert call("GET", f"{base_url}/ready").status_code == 200

    def test_ask_yeu_cau_xac_thuc(self, base_url):
        response = call("POST", f"{base_url}/ask", json={"question": "Hello"})
        assert response.status_code == 401

    def test_co_anh_chup_man_hinh(self, repo_root):
        folder = repo_root / "screenshots"
        images = (
            [p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
            if folder.exists()
            else []
        )
        assert images, (
            "phương án dự phòng cần ít nhất 1 ảnh trong screenshots/ "
            "(terminal đang chạy `docker compose ps` và kết quả gọi API)"
        )
