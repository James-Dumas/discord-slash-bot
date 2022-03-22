import discord, asyncio, os, json, time, traceback
from discord_slash import SlashCommand
from aiohttp import client_exceptions
from datetime import datetime
from threading import Thread, Event
from queue import Queue

class SlashBot(discord.Client):
    options = {
        "token": "",
        "task_interval": 1.0,
        "log_dir": "logs",
        "max_log_files": 10,
        "max_consecutive_errors": 10,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.stop = Event()
        self.slash = SlashCommand(self)

        self.__log_thread = Thread(target=self.__log_thread_task)
        self.__log_queue = Queue()
        self.__stopped = Event()
        self.__consecutive_errors = 0
        self.__last_error_ts = 0
        self.__tasks = []
        self.__on_ready_tasks = []
        
        # read options
        if os.path.isfile("options.json"):
            with open("options.json", "rw") as f:
                new_options = json.load(f)
                self.options.update(new_options)

            with open("options.json", "w") as f:
                json.dump(self.options, f, indent=4)

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

        # setup threaded __tasks
        self.__log_thread.daemon = True
        self.__log_thread.start()

        # setup async __tasks
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
            self.stop.set()
            gathered_tasks = asyncio.gather(*async_tasks[1:])
            self.loop.run_until_complete(gathered_tasks)

            for task in async_tasks:
                if not task.done():
                    task.cancel()

        if not self.is_closed():
            self.loop.run_until_complete(self.close())

        self.loop.close()
        self.__stopped.set()
        self.log("done")
        self.__log_thread.join()

    async def on_ready(self):
        self.log("bot ready")
        await self.slash.sync_all_commands()
        try:
            if len(self.__on_ready_tasks) > 0:
                await asyncio.gather(*[task() for task in self.__on_ready_tasks])
                
        except Exception as e:
            error_msg = "".join(traceback.format_exception(etype=type(e), value=e, tb=e.__traceback__))
            self.log(error_msg)

    async def __task_runner(self):
        while not self.is_closed():
            try:
                if self.stop.is_set():
                    self.log("stopping...")
                    await self.close()
                else:
                    if len(self.__tasks) > 0:
                        await asyncio.gather(*[task() for task in self.__tasks])

            except Exception as e:
                error_msg = "".join(traceback.format_exception(etype=type(e), value=e, tb=e.__traceback__))
                self.log(error_msg)
                if time.time() - self.__last_error_ts < 10:
                    self.__consecutive_errors += 1
                    if self.__consecutive_errors >= self.options["max_consecutive_errors"]:
                        self.log("too many consecutive errors!")
                        self.stop.set()

                else:
                    self.__consecutive_errors = 1

                self.__last_error_ts = time.time()

            await asyncio.sleep(self.options["task_interval"])

    def log(self, text: str):
        print(text)
        self.__log_queue.put((time.time(), text))

    def __log_thread_task(self):
        while not self.__stopped.is_set():
            log_item = self.__log_queue.get()
            with open(self.log_file, "a") as f:
                f.write(f"[{datetime.fromtimestamp(log_item[0]).strftime('%H:%M:%S')}]: {log_item[1]}\n")
    
    # decorators

    def task(self, func):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("task decorator must be used on a coroutine")

        self.__tasks.append(func)
        return func

    def on_ready_task(self, func):
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("on_ready_task decorator must be used on a coroutine")

        self.__on_ready_tasks.append(func)
        return func

