"""Классификатор вакансий по профессиям (keyword-based)
Обновлён 05.03.2026 на основе анализа 578 сообщений из 3 чатов.
"""
import re
from bot.config import PROFESSIONS, VACANCY_SIGNALS, SPAM_SIGNALS


def classify_vacancy(text: str) -> list[str]:
    """
    Определяет профессии, к которым относится вакансия.
    Возвращает список подходящих профессий.
    Поддерживает как обычные подстроки, так и regex-паттерны (содержат . * + и т.д.)
    """
    text_lower = text.lower()
    matched = []

    for profession, keywords in PROFESSIONS.items():
        for kw in keywords:
            kw_lower = kw.lower()
            # Если ключевое слово содержит regex-спецсимволы — используем re.search
            if any(c in kw_lower for c in ".*+?[](){}|\\^$"):
                if re.search(kw_lower, text_lower):
                    matched.append(profession)
                    break
            else:
                if kw_lower in text_lower:
                    matched.append(profession)
                    break

    return matched


def is_vacancy(text: str) -> bool:
    """
    Определяет, похоже ли сообщение на вакансию.
    Двухуровневая проверка: позитивные сигналы + антиспам.
    """
    if not text or len(text) < 30:
        return False

    text_lower = text.lower()

    # Антиспам — если совпало, это НЕ вакансия
    # re.DOTALL чтобы .* ловил переносы строк
    for pattern in SPAM_SIGNALS:
        if re.search(pattern, text_lower, re.DOTALL):
            return False

    # Позитивные сигналы
    positive_count = sum(1 for s in VACANCY_SIGNALS if s in text_lower)

    # Хэштеги #ищу #вакансия — сильный сигнал
    if "#вакансия" in text_lower or "#ищу" in text_lower or "#работа" in text_lower:
        positive_count += 2

    # 1 сигнала достаточно — антиспам уже отсёк мусор выше
    return positive_count >= 1
