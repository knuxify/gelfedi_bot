# gelfedi_bot

Mastodon.py bot that posts images from gelbooru using pygelbooru

## Features

- Get random post with certain tags
- Exclude specified tags
- Exclude posts on an ID denylist
- Operator can ping the bot and say "delete this" to delete a post and add it to the denylist, and "post now" to force a post

## Setup

1. Copy ``config.json.sample`` to ``config.json`` and modify the settings you need
2. Run the usual [Mastodon.py setup](https://mastodonpy.readthedocs.io/en/stable), replace the ``pytooter_usercred.secret`` with ``usercred.secret``
3. Run ``main.py`` from the bot's directory

``main.py`` loops forever, so there's no need to wrap it in a separate file.
