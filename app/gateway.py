import asyncio
import random
from typing import Literal


async def simulate_payment() -> Literal["succeeded", "failed"]:
    await asyncio.sleep(random.uniform(2, 5))

    if random.random() < 0.9:
        return "succeeded"

    return "failed"