import discord, asyncio, os, json, time, traceback, socket, glob
from discord_slash import SlashCommand
from aiohttp import client_exceptions
from datetime import datetime
from threading import Thread, Event
from queue import Queue

# functions

def has_connection(host="8.8.8.8", port=53, timeout=3):
    """Check if there is an internet connection"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.shutdown(socket.SHUT_RDWR)
        s.close()
        return True
    except socket.error as ex:
        return False

# Bot class

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
            with open("options.json", "r") as f:
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

        if not has_connection():
            self.log("no internet connection, waiting...")
            connection_wait_start = time.time()
            time.sleep(2)
            while not has_connection():
                time.sleep(2)
                if time.time() - connection_wait_start > 300:
                    self.log("no internet connection for 5 minutes, stopping...")
                    self.stop.set()
                    break

        if not self.stop.is_set():
            clean_exit = False
            self.log("connecting...")
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

# Database stuff

class DatabaseClosedException(Exception):
    def __init__(self):
        super.__init__(self, "Cannot access database after it has been closed")

class BotDatabase:

    def __init__(self, db_dir, default_data={}, cache_size=10, io_sleep_interval=0.01):
        if not os.path.isabs(db_dir):
            db_dir = os.path.abspath(db_dir)

        os.makedirs(db_dir, exist_ok=True)

        self.db_dir = db_dir
        self.default_data = default_data
        self.cache_size = cache_size
        self.io_sleep_interval = io_sleep_interval

        self.stop = Event()
        self.io_queue = Queue()
        self.data_out = {}
        self.cached_guilds = []
        self.cache = {}
        self.gid_locks = {}
        self.gid_events = {}
        prev_dir = os.getcwd()
        os.chdir(self.db_dir)
        for fn in glob.glob("*"):
            self.gid_locks[fn] = asyncio.Lock()
            self.gid_events[fn] = Event()

        os.chdir(prev_dir)
        self.io_thread = Thread(target=self.__data_io)
        self.io_thread.daemon = True
        self.io_thread.start()
    
    def reinit(self):
        """Re-initialize the database if it was closed"""
        if self.stop.is_set():
            self.stop.clear()
            self.io_thread.start()

    def close(self):
        """Close the database"""
        self.stop.set()
        self.io_thread.join()
        self.data_out = {}
        self.cache = {}
        self.cached_guilds = []

    def __data_io(self):
        """Threaded function to write data on disk"""
        while not self.stop.is_set() or not self.io_queue.empty():
            sleep = True
            if not self.io_queue.empty():
                sleep = False
                ts, guild_id, data = self.io_queue.get()
                if data != None:
                    # write data
                    with open(os.path.join(self.db_dir, str(guild_id)), "w") as f:
                        json.dump(data, f)

                    self.gid_events[guild_id].set()
                else:
                    # read data
                    with open(os.path.join(self.db_dir, str(guild_id)), "r") as f:
                        data = json.load(f)
                    
                    self.data_out[ts] = data
                    self.gid_events[guild_id].set()
            
            if sleep:
                time.sleep(self.io_sleep_interval)
        
    async def __write(self, guild_id: str, data: dict):
        if guild_id in self.cache:
            self.cache[guild_id] = data

        self.io_queue.put((time.time(), guild_id, data))
        while not self.gid_events[guild_id].is_set():
            await asyncio.sleep(self.io_sleep_interval)

        self.gid_events[guild_id].clear()

    async def __read(self, guild_id: str) -> dict:
        if guild_id in self.cache:
            self.cached_guilds.remove(guild_id)
            self.cached_guilds.insert(0, guild_id)
            return self.cache[guild_id]
        else:
            ts = time.time()
            self.io_queue.put((ts, guild_id, None))
            while not self.gid_events[guild_id].is_set():
                await asyncio.sleep(self.io_sleep_interval)
            
            self.gid_events[guild_id].clear()
            data = self.data_out.pop(ts)

            if self.cache_size > 0:
                self.cached_guilds.insert(0, guild_id)
                self.cache[guild_id] = data

            if self.cache_size >= 0 and len(self.cached_guilds) > self.cache_size:
                del self.cache[self.cached_guilds.pop()]
            
            return data

    async def get(self, guild: discord.Guild) -> dict:
        """Retrieve a guild's database"""
        if self.stop.is_set():
            raise DatabaseClosedException()

        gid = str(guild.id)
        data = {}
        if gid in self.gid_locks:
            async with self.gid_locks[gid]:
                data = await self.__read(gid)

        data["id"] = gid
        data["name"] = guild.name
        for key in self.default_data:
            if key not in data:
                data[key] = self.default_data[key]

        return data

    async def put(self, guild: discord.Guild, data: dict):
        """Put data into a guild's database"""
        if self.stop.is_set():
            raise DatabaseClosedException()

        gid = str(guild.id)
        file_not_exist = False
        if gid not in self.gid_locks:
            self.gid_locks[gid] = asyncio.Lock()
            self.gid_events[gid] = Event()
            file_not_exist = True

        async with self.gid_locks[gid]:
            if file_not_exist:
                current_data = {}
                current_data.update(self.default_data)
                current_data["id"] = gid
                current_data["name"] = guild.name
            else:
                current_data = await self.__read(gid)

            current_data.update(data)
            await self.__write(gid, current_data)
    
    async def delete(self, guild: discord.Guild, keys: tuple) -> int:
        """Delete items from a guild's database"""
        if self.stop.is_set():
            raise DatabaseClosedException()

        gid = str(guild.id)
        num_deleted = 0
        if gid in self.gid_locks:
            async with self.gid_locks[gid]:
                current_data = await self.__read(gid)
                for key in keys:
                    if (key not in ("id", "name")) and (key not in self.default_data) and (key in current_data):
                        del current_data[key]
                        num_deleted += 1

                if num_deleted > 0:
                    await self.__write(gid, current_data)
        
        return num_deleted
