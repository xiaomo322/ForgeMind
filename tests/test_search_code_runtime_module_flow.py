from pathlib import Path

from forgemind.runtime.search_code_execution import execute_search_code_action
from forgemind.schema.actions import AcceptedSearchCodeToolAction
from forgemind.schema.search_code import SearchIncompleteReason
from forgemind.state.action_registry import InMemoryActionRegistry
from forgemind.state.observation_registry import InMemoryObservationRegistry


def test_search_code_runtime_module_records_limited_ordered_result(
    tmp_path: Path,
) -> None:
    # 第一步：创建真实项目目录，并建立 a.py 与 b.py。
    # 两个文件共写入 3 条 discount 命中，文件创建顺序先 b.py 后 a.py。
    project_root = tmp_path / "project"
    project_root.mkdir()

    (project_root / "b.py").write_text(
        "discount = 2\ndiscount = 3\n",
        encoding="utf-8",
    )
    (project_root / "a.py").write_text(
        "discount = 1\n",
        encoding="utf-8",
    )
    # 第二步：创建 Action Registry，并构造 max_results=2 的
    # AcceptedSearchCodeToolAction，再把 Action 注册进去。
    actions = InMemoryActionRegistry()
    action = AcceptedSearchCodeToolAction(
        action_id="action-search-module-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="search_code",
        arguments={
            "query": "discount",
            "scope": ".",
            "max_results": 2,
        },
        reason="验证完整搜索流程",
    )
    actions.register(action)

    # 第三步：使用同一个 Action Registry 创建 Observation Registry。
    observations = InMemoryObservationRegistry(actions)

    # 第四步：调用 execute_search_code_action 执行完整 Runtime 流程。
    observation = execute_search_code_action(
        action,
        project_root=project_root,
        observations=observations,
    )
    # 第五步：断言结果先返回 a.py 再返回 b.py，证明顺序由项目路径决定，
    # 而不是由文件创建顺序决定。
    assert observation.status == "success"
    assert [
        (match.path, match.line_number)
        for match in observation.result.matches
    ] == [
        ("a.py", 1),
        ("b.py", 1),
    ]

    # 第六步：断言 returned_count=2、is_complete=False，并且原因是
    # RESULT_LIMIT_REACHED，证明系统实际发现了第 3 条命中。
    assert observation.result.returned_count == 2
    assert observation.result.is_complete is False
    assert observation.result.incomplete_reasons == (
        SearchIncompleteReason.RESULT_LIMIT_REACHED,
    )
    # 第七步：断言从 Observation Registry 取出的对象就是返回对象本身。
    assert observations.get(action.action_id) is observation
