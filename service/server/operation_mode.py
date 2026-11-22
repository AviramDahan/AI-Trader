"""Operational separation of Telegram news from PAPER entry discovery."""
import os


def news_only():
    value = os.getenv('AI_TRADER_OPERATION_MODE', 'paper').strip().lower()
    if value not in {'paper', 'news_only'}:
        raise ValueError('invalid_operation_mode')
    return value == 'news_only'


def require_entry_allowed(action):
    if str(action).strip().lower() in {'buy', 'short'} and news_only():
        raise ValueError('news_only_mode')
