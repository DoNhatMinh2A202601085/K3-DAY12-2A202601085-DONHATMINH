"""BONUS — CI/CD với GitHub Actions (tối đa +10 điểm cộng).

Chạy: pytest tests/test_bonus_cicd.py -v
File cần tạo: .github/workflows/ci.yml  (bạn tự viết, lab không cho sẵn)

Phần này KHÔNG bắt buộc. Làm xong 5 checkpoint chính rồi hãy đụng tới.

Mục tiêu: mỗi lần bạn `git push`, GitHub tự chạy test, tự build image, và
CHỈ khi mọi thứ xanh mới tự deploy. Không còn cảnh "quên chạy test trước khi
deploy" hay "deploy từ máy của một bạn nào đó rồi không ai biết đã deploy gì".

Hướng dẫn chi tiết: LAB_GUIDE.md § Bonus — CI/CD với GitHub Actions
"""

from __future__ import annotations

import re

import httpx
import pytest
import yaml

WORKFLOW_DIR = ".github/workflows"
BADGE_TIMEOUT = 20.0


@pytest.fixture(scope="module")
def workflow_path(repo_root):
    folder = repo_root / WORKFLOW_DIR
    if not folder.exists():
        pytest.fail(
            f"chưa có thư mục {WORKFLOW_DIR}/ — phần bonus này yêu cầu bạn tự "
            "viết một workflow GitHub Actions. Xem LAB_GUIDE.md § Bonus."
        )
    files = sorted(folder.glob("*.yml")) + sorted(folder.glob("*.yaml"))
    if not files:
        pytest.fail(f"{WORKFLOW_DIR}/ rỗng — chưa có file workflow nào")
    return files[0]


@pytest.fixture(scope="module")
def workflow(workflow_path) -> dict:
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{workflow_path.name} không phải YAML hợp lệ"
    return data


@pytest.fixture(scope="module")
def workflow_text(workflow_path) -> str:
    return workflow_path.read_text(encoding="utf-8")


def _jobs(workflow: dict) -> dict:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow chưa khai báo `jobs`"
    return jobs


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps", []) if isinstance(s, dict)]


