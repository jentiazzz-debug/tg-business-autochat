"""Разделяемое состояние в памяти процесса.

Отдельный модуль нужен, чтобы business.py и команды могли смотреть в
одни и те же данные, не импортируя друг друга: иначе получается кольцо
business → commands → cmd_chat → business, и Python на нём падает.

Всё здесь живёт до перезапуска и намеренно не пишется в базу: это
подсказки на пару минут, а не история.
"""

from __future__ import annotations

import time

#: (owner_id, chat_id) -> (когда, что сделал, почему)
_decisions: dict[tuple[int, int], tuple[float, str, str]] = {}

#: Кому уже говорили про нехватку прав — чтобы не напоминать на каждую
#: команду.
_warned: set[tuple[int, str]] = set()


def remember(owner_id: int, chat_id: int, kind: str, reason: str) -> None:
    _decisions[(owner_id, chat_id)] = (time.time(), kind, reason)


def last(owner_id: int, chat_id: int) -> tuple[float, str, str] | None:
    return _decisions.get((owner_id, chat_id))


def warn_once(owner_id: int, topic: str) -> bool:
    """True — про это владельцу ещё не говорили."""
    key = (owner_id, topic)
    if key in _warned:
        return False
    _warned.add(key)
    return True


def forget_owner(owner_id: int) -> None:
    for key in [k for k in _decisions if k[0] == owner_id]:
        _decisions.pop(key, None)
    for key in [k for k in _warned if k[0] == owner_id]:
        _warned.discard(key)
