# discord-slash-bot
A wrapper API for [discord.py](https://discordpy.readthedocs.io/en/stable/) and [discord-py-interactions](https://pypi.org/project/discord-py-interactions/) that allows easily creating a discord bot with slash commands.

## Features

- decorators allow customizing the behavior of your bot without having to subclass `discord.Client`
- configurable through a json file (automatically generated on first run)
- output/error logging & automatic deletion of old log files
- stops automatically after many consecutive errors

## Example

```python
from discord_slash_bot import SlashBot
from discord_slash import SlashContext
from discord import Message

bot = SlashBot()

# create a function that will run once the bot has connected to discord
@bot.on_ready_task
async def run_when_ready():
  bot.log("we have connected to Discord.")

# create a function that will run repeatedly (interval specified in options.json)
@bot.task
async def run_repeatedly():
  bot.log("beep boop!")

# create a slash command for the bot
@bot.slash.slash(name="hello", description="A friendly greeting")
async def command_hello(context: SlashContext):
  await context.send(content="Hello there!")

# subscribe to the on_message event from discord.py
@bot.event
async def on_message(message: Message):
  if message.mention_everyone:
    await message.channel.send(content="I can't believe you've done this.")

bot.run()
```
