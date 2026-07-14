# 上游合并与签到修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `millylee/anyrouter-check-in` 最新 `main` 合并到当前 fork，移除导致 Action 退出码 1 的二元组/三元组契约冲突，并保留 fork 的保活工作流。

**Architecture:** 使用普通、未提交的 merge 保留双方历史。认证、WAF 和签到主流程采用上游实现；fork 独有文件继续保留，冲突测试以上游生产接口为准，`.gitignore` 使用双方并集。

**Tech Stack:** Python 3.11、pytest、pytest-asyncio、uv、Ruff、GitHub Actions

---

### Task 1：建立基线并复现返回契约错误

**Files:**
- Modify: `tests/test_checkin.py`

- [ ] **Step 1：同步开发依赖**

Run: `uv sync --dev`

Expected: 依赖同步成功，命令退出码为 0。

- [ ] **Step 2：验证合并前测试基线**

Run: `uv run pytest tests -q`

Expected: 现有测试全部通过；真实通知测试允许跳过。

- [ ] **Step 3：增加三元组返回契约测试**

在 `tests/test_checkin.py` 中导入：

```python
from checkin import check_in_account
from utils.config import AccountConfig, AppConfig, ProviderConfig
```

在文件末尾增加：

```python
class TestCheckInAccountContract:
	async def test_missing_provider_returns_three_values(self):
		account = AccountConfig(cookies={'session': 'test'}, api_user='1', provider='missing')

		result = await check_in_account(account, 0, AppConfig(providers={}))

		assert result == (False, None, None)
```

- [ ] **Step 4：运行测试并确认 RED**

Run: `uv run pytest tests/test_checkin.py::TestCheckInAccountContract::test_missing_provider_returns_three_values -q`

Expected: FAIL；实际结果为 `(False, None)`，期望为 `(False, None, None)`。

### Task 2：合并上游并解决冲突

**Files:**
- Modify: `.gitignore`
- Modify: `checkin.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_notify.py`
- Preserve: `.github/workflows/auto_run.yml`
- Merge upstream changes across the repository

- [ ] **Step 1：配置并获取上游远端**

Run:

```powershell
if (git remote get-url upstream 2>$null) {
	git remote set-url upstream https://github.com/millylee/anyrouter-check-in.git
} else {
	git remote add upstream https://github.com/millylee/anyrouter-check-in.git
}
git fetch --no-tags upstream main
```

Expected: `upstream/main` 指向上游最新提交，命令退出码为 0。

- [ ] **Step 2：开始未提交的普通合并**

Run: `git merge --no-commit --no-ff upstream/main`

Expected: Git 进入合并状态；冲突集中在 `.gitignore`、`checkin.py`、`tests/conftest.py`、`tests/test_notify.py`。

- [ ] **Step 3：采用上游签到与测试基础实现**

Run:

```powershell
git restore --source=upstream/main --staged --worktree -- checkin.py tests/conftest.py tests/test_notify.py
```

Expected: 三个文件不再包含冲突标记，并与上游版本一致。

- [ ] **Step 4：合并 `.gitignore` 规则**

将 `.gitignore` 完整内容整理为：

```gitignore
.claude
.env
.venv
__pycache__
.pytest_cache
.ruff_cache
.mypy_cache
.coverage
coverage.xml
htmlcov
balance_hash.txt
.browser_profiles
checkin_screenshots

.DS_Store
secret.txt
```

Run: `git add .gitignore checkin.py tests/conftest.py tests/test_notify.py`

Expected: `git diff --name-only --diff-filter=U` 无输出。

- [ ] **Step 5：确认 fork 独有工作流仍存在**

Run: `git diff --exit-code HEAD -- .github/workflows/auto_run.yml`

Expected: 无差异，退出码为 0。

### Task 3：验证根因修复

**Files:**
- Test: `tests/test_checkin.py`
- Verify: `checkin.py`

- [ ] **Step 1：运行定向回归测试并确认 GREEN**

