import asyncio
import sys
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.workflows.checkpointer import checkpoint_manager


class CheckpointTestState(TypedDict):
    value: int


def build_test_graph():
    builder = StateGraph(CheckpointTestState)

    builder.add_node(
        "store_value",
        lambda state: {"value": state["value"]},
    )

    builder.add_edge(START, "store_value")
    builder.add_edge("store_value", END)

    return builder.compile(
        checkpointer=checkpoint_manager.checkpointer
    )


def test_postgres_checkpoint_persistence():
    async def run_test():
        await checkpoint_manager.start()

        try:
            config = {
                "configurable": {
                    "thread_id": str(uuid4()),
                }
            }

            # Execute the workflow and save its state.
            graph = build_test_graph()

            result = await graph.ainvoke(
                {"value": 42},
                config,
            )

            assert result["value"] == 42

            # Retrieve the saved checkpoint.
            saved_state = await graph.aget_state(config)

            assert saved_state.values["value"] == 42

            # Close and reopen the PostgreSQL pool.
            await checkpoint_manager.close()
            await checkpoint_manager.start()

            # Restore the workflow using the new connection pool.
            restored_graph = build_test_graph()

            restored_state = await restored_graph.aget_state(config)

            assert restored_state.values["value"] == 42

        finally:
            await checkpoint_manager.close()

    if sys.platform == "win32":
        asyncio.run(
            run_test(),
            loop_factory=asyncio.SelectorEventLoop,
        )
    else:
        asyncio.run(run_test())