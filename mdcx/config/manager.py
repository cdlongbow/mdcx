import concurrent.futures
import contextlib
import json
import logging
import os
import os.path
import sys
import threading
from pathlib import Path
from types import TracebackType

from ..consts import IS_PYINSTALLER, MAIN_PATH, MARK_FILE
from ..utils import executor
from .computed import Computed
from .models import Config
from .v1 import ConfigV1, load_v1

logger = logging.getLogger(__name__)


def _consume_result(fut: concurrent.futures.Future) -> None:
    """消费后台任务结果，避免未取回的异常告警。"""
    with contextlib.suppress(Exception):
        fut.result()


def _write_windows(path: Path, text: str) -> None:
    """Windows 直写配置，保留文件 inode 与 ACL/安全描述符。

    不用 tmp + os.replace：替换会用新文件顶替旧文件，新文件继承父目录 ACL，
    用户在原文件上配置的显式权限条目会整体丢失（issue #42）。
    不做 icacls 收权：/inheritance:r 清空继承的 ACE，/grant:r 只替换式授予
    当前运行用户读写，在管理员运行或非 ASCII 用户名下会产生孤儿 SID，
    程序自身都会读取失败。写失败时重试 → 去只读 → 兜底报错。
    """
    import stat
    import time

    last_err: OSError | None = None
    for attempt in range(5):
        try:
            path.write_text(text, encoding="UTF-8")
            return
        except PermissionError as e:
            last_err = e
            if attempt == 0:
                time.sleep(0.02)  # 杀软实时扫描瞬时占用（缩短等待降低主线程卡顿）
            elif attempt == 1:
                time.sleep(0.05)
            elif attempt == 2:
                try:
                    os.chmod(str(path), stat.S_IWRITE)  # 打包资源文件可能带只读位
                except Exception:
                    pass
            elif attempt == 3:
                time.sleep(0.15)
    raise PermissionError(
        f"配置文件写入被拒绝访问（可能被其它程序占用或目录无写权限）：{path}\n"
        "请关闭打开该文件的程序（编辑器/资源管理器预览/杀毒软件实时扫描）后重试；"
        "若目录需管理员权限，请以管理员身份运行或更换保存目录。"
    ) from last_err


