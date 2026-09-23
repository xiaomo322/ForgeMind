"""连接 search_code 的范围检查、Tool 执行与终态 Observation。"""

from pathlib import Path

from forgemind.runtime.project_paths import UnsafeProjectPathError
from forgemind.runtime.search_scope import (
    UnsupportedSearchScopeError,
    resolve_search_scope,
)
from forgemind.schema.actions import AcceptedSearchCodeToolAction
from forgemind.schema.observations import (
    FailedObservation,
    ObservationError,
    ObservationErrorCode,
    ObservationErrorDetail,
    RejectedObservation,
    SearchCodeSuccessObservation,
    TerminalObservation,
)
from forgemind.schema.search_code import SearchCodeResult
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.search_code import (
    SearchScopeNotFoundError,
    search_python_code,
)


class SearchCodeResultActionMismatchError(ValueError):
    """search_code 成功结果偏离了 AcceptedAction 的权威参数。"""


class SearchScopeCheckActionMismatchError(ValueError):
    """scope 检查失败并不属于当前准备登记的 Action。"""


def _scope_details(
    action: AcceptedSearchCodeToolAction,
) -> tuple[ObservationErrorDetail, ...]:
    return (
        ObservationErrorDetail(
            key="requested_scope",
            value=action.arguments.scope,
        ),
    )


def record_search_scope_rejection(
    action: AcceptedSearchCodeToolAction,
    failure: UnsafeProjectPathError | UnsupportedSearchScopeError,
    *,
    observations: InMemoryObservationRegistry,
) -> RejectedObservation:
    """把 Tool 调用前的 scope 拦截登记为 rejected。"""

    if isinstance(failure, UnsafeProjectPathError):
        failure_scope = failure.requested_path
        code = ObservationErrorCode.PATH_OUTSIDE_PROJECT
        message = "搜索范围不在项目根目录内"
    elif isinstance(failure, UnsupportedSearchScopeError):
        failure_scope = failure.requested_scope
        code = ObservationErrorCode.UNSUPPORTED_SEARCH_SCOPE
        message = "search_code 只支持 Python 单文件或目录"
    else:
        raise TypeError(f"不支持的搜索范围错误：{type(failure).__name__}")

    if failure_scope != action.arguments.scope:
        raise SearchScopeCheckActionMismatchError(
            "搜索范围错误与当前 Action 的 scope 不一致"
        )

    rejected = RejectedObservation(
        action_id=action.action_id,
        status="rejected",
        error=ObservationError(
            code=code,
            message=message,
            details=_scope_details(action),
        ),
    )
    observations.record(rejected)
    return rejected


def record_search_scope_missing(
    action: AcceptedSearchCodeToolAction,
    failure: SearchScopeNotFoundError,
    *,
    resolved_scope: Path,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """记录 Tool 执行阶段确认搜索范围不存在的事实。"""

    if failure.scope != resolved_scope:
        raise ValueError("搜索失败引用的 scope 与当前 Action 不一致")

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(
            code=ObservationErrorCode.SEARCH_SCOPE_NOT_FOUND,
            message="搜索范围不存在",
            details=_scope_details(action),
        ),
    )
    observations.record(failed)
    return failed


def record_search_failure(
    action: AcceptedSearchCodeToolAction,
    failure: OSError,
    *,
    observations: InMemoryObservationRegistry,
) -> FailedObservation:
    """记录搜索过程未能启动或完成的系统错误。"""

    failed = FailedObservation(
        action_id=action.action_id,
        status="failed",
        error=ObservationError(
            code=ObservationErrorCode.SEARCH_FAILED,
            message="未能完成源码搜索",
            details=_scope_details(action)
            + (
                ObservationErrorDetail(
                    key="error_type",
                    value=type(failure).__name__,
                ),
            ),
        ),
    )
    observations.record(failed)
    return failed


def record_search_success(
    action: AcceptedSearchCodeToolAction,
    result: SearchCodeResult,
    *,
    observations: InMemoryObservationRegistry,
) -> SearchCodeSuccessObservation:
    """核对 search_code 结果后，登记并返回成功事实。"""

    if (
        result.query != action.arguments.query
        or result.searched_scope != action.arguments.scope
        or result.returned_count > action.arguments.max_results
    ):
        raise SearchCodeResultActionMismatchError(
            "search_code 结果与 AcceptedAction 参数不一致"
        )

    success = SearchCodeSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )
    observations.record(success)
    return success


def execute_search_code_action(
    action: AcceptedSearchCodeToolAction,
    *,
    project_root: Path,
    observations: InMemoryObservationRegistry,
) -> TerminalObservation:
    """执行已接受的 search_code Action，并登记唯一终态事实。"""

    # 第一步：安全解析 Action 中的 scope。
    try:
        resolved_scope = resolve_search_scope(
            project_root,
            action.arguments.scope,
        )
    except (
        UnsafeProjectPathError,
        UnsupportedSearchScopeError,
    ) as failure:
        # 第二步：范围越出项目或指向非 Python 单文件时，登记 rejected 并返回。
        return record_search_scope_rejection(
            action,
            failure,
            observations=observations,
        )

    try:
        result = search_python_code(
            project_root,
            resolved_scope,
            action.arguments,
        )
        # 第三步：调用 Tool；Tool 确认 scope 不存在时登记 failed，
        # 不能把“没有执行搜索”伪装成零匹配。
    except SearchScopeNotFoundError as failure:
        return record_search_scope_missing(
            action,
            failure,
            resolved_scope=resolved_scope,
            observations=observations,
        )
    # 第四步：Tool 的其他系统错误同样登记 failed 并返回。
    except OSError as failure:
        return record_search_failure(
            action,
            failure,
            observations=observations,
        )

    # 第五步：Tool 返回结果后，登记 success 并返回同一 Observation。
    return record_search_success(
        action,
        result,
        observations=observations,
    )
