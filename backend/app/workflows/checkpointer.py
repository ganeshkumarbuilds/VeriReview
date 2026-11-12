from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings


class CheckpointManager:
    """
    Manages asynchronous PostgreSQL connections
    and LangGraph checkpoint persistence.
    """

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None
        self._checkpointer: AsyncPostgresSaver | None = None

    @staticmethod
    def _get_connection_string() -> str:
        """
        Convert the existing SQLAlchemy database URL
        into a psycopg-compatible PostgreSQL URL.
        """

        database_url = make_url(settings.DATABASE_URL)

        if database_url.get_backend_name() != "postgresql":
            raise ValueError(
                "LangGraph checkpointing requires PostgreSQL."
            )

        psycopg_url = database_url.set(
            drivername="postgresql"
        )

        return psycopg_url.render_as_string(
            hide_password=False
        )

    async def start(self) -> None:
        """
        Initialize the connection pool and checkpoint tables.
        """

        if self._pool is not None:
            return

        pool = AsyncConnectionPool(
            conninfo=self._get_connection_string(),
            min_size=1,
            max_size=5,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
            },
            open=False,
        )

        try:
            await pool.open(wait=True)

            checkpointer = AsyncPostgresSaver(pool)

            await checkpointer.setup()

            self._pool = pool
            self._checkpointer = checkpointer

        except Exception:
            await pool.close()
            raise

    @property
    def checkpointer(self) -> AsyncPostgresSaver:
        """
        Return the initialized LangGraph checkpointer.
        """

        if self._checkpointer is None:
            raise RuntimeError(
                "Checkpoint manager has not been started."
            )

        return self._checkpointer

    async def close(self) -> None:
        """
        Close the PostgreSQL connection pool.
        """

        if self._pool is not None:
            await self._pool.close()

            self._pool = None
            self._checkpointer = None


checkpoint_manager = CheckpointManager()