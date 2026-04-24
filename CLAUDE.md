# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AnyRouter 多账号自动签到工具。支持 AnyRouter、AgentRouter 及其它兼容 NewAPI/OneAPI 的平台。通过 GitHub Actions 定时执行，支持 WAF 绕过和多渠道通知。

## 常用命令

```bash
# 安装依赖（使用 uv 包管理器）
uv sync --dev

# 安装 Playwright 浏览器
uv run playwright install chromium

# 运行签到脚本
uv run checkin.py

# 运行测试
uv run pytest tests/

# 代码检查与格式化（通过 pre-commit）
uv run pre-commit run --all-files

# 单独运行 ruff
uv run ruff check .
uv run ruff format .
```

## 代码风格

- 使用 Tab 缩进，单引号字符串（ruff format 配置）
- 行宽限制 120 字符
- Lint 规则：ASYNC, E, F, FAST, I, PLE（具体忽略项见 pyproject.toml）
- pre-commit hooks 会自动执行 ruff check 和 ruff format

## 架构

项目为扁平结构，非标准 Python 包（无 src/ 目录）：

- **`checkin.py`** — 主入口，async 主函数。加载账号配置 → 遍历账号执行签到 → 对比余额 hash 判断是否通知 → 发送通知
- **`utils/config.py`** — 配置管理。三个 dataclass：
  - `ProviderConfig`：服务商配置（域名、API 路径、WAF 绕过策略）
  - `AppConfig`：应用配置，内置 anyrouter/agentrouter 两个 provider，支持通过 `PROVIDERS` 环境变量扩展
  - `AccountConfig`：账号配置（cookies、api_user、provider 名称）
- **`utils/notify.py`** — 通知模块。`NotificationKit` 类支持 8 种通知渠道（邮件、钉钉、飞书、企微、PushPlus、Server酱、Telegram、Gotify），通过 `push_message()` 统一调用，单个渠道失败不影响其它渠道

## 关键设计模式

- **Provider 抽象**：通过 `ProviderConfig` 抽象不同平台的差异（域名、路径、WAF 策略），内置配置可被环境变量覆盖
- **WAF 绕过**：`bypass_method="waf_cookies"` 时使用 Playwright 无头浏览器访问登录页获取 WAF cookies（如 acw_tc、cdn_sec_tc），再合并用户 cookies 发送签到请求
- **余额变化检测**：生成余额数据的 SHA256 hash 并持久化到 `balance_hash.txt`，仅在余额变化或签到失败时发送通知
- **agentrouter 特殊处理**：`sign_in_path=None` 表示查询用户信息时自动完成签到，无需单独调用签到接口

## 环境变量

- `ANYROUTER_ACCOUNTS`（必需）：JSON 数组格式的账号配置
- `PROVIDERS`（可选）：JSON 对象格式的自定义 provider 配置
- 通知相关环境变量见 `.env.example`

## CI/CD

- **`checkin.yml`**：每 6 小时执行一次签到，Windows runner，缓存 uv 依赖和 Playwright 浏览器
- **`auto_run.yml`**：每 30 天空提交防止 GitHub Actions 被暂停
