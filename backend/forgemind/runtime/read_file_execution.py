"""把 read_file 的同一字节快照连接到版本校验和分段结果。"""

from forgemind.runtime.versioning import verify_read_file_snapshot_version
from forgemind.schema.actions import AcceptedReadFileToolAction
from forgemind.schema.observations import ReadFileSuccessObservation
from forgemind.schema.read_file import ReadFileResult
from forgemind.state.observation_registry import InMemoryObservationRegistry
from forgemind.tools.read_file import slice_verified_text_snapshot


class ReadFileResultActionMismatchError(ValueError):
    """read_file 成功结果超出了对应 Action 的权威参数范围。"""

    def __init__(self, mismatched_fields: tuple[str, ...]) -> None:
        self.mismatched_fields = mismatched_fields
        super().__init__(
            "read_file 结果与 Action 不一致：" + ", ".join(mismatched_fields)
        )


def build_read_file_result_from_snapshot(
    action: AcceptedReadFileToolAction,
    *,
    content: bytes,
) -> ReadFileResult:
    """从同一份已读取字节生成经过版本校验的 read_file 结果。"""

    # 先校验版本，避免解码或返回未经批准的新内容。
    version = verify_read_file_snapshot_version(action, content=content)

    # 校验与解码必须使用同一份 content，不能在中间重新打开文件。
    text = content.decode("utf-8")
    arguments = action.arguments

    # 分段范围来自 Runtime 已接受并冻结的 Action 参数。
    return slice_verified_text_snapshot(
        path=arguments.path,
        text=text,
        start_line=arguments.start_line,
        max_lines=arguments.max_lines,
        version=version,
    )


def verify_read_file_result_matches_action(
    action: AcceptedReadFileToolAction,
    result: ReadFileResult,
) -> ReadFileResult:
    """确认成功结果没有偏离 Runtime 接受的 Action 参数。"""

    # 第一步：取得权威参数并准备错误列表。
    arguments = action.arguments
    mismatched_fields: list[str] = []

    # 第二步：检查路径。
    if result.path != arguments.path:
        mismatched_fields.append("path")

    # 第三步：检查起始行。
    if result.start_line != arguments.start_line:
        mismatched_fields.append("start_line")

    # 第四步：检查实际返回行数不能超过批准上限。
    if result.returned_lines > arguments.max_lines:
        mismatched_fields.append("returned_lines")

    # 第五步：检查结果属于 Action 绑定的文件版本。
    if result.version != arguments.expected_version:
        mismatched_fields.append("version")

    # 第六步：存在问题时一次报告全部不一致字段。
    if mismatched_fields:
        raise ReadFileResultActionMismatchError(tuple(mismatched_fields))

    # 第七步：全部一致时返回原结果。
    return result


def record_read_file_success(
    action: AcceptedReadFileToolAction,
    result: ReadFileResult,
    *,
    observations: InMemoryObservationRegistry,
) -> ReadFileSuccessObservation:
    """形成 read_file 成功事实，登记到 State 后再返回。"""

    verify_read_file_result_matches_action(action, result)

    # 成功结果必须引用权威 Action 的编号，不能另造关联标识。
    success = ReadFileSuccessObservation(
        action_id=action.action_id,
        status="success",
        result=result,
    )

    # 先写入 State；登记失败时不能向 Agent 声称操作已经成功。
    observations.record(success)
    return success
