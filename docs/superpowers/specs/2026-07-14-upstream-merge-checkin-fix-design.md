# 上游合并与签到修复设计

## 目标

将 `millylee/anyrouter-check-in` 的最新 `main` 合并到当前 fork，在保留 fork 独有保活工作流的同时，消除签到失败路径中的返回值数量不一致问题，并完成自动化验证。

## 合并策略

- 使用普通 merge 保留双方历史，不重写当前 `main`。
- `checkin.py`、签到工作流及认证/WAF 流程优先采用上游新版实现。
- 保留 fork 独有的 `.github/workflows/auto_run.yml`。
- `.gitignore` 采用双方规则并集。
- 测试与通知相关冲突以上游结构为基础；仅保留仍有对应生产实现的 fork 功能。

## 缺陷处理

当前 fork 的浏览器兜底函数返回二元组，而主循环要求三元组。先增加返回契约回归测试并确认它在合并前失败，再通过合并上游新版流程消除错误分支。所有 `check_in_account` 退出路径必须返回 `(success, user_info_before, user_info_after)`。

上游新版已重新设计认证与 WAF 流程，因此不继续维护 fork 中旧的 `check_in_via_browser` 兜底实现，避免并存两套认证路径。

## 冲突处理

- `checkin.py`：采用上游实现，确认所有返回路径为三元组。
- `tests/conftest.py`：采用上游测试夹具结构，并保留必要的项目路径初始化。
- `tests/test_notify.py`：按合并后的 `utils/notify.py` 接口整理测试，不保留失效断言。
- `.gitignore`：保留双方新增忽略项。

## 验证

1. 合并前运行返回契约测试，确认能够复现失败。
2. 合并并解决冲突后运行该定向测试，确认通过。
3. 运行完整 `pytest` 测试套件。
4. 运行 Ruff 检查与格式校验。
5. 检查工作流 YAML、Git 状态和最终差异，不提交、不推送。