class ConfigManager:
    def __init__(self):
        self._computed_lock = threading.RLock()
        if not MARK_FILE.is_file():  # 标记文件不存在
            self.path = MAIN_PATH / "config.json"  # 默认配置文件路径
        else:
            mark_path = self.read_mark_file()
            if not mark_path or "\x00" in mark_path:
                logger.error("标记文件内容无效，回退默认配置路径: %r", mark_path)
                self.path = MAIN_PATH / "config.json"
            else:
                self._path = Path(mark_path)
                self.data_folder, self.file = self._path.parent, self._path.name
        if not os.path.exists(self._path):  # 配置文件不存在, 写入默认值
            if self._path.suffix == ".ini":
                self.path = self._path.with_suffix(".json")
            self.reset()
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    @path.setter
    def path(self, path: str | Path):
        p = Path(path)
        self.data_folder, self.file = p.parent, p.name
        self.write_mark_file(p)  # 更新标记文件路径
        self._path = p

    def switch_to_failed_session(self) -> None:
        """把当前会话切到 _failed.json（校验失败保护分支专用）。

        与 path setter 的区别：不写 MARK_FILE——_failed.json 此刻并不存在，
        把标记文件指向它，用户直接关闭程序后下次启动 reset() 会把默认配置
        写进 _failed.json 并永久指向，原配置完好在原处却永不再加载
        （全库审查 M6）。绕过标记后 _failed.json 仅是本会话内存配置，
        MARK_FILE 保持指向原配置，重启即自动回到原文件。
        """
        self._path = self.data_folder / "_failed.json"
        self.data_folder, self.file = self._path.parent, self._path.name

    def load(self) -> list[str]:
        if self._path.suffix == ".ini":  # handle v1 config
            return self.handle_v1()
        try:
            d = json.loads(self._path.read_text(encoding="UTF-8"))
            errors = Config.update(d)
            config = Config.model_validate(d)
            self._replace_config(config)
            return errors
        except json.JSONDecodeError as e:
            # JSON 语法错误（用户手工编辑丢逗号/引号）单独提示：
            # 给出错误位置行号列号 + 自动备份避免反复读坏文件 + 跳到干净默认配置
            backup = self._path.with_suffix(self._path.suffix + ".corrupt.bak")
            try:
                backup.write_bytes(self._path.read_bytes())
                backup_hint = f"已把坏配置备份为 {backup.name}，您可以打开对比修复；"
            except OSError:
                backup_hint = ""
            self._replace_config(Config())
            msg = (
                f" 配置文件 {self._path} 不是合法 JSON（语法错误, 第 {e.lineno} 行第 {e.colno} 列: {e.msg}）。"
                f"{backup_hint}已为您加载默认配置，您可以直接在设置页改回正确值后再保存。"
            )
            logger.error("配置文件 JSON 语法错误: %s", e)
            return msg.splitlines()
        except Exception as e:
            # 其他校验失败时不再静默回退到默认配置(会丢失用户配置),
            # 而是保留内存中已加载的旧配置(若存在), 仅记录错误并返回报错信息。
            old_config = getattr(self, "config", None)
            if old_config is None:
                self._replace_config(Config())
            else:
                logger.error("配置文件 %s 验证失败, 继续使用旧配置: %s", self._path, e)
            msg = f" 配置文件 {self._path} 验证失败. 错误信息: \n{e!s}"
            return msg.splitlines()

    def handle_v1(self):
        v2path = self.path.with_suffix(".v2.json")
        v1path = self.path
        if os.path.exists(v2path):
            self.path = v2path
            return [f"[V1] {v1path} 是旧版配置文件, 对应的新版配置文件已存在, 改为加载新版配置: {v2path}"] + self.load()

        try:
            d, v1_errors = load_v1(self.path)
            config_v1 = ConfigV1(**d)
            config_v1.init()
        except Exception as e:
            # 迁移链任何异常都不能打穿 ConfigManager()（模块级实例化会连锁崩溃整个应用）；
            # 也不写 v2path MARK_FILE（此时 v2 文件并不存在，指向它会让下次启动 reset 丢配置），
            # 保留 v1 路径回退默认配置，让用户仍可从旧文件手动恢复。
            logger.exception("v1 配置迁移失败: %s", v1path)
            self._replace_config(Config())
            return [
                f"[V1] 旧版配置文件 {v1path} 自动转换失败（{e!s}）。",
                "[V1] 已为您加载默认配置；旧版配置文件未被删除，可提交 issue 附带该文件排查。",
            ]
        self.path = v2path
        errors = [
            f"[V1] {v1path} 是旧版配置文件, 将自动转换为新版配置并保存到 {v2path}",
            "[V1] 旧版配置文件不会被删除. 当保存配置时, 仅会写入新版配置文件, 后续会自动使用新版配置文件",
        ] + v1_errors
        self._replace_config(config_v1.to_pydantic_model())
        self.save()
        return errors

    def _replace_config(self, config: Config) -> None:
        """热切换配置派生对象，旧对象等待持有方释放后再关闭。"""
        computed = Computed(config)
        with self._computed_lock:
            old_computed = getattr(self, "computed", None)
            self.config = config
            self.computed = computed
        self._close_old_computed(old_computed)

    def acquire_computed(self) -> "ComputedLease":
        return ComputedLease(self)

    def _close_old_computed(self, old_computed: Computed | None):
        if old_computed is None:
            return
        executor.submit(old_computed.close_when_idle())

    @staticmethod
    def _write_config_text(path: Path, text: str) -> None:
        """写入配置文件。

        - Windows: 直写原文件（`_write_windows`），保留 ACL/安全描述符，
          不做原子替换与 icacls 收权（两者都会破坏用户配置的显式权限条目）。
        - POSIX: 先写同目录 .tmp 再 os.replace 原子写，避免写入中断损坏整个配置；
          os.replace 偶发 PermissionError (杀软瞬时扫描/只读属性/占用) 时
          重试 → 去只读 → 删目标改名 → 直接覆盖写，逐级回退保成功率；
          完成后 chmod 0o600（仅属主读写，降低敏感字段被同机其它用户读取的风险）。
        """
        if os.name == "nt":
            _write_windows(path, text)
            return

        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(text, encoding="UTF-8")
        try:
            os.replace(str(tmp), str(path))
        except PermissionError:
            import stat
            import time

            replaced = False
            # 1. 重试：应对杀毒软件实时扫描 .tmp 产生的瞬时占用 (Windows 上最常见)
            #    缩短等待间隔，降低主线程阻塞（写失败本身是异常场景）
            for _ in range(4):
                time.sleep(0.02)
                try:
                    os.replace(str(tmp), str(path))
                    replaced = True
                    break
                except PermissionError:
                    continue
            # 2. 去只读属性后重试 (打包发布的资源文件可能带只读位)
            if not replaced:
                try:
                    os.chmod(str(path), stat.S_IWRITE)
                    os.replace(str(tmp), str(path))
                    replaced = True
                except PermissionError:
                    pass
            # 3. 删目标后改名 (绕过部分占用场景)
            if not replaced:
                try:
                    path.unlink(missing_ok=True)
                    tmp.rename(str(path))
                    replaced = True
                except Exception:
                    pass
            # 4. 最后手段：直接覆盖写目标 (非原子)，并清理 tmp，保证配置可保存
            if not replaced:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    path.write_text(text, encoding="UTF-8")
                    replaced = True
                except Exception:
                    pass
            if not replaced:
                raise PermissionError(
                    f"配置文件写入被拒绝访问（可能被其它程序占用或目录无写权限）：{path}\n"
                    "请关闭打开该文件的程序（编辑器/资源管理器预览/杀毒软件实时扫描）后重试；"
                    "若目录需管理员权限，请以管理员身份运行或更换保存目录。"
                ) from None
        os.chmod(path, 0o600)

    def save(self):
        # 在锁内读取 config，与 _replace_config 的切换互斥，避免读到切换中的不一致状态
        with self._computed_lock:
            text = self.config.model_dump_json(indent=2)
        self._write_config_text(self._path, text)

    def reset(self):
        """写入默认配置"""
        template_path = self._get_default_template_path()
        if template_path.is_file():
            try:
                template = json.loads(template_path.read_text(encoding="UTF-8"))
                Config.update(template)
                self._write_config_text(self._path, Config.model_validate(template).model_dump_json(indent=2))
                return
            except Exception:
                pass
        self._write_config_text(self._path, Config().model_dump_json(indent=2))

    @staticmethod
    def _get_default_template_path() -> Path:
        if IS_PYINSTALLER:
            try:
                return Path(sys._MEIPASS) / "resources" / "config" / "default_config.json"  # type: ignore[attr-defined]
            except Exception:
                pass
        return MAIN_PATH / "resources" / "config" / "default_config.json"

    def list_configs(self) -> list[str]:
        """列出配置文件夹中的所有配置文件名."""
        if not self._path.parent.exists():
            return []
        return [f.name for f in self._path.parent.iterdir() if f.suffix in (".json", ".ini")]

    @staticmethod
    def write_mark_file(path: str | Path):
        """写入 MARK_FILE"""
        if not os.path.exists(MARK_FILE):  # 标记文件不存在
            # 确保 MARK_FILE 所在目录存在
            mark_dir = os.path.dirname(MARK_FILE)
            if mark_dir:
                os.makedirs(mark_dir, exist_ok=True)
        with open(MARK_FILE, "w", encoding="UTF-8") as f:
            f.write(str(path))

    @staticmethod
    def read_mark_file() -> str:
        """读取 MARK_FILE"""
        with open(MARK_FILE, encoding="UTF-8") as f:
            return f.read().strip()


class ComputedLease:
    def __init__(self, manager: ConfigManager):
        self._manager = manager
        self._computed: Computed | None = None
        self._entered = False

    def _enter(self) -> Computed:
        if self._entered:
            raise RuntimeError("Computed 租约不能重复进入")
        with self._manager._computed_lock:
            computed = self._manager.computed
            computed.retain()
        self._computed = computed
        self._entered = True
        return computed

    def __enter__(self) -> Computed:
        return self._enter()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        computed = self._computed
        if computed is not None:
            self._computed = None
            # 走关键通道：release 若被 cancel_async 取消（如停止刮削），租约永不归零，
            # 旧网络栈的 close_when_idle 将陷入无限轮询且永不释放（议题 #55）
            future = executor.submit_critical(computed.release())
            future.add_done_callback(_consume_result)

    async def __aenter__(self) -> Computed:
        return self._enter()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        computed = self._computed
        if computed is not None:
            self._computed = None
            await computed.release()


manager = ConfigManager()


def get_new_str(a: str, wanted=False):
    return a
