#!/usr/bin/env python3

import re
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
import asyncio
import os
from os import path
import aiosqlite
import toml
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, DocumentAttributeFilename, MessageMediaWebPage, User


if not path.exists('db'):
    os.makedirs('db')

if path.exists("data.sqlite3"):
    os.rename("data.sqlite3", "./db/data.sqlite3")

DB_PATH = './db/data.sqlite3'

config = toml.load('config.toml')

api_id = config.get('api_id')
api_hash = config.get('api_hash')
session = config.get('session')
enabled_chats = config.get('enabled_chats', [])
disabled_chats = config.get('disabled_chats', [])
save_media = config.get('save_media', True)
log_to_file = config.get('log_to_file', False)
log_colors = config.get('log_colors', not log_to_file and sys.stdout.isatty())

if log_colors:
    RESET = '\x1b[0m'
    BOLD = '\x1b[1m'
    DIM = '\x1b[2m'
    RED = '\x1b[31m'
    GREEN = '\x1b[32m'
    YELLOW = '\x1b[33m'
    BLUE = '\x1b[34m'
    MAGENTA = '\x1b[35m'
    CYAN = '\x1b[36m'
    WHITE = '\x1b[37m'
    GRAY = '\x1b[90m'
else:
    RESET = ''
    BOLD = ''
    DIM = ''
    RED = ''
    GREEN = ''
    YELLOW = ''
    BLUE = ''
    MAGENTA = ''
    CYAN = ''
    WHITE = ''
    GRAY = ''


