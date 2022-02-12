from telethon import TelegramClient
from telethon.sessions import StringSession
import toml

config = toml.load('config.toml')

api_id = config.get('api_id')
api_hash = config.get('api_hash')


with TelegramClient(StringSession(), api_id, api_hash) as client:
    print(client.session.save())
