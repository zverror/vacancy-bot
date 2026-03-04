"""Классификатор вакансий по профессиям (keyword-based)"""
import re
from bot.config import PROFESSIONS


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
    Грубая проверка: похоже ли сообщение на вакансию.
    Отсеивает мусор, флуд, обсуждения.
    """
    if not text or len(text) < 50:
        return False

    text_lower = text.lower()

    # Позитивные сигналы — слова типичные для вакансий
    positive_signals = [
        "ищу", "ищем", "требуется", "вакансия", "нужен", "нужна", "нужны",
        "оплата", "бюджет", "зп", "з/п", "гонорар", "берём", "берем",
        "удалённо", "удаленно", "удалёнка", "удаленка", "фриланс",
        "проект", "заказ", "задача", "сотрудничество",
        "откликайтесь", "откликайся", "пишите", "пиши в лс",
        "опыт от", "опыт работы", "резюме", "портфолио",
    ]

    positive_count = sum(1 for s in positive_signals if s in text_lower)

    # Минимум 2 позитивных сигнала
    return positive_count >= 2
