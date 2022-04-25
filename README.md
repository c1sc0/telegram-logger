# telegram-logger

A simple Python script using Telethon to log all (or some) messages a user or bot account can see on Telegram.

# Requirements
* Python 3.6 or newer
* Python package dependencies: `poetry install` or `pip install -r requirements.txt`
* A Telegram user or bot account

# Usage
Set your `api_id`, `api_hash` and `session` in `config.toml`. You can get your `api_id` and `api_hash` from "API development tools" on <https://my.telegram.org/>. Note that this authenticates an app, not a user.

Before you start the script use the provided `getStringSession.py` to get your session string. You will be prompted for credentials. Upon successful authentication, it will start logging all messages it can see to stdout.
`docker run --rm -it -v $(pwd)/config.toml:/src/config.toml -v $(pwd):/src/getSessionString scr.somogyi.xyz/telegram-logger:latest sh` (`python getStringSession.py`)

You can set `enabled_chats` and `disabled_chats` in the config to a list of chat IDs to control which chats should be logged (the default is all).

# Docker
You can also run the script in docker or podman. 

Build with `podman build -t telegram-logger .`

Run with `podman run -v $(pwd)/config.toml:/src/config.toml -v $(pwd)/db:/src/db -d telegram-logger:latest`
