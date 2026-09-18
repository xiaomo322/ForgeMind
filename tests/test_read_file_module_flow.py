"""read_file 快照处理与成功登记模块的用户编写集成测试。"""

from forgemind.runtime.read_file_execution import (
    build_read_file_result_from_snapshot,
    record_read_file_success,
)
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def test_read_file_snapshot_success_flow_records_authoritative_result() -> None:
    """验证已批准快照从 Action 一直成为 State 中的成功事实。"""

    content = b"line1\nprice = 100\nline3\n"
    expected_version = calculate_content_version(content)

    # 第一步：构造从第 2 行读取 1 行、绑定 expected_version 的 Action。
    action = AcceptedReadFileToolAction(
        action_id="action-module-001",
        task_id="task-module-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/pricing.py",
            "start_line": 2,
            "max_lines": 1,
            "expected_version": expected_version,
        },
        reason="读取价格计算代码",
    )

    # 第二步：创建 Action Registry，登记 Action，再创建 Observation Registry。
    actions = InMemoryActionRegistry()
    actions.register(action)
    observations = InMemoryObservationRegistry(actions)

    # 第三步：用同一份 content 生成 ReadFileResult，并登记成功 Observation。
    result = build_read_file_result_from_snapshot(
        action,
        content=content,
    )
    success = record_read_file_success(
        action,
        result,
        observations=observations,
    )

    # 第四步：从 Observation Registry 取回 action_id 对应的权威记录。
    stored = observations.get(action.action_id)

    # 第五步：断言状态为 success，内容为 price 行，范围为第 2 行，
    assert success.status == "success"
    assert success.result.content == "price = 100\n"
    assert success.result.start_line == 2
    assert success.result.end_line == 2
    assert success.result.version == expected_version
    assert stored is success
