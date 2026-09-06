"""复现：fanart 原子复制的 .tmp 残留场景.

用户报告：正常刮削完成后 fanart.jpg 未生成，出现 .fanart.jpg.xxx.tmp（mkstemp 随机串形态）。
链路：fanart_download → copy_file_async → _copy_file_atomic_sync
  → mkstemp(.fanart.jpg.XXX.tmp) → shutil.copy → os.replace(tmp, fanart.jpg)
残留与假成功：os.replace 被 Windows 瞬时占用挡下（杀软扫描/索引）且 unlink 同败时，
copy_file_async 返回 False——此前 fanart_download 不查返回值，日志照打 Fanart done!，
表现为「正常刮削但 fanart 只剩 .tmp」。
"""

import os
from pathlib import Path

import mdcx.utils.file as fmod


def test_atomic_copy_normal_no_tmp_left(tmp_path: Path):
    src = tmp_path / "thumb.jpg"
    src.write_bytes(b"x" * 100)
    dst = tmp_path / "fanart.jpg"
    ok, err = fmod.copy_file_sync(src, dst)
    assert ok, err
    assert dst.read_bytes() == b"x" * 100
    # 正常路径无 .tmp 残留
    leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*"))
    assert not leftovers, f"正常路径残留: {leftovers}"


def test_sweep_stale_atomic_temps_cleans_orphans(tmp_path: Path):
    """孤儿 tmp 兜底清理：mkstemp 形态（.fanart.jpg.xxx.tmp）删除，正常文件不动."""
    from mdcx.utils.file import sweep_stale_atomic_temps

    # 造孤儿（进程中断形态）
    orphan1 = tmp_path / ".fanart.jpg.a8x3f2.tmp"
    orphan1.write_bytes(b"partial")
    orphan2 = tmp_path / ".poster.jpg.zz9.tmp"
    orphan2.write_bytes(b"partial")
    # 正常文件（不能被误伤）
    keep1 = tmp_path / "fanart.jpg"
    keep1.write_bytes(b"real")
    keep2 = tmp_path / "notes.tmp"  # 无前导点的 tmp 不是 mkstemp 孤儿形态
    keep2.write_bytes(b"user file")
    keep3 = tmp_path / ".hidden.jpg"  # 隐藏但非 .tmp 后缀
    keep3.write_bytes(b"cache")

    removed = sweep_stale_atomic_temps(tmp_path)

    assert sorted(removed) == sorted([str(orphan1), str(orphan2)])
    assert not orphan1.exists() and not orphan2.exists()
    assert keep1.exists() and keep2.exists() and keep3.exists()


def test_atomic_copy_retries_replace_on_windows_lock(tmp_path: Path, monkeypatch):
    """Windows 瞬时占用：replace 前两次 PermissionError，第三次成功（重试后落成正式文件）。"""
    src = tmp_path / "thumb.jpg"
    src.write_bytes(b"payload")
    dst = tmp_path / "fanart.jpg"

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(f"locked (attempt {calls['n']})")
        return real_replace(a, b)

    monkeypatch.setattr(fmod.os, "replace", flaky_replace)
    ok, err = fmod.copy_file_sync(src, dst)
    assert ok, f"重试后应成功: {err}"
    assert calls["n"] == 3, f"应重试 3 次: {calls['n']}"
    assert dst.read_bytes() == b"payload"
    assert not list(tmp_path.glob(".*fanart.jpg.*.tmp")), "成功后无 tmp 残留"


def test_atomic_copy_gives_up_after_three_locks(tmp_path: Path, monkeypatch):
    """持续占用：3 次重试后放弃，返回失败（不再假报成功），tmp 清理尽力."""
    src = tmp_path / "thumb.jpg"
    src.write_bytes(b"payload")
    dst = tmp_path / "fanart.jpg"

    def always_locked(a, b):
        raise PermissionError("locked forever")

    monkeypatch.setattr(fmod.os, "replace", always_locked)
    ok, err = fmod.copy_file_sync(src, dst)
    assert not ok, "持续占用应返回 False（此前被吞成假成功）"
    assert "locked forever" in err
    # Linux 可清理；Windows 占用中 unlink 同败时由刮削结束兜底
    assert not list(tmp_path.glob(".*fanart.jpg.*.tmp")), "Linux 下失败路径应清理 tmp"


def test_sweep_stale_atomic_temps_missing_dir():
    from mdcx.utils.file import sweep_stale_atomic_temps

    assert sweep_stale_atomic_temps("/nonexistent/definitely/not/here") == []
