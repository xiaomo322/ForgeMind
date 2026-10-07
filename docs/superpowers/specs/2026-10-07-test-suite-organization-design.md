# ForgeMind 测试目录整理设计

## 目标

把 `tests/` 根目录中的正式测试按职责分组，让学习者能从目录名判断测试对象，同时保持测试行为、断言和生产代码不变。

## 目录结构

```text
tests/
├── README.md       # 分类规则和常用运行命令
├── contracts/      # Pydantic 模型、参数、结果和数据校验
├── agent/          # Agent 决策、上下文、模型与循环
├── tools/          # 文件、搜索、命令和 pytest 工具的底层行为
├── runtime/        # Action 接收、执行调度、权限策略与处理器
├── state/          # Registry、状态视图和 SQLite 持久化
├── application/    # 应用服务和 CLI 入口
├── api/            # ForgeMind 正式 HTTP/SSE 接口
├── integration/    # 两个或更多模块连接后的完整链路
└── e2e/            # 从入口到最终结果的产品级流程
```

分类以测试的主要职责为准。例如 `read_file` 的字节读取和切片属于 `tools`，而 Agent 发出读取决定后的完整处理链路属于 `integration`。

## FastAPI 学习代码

独立练习移到 `learning/fastapi/`，不会被 ForgeMind 默认的 `testpaths = ["tests"]` 收集。正式的 SSE 接口测试仍属于项目，移动到 `tests/api/`。

## 兼容与验证

- 使用 Git 移动保留已跟踪文件的历史。
- 不修改测试函数、断言或生产代码。
- 移动前基线为 `611 passed`；整理期间学习者新增了一项 SSE 延迟测试，因此移动后预期为 612 项。
- 移动后分别执行目录收集检查、分类测试和完整回归；除新增的 SSE 测试外，原有用例数量必须保持一致。
- 历史实施计划保留当时的路径记录，新路径以 `tests/README.md` 为准。
