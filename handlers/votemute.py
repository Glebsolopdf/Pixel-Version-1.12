"""
Обработчики команд голосования за мут
"""
import asyncio
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from databases.database import db
from databases.votemute_db import votemute_db
from databases.reputation_db import reputation_db
from utils.permissions import get_effective_rank
from utils.formatting import get_user_mention_html
from utils.constants import RANK_USER
from handlers.common import fast_edit_message, safe_answer_callback

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def register_votemute_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команд голосования"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Команды
    dp.message.register(votemute_command, Command("votemute"))
    
    # Callbacks
    dp.callback_query.register(votemute_vote_callback, F.data.startswith("votemute_vote_"))


async def send_votemute_message(chat_id: int, vote_id: int, vote_data: dict) -> Message:
    """Отправить сообщение с голосованием"""
    target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" or f"ID{vote_data['target_user_id']}"
    creator_name = vote_data['creator_first_name'] or f"@{vote_data['creator_username']}" or f"ID{vote_data['creator_id']}"
    
    mute_duration_min = vote_data['mute_duration'] // 60
    mute_duration_text = f"{mute_duration_min} минут" if mute_duration_min < 60 else f"{mute_duration_min // 60} час"
    
    text = f"""🗳 <b>Голосование за мут</b>

👤 <b>Нарушитель:</b> {target_name}
⏱️ <b>Время мута:</b> {mute_duration_text}
<b>Нужно голосов:</b> {vote_data['required_votes']}
⏰ <b>Голосование:</b> {vote_data['vote_duration']} мин

👥 <b>Голоса за:</b> 0
❌ <b>Голоса против:</b> 0

<i>Создатель: {creator_name}</i>"""
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ За мут (0)",
        callback_data=f"votemute_vote_{vote_id}_for"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Против (0)",
        callback_data=f"votemute_vote_{vote_id}_against"
    ))
    builder.adjust(2)
    
    return await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )


async def update_votemute_message(chat_id: int, message_id: int, vote_id: int):
    """Обновить сообщение с голосованием"""
    try:
        vote_data = await votemute_db.get_vote(vote_id)
        if not vote_data:
            return
        
        votes_for = await votemute_db.get_votes_count(vote_id, 'for')
        votes_against = await votemute_db.get_votes_count(vote_id, 'against')
        
        target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" or f"ID{vote_data['target_user_id']}"
        creator_name = vote_data['creator_first_name'] or f"@{vote_data['creator_username']}" or f"ID{vote_data['creator_id']}"
        
        mute_duration_min = vote_data['mute_duration'] // 60
        mute_duration_text = f"{mute_duration_min} минут" if mute_duration_min < 60 else f"{mute_duration_min // 60} час"
        
        text = f"""🗳 <b>Голосование за мут</b>

👤 <b>Нарушитель:</b> {target_name}
⏱️ <b>Время мута:</b> {mute_duration_text}
<b>Нужно голосов:</b> {vote_data['required_votes']}
⏰ <b>Голосование:</b> {vote_data['vote_duration']} мин

👥 <b>Голоса за:</b> {votes_for}
❌ <b>Голоса против:</b> {votes_against}

<i>Создатель: {creator_name}</i>"""
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=f"✅ За мут ({votes_for})",
            callback_data=f"votemute_vote_{vote_id}_for"
        ))
        builder.add(InlineKeyboardButton(
            text=f"❌ Против ({votes_against})",
            callback_data=f"votemute_vote_{vote_id}_against"
        ))
        builder.adjust(2)
        
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения голосования: {e}")


