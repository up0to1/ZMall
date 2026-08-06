"""
MySQL 数据库客户端统一封装

现统一封装为 DbClient 类，从环境变量读 MySQL 配置，提供：
  - get_engine()：获取 SQLAlchemy Engine（连接池）
  - get_session()：获取 SQLAlchemy Session 上下文管理器
  - execute()：便捷执行 SQL（支持 text + 参数）

配置来源（环境变量，与 .env 对齐）：
  MYSQL_HOST / MYSQL_PORT / MYSQL_USERNAME / MYSQL_PASSWORD / MYSQL_DATABASE

用法：
    from shared.db_client import DbClient

    db = DbClient()
    with db.get_session() as session:
        from sqlalchemy import text
        rows = session.execute(text("SELECT id, name FROM item LIMIT 10")).all()

    # 或便捷执行
    rows = db.execute("SELECT id, name FROM item LIMIT 10")
"""
import logging
import os
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DbClient:
    """MySQL 数据库客户端（SQLAlchemy 封装，连接池复用）

    单例模式：同一进程复用同一 Engine 和 sessionmaker。
    """

    _engine: Engine | None = None
    _session_factory: sessionmaker | None = None

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ):
        """
        Args:
            host/port/username/password/database: 数据库连接参数
                不传时从环境变量读取（MYSQL_HOST 等）
        """
        self.host = host or os.getenv("MYSQL_HOST", "192.168.59.128")
        self.port = port or int(os.getenv("MYSQL_PORT", "3306"))
        self.username = username or os.getenv("MYSQL_USERNAME", "root")
        self.password = password or os.getenv("MYSQL_PASSWORD", "")
        self.database = database or os.getenv("MYSQL_DATABASE", "hmall")

    def _mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )

    def get_engine(self) -> Engine:
        """获取 SQLAlchemy Engine（单例，连接池复用）

        pool_pre_ping=True：每次借出连接前 ping 一下，避免使用已断开的连接
        pool_recycle=3600：1 小时回收连接，避免 MySQL wait_timeout 踢掉连接
        """
        if self._engine is None:
            self._engine = create_engine(
                self._mysql_url(),
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=5,
                max_overflow=10,
            )
            logger.info("MySQL Engine 已创建: %s@%s:%s/%s",
                         self.username, self.host, self.port, self.database)
        return self._engine

    def get_session_factory(self) -> sessionmaker:
        """获取 sessionmaker（单例）"""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.get_engine())
        return self._session_factory

    @contextmanager
    def get_session(self):
        """获取 Session 上下文管理器（自动 commit/rollback/close）

        用法：
            with db.get_session() as session:
                session.execute(text("INSERT INTO ..."))
                # 退出 with 块时自动 commit（无异常）或 rollback（有异常）
        """
        session: Session = self.get_session_factory()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute(self, sql: str, params: dict | None = None) -> list[Any]:
        """便捷执行 SQL 查询（返回结果行列表）

        Args:
            sql: SQL 语句（用 :name 占位符）
            params: 参数字典
        Returns:
            Row 对象列表（可通过 row.column_name 或 row[0] 访问）
        """
        with self.get_session() as session:
            result = session.execute(text(sql), params or {})
            return list(result.all())

    def close(self):
        """释放 Engine 资源"""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("MySQL Engine 已释放")
