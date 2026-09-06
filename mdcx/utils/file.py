import asyncio
import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from collections.abc import Iterable
from pathlib import Path

import aiofiles.os
from PIL import Image

from ..consts import IS_MAC, IS_WINDOWS
from ..signals import signal


def _build_file_name_index_sync(folder: Path) -> dict[str, Path]:
    file_name_index: dict[str, Path] = {}
    for root, dirs, files in folder.walk(top_down=True):
        dirs.sort()
        for file in sorted(files):
            file_name_index.setdefault(file.lower(), root / file)
    return file_name_index


async def build_file_name_index(folder: str | Path) -> dict[str, Path]:
    """递归索引目录内文件名，用于在字幕包等外部目录中快速匹配文件。"""
    folder = Path(folder)
    if not await aiofiles.os.path.isdir(folder):
        return {}
    return await asyncio.to_thread(_build_file_name_index_sync, folder)


def find_file_from_index(file_name_index: dict[str, Path], file_names: Iterable[str]) -> Path | None:
    for file_name in file_names:
        if file_path := file_name_index.get(file_name.lower()):
            return file_path
    return None


async def find_file_in_folder(folder: str | Path, file_names: Iterable[str]) -> Path | None:
    file_name_index = await build_file_name_index(folder)
    return find_file_from_index(file_name_index, file_names)


def delete_file_sync(p: str | Path):
    p = Path(p)
    if p == Path():
        return False, "路径不能为空"
    try:
        p.unlink(missing_ok=True)
        return True, ""
    except Exception as e:
        error_info = f" 删除文件: {p}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
    return False, error_info


def move_file_sync(old: str | Path, new: str | Path):
    old = Path(old)
    new = Path(new)
    try:
        if _is_same_path(old, new):
            return True, ""  # 同一路径（含不同写法），无需移动，避免误删源文件
        if new.is_dir() and not new.is_symlink():
            return False, f"目标是目录，无法覆盖文件: {new}"
        shutil.move(old, new)
        return True, ""
    except Exception as e:
        error_info = f" 移动文件: {old}\n 目标: {new} \n 错误: {e}\n{traceback.format_exc()}\n"
        signal.add_log(error_info)
        print(error_info)
    return False, error_info


