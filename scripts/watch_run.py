"""Watch a flow run until it reaches a final state, printing progress.

Usage: PREFECT_API_URL=... uv run python scripts/watch_run.py <flow_run_id>
"""

import asyncio
import sys
from uuid import UUID


async def main(run_id: UUID) -> None:
    from prefect.client.orchestration import get_client

    async with get_client() as client:
        last_state = None
        while True:
            fr = await client.read_flow_run(run_id)
            state = fr.state
            if state.name != last_state:
                print(f"state: {state.type.value} - {state.name}", flush=True)
                last_state = state.name
            if state.is_final():
                print(f"FINAL: {state.type.value} - {state.name}")
                print(f"start: {fr.start_time}  end: {fr.end_time}")
                if fr.start_time and fr.end_time:
                    print(f"duration: {(fr.end_time - fr.start_time)}")
                break
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main(UUID(sys.argv[1])))
