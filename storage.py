"""FSM-хранилище в памяти, которое не копит пустые записи.

Стандартный MemoryStorage aiogram держит запись на каждого, кто хоть раз
заходил в форму, — и после state.clear() она остаётся пустой. В открытом
боте с зеркалами это тысячи мёртвых словарей. Здесь запись удаляется,
как только в ней не остаётся ни состояния, ни данных.
"""

from __future__ import annotations

from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


class LeanStorage(BaseStorage):
    def __init__(self) -> None:
        self._states: dict[StorageKey, str] = {}
        self._data: dict[StorageKey, dict[str, Any]] = {}

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        if value is None:
            self._states.pop(key, None)
        else:
            self._states[key] = value

    async def get_state(self, key: StorageKey) -> str | None:
        return self._states.get(key)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if data:
            self._data[key] = dict(data)
        else:
            self._data.pop(key, None)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return dict(self._data.get(key) or {})

    async def close(self) -> None:
        self._states.clear()
        self._data.clear()
