"""由学习者编写的 read_file Runtime 完整模块测试。"""

from pathlib import Path

from forgemind.runtime.read_file_execution import execute_read_file_action
from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def test_read_file_runtime_reads_real_slice_and_records_state(
    tmp_path: Path,
) -> None:
    # 第一步：在临时项目中创建 src/app.py，并写入四行真实字节内容。
    project_root = tmp_path / "project"
    target = project_root / "src" / "app.py"
    target.parent.mkdir(parents=True)

    content = b"line 1\nline 2\nline 3\nline 4\n"
    target.write_bytes(content)

    # 第二步：创建 Action Registry 和 Observation Registry。
    actions = InMemoryActionRegistry()
    observations = InMemoryObservationRegistry(actions)
    # 第三步：构造 read_file AcceptedAction：
    # path 使用项目相对路径，start_line=2，max_lines=2，
    # expected_version 必须根据第一步写入的同一份 bytes 计算。
    expected_version = calculate_content_version(content)

    action = AcceptedReadFileToolAction(
        action_id="action-read-module-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="read_file",
        arguments={
            "path": "src/app.py",
            "start_line": 2,
            "max_lines": 2,
            "expected_version": expected_version,
        },
        reason="读取文件中间两行",
    )
    # 第四步：先把 AcceptedAction 登记到 Action Registry。
    actions.register(action)
    # 第五步：调用统一 execute_read_file_action 执行真实读取。
    observation = execute_read_file_action(
        action,
        project_root=project_root,
        observations=observations,
    )
    # 第六步：断言顶层 status 是 success。
    assert observation.status == "success"
    # 第七步：断言返回内容恰好是第 2、3 行，范围是 2 到 3，
    # returned_lines=2，并且 eof=False、is_truncated=True。
    assert observation.result.content == "line 2\nline 3\n"
    assert observation.result.start_line == 2
    assert observation.result.end_line == 3
    assert observation.result.returned_lines == 2
    assert observation.result.eof is False
    assert observation.result.is_truncated is True
    # 第八步：断言结果 version 等于 Action 中冻结的 expected_version。
    assert observation.result.version == expected_version
    # 第九步：从 Observation Registry 按 action_id 取回记录，
    # 并断言它就是第五步返回的同一个 Observation 对象。
    assert observations.get(action.action_id) is observation
