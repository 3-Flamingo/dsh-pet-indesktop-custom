"""槽档案被电源掉电写坏时，「生小肥鱼 / 生成 slot0」不能把用户堵死。

2026-11-11 事故：14:30 意外断电，``config-slot-0.json`` 被写成一整片空格
（1215 字节、合法长度、内容是空白）。此后每次读它都是 ``corrupt``，UI 只
逐拍记一条 WARNING，而**主进程没有任何入口**能重建这份档案——托盘与恢复窗
的「生成 / 恢复 slot0」走的都是"读快照 → 不是 ok 就抛错"，于是用户能看到的
只有一条永远消不掉的报错。

修复口径：**读**依旧严谨（坏档案不参与任何写、``read_slot_snapshot`` 仍报
``corrupt``）；只有"重建这只宠"这一条**显式入口**在档案损坏时走恢复路径——
与 :func:`pet.pet_profiles.write_profile_settings` 的 ``on_broken=
"backup-overwrite"`` 同一套约定（先备份、再重建），坏文件一个字节都不丢。
"""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from pet.config import APP_DIR_NAME
from pet import pet_profiles as profiles
from tests.test_overlay_spawn import _make_persistent_shell


def _corrupt_like_power_loss(path):
    """按事故现场复刻：长度对、内容是空白（断电时缓冲区被零页/空格顶掉）。"""
    path.write_bytes(b' ' * len(path.read_bytes()))


def _backups(path):
    return sorted(p for p in path.parent.iterdir()
                  if p.name.startswith(path.name + '.corrupt-'))


def test_corrupt_slot0_can_be_rebuilt_from_the_tray_entry(tmp_path):
    shell, _ = _make_persistent_shell(tmp_path)
    directory = tmp_path / APP_DIR_NAME
    path = profiles.slot_profile_path(directory, 0)
    try:
        assert path.is_file(), '前提：第一次运行时 slot0 档案已落盘'
        legacy_scale = (shell.cfg.get('scale') if hasattr(shell, 'cfg')
                        else shell._config.get('scale'))
        _corrupt_like_power_loss(path)
        assert profiles.read_slot_snapshot(directory, 0).status == 'corrupt', (
            '前提：读侧仍把坏档案判为不可信')

        shell.exit_pet(shell.sprite)
        assert shell.sprite is None

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        menu = shell.tray.contextMenu()
        action = next(a for a in menu.actions() if a.text() == '生成 / 恢复 slot0')
        action.trigger()
        app.processEvents()

        assert shell.sprite is not None, '坏档案必须能从托盘入口重建回来'
        assert shell._active_slots() == [0]
        snapshot = profiles.read_slot_snapshot(directory, 0)
        assert snapshot.status == 'ok', snapshot
        rebuilt = profiles.read_slot_profile(directory, 0).data
        assert rebuilt.get('scale') == pytest.approx(float(legacy_scale)), (
            '重建要沿用全局配置里的旧几何，而不是清成默认值')
        backups = _backups(path)
        assert backups, '坏档案必须先备份再重建（一个字节都不丢）'
        assert backups[-1].read_bytes() == b' ' * len(backups[-1].read_bytes())
    finally:
        shell.stop()


def test_corrupt_slot1_is_rebuilt_on_spawn(tmp_path):
    # 档案里记着屏名却不等于承载屏时，几何自存会整块跳过（临时承载不落盘）——
    # 这里让跨屏关着，即"落位就是归属"。
    shell, _ = _make_persistent_shell(tmp_path, {"allow_cross_screen": False})
    directory = tmp_path / APP_DIR_NAME
    try:
        shell.spawn_pet()
        path = profiles.slot_profile_path(directory, 1)
        assert path.is_file()
        # 先让 slot1 **退役**：活跃集合只留 0，分配器下次才会把 1 发回来
        # （生成只补"最小非活跃槽"，不会覆盖正在跑的宠）
        shell.exit_pet(shell._spawned[0])
        assert shell._active_slots() == [0]
        _corrupt_like_power_loss(path)
        before = len(shell._spawned)

        shell.spawn_pet()

        assert len(shell._spawned) == before + 1, '坏掉的子槽也要能重新生成'
        assert profiles.read_slot_snapshot(directory, 1).status == 'ok'
        assert _backups(path)
    finally:
        shell.stop()
