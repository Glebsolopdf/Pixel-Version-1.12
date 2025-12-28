"""
Обработчики команд часовых поясов
"""
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def register_timezone_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков часовых поясов"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # TODO: Зарегистрировать все обработчики часовых поясов
    # dp.message.register(mytime_command, Command("mytime"))
    # dp.callback_query.register(timezone_callback, F.data.startswith("timezone_"))
    # и т.д.


# TODO: Перенести все функции часовых поясов из bot.py
async def mytime_command(message: Message):
    """Команда настройки часового пояса"""
    # TODO: Реализовать
    pass


async def update_timezone_panel(callback: CallbackQuery, user_id: int):
    """Обновление панели часовых поясов"""
    # TODO: Реализовать
    pass

