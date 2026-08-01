"""CHECKPOINT 2 — Docker: multi-stage build, bảo mật image, compose stack.

Chạy: pytest tests/test_cp2.py -v
File cần sửa: Dockerfile, .dockerignore, docker-compose.yml

Các test có mark `docker` sẽ tự bỏ qua nếu máy bạn chưa cài/chưa bật Docker —
bạn không bị mất điểm vì lý do đó, nhưng nên tự chạy `docker build` một lần.
"""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml

IMAGE_TAG = "day12-agent:cp2-test"
MAX_IMAGE_SIZE_MB = 500


def docker_available() -> bool:
    """Docker daemon có đang chạy không? Không có thì bỏ qua các test build."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30, check=False
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@pytest.fixture(scope="module")
def dockerfile_text(lab_root) -> str:
    """Nội dung Dockerfile, đã bỏ comment — chấm lệnh thật, không chấm chú thích."""
    path = lab_root / "Dockerfile"
    assert path.exists(), "Không tìm thấy Dockerfile ở gốc repo"
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


@pytest.fixture(scope="module")
def compose(lab_root) -> dict:
    path = lab_root / "docker-compose.yml"
    assert path.exists(), "Không tìm thấy docker-compose.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "docker-compose.yml không phải YAML hợp lệ"
    return data


def _env_value(service: dict, name: str) -> str | None:
    """Đọc một biến môi trường từ service compose (hỗ trợ cả 2 cú pháp)."""
    env = service.get("environment")
    if isinstance(env, dict):
        value = env.get(name)
        return None if value is None else str(value)
    if isinstance(env, list):
        for item in env:
            text = str(item)
            if text.startswith(f"{name}="):
                return text.split("=", 1)[1]
    return None


def _instructions(text: str, keyword: str) -> list[str]:
    """Các dòng lệnh Dockerfile bắt đầu bằng keyword (bỏ comment)."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(keyword.upper() + " "):
            out.append(stripped)
    return out


class TestDockerfile:
    def test_multi_stage_build(self, dockerfile_text):
        """Ít nhất 2 stage, và stage đầu có đặt tên bằng AS."""
        froms = _instructions(dockerfile_text, "FROM")
        assert len(froms) >= 2, f"cần ≥2 lệnh FROM (multi-stage), đang có {len(froms)}"
        assert any(re.search(r"\bAS\s+\w+", f, re.IGNORECASE) for f in froms), (
            "phải đặt tên stage, ví dụ: FROM python:3.11-slim AS builder"
        )

    def test_base_image_gon_nhe(self, dockerfile_text):
        """python:3.11 đầy đủ nặng ~1GB; slim/alpine nhỏ hơn nhiều lần."""
        froms = " ".join(_instructions(dockerfile_text, "FROM")).lower()
        assert "slim" in froms or "alpine" in froms, (
            "dùng base image slim hoặc alpine cho stage runtime"
        )

    def test_cai_dependency_truoc_khi_copy_source(self, dockerfile_text):
        """COPY requirements.txt → RUN pip install → rồi mới COPY code.

        Làm ngược lại thì mỗi lần sửa 1 dòng code là cài lại toàn bộ thư viện.
        """
        lowered = dockerfile_text.lower()
        req_pos = lowered.find("copy requirements.txt")
        pip_pos = lowered.find("pip install")
        assert req_pos != -1, "phải COPY requirements.txt riêng một dòng"
        assert pip_pos != -1, "phải có RUN pip install"
        assert req_pos < pip_pos, "COPY requirements.txt phải đứng trước pip install"

        copy_all = re.search(r"^\s*COPY\s+\.\s", dockerfile_text, re.MULTILINE | re.IGNORECASE)
        if copy_all:
            assert pip_pos < copy_all.start(), (
                "COPY toàn bộ source phải đứng SAU pip install để tận dụng cache"
            )

    def test_khong_chay_bang_root(self, dockerfile_text):
        users = _instructions(dockerfile_text, "USER")
        assert users, "thiếu lệnh USER — container đang chạy bằng root"
        assert not users[-1].split()[1].strip().lower().startswith("root"), (
            "lệnh USER cuối cùng vẫn đang là root"
        )

    def test_co_healthcheck(self, dockerfile_text):
        assert _instructions(dockerfile_text, "HEALTHCHECK"), (
            "thiếu HEALTHCHECK — Docker không biết container có còn phục vụ được không"
        )

    def test_khong_hardcode_secret(self, dockerfile_text):
        for bad in ("sk-", "AGENT_API_KEY=", "password"):
            assert bad not in dockerfile_text, (
                f"Dockerfile chứa secret hardcode: {bad!r}. "
                "Secret phải truyền lúc chạy, không nướng vào image."
            )


