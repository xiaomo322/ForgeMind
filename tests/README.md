# ForgeMind 测试目录

测试按“主要验证对象”分类。查找某个功能的测试时，先判断它是在验证单个组件，还是在验证多个组件连接后的链路。

| 目录 | 主要内容 | 示例 |
| --- | --- | --- |
| `contracts/` | Pydantic 模型、参数、结果与字段校验 | `test_edit_file_schema.py` |
| `agent/` | Agent 决策、上下文、模型调用和单步循环 | `test_agent_loop_step.py` |
| `tools/` | 文件、搜索、命令和 pytest 工具的底层行为 | `test_read_file_slicing.py` |
| `runtime/` | Action 接收、权限策略、调度和处理器 | `test_permission_checks.py` |
| `state/` | Registry、状态视图和 SQLite 持久化 | `test_sqlite_task_registry.py` |
| `application/` | 应用服务和 CLI 入口 | `test_cli.py` |
| `api/` | ForgeMind 正式 HTTP/SSE 接口 | `test_learning_sse.py` |
| `integration/` | 两个或更多模块连接后的执行链路 | `test_read_file_module_flow.py` |
| `e2e/` | 从用户任务到最终结果的完整流程 | `test_forgemind_end_to_end.py` |

## 如何运行

运行全部正式测试：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/full tests
```

只运行一个分类：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/tools tests/tools
```

只运行一个文件：

```powershell
uv --cache-dir .uv-cache run --no-sync pytest -q -p no:cacheprovider --basetemp=.test-tmp/read-file tests/tools/test_read_file_slicing.py
```

## 新测试放在哪里

如果测试只验证一个类或函数，放进该组件对应的目录。如果一次测试连接了 Agent、Runtime、State 或 Tool 中的多个部分，放进 `integration/`。只有覆盖完整产品入口和最终结果的测试才放进 `e2e/`。

独立的 FastAPI 学习练习位于 `learning/fastapi/`，不属于 ForgeMind 默认回归测试。
