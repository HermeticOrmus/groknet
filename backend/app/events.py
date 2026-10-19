"""In-process event bus feeding the dashboard's /api/events SSE stream.

Every event the backend delivers to a bot webhook (and its delivery result)
is also published here. Single-process only, which is all the demo needs.
"""

import asyncio
import json
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        data = json.dumps(event, default=str)
        for q in list(self._subscribers):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                self._subscribers.discard(q)


bus = EventBus()