class TestDockerignore:
    def test_ton_tai_va_day_du(self, lab_root):
        path = lab_root / ".dockerignore"
        assert path.exists(), "thiếu file .dockerignore"
        content = path.read_text(encoding="utf-8")
        for entry in (".env", "__pycache__", ".git", ".venv"):
            assert entry in content, f".dockerignore thiếu mục {entry!r}"

    def test_khong_loai_tru_nham_file_can_thiet(self, lab_root):
        content = (lab_root / ".dockerignore").read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines()]
        for needed in ("app", "app/", "requirements.txt", "utils"):
            assert needed not in lines, f"{needed!r} là thứ image CẦN, đừng ignore"


class TestDockerCompose:
    def test_co_service_agent_va_redis(self, compose):
        services = compose.get("services", {})
        assert "agent" in services, "thiếu service `agent`"
        assert "redis" in services, "thiếu service `redis`"

    def test_agent_build_tu_dockerfile(self, compose):
        agent = compose["services"]["agent"]
        assert "build" in agent, "service `agent` phải build từ Dockerfile trong repo"

    def test_agent_phu_thuoc_redis(self, compose):
        agent = compose["services"]["agent"]
        depends = agent.get("depends_on", {})
        names = list(depends.keys()) if isinstance(depends, dict) else list(depends)
        assert "redis" in names, "`agent` phải depends_on redis"

    def test_agent_tro_dung_toi_redis_service(self, compose):
        """Trong compose, hostname chính là tên service → redis://redis:6379."""
        url = _env_value(compose["services"]["agent"], "REDIS_URL")
        assert url, "service `agent` chưa truyền REDIS_URL"
        assert url.startswith("redis://redis"), (
            f"REDIS_URL đang là {url!r}; phải là redis://redis:6379/0 — "
            "localhost bên trong container là chính container đó, không phải Redis"
        )

    def test_secret_khong_nam_trong_compose(self, compose):
        """AGENT_API_KEY phải lấy qua nội suy ${...}, không viết thẳng."""
        value = _env_value(compose["services"]["agent"], "AGENT_API_KEY")
        assert value, "service `agent` chưa truyền AGENT_API_KEY"
        assert value.startswith("${"), (
            f"AGENT_API_KEY đang hardcode ({value!r}); dùng ${{AGENT_API_KEY}} "
            "để compose đọc từ file .env"
        )

    def test_agent_co_healthcheck(self, compose):
        assert "healthcheck" in compose["services"]["agent"], (
            "service `agent` cần healthcheck để compose biết khi nào nó sẵn sàng"
        )


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="Docker chưa chạy — bỏ qua")
class TestBuildThat:
    """Các test này build image thật. Chậm (vài phút) nhưng là bằng chứng cuối cùng."""

    def test_build_thanh_cong(self, lab_root, repo_root):
        result = subprocess.run(
            ["docker", "build", "-f", str(lab_root / "Dockerfile"), "-t", IMAGE_TAG, "."],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert result.returncode == 0, f"docker build thất bại:\n{result.stderr[-3000:]}"

    def test_image_du_nho(self):
        result = subprocess.run(
            ["docker", "images", IMAGE_TAG, "--format", "{{.Size}}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        size_text = result.stdout.strip()
        assert size_text, "chưa build được image — xem test_build_thanh_cong"
        number = float(re.sub(r"[^0-9.]", "", size_text) or 0)
        megabytes = number * 1024 if "GB" in size_text.upper() else number
        assert megabytes < MAX_IMAGE_SIZE_MB, (
            f"image {size_text} — cần dưới {MAX_IMAGE_SIZE_MB}MB. "
            "Kiểm tra lại multi-stage và base image."
        )
