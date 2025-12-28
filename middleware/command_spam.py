"""
Middleware для защиты от спама командами
"""
import logging
from typing import Any, Awaitable, Callable

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject

from databases.utilities_db import utilities_db

logger = logging.getLogger(__name__)


class CommandSpamMiddleware(BaseMiddleware):
    """Middleware для проверки команд на спам перед их обработкой"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        """Проверка команды на спам перед обработкой"""
        
        # Проверяем, что это сообщение
        if not isinstance(event, Message):
            return await handler(event, data)
        
        message: Message = event
        
        # Проверяем только команды в группах и супергруппах
        if message.chat.type not in ['group', 'supergroup']:
            return await handler(event, data)
        
        # Проверяем, что это команда (начинается с /)
        if not message.text or not message.text.strip().startswith('/'):
            # Но если в сообщении есть команды через entities - обнаруживаем их
            if message.text and message.entities:
                utilities_settings = await utilities_db.get_settings(message.chat.id)
                if utilities_settings.get('fake_commands_enabled', False):
                    # Ищем команды через entities (type == "bot_command")
                    for entity in message.entities:
                        if entity.type == "bot_command":
                            # Извлекаем текст команды из сообщения
                            command_text = message.text[entity.offset:entity.offset + entity.length]
                            # Записываем обнаруженную команду в БД
                            await utilities_db.add_command_detection(message.chat.id, command_text)
                            logger.debug(f"Обнаружена команда {command_text} в сообщении от пользователя {message.from_user.id} в чате {message.chat.id}")
            
            logger.debug(f"CommandSpamMiddleware: не команда, пропускаем")
            return await handler(event, data)
        
        logger.debug(f"CommandSpamMiddleware: обрабатываем команду")
        
        # Это команда, начинающаяся с /
        utilities_settings = await utilities_db.get_settings(message.chat.id)
        
        if not utilities_settings.get('fake_commands_enabled', False):
            logger.debug(f"CommandSpamMiddleware: fake_commands_enabled=False, пропускаем команду")
            return await handler(event, data)
        
        # Извлекаем команду из текста (первое слово)
        command_text = message.text.split()[0] if message.text.split() else message.text.strip()
        logger.debug(f"CommandSpamMiddleware: обрабатываем команду {command_text} в чате {message.chat.id}")
        
        # СНАЧАЛА проверяем tracking команды (до записи/обновления)
        tracking = await utilities_db.get_command_tracking(message.chat.id, command_text)
        
        if tracking and tracking.get('is_active', False):
            from datetime import datetime
            # Проверяем, прошло ли менее 60 секунд с последнего использования
            last_used_time = datetime.fromisoformat(tracking['last_used_time'])
            time_since_last_use = (datetime.now() - last_used_time).total_seconds()
            
            # Если команда использовалась ранее (usage_count >= 1) и прошло менее 60 секунд - удаляем
            if tracking.get('usage_count', 0) >= 1 and time_since_last_use < 60:
                logger.info(f"CommandSpamMiddleware: команда {command_text} считается спамом, удаляем сообщение")
                try:
                    from aiogram import Bot
                    bot: Bot = data.get('bot')
                    if bot:
                        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
                        logger.info(f"Удалена команда {command_text} в чате {message.chat.id} (спам командами)")
                        # НЕ прерываем обработку - пусть команда обработается, просто удалим сообщение
                        # return  # Прерываем обработку команды
                    else:
                        logger.warning(f"Bot не найден в data для удаления команды {command_text}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении команды-спама: {e}", exc_info=True)
        
        # Обнаруживаем команду в сообщении (если есть entities) и записываем в БД
        if message.entities:
            for entity in message.entities:
                if entity.type == "bot_command":
                    detected_command = message.text[entity.offset:entity.offset + entity.length]
                    # Записываем обнаруженную команду в БД
                    await utilities_db.add_command_detection(message.chat.id, detected_command)
        
        # Также записываем команду, если её нет в entities (на случай если это команда без @bot)
        await utilities_db.add_command_detection(message.chat.id, command_text)
        
        # Обновляем счетчик использования команды ПОСЛЕ проверки
        await utilities_db.increment_command_usage(message.chat.id, command_text)
        
        # Продолжаем обработку команды
        logger.debug(f"CommandSpamMiddleware: передаем команду {command_text} дальше в обработчик")
        return await handler(event, data)

