import discord, asyncio, os, json, time, traceback
from discord_slash import SlashCommand
from aiohttp import client_exceptions
from datetime import datetime
from threading import Thread, Event
from queue import Queue

class SlashCommandBot(discord.Client):
    options = {
        "token": "",
        "task_sleep": 1.0,
        "log_dir": "logs",
        "max_log_files": 10,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.stop = False
        self.slash = SlashCommand(self)
        self.log_thread = Thread(target=self.__log_thread_task)
        self.log_queue = Queue()
        self.stopped = Event()
        self.consecutive_errors = 0
        self.last_error_ts = 0
        self.tasks = []
        self.on_ready_tasks = []
        
        # read options
        if os.path.isfile("options.json"):
            with open("options.json", "r") as f:
                self.options = json.load(f)
        else:
            self.log("options.json not found! creating template file, please fill in the token")
            with open("options.json", "w") as f:
                json.dump(self.options, f, indent=4)

        # check log dir
        if os.path.isdir(self.options["log_dir"]):
            log_files = os.listdir(self.options["log_dir"])
            if len(log_files) > self.options["max_log_files"] - 1:
                log_files.sort(reverse=True)
                for f in log_files[self.options["max_log_files"] - 1:]:
                    os.remove(os.path.join(self.options['log_dir'], f))
        else:
            os.mkdir(self.options["log_dir"])

        self.log_file = os.path.join(self.options['log_dir'], f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
    
    def run(self):
        self.log("starting bot...")

        # setup threaded tasks
        self.log_thread.daemon = True
        self.log_thread.start()

        # setup async tasks
        async_tasks = [
            self.loop.create_task(self.start(self.options["token"], reconnect=True)),
            self.loop.create_task(self.__task_runner()),
        ]

        gathered_tasks = asyncio.gather(*async_tasks)

        clean_exit = False
        try:
            # start async
            self.loop.run_until_complete(gathered_tasks)
            clean_exit = True
        
        except (client_exceptions.ClientConnectorError, client_exceptions.ClientConnectionError, discord.errors.DiscordServerError):
            self.log("error connecting to Discord")
    
        except discord.errors.LoginFailure:
            self.log("bot failed to login (invalid token?)")

        except KeyboardInterrupt:
            pass

        if not clean_exit:
            self.stop = True
            gathered_tasks = asyncio.gather(*async_tasks[1:])
            self.loop.run_until_complete(gathered_tasks)

            for task in async_tasks:
                if not task.done():
                    task.cancel()

        if not self.is_closed():
            self.loop.run_until_complete(self.close())

        self.loop.close()
        self.stopped.set()
        self.log("done")
        self.log_thread.join()

    async def on_ready(self):
        self.log("bot ready")
        await self.slash.sync_all_commands()
        try:
            if len(self.on_ready_tasks) > 0:
                await asyncio.gather(*[task(self) for task in self.on_ready_tasks])
                
        except Exception as e:
            error_msg = "".join(traceback.format_exception(etype=type(e), value=e, tb=e.__traceback__))
            self.log(error_msg)

    async def __task_runner(self):
        while not self.is_closed():
            try:
                if self.stop:
                    self.log("stopping...")
                    await self.close()
                else:
                    if len(self.tasks) > 0:
                        await asyncio.gather(*[task(self) for task in self.tasks])

            except Exception as e:
                error_msg = "".join(traceback.format_exception(etype=type(e), value=e, tb=e.__traceback__))
                self.log(error_msg)
                if time.time() - self.last_error_ts < 10:
                    self.consecutive_errors += 1
                    if self.consecutive_errors >= 10:
                        self.log("too many consecutive errors!")
                        self.stop = True

                else:
                    self.consecutive_errors = 1

                self.last_error_ts = time.time()

            await asyncio.sleep(self.options["task_sleep"])

    def log(self, text: str):
        print(text)
        self.log_queue.put((time.time(), text))

    def __log_thread_task(self):
        while not self.stopped.is_set():
            log_item = self.log_queue.get()
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.fromtimestamp(log_item[0]).strftime('%H:%M:%S')}]: {log_item[1]}\n")
    
    # decorators

    def task(self, func):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("task decorator must be used on a coroutine")

        self.tasks.append(func)
        return func

    def on_ready_task(self, func):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("on_ready_task decorator must be used on a coroutine")

        self.on_ready_tasks.append(func)
        return func

bot = SlashCommandBot()
bot.run()