"""
Модуль для работы с часовыми поясами пользователей
"""
import sqlite3
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Импортируем TIMEZONE_DB_PATH из config, если доступен
try:
    from config import TIMEZONE_DB_PATH
    DEFAULT_DB_PATH = TIMEZONE_DB_PATH
except ImportError:
    # Если файл в databases/, то корень проекта на уровень выше
    BASE_PATH = Path(__file__).parent.parent.absolute()
    DEFAULT_DB_PATH = str(BASE_PATH / 'data' / 'timezones.db')


class TimezoneDatabase:
    """Класс для работы с часовыми поясами пользователей"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            with sqlite3.connect(self.db_path) as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS user_timezones (
                        user_id INTEGER PRIMARY KEY,
                        timezone_offset INTEGER NOT NULL DEFAULT 3,
                        updated_at TEXT NOT NULL
                    )
                """)
                db.commit()
                logger.info(f"База данных часовых поясов инициализирована: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации базы данных часовых поясов: {e}")
    
    async def get_user_timezone(self, user_id: int) -> int:
        """Получить часовой пояс пользователя (по умолчанию UTC+3)"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        "SELECT timezone_offset FROM user_timezones WHERE user_id = ?",
                        (user_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return row[0]
                    return 3  # По умолчанию UTC+3
            except Exception as e:
                logger.error(f"Ошибка при получении часового пояса пользователя {user_id}: {e}")
                return 3
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def set_user_timezone(self, user_id: int, offset: int) -> bool:
        """Установить часовой пояс пользователя"""
        # Проверяем валидность часового пояса
        if not (-12 <= offset <= 14):
            logger.warning(f"Недопустимый часовой пояс {offset} для пользователя {user_id}")
            return False
        
        def _set_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO user_timezones (user_id, timezone_offset, updated_at)
                        VALUES (?, ?, ?)
                    """, (user_id, offset, datetime.now().isoformat()))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке часового пояса пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_sync)
    
    async def get_user_date(self, user_id: int) -> str:
        """Получить текущую дату с учетом часового пояса пользователя"""
        offset = await self.get_user_timezone(self)
        # Для SQLite используем смещение от UTC
        sqlite_offset = offset - 3  # 3 - это UTC+3 (серверное время)
        
        def _get_date_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if sqlite_offset == 0:
                        cur = db.execute("SELECT date('now')")
                    else:
                        cur = db.execute("SELECT date('now', ? || ' hours')", (sqlite_offset,))
                    row = cur.fetchone()
                    return row[0] if row else datetime.now().strftime('%Y-%m-%d')
            except Exception as e:
                logger.error(f"Ошибка при получении даты для пользователя {user_id}: {e}")
                return datetime.now().strftime('%Y-%m-%d')
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_date_sync)
    
    async def get_user_datetime(self, user_id: int) -> str:
        """Получить текущую дату и время с учетом часового пояса пользователя"""
        offset = await self.get_user_timezone(user_id)
        # Для SQLite используем смещение от UTC
        sqlite_offset = offset - 3  # 3 - это UTC+3 (серверное время)
        
        def _get_datetime_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if sqlite_offset == 0:
                        cur = db.execute("SELECT datetime('now')")
                    else:
                        cur = db.execute("SELECT datetime('now', ? || ' hours')", (sqlite_offset,))
                    row = cur.fetchone()
                    return row[0] if row else datetime.now().isoformat()
            except Exception as e:
                logger.error(f"Ошибка при получении даты и времени для пользователя {user_id}: {e}")
                return datetime.now().isoformat()
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_datetime_sync)
    
    def format_timezone_offset(self, offset: int) -> str:
        """Форматировать смещение часового пояса в строку"""
        if offset >= 0:
            return f"UTC+{offset}"
        else:
            return f"UTC{offset}"
    
    def get_popular_timezones(self) -> list[tuple[int, str]]:
        """Получить список популярных часовых поясов"""
        return [
            (-12, "UTC-12"),
            (-8, "UTC-8"),
            (-5, "UTC-5"),
            (0, "UTC"),
            (3, "UTC+3"),
            (8, "UTC+8"),
            (12, "UTC+12"),
            (14, "UTC+14")
        ]
    
    async def delete_user_timezone(self, user_id: int) -> bool:
        """Удалить часовой пояс пользователя"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM user_timezones WHERE user_id = ?", (user_id,))
                    db.commit()
                    logger.info(f"Часовой пояс пользователя {user_id} удален")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении часового пояса пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)