def _copy_file_atomic_sync(old: Path, new: Path) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=new.parent, prefix=f".{new.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.close(fd)
        # 网络/映射盘（用户 Z: 盘实测）上 os.path.samefile 对两个不同文件也会返回
        # True（inode 不可靠），shutil.copy 内部因此抛 SameFileError。改用字节流读写
        # 完全避开 samefile 判定，目标只依赖 mkstemp 文件名（OS 原子生成，不重名）。
        with open(old, "rb") as fsrc, open(tmp, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
        # Windows 上目标被瞬时占用（杀软扫描/缩略图索引/预览句柄）会 PermissionError，
        # 通常毫秒~秒级自解；短间隔重试后再放弃（用户实测 .fanart.jpg.xxx.tmp 残留案）。
        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                os.replace(tmp, new)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.1 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    except BaseException:
        # replace 重试后仍失败：清理尽力而为+记录，孤儿由刮削结束时的
        # sweep_stale_atomic_temps 兜底回收（Windows 被占用时 unlink 可能同败）。
        try:
            tmp.unlink(missing_ok=True)
        except OSError as cleanup_err:
            signal.add_log(f" 临时文件清理失败（稍后刮削结束时重试）: {tmp} 错误: {cleanup_err}")
        raise


def sweep_stale_atomic_temps(directory: str | Path, pattern: str = ".*.tmp") -> list[str]:
    """清理目录下原子写/原子复制遗留的孤儿临时文件（进程中断/占用残留）。

    命名形态：mkstemp(prefix=".目标名.", suffix=".tmp") → `.fanart.jpg.a8x3f2.tmp`。
    只删隐藏文件（前导点）且后缀 .tmp 的——不会误伤用户正常文件。
    返回已清理的文件路径列表（供日志）。
    """
    removed: list[str] = []
    base = Path(directory)
    if not base.is_dir():
        return removed
    for p in base.glob(pattern):
        if not p.is_file():
            continue
        try:
            p.unlink(missing_ok=True)
            removed.append(str(p))
        except OSError:
            pass  # 仍被占用（Windows）——留给下次刮削结束重试
    return removed


def copy_file_sync(old: Path | str, new: Path | str):
    old = Path(old)
    new = Path(new)
    if not old.exists():
        return False, f"不存在: {old}"
    try:
        if new.exists() and old.samefile(new):
            return True, ""
        _copy_file_atomic_sync(old, new)
        return True, ""
    except Exception as e:
        error_info = f" 复制文件: {old}\n 目标: {new} \n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


def _strip_win_long_prefix(path: str) -> str:
    if IS_WINDOWS and path.startswith("\\\\?\\"):
        return path[4:]
    return path


def read_link_sync(p: str | Path) -> str:
    """获取符号链接的真实路径，并正确解析相对链接目标。"""
    current = Path(os.path.normpath(p))
    seen: set[Path] = set()
    while current.is_symlink():
        absolute_current = current.absolute()
        if absolute_current in seen:
            return _strip_win_long_prefix(str(current))
        seen.add(absolute_current)
        target = Path(os.readlink(current))
        current = target if target.is_absolute() else Path(os.path.normpath(current.parent / target))
    return _strip_win_long_prefix(str(current))


def resolve_link_source_sync(p: str | Path):
    p = Path(p)
    try:
        if p.is_symlink():
            return True, p.resolve(strict=True), ""
        if p.exists():
            return True, p, ""
        return False, p, f"不存在: {p}"
    except Exception as e:
        error_info = f" 解析链接源文件: {p}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, p, error_info


def resolve_success_record_source_sync(p: str | Path):
    p = Path(p)
    try:
        if p.is_symlink():
            return True, p.resolve(strict=True), "检测到源文件为软链接，成功列表将记录其真实源文件路径"

        if not p.exists():
            return False, p, f"不存在: {p}"

        return True, p, ""
    except Exception as e:
        error_info = f" 解析成功列表源文件: {p}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, p, error_info


def create_symlink_sync(source: str | Path, target: str | Path):
    source = Path(source)
    target = Path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if target.is_symlink() and target.resolve(strict=False) == source.resolve(strict=False):
                return True, "已存在同源软链接"
            return False, f"目标已存在: {target}"
        os.symlink(source, target)
        return True, ""
    except Exception as e:
        error_info = f" 创建软链接: {target}\n 源文件: {source}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


def create_hardlink_sync(source: str | Path, target: str | Path):
    source = Path(source)
    target = Path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if target.exists() and not target.is_symlink():
                try:
                    if source.exists() and source.samefile(target):
                        return True, "已存在同源硬链接/文件"
                except Exception:
                    pass
            return False, f"目标已存在: {target}"
        os.link(source, target)
        return True, ""
    except Exception as e:
        error_info = f" 创建硬链接: {target}\n 源文件: {source}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


def check_pic_sync(p: str):
    if os.path.exists(p):
        try:
            with Image.open(p) as img:  # 如果文件不是图片，报错
                img.load()  # 如果图片不完整，报错OSError: image file is truncated
                return img.size
        except Exception as e:
            signal.add_log(f"文件损坏: {p} \n Error: {e}")
            try:
                os.remove(p)
                signal.add_log("删除成功！")
            except Exception as remove_err:
                # 常见原因：Windows 下文件被资源管理器/杀软占用（PermissionError/WinError 32），权限不足（WinError 5）
                signal.add_log(f"删除失败: {remove_err}（若是 WinError 32 请关闭预览/播放器，或重启软件后重试）")
    return False


def open_file_thread(p: Path, is_dir: bool) -> None:
    if IS_WINDOWS:
        if is_dir:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["explorer", str(p)])
    elif IS_MAC:
        if is_dir:
            if p.is_symlink():
                p = p.parent
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["open", str(p)])
    else:
        if is_dir:
            if p.is_symlink():
                p = p.parent
            try:
                subprocess.Popen(["dolphin", "--select", p])
            except Exception:
                # xdg-open 不支持 -R（那是 macOS open 的参数），打开目录本身
                subprocess.Popen(["xdg-open", str(p)])
        else:
            subprocess.Popen(["xdg-open", p])


async def write_file_atomic_async(p: str | Path, content: str, encoding: str = "UTF-8") -> None:
    """原子写入文本文件：同目录临时文件 + os.replace，避免写入中断损坏原文件。

    约束（借鉴 OpenAver 的 atomic_write 经验，防止历史踩坑）：
    - 临时文件必须与目标同目录：跨卷 os.replace 会抛 EXDEV
    - 使用 mkstemp 生成随机临时名，避免并发写同一目标互相撞 .tmp
    - 先关闭 mkstemp 返回的 fd 再 os.replace：Windows 上打开着的句柄会阻止替换
    - 失败时清理临时文件、原文件字节不变、原始异常原样上抛；
      捕获 BaseException（KeyboardInterrupt/SystemExit 也要清临时文件）
    """
    p = Path(p)
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.close(fd)
        async with aiofiles.open(tmp, "w", encoding=encoding) as f:
            await f.write(content)
        await asyncio.to_thread(os.replace, str(tmp), str(p))
    except BaseException:
        try:
            await asyncio.to_thread(tmp.unlink, missing_ok=True)
        except OSError:
            pass
        raise