async def votemute_timer(vote_id: int, duration_seconds: int):
    """Таймер голосования"""
    await asyncio.sleep(duration_seconds)
    
    try:
        vote_data = await votemute_db.get_vote(vote_id)
        if not vote_data or not vote_data['is_active']:
            return
        
        # Завершаем голосование
        votes_for = await votemute_db.get_votes_count(vote_id, 'for')
        votes_against = await votemute_db.get_votes_count(vote_id, 'against')
        
        # Определяем результат
        if votes_for >= vote_data['required_votes'] and votes_for > votes_against:
            # Мут одобрен
            await apply_mute_from_vote(vote_data, votes_for, votes_against)
        else:
            # Мут отклонен
            await reject_mute_from_vote(vote_data, votes_for, votes_against)
        
        # Деактивируем голосование
        await votemute_db.deactivate_vote(vote_id)
        
    except Exception as e:
        logger.error(f"Ошибка в таймере голосования {vote_id}: {e}")


async def apply_mute_from_vote(vote_data: dict, votes_for: int, votes_against: int):
    """Применить мут после голосования"""
    try:
        chat_id = vote_data['chat_id']
        target_user_id = vote_data['target_user_id']
        mute_duration = vote_data['mute_duration']
        
        mute_until = datetime.now() + timedelta(seconds=mute_duration)
        
        # Применяем мут
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=mute_until
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('mute', mute_duration)
        await reputation_db.add_recent_punishment(target_user_id, 'mute', mute_duration)
        await reputation_db.update_reputation(target_user_id, penalty)
        
        # Формируем сообщение о результате
        target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" or f"ID{target_user_id}"
        mute_duration_min = mute_duration // 60
        mute_duration_text = f"{mute_duration_min} минут" if mute_duration_min < 60 else f"{mute_duration_min // 60} час"
        
        result_text = f"""✅ <b>Голосование завершено</b>

👤 <b>Нарушитель:</b> {target_name}
🔇 <b>Мут применен на:</b> {mute_duration_text}

<b>Результаты:</b>
✅ За: {votes_for}
❌ Против: {votes_against}"""
        
        await bot.edit_message_text(
            result_text,
            chat_id=chat_id,
            message_id=vote_data['message_id'],
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при применении мута из голосования: {e}")


async def reject_mute_from_vote(vote_data: dict, votes_for: int, votes_against: int):
    """Отклонить мут после голосования"""
    try:
        chat_id = vote_data['chat_id']
        target_user_id = vote_data['target_user_id']
        
        target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" or f"ID{target_user_id}"
        
        result_text = f"""❌ <b>Голосование отклонено</b>

👤 <b>Участник:</b> {target_name}
🔊 <b>Мут не применен</b>

<b>Результаты:</b>
✅ За: {votes_for} (требовалось: {vote_data['required_votes']})
❌ Против: {votes_against}"""
        
        await bot.edit_message_text(
            result_text,
            chat_id=chat_id,
            message_id=vote_data['message_id'],
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отклонении мута из голосования: {e}")


async def votemute_command(message: Message):
    """Команда создания голосования за мут"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if message.chat.type == 'private':
        await message.answer("Эта команда работает только в группах и супергруппах")
        return
    
    can_create = await votemute_db.check_cooldown(chat_id)
    if not can_create:
        await message.answer("Голосование можно создать раз в 3 минуты. Подождите немного.")
        return
    
    active_vote = await votemute_db.get_active_vote(chat_id)
    if active_vote:
        await message.answer("В чате уже есть активное голосование. Дождитесь его завершения.")
        return
    
    args = message.text.split()
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            await message.answer(
                "Некорректный формат команды\n\n"
                "Использование:\n"
                "• /votemute (при ответе на сообщение)\n"
                "• /votemute @username"
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            await message.answer(
                "Некорректный формат команды\n\n"
                "Использование:\n"
                "• /votemute (при ответе на сообщение)\n"
                "• /votemute @username"
            )
            return
        
        username = args[1]
        if not username.startswith('@'):
            await message.answer("Укажите username с символом @")
            return
        
        username = username[1:]
        
        try:
            user_info = await db.get_user_by_username(username)
            if not user_info:
                await message.answer(f"Пользователь @{username} не найден в базе данных.")
                return
            
            target_user = SimpleNamespace(
                id=user_info['user_id'],
                username=user_info['username'],
                first_name=user_info['first_name'],
                last_name=user_info['last_name'],
                is_bot=user_info['is_bot']
            )
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя @{username}: {e}")
            await message.answer(f"Ошибка при поиске пользователя @{username}")
            return
    
    if target_user.id == user_id:
        await message.answer("Нельзя создать голосование на самого себя")
        return
    
    if target_user.is_bot:
        await message.answer("Нельзя создать голосование на бота")
        return
    
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank != RANK_USER:
        await message.answer("Голосование можно создать только на обычных участников")
        return
    
    try:
        await votemute_db.set_cooldown(chat_id)
        
        vote_id = await votemute_db.create_vote(
            chat_id=chat_id,
            target_user_id=target_user.id,
            creator_id=user_id,
            mute_duration=30 * 60,
            required_votes=5,
            vote_duration=5,
            is_pinned=False,
            target_username=target_user.username,
            target_first_name=target_user.first_name,
            target_last_name=target_user.last_name,
            creator_username=message.from_user.username,
            creator_first_name=message.from_user.first_name,
            creator_last_name=message.from_user.last_name
        )
        
        vote_data = {
            'target_user_id': target_user.id,
            'target_username': target_user.username,
            'target_first_name': target_user.first_name,
            'target_last_name': target_user.last_name,
            'creator_id': user_id,
            'creator_username': message.from_user.username,
            'creator_first_name': message.from_user.first_name,
            'creator_last_name': message.from_user.last_name,
            'mute_duration': 30 * 60,
            'required_votes': 5,
            'vote_duration': 5,
            'vote_id': vote_id
        }
        
        vote_message = await send_votemute_message(chat_id, vote_id, vote_data)
        
        await votemute_db.update_vote_message_id(vote_id, vote_message.message_id)
        
        asyncio.create_task(votemute_timer(vote_id, 5 * 60))
        
    except Exception as e:
        logger.error(f"Ошибка при создании голосования: {e}")
        await message.answer("❌ Ошибка при создании голосования")


async def votemute_vote_callback(callback: CallbackQuery):
    """Обработчик голосования"""
    try:
        parts = callback.data.split("_")
        vote_id = int(parts[2])
        vote_type = parts[3]
        
        user_id = callback.from_user.id
        
        vote_data = await votemute_db.get_vote(vote_id)
        if not vote_data:
            await safe_answer_callback(callback, "Голосование не найдено", show_alert=True)
            return
        
        if not vote_data['is_active']:
            await safe_answer_callback(callback, "Голосование завершено", show_alert=True)
            return
        
        # Проверяем, не голосовал ли уже пользователь
        existing_vote = await votemute_db.get_user_vote(vote_id, user_id)
        if existing_vote:
            await safe_answer_callback(callback, "Вы уже проголосовали", show_alert=True)
            return
        
        # Нельзя голосовать за себя
        if user_id == vote_data['target_user_id']:
            await safe_answer_callback(callback, "Нельзя голосовать за себя", show_alert=True)
            return
        
        # Регистрируем голос
        await votemute_db.add_vote(vote_id, user_id, vote_type)
        
        # Обновляем сообщение
        await update_votemute_message(
            vote_data['chat_id'],
            vote_data['message_id'],
            vote_id
        )
        
        # Проверяем, не достигнут ли лимит голосов
        votes_for = await votemute_db.get_votes_count(vote_id, 'for')
        if votes_for >= vote_data['required_votes']:
            votes_against = await votemute_db.get_votes_count(vote_id, 'against')
            await votemute_db.deactivate_vote(vote_id)
            await apply_mute_from_vote(vote_data, votes_for, votes_against)
            await safe_answer_callback(callback, "Мут одобрен!")
            return
        
        await safe_answer_callback(callback, "Голос учтен!")
        
    except Exception as e:
        logger.error(f"Ошибка в votemute_vote_callback: {e}")
        await safe_answer_callback(callback, "Ошибка", show_alert=True)
