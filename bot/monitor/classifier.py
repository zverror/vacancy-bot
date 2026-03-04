"""Классификатор вакансий по профессиям (keyword-based)
Обновлён 05.03.2026 на основе анализа 578 сообщений из 3 чатов.
"""
import re
from bot.config import PROFESSIONS, VACANCY_SIGNALS, SPAM_SIGNALS


def classify_vacancy(text: str) -> list[str]:
    """
    Определяет профессии, к которым относится вакансия.
    Возвращает список подходящих профессий.
    """
    text_lower = text.lower()
    matched = []

    for profession, keywords in PROFESSIONS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(profession)
                break

    return matched


def is_vacancy(text: str) -> bool:
    """
    Определяет, похоже ли сообщение на вакансию.
    Двухуровневая проверка: позитивные сигналы + антиспам.
    """
    if not text or len(text) < 40:
        return False

    text_lower = text.lower()

    # Антиспам — если совпало, это НЕ вакансия
    for pattern in SPAM_SIGNALS:
        if re.search(pattern, text_lower):
            return False

    # Позитивные сигналы
    positive_count = sum(1 for s in VACANCY_SIGNALS if s in text_lower)

    # Хэштеги #ищу #вакансия — сильный сигнал
    hashtag_boost = 0
    if "#вакансия" in text_lower or "#ищу" in text_lower:
        hashtag_boost = 2

    # Минимум 2 позитивных сигнала (или 1 + хэштег)
    return (positive_count + hashtag_boost) >= 2
