"""为一个任务组合全部 Agent Decision 的 Runtime 处理器。"""

from functools import partial

from forgemind.runtime.ask_user import accept_ask_user_and_wait
from forgemind.runtime.completion import complete_task
from forgemind.runtime.decision_dispatch import AgentDecisionHandlers
from forgemind.runtime.edit_file_handler import handle_edit_file_decision
from forgemind.runtime.read_file_handler import handle_read_file_decision
from forgemind.runtime.run_command_handler import handle_run_command_decision
from forgemind.runtime.run_tests_handler import handle_run_tests_decision
from forgemind.runtime.search_code_handler import handle_search_code_decision
from forgemind.state.sqlite_state import SQLiteForgeMindState


def build_runtime_handlers(
    *,
    task_id: str,
    state: SQLiteForgeMindState,
) -> AgentDecisionHandlers[object]:
    """绑定任务身份和权威 State，避免每个调用点手工遗漏分支。"""

    shared = {"task_id": task_id, "state": state}
    return AgentDecisionHandlers(
        ask_user=partial(accept_ask_user_and_wait, **shared),
        read_file=partial(handle_read_file_decision, **shared),
        search_code=partial(handle_search_code_decision, **shared),
        edit_file=partial(handle_edit_file_decision, **shared),
        run_tests=partial(handle_run_tests_decision, **shared),
        run_command=partial(handle_run_command_decision, **shared),
        complete=partial(complete_task, **shared),
    )
