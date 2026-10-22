# dsh-pet-indesktop-custom

基于上游 [**MerZlin/dsh-pet-indesktop**](https://github.com/MerZlin/dsh-pet-indesktop) **v4.3.4**（MIT）的本地修复版。
只动了两个缺陷，其余保持上游原样；修复都带回归测试。

## 相对上游的改动

| 提交 | 内容 |
|---|---|
| `fix(menu)` | 右键菜单点菜单以外的任何地方都不收起，只有点桌宠本身才关 |
| `fix(weather)` | 中国天气网街道级 12 位码失效导致「返回数据无效」；镇级标签在 open-meteo 查不到 |
| `test(menu)` | 菜单外部点击看门狗的回归用例 |

### 1. 菜单：点外部收起

**成因**：桌宠叠层窗带 `WS_EX_NOACTIVATE`（上游 issue #98，故意不抢前台/键盘焦点），
`QMenu` 的 popup 因此也不会激活；Qt 原生「点别处 → popup 失活 / 丢鼠标抓取 → 自动关闭」
依赖激活态，永远走不到，点别的应用更是根本不进本进程事件循环。

**修法**：新增 `pet/menu_dismiss.py`。`run_menu()` 在 `exec` 期间用 30 ms 定时器轮询
全局左键（`GetAsyncKeyState`）与光标位置（`GetCursorPos`），落在菜单树几何之外就
`close()` 并停表。不装全局钩子、不抢焦点、不改窗口样式；`exec` 返回即停止。
5 个弹出点（`overlay_shell.py` ×2、`overlay_window.py` ×1、`window.py` ×2）改用 `run_menu`。

> **注意**：不能用「把 `QMenu.exec` 包一层」的通用做法。PySide6 的 `QMenu.exec` 是 C++ 方法，
> 在 Python 层赋值实测无效——包装器从不被调用，探针会直接落进原生阻塞菜单。

### 2. 天气：两级降级

**成因 A**：中国天气网检索会给出 **12 位街道码**（如马桥镇 `101020200005`），而
`d1.weather.com.cn/sk_2d/` 对它 302 到 404 页面，JSON 解析必然失败；旧实现
「按码失败 → 回退检索」又把同一个坏码 `pick_candidate` 回来，等于没回退，
最终气泡只剩「返回数据无效：返回数据无效」。

**修法 A**：`cn_code_variants()` 先试 9 位区县码（`101020200` = 闵行，实测可取数），
仍失败则按候选顺序逐个试。

**成因 B**：open-meteo 只拿标签前半段（马桥镇）去 GeoNames，镇名查不到就整源失败。

**修法 B**：`open_meteo_query_names()` 按 基础名 → 标签两侧（上海）→ 全串 逐个试。

## 构建

上游的 onedir 打包流程见 [`docs/ONEDIR_PACKAGING.md`](docs/ONEDIR_PACKAGING.md)：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_onedir.ps1 -SkipZip
```

两个前提（构建硬门要求，仓库里没有）：

- `assets/characters/<角色>/frameseq/`：帧序列派生产物（`.gitignore` 里），
  v4.3.4 基线要的是 **v5** 世代；缺失时 `scripts/check_frameseq_bundle.py` 会中止打包；
- `resources/presentmon/` 与 `resources/rapidocr_models/`：随包二进制/模型（已入库）。

## 已验证

- `ruff check pet tests` 通过；
- `pytest tests/test_menu_dismiss.py tests/test_weather.py tests/test_weather_fallback.py tests/test_context_menu_lifecycle.py tests/test_sprite_menu.py` = 106 passed；
- 真机（Windows 10，1920×1080 + 副屏）：右键弹菜单 → 点 DSH 窗口 → 菜单立即收起；天气取数返回「闵行 多云 22.1℃」。

## 许可

上游为 MIT，本仓库保留其 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`；改动同样以 MIT 提供。