async def main():
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:

        def get_display_name(entity: Union[Channel, Chat, User]) -> str:
            username = getattr(entity, 'username', None)
            if username:
                return username

            if isinstance(entity, User):
                display_name = entity.first_name
                if entity.last_name:
                    display_name += f' {entity.last_name}'
            else:
                display_name = entity.title

            return display_name

        def is_enabled(chat_id: int) -> bool:
            return (not enabled_chats or chat_id in enabled_chats) and (chat_id not in disabled_chats)

        def iso_date(dt: datetime) -> str:
            return dt.strftime('%Y-%m-%d %H:%M:%S')

        async def get_user(user_id: int, chat_id: Optional[int] = None) -> User:
            if not user_id:
                return None

            try:
                return await client.get_entity(user_id)
            except ValueError:
                if not chat_id:
                    return None

                await client.get_participants(chat_id)

                try:
                    return await client.get_entity(user_id)
                except ValueError:
                    await client.get_participants(chat_id, aggressive=True)
                    try:
                        return await client.get_entity(user_id)
                    except ValueError:
                        return None

        @client.on(events.NewMessage)
        async def on_new_message(event: events.NewMessage.Event) -> None:
            msg = event.message

            date = msg.date

            chat = await client.get_entity(msg.peer_id)
            if not is_enabled(chat.id):
                return

            user = await get_user(msg.from_id, chat.id)

            text = msg.message

            chat_display = f'[{get_display_name(chat)} ({chat.id})]'
            msg_display = f'({msg.id})'
            if user:
                user_display = f'<{get_display_name(user)} ({user.id})>'

            out = f'{GRAY}{iso_date(date)}{RESET} {BOLD}{BLUE}MSG{RESET} {BOLD}{GRAY}{chat_display}{RESET} {GRAY}{msg_display}{RESET}'
            if user:
                out += f' {BOLD}{user_display}{RESET}'
            if text:
                out += f' {text}{RESET}'
            if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                media_type = re.sub(r'^MessageMedia', '', msg.media.__class__.__name__)
                try:
                    filename = next(
                        x.file_name for x in msg.media.document.attributes if isinstance(x, DocumentAttributeFilename))
                except (AttributeError, StopIteration):
                    filename = None

                if filename:
                    media_display = f'[{media_type}: {filename}]'
                else:
                    media_display = f'[{media_type}]'
                out += f' {MAGENTA}{media_display}{RESET}'
            else:
                media_type = None
                filename = None

            if log_to_file:
                logfile = Path('logs', f'{chat.id}.log')
                logfile.parent.mkdir(exist_ok=True)
                with logfile.open('a') as fd:
                    fd.write(f'{out}\n')
            else:
                print(out, flush=True)

            file_id = None
            if filename is not None:
                file_id = msg.media.document.id

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO event
                        (type, date, chat_id, message_id, user_id, text, media_type, media_filename, media_id)
                    VALUES
                        ('new_message', :date, :chat_id, :message_id, :user_id, :text, :media_type, :media_filename, :media_id)
                """, {
                    'date': msg.date.timestamp(),
                    'chat_id': chat.id,
                    'message_id': msg.id,
                    'user_id': user.id if user else None,
                    'text': text,
                    'media_type': media_type,
                    'media_filename': filename,
                    'media_id': file_id,
                })
                await db.commit()

            if msg.media and not isinstance(msg.media, MessageMediaWebPage) and save_media:
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute('SELECT * FROM event WHERE media_id = :media_id', {'media_id': file_id})
                    row = len(await cursor.fetchall())
                    if row > 1:
                        return

                path = Path('media', str(chat.id), str(msg.id))
                path.mkdir(parents=True, exist_ok=True)
                await client.download_media(msg, path)

        @client.on(events.MessageEdited)
        async def on_message_edited(event: events.MessageEdited.Event) -> None:
            msg = event.message

            date = msg.edit_date

            chat = await client.get_entity(msg.peer_id)
            if not is_enabled(chat.id):
                return

            user = await get_user(msg.from_id, chat.id)

            text = msg.message

            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("""
                SELECT
                    text, media_type, media_filename
                FROM
                    event
                WHERE
                    chat_id = :chat_id
                    AND message_id = :message_id
                ORDER BY
                    rowid DESC
                LIMIT
                    1
                """, {'chat_id': chat.id, 'message_id': msg.id})

                innerRow = await cursor.fetchone()
                await cursor.close()

            if innerRow:
                old_text, old_media_type, old_filename = innerRow
            else:
                old_text, old_media_type, old_filename = None, None, None

            # TODO: Find a way to check if media is the same
            # if text == old_text:
            #    # Non-text change (e.g. inline keyboard)
            #    return

            chat_display = f'[{get_display_name(chat)} ({chat.id})]'
            msg_display = f'({msg.id})'
            if user:
                user_display = f'<{get_display_name(user)} ({user.id})>'
            if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                media_type = re.sub(r'^MessageMedia', '', msg.media.__class__.__name__)
                try:
                    filename = next(
                        x.file_name for x in msg.media.document.attributes if isinstance(x, DocumentAttributeFilename))
                except (AttributeError, StopIteration):
                    filename = None
                if filename:
                    media_display = f'[{media_type}: {filename}]'
                else:
                    media_display = f'[{media_type}]'
            else:
                media_type = None
                filename = None

            out = f'{GRAY}{iso_date(date)}{RESET} {BOLD}{YELLOW}EDIT{RESET} {BOLD}{GRAY}{chat_display}{RESET} {GRAY}{msg_display}{RESET}'
            if user:
                out += f' {BOLD}{user_display}{RESET}'
            if old_text or old_media_type:
                out += '\n-'
                if old_text:
                    out += f'{RED}{old_text}{RESET}'
                if old_media_type:
                    if old_filename:
                        old_media_display = f'[{old_media_type}: {old_filename}]'
                    else:
                        old_media_display = f'[{old_media_type}]'

                    if old_text:
                        out += ' '
                    out += f'{MAGENTA}{old_media_display}{RESET}'

                out += '\n+'
                if text:
                    out += f'{GREEN}{text}{RESET}'
                if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                    if text:
                        out += ' '
                    if filename:
                        media_display = f'[{media_type}: {filename}]'
                    else:
                        media_display = f'[{media_type}]'
                    out += f'{MAGENTA}{media_display}{RESET}'
            else:
                if text:
                    out += f' {GREEN}{text}{RESET}'
                if msg.media and not isinstance(msg.media, MessageMediaWebPage):
                    out += f' {MAGENTA}{media_display}{RESET}'

            if log_to_file:
                logfile = Path('logs', f'{chat.id}.log')
                logfile.parent.mkdir(exist_ok=True)
                with logfile.open('a') as fd:
                    fd.write(f'{out}\n')
            else:
                print(out)

            file_id = None
            if filename is not None:
                file_id = msg.media.document.id

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO event
                        (type, date, chat_id, message_id, user_id, text, media_type, media_filename, media_id)
                    VALUES
                        ('message_edited', :date, :chat_id, :message_id, :user_id, :text, :media_type, :media_filename, :media_id)
                """, {
                    'date': msg.date.timestamp(),
                    'chat_id': chat.id,
                    'message_id': msg.id,
                    'user_id': user.id if user else None,
                    'text': text,
                    'media_type': media_type,
                    'media_filename': filename,
                    'media_id': file_id
                })
                await db.commit()

            if msg.media and not isinstance(msg.media, MessageMediaWebPage) and save_media:
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute('SELECT * FROM event WHERE media_id = :media_id', { 'media_id': file_id })
                    row = len(await cursor.fetchall())
                    if row > 1:
                        return

                path = Path('media', str(chat.id), str(msg.id))
                path.mkdir(parents=True, exist_ok=True)
                await client.download_media(msg, path)

        @client.on(events.MessageDeleted)
        async def on_message_deleted(event: events.MessageDeleted.Event) -> None:
            msg = event.original_update

            date = datetime.utcnow()

            if getattr(msg, 'channel_id', None):
                chat = await client.get_entity(msg.channel_id)
                if not is_enabled(chat.id):
                    return
            else:
                chat = None

            if chat:
                chat_display = f'[{get_display_name(chat)} ({chat.id})]'

            for msg_id in event.deleted_ids:
                msg_display = f'({msg_id})'

                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute("""
                    SELECT
                        chat_id, user_id, text, media_type, media_filename
                    FROM
                        event
                    WHERE
                        chat_id LIKE :chat_id
                        AND message_id = :message_id
                    ORDER BY
                        rowid DESC
                    LIMIT
                        1
                    """, {
                        'chat_id': chat.id if chat else '%',
                        'message_id': msg_id,
                    })

                    inner_row = await cursor.fetchone()
                    await cursor.close()

                if inner_row:
                    chat_id, user_id, old_text, old_media_type, old_filename = inner_row
                else:
                    chat_id, user_id, old_text, old_media_type, old_filename = None, None, None, None, None

                if chat_id and not is_enabled(chat_id):
                    return

                if user_id:
                    user = await get_user(user_id, chat.id if chat else None)
                else:
                    user = None
                if user:
                    user_display = f'<{get_display_name(user)} ({user.id})>'

                out = f'{GRAY}{iso_date(date)}{RESET} {BOLD}{RED}DEL{RESET}'
                if chat:
                    out += f' {BOLD}{GRAY}{chat_display}{RESET}'
                out += f' {GRAY}{msg_display}{RESET}'
                if user:
                    out += f' {RESET}{BOLD}{user_display}'
                if old_text:
                    out += f' {RESET}{RED}{old_text}'
                if old_media_type:
                    if old_filename:
                        old_media_display = f'[{old_media_type}: {old_filename}]'
                    else:
                        old_media_display = f'[{old_media_type}]'

                    if old_text:
                        out += ' '
                    out += f'{MAGENTA}{old_media_display}{RESET}'
                out += RESET

                if log_to_file:
                    logfile = Path('logs', f'{chat.id if chat else "unknown"}.log')
                    with logfile.open('a') as fd:
                        fd.write(f'{out}\n')
                else:
                    print(out)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT INTO event
                            (type, date, chat_id, message_id)
                        VALUES
                            ('message_deleted', :date, :chat_id, :message_id)
                    """, {
                        'date': date.timestamp(),
                        'chat_id': chat.id if chat else None,
                        'message_id': msg_id,
                    })
                    await db.commit()

        await client.run_until_disconnected()

with sqlite3.connect(DB_PATH) as conn:
    c = conn.cursor()

    row = c.execute('PRAGMA user_version')
    schema_version = row.fetchone()[0]

    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        type TEXT NOT NULL,
        date REAL NOT NULL,
        chat_id INTEGER,
        message_id INTEGER NOT NULL,
        user_id INTEGER,
        text TEXT
    )
    """)

    if schema_version < 1:
        print('Performing database migration from version 0 to 1')
        c.execute('ALTER TABLE events RENAME TO event')
        c.execute('ALTER TABLE event ADD media_type TEXT')
        c.execute('ALTER TABLE event ADD media_filename TEXT')
        c.execute('PRAGMA user_version = 1')

    if schema_version < 2:
        print('Performing db migration from version 1 to 2')
        c.execute('ALTER TABLE event ADD media_id TEXT')
        c.execute('PRAGMA user_version = 2')

    conn.commit()

if __name__ == '__main__':
    print('Listening for messages')
    if log_to_file:
        print('Logging to file')
    asyncio.run(main())

