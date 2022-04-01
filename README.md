# discord-slash-bot
A wrapper API for [discord.py](https://discordpy.readthedocs.io/en/stable/) and [discord-py-interactions](https://pypi.org/project/discord-py-interactions/) that allows easily creating a discord bot with slash commands.

## Install

Clone the repository, then run `python3 setup.py install --user` to install for your user, or `sudo python3 setup.py install` to install globally.

## Features

- decorators allow customizing the behavior of your bot without having to subclass `discord.Client`
- configurable through a json file (automatically generated on first run)
- any custom options can be added to the json file and will be accessible from the bot instance
- output/error logging & automatic deletion of old log files
- stops automatically after a specified maximum number of consecutive errors

## Example

```python
from discord_slash_bot import SlashBot
from discord_slash import SlashContext
from interactions import OptionType
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
@bot.slash(
    name="hello",
    description="A friendly greeting",
    options=[
        {
            "name": "greeting",
            "description": "How to greet the user",
            "type": OptionType.STRING,
            "required": True
        },
        {
            "name": "nice_day",
            "description": "Whether the day is nice",
            "type": OptionType.BOOLEAN,
            "required": False
        },
    ],
    guild_ids=[775372599324573706] # put the ID of your testing server here. remove this argument for deployment.
)
async def command_hello(context: SlashContext, greeting: str, nice_day: bool = True):
  await context.send(content=f"{greeting}\nToday is{('' if nice_day else ' not')} a nice day!")

# subscribe to the on_message event from discord.py
@bot.event
async def on_message(message: Message):
  if message.mention_everyone:
    await message.channel.send(content="I can't believe you've done this.")

bot.run()
```