def write_file_atomic(p: str | Path, content: str, encoding: str = "UTF-8") -> None:
    """同步版原子写入，供非 async 上下文使用（参数语义同 write_file_atomic_async）。"""
    p = Path(p)
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.close(fd)
        with open(tmp, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


async def delete_file_async(p: str | Path):
    """异步删除文件"""
    p = Path(p)
    if p == Path():
        return False, "路径不能为空"
    try:
        await asyncio.to_thread(p.unlink, missing_ok=True)
        return True, ""
    except Exception as e:
        error_info = f" 删除文件: {p}\n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


async def move_file_async(old: str | Path, new: str | Path, *, overwrite: bool = False):
    """异步移动文件。

    目标已存在且与源不是同一文件时，默认把旧目标重命名为
    ``{stem}_conflict_{ts}{ext}`` 保留后再移动——shutil.move 会静默覆盖
    同名目标，批量任务里命名撞车会造成不可逆的数据丢失（实测复现：
    受害者内容直接被覆盖消失）。

    ``overwrite=True`` 用于「临时文件落位」语义（.[MARK].jpg / _temp /
    .tmp 等移动到正式名）：目标本就是同一资源的旧版本，直接覆盖。
    """
    old = Path(old)
    new = Path(new)
    try:
        if _is_same_path(old, new):
            return True, ""
        if await aiofiles.os.path.isdir(new) and not await aiofiles.os.path.islink(new):
            return False, f"目标是目录，无法覆盖文件: {new}"
        if not overwrite and await aiofiles.os.path.exists(new):
            same = False
            with contextlib.suppress(OSError):
                same = await asyncio.to_thread(os.path.samefile, old, new)
            if not same:
                backup = new.with_name(f"{new.stem}_conflict_{int(time.time())}{new.suffix}")
                await asyncio.to_thread(os.rename, str(new), str(backup))
                signal.add_log(f"⚠️ 目标已存在同名文件，旧文件已重命名保留: {backup}")
        await asyncio.to_thread(shutil.move, str(old), str(new))
        return True, ""
    except Exception as e:
        error_info = f" 移动文件: {old}\n 目标: {new} \n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


async def copy_file_async(old: str | Path, new: str | Path):
    """异步复制文件"""
    old = Path(old)
    new = Path(new)
    if not await aiofiles.os.path.exists(old):
        return False, f"不存在: {old}"
    try:
        if await aiofiles.os.path.exists(new) and await asyncio.to_thread(os.path.samefile, old, new):
            return True, ""
        await asyncio.to_thread(_copy_file_atomic_sync, old, new)
        return True, ""
    except Exception as e:
        error_info = f" 复制文件: {old}\n 目标: {new} \n 错误: {e}\n{traceback.format_exc()}"
        signal.add_log(error_info)
        print(error_info)
        return False, error_info


def _is_same_path(a: Path, b: Path) -> bool:
    """检查两个路径是否指向同一个文件系统对象。

    先做字符串归一化比较（捕获 a==b 的简单情况，且当文件不存在时
    os.path.samefile 会抛 FileNotFoundError，字符串比较仍能兜底）。
    如果两侧文件都存在，再 os.path.samefile 做_inode 级判定。
    """
    a_str = str(a.resolve())
    b_str = str(b.resolve())
    if a_str == b_str:
        return True
    try:
        return os.path.samefile(a_str, b_str)
    except OSError:
        return False


def safe_copytree(src: str | Path, dst: str | Path, **kwargs) -> None:
    """shutil.copytree 的安全封装：src==dst 时直接返回，避免先 rmtree 再 copytree 导致数据丢失。

    风险场景：用户把 extrafanart_folder 配成 "extrafanart"，
    导致 extrafanart_copy_path == extrafanart_path，
    外层先 rmtree(extrafanart_copy_path) 再 copytree，会把源目录删掉。
    """
    src = Path(src)
    dst = Path(dst)
    if _is_same_path(src, dst):
        return
    shutil.copytree(str(src), str(dst), **kwargs)


async def safe_copytree_async(src: str | Path, dst: str | Path, **kwargs) -> None:
    """safe_copytree 的异步版本，用于 asyncio 上下文。"""
    src = Path(src)
    dst = Path(dst)
    if _is_same_path(src, dst):
        return
    await asyncio.to_thread(lambda: shutil.copytree(str(src), str(dst), **kwargs))


def _check_pic_blocking(p: str | Path):
    """阻塞版本的图片检查，用于在线程中执行"""
    with Image.open(p) as img:  # 如果文件不是图片，报错
        img.load()  # 如果图片不完整，报错OSError: image file is truncated
        return img.size


async def check_pic_async(p: str | Path):
    """异步检查图片文件"""
    if await aiofiles.os.path.exists(p):
        try:
            # 在线程中执行PIL操作，因为PIL不支持异步
            result = await asyncio.to_thread(_check_pic_blocking, p)
            return result
        except Exception as e:
            signal.add_log(f"文件损坏: {p} \n Error: {e}")
            try:
                await aiofiles.os.remove(p)
                signal.add_log("删除成功！")
            except Exception as remove_err:
                # 同上同步版：常见 WinError 32（被占用）/ WinError 5（权限不足）
                signal.add_log(f"删除失败: {remove_err}（若是 WinError 32 请关闭预览/播放器后重试）")
    return False
