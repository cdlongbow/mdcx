import asyncio
import contextvars
import threading

try:
    from warnings import deprecated
except ImportError:

    def deprecated(_message):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator


class LogBuffer:
    _lock = threading.Lock()
    all_buffers: dict[int, dict[str, "LogBuffer"]] = {}
    global_buffer = None

    # 任务树归因：记录"当前逻辑任务组"的根 task_id。
    # asyncio.create_task 会拷贝当前 context，子协程自动继承同一 root——
    # 这是"聚合自己派生的后代"的依据；兄弟任务在入口 new_root() 切断继承。
    # to_thread 内 contextvar 依然可见（ctx.run 语义），线程写入归因到发起者。
    _ROOT: contextvars.ContextVar[int | None] = contextvars.ContextVar("logbuffer_root", default=None)

    @staticmethod
    def _global_buffer() -> "LogBuffer":
        if LogBuffer.global_buffer is None:
            LogBuffer.global_buffer = LogBuffer()
        return LogBuffer.global_buffer

    @staticmethod
    def _get_task_id() -> int | None:
        """获取当前协程的 Task ID，如果在协程环境下运行则返回 Task ID，否则返回线程 ID"""
        try:
            # 尝试获取当前协程
            task = asyncio.current_task()
            if task is not None:
                # 使用 Task 对象的 id 作为唯一标识符
                return id(task)
        except RuntimeError:
            # 如果不在协程环境中，会抛出 RuntimeError
            pass

        # 如果不是协程或获取失败，则回退到使用线程 ID
        return threading.current_thread().ident

    @staticmethod
    def _current_root() -> int | None:
        """取当前任务组根 id：优先 root contextvar，其次当前 task/线程自身。

        root contextvar 经 create_task / to_thread 的 context 拷贝自动继承，
        使子协程与线程内写入归因到发起者；未设定时（顶层任务）惰性取自身 id，
        即"未显式归组的任务自成一组"。
        """
        root = LogBuffer._ROOT.get()
        if root is not None:
            return root
        return LogBuffer._get_task_id()

    @staticmethod
    def new_root() -> int:
        """显式开启新的任务组：并发兄弟任务入口调用，切断彼此的归因继承。

        返回组 id（= 调用者 task/线程 id）。此后本任务及其 create_task 派生的
        全部后代、to_thread 线程写入都归入这一组；其他兄弟组的 get() 不再拼入。
        """
        root = LogBuffer._get_task_id()
        if root is None:  # 理论不可达（_get_task_id 线程回退恒非 None），mypy 收窄
            root = 0
        LogBuffer._ROOT.set(root)
        return root

    @staticmethod
    def _get_buffer(category: str) -> "LogBuffer":
        """按任务组 root 归因取 buffer。

        写入侧统一落【root】键（而非当前 task_id）：子协程与 to_thread
        线程内的写入因此与发起者共享同一 buffer，get()/clear_task()
        按 root 一次命中整组。
        """
        root = LogBuffer._current_root()
        if root is None:
            return LogBuffer._global_buffer()
        with LogBuffer._lock:
            if root not in LogBuffer.all_buffers:
                LogBuffer.all_buffers[root] = {}
            if category not in LogBuffer.all_buffers[root]:
                LogBuffer.all_buffers[root][category] = LogBuffer()
            return LogBuffer.all_buffers[root][category]

    @staticmethod
    def clear_task():
        """清空当前任务组的全部 buffer（整树回收）。

        旧实现只按当前 task_id 弹出，create_task 子任务与并发兄弟任务的
        buffer 全部残留，all_buffers 随刮削量无界增长。现按 root 归因回收
        本组全部条目；root 下的子任务 buffer 一并释放。
        """
        root = LogBuffer._current_root()
        if root is None:
            return
        with LogBuffer._lock:
            LogBuffer.all_buffers.pop(root, None)
            # root 归因下，后代任务的 task_id 不在 all_buffers 顶层键中
            # （写入时统一落 root 键），此处一次 pop 即整树回收。
            # 兼容旧形态：无 root 的裸线程/遗留键按自身 id 落键的，同样弹出。
            own = LogBuffer._get_task_id()
            if own is not None and own != root:
                LogBuffer.all_buffers.pop(own, None)

    @staticmethod
    def clear_stale_buffers(max_size: int = 200) -> int:
        if len(LogBuffer.all_buffers) <= max_size:
            return 0
        with LogBuffer._lock:
            if len(LogBuffer.all_buffers) <= max_size:
                return 0
            keys = list(LogBuffer.all_buffers.keys())
            remove_count = len(keys) // 2
            for key in keys[:remove_count]:
                LogBuffer.all_buffers.pop(key, None)
        return remove_count

    @staticmethod
    def clear_thread():
        """兼容旧版 API，实际上调用 clear_task()"""
        LogBuffer.clear_task()

    @staticmethod
    def log() -> "LogBuffer":
        return LogBuffer._get_buffer("log")

    @staticmethod
    @deprecated("仅用于向后兼容")
    def info() -> "LogBuffer":
        return LogBuffer._get_buffer("info")

    @staticmethod
    def error() -> "LogBuffer":
        return LogBuffer._get_buffer("error")

    @staticmethod
    @deprecated("内容不会被任何位置使用")
    def req() -> "LogBuffer":
        return LogBuffer._get_buffer("req")

    def __init__(self):
        self.buffer = []

    def write(self, message, with_task_name=False):
        """
        写入日志消息

        Args:
            message: 日志消息
            with_task_name: 是否在日志消息前添加任务名称
        """
        if with_task_name:
            task_name = LogBuffer.get_task_name()
            message = f"[{task_name}] {message}"
        with LogBuffer._lock:
            if self.buffer and self.buffer[-1] == message:
                return
            self.buffer.append(message)

    def get(self, only_self: bool = False):
        """取本任务组的聚合日志（自己 + 派生后代），不含陌生兄弟任务。

        旧实现拼接【全局所有】任务的 buffer（c089eaf 为聚合子协程日志引入），
        但并发刮削的兄弟影片任务 task_id 互不相干，导致毫不相干影片的失败
        原因互相污染（写入 Flags.failed_list 与 SQLite 断点缓存，实测复现）。
        写入侧已统一按 root 归因落键，此处只读本组键即可——子协程与
        to_thread 线程写入天然包含在内，兄弟组互不可见。

        only_self=True 时只返回自身 buffer 不做组内聚合——error 通道专用：
        error().get() 若聚合本组 log 通道，失败原因会被几十行正常刮削日志
        （字段来源/下载过程）稀释污染，随 failed_list/SQLite error 列持久化
        （全库审查 B3）。
        """
        root = LogBuffer._current_root()
        with LogBuffer._lock:
            result = "".join(self.buffer)
            if only_self or root is None:
                return result
            group = LogBuffer.all_buffers.get(root)
            if group is None:
                return result
            for buf in group.values():
                if isinstance(buf, LogBuffer) and buf is not self:
                    # 浅拷贝避免并发 append 迭代异常
                    result += "".join(list(buf.buffer))
        return result

    def last(self):
        if len(self.buffer) == 0:
            return ""
        return self.buffer[-1]

    def clear(self):
        with LogBuffer._lock:
            self.buffer.clear()

    @staticmethod
    def get_task_name() -> str:
        """获取当前任务的名称（线程名或协程名）"""
        try:
            task = asyncio.current_task()
            if task:
                return task.get_name()
        except RuntimeError:
            pass

        return threading.current_thread().name or "unknown"
