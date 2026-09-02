# ForgeMind Agent 执行循环

**版本：V0.1**  
**状态：核心已确定**

## 1. 循环流程

```text
用户需求
  ↓
Agent Thinking
  ↓
生成 Action
  ↓
Runtime 结构校验
  ↓
权限与安全检查
  ↓
Tool 执行
  ↓
Observation
  ↓
Runtime 更新 State
  ↓
Agent 读取 State 并继续思考
```

## 2. 循环规则

1. Agent 每轮根据当前 State 决定下一步；
2. Action 必须是结构化的；
3. Runtime 不补全缺失参数；
4. Tool 执行结果必须形成 Observation；
5. 客观执行事实由 Runtime 根据结果写入 State；
6. Agent 根据成功、失败或错误 Observation 重新决策；
7. 未满足完成标准时不得声明任务完成。

## 3. 结束条件

- 需求已满足，且验证证据充分；
- 用户取消任务；
- 无法继续并已说明阻塞原因；
- 达到安全边界，等待用户确认。

