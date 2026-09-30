"""统一管理 SQLite 事务边界与连接关闭。"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def open_sqlite_connection(
    database_path: Path,
) -> Iterator[sqlite3.Connection]:
    """打开 SQLite 连接，提交或回滚事务，并保证最终关闭连接。"""

    # 第一步：调用 sqlite3.connect(database_path) 创建 connection。
    # 第二步：使用 closing(...) 管理 connection，保证最外层退出时调用
    # connection.close()。
    # 第三步：在 closing 内再使用 with connection，让 SQLite 在正常结束时
    # commit，发生异常时 rollback。
    # 第四步：在内层上下文中 yield connection，让调用者执行 SQL。
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            yield connection
