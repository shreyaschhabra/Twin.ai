"""
SimBuffer: a finite-capacity FIFO queue used both for configured
inter-station buffers and for each entry station's arrival queue.

Deliberately NOT built on simpy.Store. A Store's get()/put() requests
register themselves on the store's internal queue and only get cleaned up
when they actually fire — that's fine with a single consumer, but this
factory has stations that must pull from MULTIPLE buffers at a merge point
(e.g. S12 receives from both the S11->S12 buffer and the S10->S12 EV-bypass
buffer). Racing several Store.get() calls with env.any_of() leaves the
"losing" get() requests permanently registered, silently stealing a future
item out from under the buffer's real consumer later on. Every buffer here
has exactly one producer (its configured upstream station) and one consumer
(its configured downstream station), so a plain deque plus two plain
simpy.Event "doorbells" is sufficient, simpler, and avoids that failure
mode entirely: any_of() on plain Events has no side effect on the buffer's
own state, so racing across multiple input buffers is safe.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Tuple

import simpy

from backend.simulation.vehicle import Vehicle


class SimBuffer:
    def __init__(self, env: simpy.Environment, buffer_id: str, capacity: int):
        self.env = env
        self.buffer_id = buffer_id
        self.capacity = capacity
        self.items: Deque[Tuple[Vehicle, float]] = deque()
        self.max_occupancy = 0
        self.item_available = env.event()
        self.space_available = env.event()

    def is_empty(self) -> bool:
        return len(self.items) == 0

    def is_full(self) -> bool:
        return len(self.items) >= self.capacity

    def peek_enqueue_time(self) -> float:
        return self.items[0][1]

    def put(self, vehicle: Vehicle, enqueue_time: float) -> None:
        if self.is_full():
            raise RuntimeError(f"buffer {self.buffer_id} overflow (capacity {self.capacity})")
        self.items.append((vehicle, enqueue_time))
        self.max_occupancy = max(self.max_occupancy, len(self.items))
        old_event, self.item_available = self.item_available, self.env.event()
        if not old_event.triggered:
            old_event.succeed()

    def get(self) -> Tuple[Vehicle, float]:
        if self.is_empty():
            raise RuntimeError(f"buffer {self.buffer_id} underflow")
        item = self.items.popleft()
        old_event, self.space_available = self.space_available, self.env.event()
        if not old_event.triggered:
            old_event.succeed()
        return item
