# 血源 Windows 修改器

本修改器适配此项目的原生 Windows x64 运行程序，以及已验证的《血源》1.09 游戏代码。它单独运行，不修改游戏文件；不适用于 shadPS4 模拟器进程。

## 使用

1. 正常通过本项目启动器启动游戏，等待进入游戏。
2. 双击项目根目录的 `start_trainer.cmd`；打包后可直接双击 `dist/windows/修改器.exe`；若已创建桌面“血源 Windows 修改器”快捷方式，也可使用它。
3. 点击“扫描进程”，选择游戏进程后点击“连接”。连接成功不会自动开启修改。
4. 勾选功能、填写数值，点击“应用设置”。取消勾选后再次应用会关闭对应功能。
5. “恢复全部”关闭所有功能；正常断开连接或关闭修改器也会还原原始指令。

源码运行需要现有的 64 位 Python 3 和 Tcl/Tk。也可从源码目录执行 `python bloodborne_trainer.py --gui`；打包后的 `修改器.exe` 已内嵌 Python 与 Tcl/Tk，不需要安装。窗口中的“打开游戏启动器”只打开启动器，游戏仍由用户点击启动。

## 功能

| 功能 | 行为 |
| --- | --- |
| 无限生命 | 在游戏读取对应角色状态时将当前生命补到最大值 |
| 无限体力 | 在对应体力读取时补到最大值 |
| 血之回响 | 指定 0～99,999,999；下次通过对应获取/消费路径更新时写入指定值 |
| 已有物品数量 | 指定 1～99，默认 20；使用物品等触发对应数量更新时写入指定值 |

物品功能修改已有物品的数量，不生成新物品或改变物品种类。生命补满不会拦截剧情死亡或坠落即死。恢复指令不会撤销已经获得、消耗或保存到存档中的回响和物品数量。修改器不自动按每种物品的容量限制数量；所有物品种类尚未逐一实测。

偏好保存在 `user/trainer.json`。保存的选项仅预填界面，每次连接后都需要点击“应用设置”。游戏重新启动后必须重新扫描、连接。

## 校验与还原

修改器只接受本源码目录下 `dist/windows/bb-probe.exe`、`out/windows/bin/bb-probe.exe` 或与打包后的 `修改器.exe` 同目录的 `bb-probe.exe` 的进程，并校验四处原始指令来识别游戏内存映射。版本、代码或其他修改器冲突会拒绝连接或写入。连接、扫描及 `--check` 不会启用功能。

Windows 游戏映像动态分配，原 PS4 的绝对地址不能直接使用。本实现重新分配近距离跳转代码，保留原始字节，修改时暂停目标线程并检查执行位置；失败时尝试回滚，正常退出时恢复指令和释放资源。不要通过结束任务强行关闭修改器：这种关闭方式无法执行恢复，已启用效果可能保留到游戏进程退出。

## 验证

已在本机 CUSA03023 1.09 的解密代码中核验四处原始指令。28 项修改器测试通过，包含 23 项后端单元测试、4 项界面测试和 1 项真实 Windows 进程集成测试。测试验证数值范围、进程白名单、版本不匹配拒绝、开关与还原、冲突检测、线程暂停重试和写入失败回滚。

标准 Windows 验证入口 `build_windows.ps1 -Test` 会编译合成进程并运行这 28 项测试，无需游戏数据。

独立测试程序 `tests/trainer_fixture_windows.c` 不含游戏数据，模拟四处指令和字段。在真实 Windows 进程上验证连接、四项修改、数值重新设置、部分关闭、恢复全部和断开还原，并覆盖物品代码的两个进入路径。它验证 Windows 内存操作和生成指令的行为，不能代替游戏内所有场景和物品的效果测试。

复现独立进程测试，在 PowerShell 中执行（按 MSYS2 安装位置调整 PATH）：

```powershell
$env:Path = "C:\msys64\ucrt64\bin;" + $env:Path
New-Item -ItemType Directory -Force out | Out-Null
gcc tests/trainer_fixture_windows.c -O2 -Wall -Wextra -Werror -o out/trainer_fixture_windows.exe
$env:BB_TRAINER_FIXTURE = (Resolve-Path out/trainer_fixture_windows.exe).Path
python -m unittest discover -s tests -p test_windows_trainer_integration.py -v
```

## 来源与许可

Hook 位置和字段含义参考 Shiningami 的 Bloodborne 1.09 社区修改表，并与本机游戏原始指令核验。Windows 的识别、内存操作、跳转代码、界面和还原流程由本项目实现，没有直接采用社区表中的 PS4 固定绝对指针或代码洞。相关作者署名保留；新增源码沿用 GPL-2.0-or-later，见项目 `LICENSE`。
