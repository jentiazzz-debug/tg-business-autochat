"""Что можно узнать о собеседнике честными средствами.

Никакого «дoкса» тут нет и не будет: настоящих персональных данных —
телефона, адреса, паспорта — Telegram боту не отдаёт, а собирать их из
сторонних источников я не стану. Здесь только то, что человек сам
показывает в Telegram, плюс статистика поведения в переписке с
владельцем, которую бот собрал сам.

Именно вторая часть и оказывается самой полезной: чужие боты пересылают
событие «сообщение удалено» и забывают о нём. Этот помнит, и потому
может сказать «этот человек удалил у вас 14 сообщений и 6 раз правил
написанное» — то, что о собеседнике говорит больше любой анкеты.
"""

from __future__ import annotations

from datetime import date, datetime

#: Опорные точки «id — примерная дата регистрации». Telegram выдаёт id
#: подряд, поэтому по нему можно оценить, когда человек зарегистрировался.
#: Точность — месяцы, и в карточке это подписано словом «оценка»:
#: выдавать интерполяцию за точную дату нечестно.
ANCHORS: tuple[tuple[int, date], ...] = (
    (1_000_000, date(2013, 6, 1)),
    (10_000_000, date(2013, 9, 1)),
    (50_000_000, date(2014, 6, 1)),
    (100_000_000, date(2015, 6, 1)),
    (200_000_000, date(2017, 1, 1)),
    (300_000_000, date(2018, 2, 1)),
    (400_000_000, date(2019, 1, 1)),
    (500_000_000, date(2020, 4, 1)),
    (700_000_000, date(2021, 6, 1)),
    (1_000_000_000, date(2022, 1, 1)),
    (1_500_000_000, date(2022, 9, 1)),
    (2_000_000_000, date(2023, 6, 1)),
    (5_000_000_000, date(2024, 1, 1)),
    (6_000_000_000, date(2024, 6, 1)),
    (7_000_000_000, date(2024, 11, 1)),
    (8_000_000_000, date(2025, 6, 1)),
)


def registered(user_id: int) -> date | None:
    """Оценка даты регистрации по id. None — если id вне опорных точек."""
    if user_id <= 0:
        return None
    if user_id < ANCHORS[0][0]:
        return ANCHORS[0][1]
    for (id_a, date_a), (id_b, date_b) in zip(ANCHORS, ANCHORS[1:]):
        if id_a <= user_id <= id_b:
            span_ids = id_b - id_a
            span_days = (date_b - date_a).days
            k = (user_id - id_a) / span_ids if span_ids else 0
            return date_a.fromordinal(date_a.toordinal() + round(span_days * k))
    last_id, last_date = ANCHORS[-1]
    if user_id > last_id:
        # За последней точкой линейную оценку продолжаем осторожно: рост
        # id неравномерный, и уводить прогноз в будущее нельзя.
        per_day = (ANCHORS[-1][0] - ANCHORS[-2][0]) / max(
            (ANCHORS[-1][1] - ANCHORS[-2][1]).days, 1
        )
        days = (user_id - last_id) / per_day if per_day else 0
        guess = last_date.fromordinal(last_date.toordinal() + round(days))
        return min(guess, date.today())
    return None


def age_words(when: date) -> str:
    """«3 года 2 месяца» — сколько аккаунту от оценённой даты."""
    today = date.today()
    months = (today.year - when.year) * 12 + (today.month - when.month)
    years, months = divmod(max(months, 0), 12)
    parts = []
    if years:
        parts.append(f"{years} {_plural(years, 'год', 'года', 'лет')}")
    if months:
        parts.append(f"{months} {_plural(months, 'месяц', 'месяца', 'месяцев')}")
    return " ".join(parts) or "меньше месяца"


def _plural(n: int, one: str, few: str, many: str) -> str:
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def trust(chat: dict | object) -> tuple[int, str]:
    """Оценка «насколько ровно человек себя ведёт»: 0–100 и словом.

    Считается только по тому, что бот видел сам: сколько сообщений
    пришло, сколько из них человек потом удалил или переписал, сколько
    раз срабатывал антискам. Это не «рейтинг человека» — это ответ на
    вопрос «часто ли он переписывает историю переписки с вами».
    """

    def get(name: str) -> int:
        try:
            return int(chat[name] or 0)  # type: ignore[index]
        except (KeyError, TypeError, IndexError):
            return int(getattr(chat, name, 0) or 0)

    incoming = get("incoming")
    if incoming < 5:
        return 0, "мало данных"

    deleted, edited, flagged = get("deleted"), get("edited"), get("flagged")
    # Удаление весит больше правки: переписать опечатку нормально,
    # а убирать сообщения из переписки — уже привычка.
    penalty = (deleted * 3 + edited + flagged * 8) / incoming * 100
    score = max(0, min(100, round(100 - penalty)))
    if score >= 90:
        word = "ровно"
    elif score >= 70:
        word = "бывает"
    elif score >= 40:
        word = "часто правит историю"
    else:
        word = "переписку зачищает"
    return score, word


def since_words(ts: int) -> str:
    if not ts:
        return "неизвестно"
    started = datetime.fromtimestamp(ts).date()
    return f"{started.strftime('%d.%m.%Y')} ({age_words(started)} назад)"