def _all_run_commands(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _find_job(jobs: dict, *keywords: str) -> tuple[str, dict] | tuple[None, None]:
    """Tìm job theo id hoặc theo tên hiển thị."""
    for job_id, job in jobs.items():
        haystack = f"{job_id} {job.get('name', '')}".lower()
        if any(word in haystack for word in keywords):
            return job_id, job
    return None, None


def _triggers(workflow: dict):
    """`on:` trong YAML bị parse thành boolean True — đây là cái bẫy kinh điển."""
    return workflow.get("on", workflow.get(True))


class TestTrigger:
    def test_chay_khi_push_va_pull_request(self, workflow):
        triggers = _triggers(workflow)
        assert triggers, "workflow chưa khai báo `on:`"
        names = list(triggers) if isinstance(triggers, (dict, list)) else [triggers]
        assert "push" in names, "workflow phải chạy khi `push`"
        assert "pull_request" in names, (
            "workflow phải chạy cả khi `pull_request` — bắt lỗi TRƯỚC khi merge "
            "mới là mục đích chính của CI"
        )


class TestJobTest:
    def test_co_job_chay_pytest(self, workflow):
        jobs = _jobs(workflow)
        assert any("pytest" in _all_run_commands(job) for job in jobs.values()), (
            "không có job nào chạy pytest — CI mà không chạy test thì để làm gì"
        )

    def test_khong_chay_test_can_deploy_trong_ci(self, workflow):
        """test_cp5.py gọi vào service đã deploy — chạy nó trong CI sẽ luôn đỏ.

        Loại nó ra bằng `--ignore=tests/test_cp5.py` hoặc `-m "not docker"`
        kèm chọn file cụ thể.
        """
        commands = "\n".join(_all_run_commands(job) for job in _jobs(workflow).values())
        pytest_lines = [line for line in commands.splitlines() if "pytest" in line]
        assert pytest_lines, "không tìm thấy lệnh pytest"
        assert any(
            "test_cp5" in line or "ignore" in line or "-k" in line or "-m" in line
            for line in pytest_lines
        ), (
            "lệnh pytest trong CI đang chạy tất cả, kể cả test_cp5.py (cần một "
            "bản deploy sống). Giới hạn lại phạm vi test chạy trong CI."
        )

    def test_co_cai_dependency(self, workflow):
        commands = "\n".join(_all_run_commands(job) for job in _jobs(workflow).values())
        assert "requirements.txt" in commands, (
            "job test phải cài dependency từ requirements.txt"
        )


class TestJobBuild:
    def test_co_buoc_build_docker_image(self, workflow):
        jobs = _jobs(workflow)
        commands = "\n".join(_all_run_commands(job) for job in jobs.values())
        uses = " ".join(
            str(step.get("uses", "")) for job in jobs.values() for step in _steps(job)
        )
        assert "docker build" in commands or "docker/build-push-action" in uses, (
            "CI phải build thử Docker image — Dockerfile hỏng mà chỉ phát hiện "
            "lúc deploy là quá muộn"
        )


class TestJobDeploy:
    def test_co_job_deploy(self, workflow):
        job_id, _ = _find_job(_jobs(workflow), "deploy", "release", "ship")
        assert job_id, "chưa có job deploy"

    def test_deploy_chi_chay_sau_khi_test_xanh(self, workflow):
        """`needs:` là thứ biến workflow thành một cái cổng chất lượng."""
        jobs = _jobs(workflow)
        job_id, deploy = _find_job(jobs, "deploy", "release", "ship")
        assert job_id, "chưa có job deploy"

        needs = deploy.get("needs")
        assert needs, (
            "job deploy thiếu `needs:` — nếu không, GitHub chạy song song test "
            "và deploy, và code hỏng vẫn lên production trong khi test đang đỏ"
        )

    def test_deploy_gioi_han_nhanh(self, workflow):
        """Mở pull request không được kéo theo một lần deploy."""
        job_id, deploy = _find_job(_jobs(workflow), "deploy", "release", "ship")
        assert job_id, "chưa có job deploy"
        condition = str(deploy.get("if", ""))
        assert condition, (
            "job deploy thiếu `if:` — thêm điều kiện kiểu "
            "`if: github.ref == 'refs/heads/main'` để chỉ deploy từ nhánh chính"
        )


class TestBaoMat:
    def test_secret_lay_tu_github_secrets(self, workflow_text):
        assert "secrets." in workflow_text, (
            "workflow chưa dùng ${{ secrets.* }} — token deploy phải nằm trong "
            "Settings → Secrets and variables → Actions, không nằm trong file này"
        )

    def test_khong_hardcode_token(self, workflow_text):
        """Quét các giá trị trông như token thật bị dán thẳng vào workflow."""
        suspicious = re.findall(
            r"(?:TOKEN|KEY|SECRET|PASSWORD)\s*:\s*['\"]?([A-Za-z0-9_\-]{16,})",
            workflow_text,
            re.IGNORECASE,
        )
        assert not suspicious, (
            f"workflow đang hardcode secret: {suspicious}. "
            "Đổi ngay giá trị đó ở nơi cấp phát — nó đã nằm trong lịch sử git."
        )

    def test_action_duoc_ghim_phien_ban(self, workflow):
        """`actions/checkout@main` = bạn chạy code mới nhất của người khác,
        bất kể hôm nay họ vừa đổi gì trong đó."""
        jobs = _jobs(workflow)
        floating = [
            uses
            for job in jobs.values()
            for step in _steps(job)
            if (uses := str(step.get("uses", "")))
            and uses.endswith(("@main", "@master", "@latest"))
        ]
        assert not floating, (
            f"các action sau chưa ghim phiên bản: {floating}. "
            "Dùng dạng `actions/checkout@v4` (hoặc ghim theo commit SHA)."
        )


class TestBadge:
    def test_readme_co_badge(self, repo_root, workflow_path):
        """Badge cho người xem repo biết ngay nhánh main đang xanh hay đỏ."""
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        assert "badge.svg" in readme, (
            "README.md chưa có badge trạng thái. Thêm dòng:\n"
            f"![CI](https://github.com/<user>/<repo>/actions/workflows/"
            f"{workflow_path.name}/badge.svg)"
        )

    def test_badge_bao_passing(self, repo_root):
        """Bằng chứng cuối cùng: workflow đã chạy thật và đang xanh."""
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        match = re.search(r"https://github\.com/\S+?/badge\.svg[^\s)\]]*", readme)
        if not match:
            pytest.fail("không tìm thấy URL badge hợp lệ trong README.md")

        url = match.group(0)
        if "<" in url or "your-user" in url.lower():
            pytest.fail(f"badge còn để chỗ trống chưa thay: {url}")

        try:
            response = httpx.get(url, timeout=BADGE_TIMEOUT)
        except httpx.HTTPError as err:
            pytest.fail(f"không tải được badge {url} — {err}")

        assert response.status_code == 200, (
            f"badge trả {response.status_code} — repo phải public và đã push workflow"
        )
        content = response.text.lower()
        assert "passing" in content, (
            "badge chưa báo passing. Vào tab Actions trên GitHub xem log lần "
            f"chạy gần nhất (badge hiện đang là: "
            f"{'failing' if 'failing' in content else 'no status'})."
        )