Run: `uv run pytest tests/test_checkin.py::TestCheckInAccountContract::test_missing_provider_returns_three_values -q`

Expected: PASS。

- [ ] **Step 2：确认旧浏览器兜底已移除**

Run:

```powershell
if (Select-String -Path checkin.py -Pattern 'check_in_via_browser') {
	exit 1
}
```

Expected: 无匹配，退出码为 0；返回契约由上一条回归测试验证。

### Task 4：执行完整验证并保留未提交结果

**Files:**
- Verify: repository-wide merged state

- [ ] **Step 1：按合并后的锁文件同步依赖**

Run: `uv sync --dev --frozen`

Expected: 依赖同步成功，退出码为 0。

- [ ] **Step 2：运行完整测试并识别 fork 旧断言**

Run: `uv run pytest tests -q`

Expected: 首次运行暴露 fork 独有测试与上游新语义的差异；不得出现上游自带测试失败。

- [ ] **Step 3：更新 fork 独有测试的上游兼容断言**

在 `tests/test_checkin.py` 中：

```python
	def test_used_affects_hash(self):
		b1 = {'a': {'quota': 10.0, 'used': 1.0}}
		b2 = {'a': {'quota': 10.0, 'used': 99.0}}
		assert generate_balance_hash(b1) != generate_balance_hash(b2)
```

将 API 错误和无效 JSON 断言分别改为：

```python
		assert result['error'] == 'Failed to get user info: HTTP 200'
```

```python
		assert result['error'].startswith('Failed to get user info: err:')
```

- [ ] **Step 4：重新运行完整测试**

Run: `uv run pytest tests -q`

Expected: 全部测试通过；仅允许显式条件控制的真实接口测试跳过。

- [ ] **Step 5：运行代码质量检查**

Run:

```powershell
uv run ruff check .
uv run ruff format --check .
git diff --check
```

Expected: 三个命令均退出码为 0，无格式错误、Lint 错误或空白错误。

- [ ] **Step 6：检查最终 Git 状态**

Run:

```powershell
git status --short
git diff --name-only --diff-filter=U
git rev-parse --verify MERGE_HEAD
```

Expected: 无未解决冲突，`MERGE_HEAD` 存在；设计、计划和回归测试保留为未提交修改，不执行 commit 或 push。

### Task 5：处理最终代码审查问题

**Files:**
- Create: `tests/test_workflow_security.py`
- Modify: `.github/workflows/checkin.yml`
- Modify: `CLAUDE.md`

- [ ] **Step 1：增加认证 Profile 不进入 Actions cache 的失败测试**

```python
from pathlib import Path


def test_checkin_workflow_does_not_cache_browser_profiles():
	workflow = Path('.github/workflows/checkin.yml').read_text(encoding='utf-8')

	assert 'path: .browser_profiles' not in workflow
```

Run: `uv run pytest tests/test_workflow_security.py -q`

Expected: FAIL，当前上游工作流仍包含 `path: .browser_profiles`。

- [ ] **Step 2：移除浏览器 Profile cache 步骤**

从 `.github/workflows/checkin.yml` 删除“恢复浏览器 Profile 缓存”步骤。保留运行期的持久 Context，但不跨 Actions run 保存认证材料。

Run: `uv run pytest tests/test_workflow_security.py -q`

Expected: PASS。

- [ ] **Step 3：更新维护文档**

更新 `CLAUDE.md` 中的安装命令、浏览器架构、账号认证字段和 CI runner，使其与 CloakBrowser、邮箱登录、Ubuntu + xvfb 工作流一致。

Run: `rg -n "Playwright|Windows runner|缓存.*浏览器" CLAUDE.md`

Expected: 无旧架构描述。

- [ ] **Step 4：重新运行完整验证**

Run:

```powershell
uv sync --frozen
uv run pytest tests -q
uv run ruff check .
uv run ruff format --check .
git diff --check
git diff --cached --check
```

Expected: 全部命令退出码为 0；测试除显式真实通知测试外全部通过。
