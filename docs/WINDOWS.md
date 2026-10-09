# 血源 bbport：Windows 构建和运行

本项目以独立 GitHub 仓库发布，源码基于 [deadinside28/bloodborne_pc](https://github.com/deadinside28/bloodborne_pc)，保留原作者版权、上游提交历史和许可证，增加原生 Windows x64 运行库、Vulkan 渲染器构建和中文启动器。游戏进程无需 WSL。当前发布仅提供源码，没有预编译安装包或游戏数据。

已在一台 Windows 11 电脑上用 CUSA03023 1.09 进入实际关卡，1080p 预热后观察到 60 FPS。RTX 4070 Ti 上短时 4K、FSR 4 Balanced 测量中，平稳 60 帧模式平均约 60 FPS，独立显示 1% Low 约 55～58 FPS。首次着色器编译和加载仍会掉帧，完整通关与长期稳定性尚未验证。详细记录见 [WINDOWS_VALIDATION.md](WINDOWS_VALIDATION.md) 和[帧时间测量](WINDOWS_FRAME_PACING.md)。

## 环境要求

- Windows x64；已测试 Windows 11。内存后端使用现代 Windows 占位符 API，其他系统版本未验证。
- 支持 Vulkan 1.3 的显卡和驱动。当前验证机为 RTX 4070 Ti 12 GB、i5-13600KF、约 16 GB 系统内存，不代表最低配置。
- Git、Python 3（启动器需要 Tcl/Tk）和 MSYS2 UCRT64。当前构建验证使用 GCC 16.2、CMake 4.4、Ninja 和 Python 3.14；MSVC 构建未实现。
- 自己的已解密 Bloodborne 游戏目录，编号 CUSA03173 或 CUSA03023，版本 1.09。

## 获取和构建源码

```powershell
git clone --branch codex/windows-port --recurse-submodules https://github.com/yaonikaixin999999/bloodborne_pc_windows.git
cd bloodborne_pc_windows
```

已经克隆但子模块不完整时执行 `git submodule update --init --recursive`。在 **MSYS2 UCRT64** 终端安装依赖：

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc \
  mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja \
  mingw-w64-ucrt-x86_64-pkgconf mingw-w64-ucrt-x86_64-sdl3 \
  mingw-w64-ucrt-x86_64-vulkan-headers mingw-w64-ucrt-x86_64-vulkan-loader \
  mingw-w64-ucrt-x86_64-vulkan-memory-allocator mingw-w64-ucrt-x86_64-ffmpeg \
  mingw-w64-ucrt-x86_64-boost mingw-w64-ucrt-x86_64-fmt \
  mingw-w64-ucrt-x86_64-robin-map mingw-w64-ucrt-x86_64-xxhash \
  mingw-w64-ucrt-x86_64-zydis mingw-w64-ucrt-x86_64-glslang \
  mingw-w64-ucrt-x86_64-spirv-tools mingw-w64-ucrt-x86_64-spirv-cross \
  mingw-w64-ucrt-x86_64-python
```

然后在源码目录的 PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -MsysRoot "C:\msys64" -Test
```

将 `C:\msys64` 换成实际安装位置。脚本也会自动探测默认目录及源码上级目录的 `tools-local/msys64`。`-Test` 运行 CTest 和八组 Python 测试，包括修改器的合成 Windows 进程集成测试；任一失败都会停止。仅编译时省略它。默认并行 4 个任务，可用 `-Jobs 3` 降低内存压力，`-BuildDir` 指定其他构建目录。`-Diagnostics` 仅构建诊断后端，不能玩游戏。

CMake 首次配置会下载固定版本的 magic_enum、xbyak、miniz 等依赖，需要联网；已有 `out/dependency-sources/` 缓存时构建脚本可以复用。完整产物为 `out/windows/bin/bb-probe.exe`。

## 准备游戏目录

选择直接包含 `eboot.bin` 的目录，例如 `C:\Games\CUSA03023`：

```text
CUSA03023/
  eboot.bin
  sce_sys/param.sfo
  sce_module/
    libc.prx
    libSceFios2.prx
    ...
  dvdroot_ps4/
    chr/
    map/
    msg/
    ...
```

启动器读取 `param.sfo`，检查 `TITLE_ID=CUSA03173` 或 `CUSA03023`、`APP_VER=01.09` 或 `1.09`，准备脚本继续验证可加载代码。编号是 PS4 游戏发行版本标识，文件夹名称本身不能改变编号。无需重命名 CUSA03023，也不要选择它的上级目录。更新须已合并为 1.09；程序不下载游戏或系统模块。

也可以自行将游戏数据放在源码目录的 `game/CUSA03023` 或 `game/CUSA03173`。没有有效的已选目录时，启动器会自动检测这两个位置；已有有效的外部目录仍会保留。源码目录内的游戏路径保存为相对路径，整个本地目录移动后可继续识别；命令行省略 `--game` 时沿用已保存或自动检测到的目录。

打包后的 `启动游戏.exe` 以所在目录为数据根，自动检测的是 exe 旁的 `game/CUSA03173`、`game/CUSA03023`；也可以在选择窗口里直接选任意位置（例如 `D:\Games\CUSA03173`），选择结果保存在 `user/launcher.json`。游戏目录请放在 `--clean` 重建范围之外，或者在重新打包时不要加 `--clean`。

## 启动与设置

```powershell
python .\run_windows.py --gui
```

也可以双击源码根目录的 `start_windows.cmd`。在“启动”页选择游戏目录、输出分辨率、60 帧、语言及窗口/全屏；“画面设置”页调整超分和特效。首次建议使用 1080p、FSR 3.1，进入关卡后再提高负载。首次启动会生成加载镜像、链接游戏自带模块并应用补丁。

打包后的 `dist/windows` 自带单文件启动器：双击 `启动游戏.exe` 即可，不需要系统 Python（启动脚本与运行时都内嵌在 exe 里）；`修改器.exe` 是同目录的独立修改器。

游戏语言支持 `auto/zh-cn/zh-tw/en`。自动模式优先检测 `dvdroot_ps4/msg/zhocn` 简体资源，再检测 `zhotw` 繁体资源，最后英语；明确选择中文但资源缺失时会报错。普通全屏使用桌面无边框模式；平稳 60 帧选项可切换为同分辨率的 120 Hz 全屏显示模式。

“全屏运行”旁的“垂直同步”勾选框控制显示器同步，保存后在下次启动游戏时生效，独立于游戏帧率选择。勾选使用 FIFO，取消使用 Immediate；如果显卡不支持 Immediate，渲染器会回退到 FIFO。命令行可用 `--vsync` / `--no-vsync`，省略时沿用已保存选择；首次默认关闭。

支持 120 Hz 的显示器建议选择 **60 帧**，并勾选 **全屏运行、垂直同步、平稳 60 帧（120 Hz 全屏）**。新选项首次默认关闭、保存后下次启动生效，只有 60 帧、全屏和垂直同步同时成立时才启用。它使用动态游戏时序补丁，再单独限制为 60 FPS，并使用两帧队列；游戏仍以 60 帧运行，120 Hz 指显示器刷新率。在 120 Hz 下，每个游戏帧可保持两次刷新，减少 160 Hz 桌面下 60 帧不均匀的显示间隔。

该选项只请求当前桌面分辨率的 120 Hz 模式；不存在兼容模式时保留桌面刷新率，60 FPS 限制继续生效。退出后恢复桌面模式；本机已验证 3840×2160@159.98 → 120 → 159.98 Hz。取消勾选即可使用原来的固定 60 帧方案。CLI 使用 `--sync-refresh` / `--no-sync-refresh`，省略时沿用保存选择；30/90/`uncap` 档位不启用此组合。更多结果、局限及回退方式见 [WINDOWS_FRAME_PACING.md](WINDOWS_FRAME_PACING.md)。

启动器提供独立的“A/B 互换”和“X/Y 互换”勾选框，可只换一组或同时换两组。选择保存后在下次启动游戏时生效，下方显示当前对应关系。旧 Xbox 方案会恢复为两项都勾选。

| `--controller-layout` | 互换 | 实体 A/B/X/Y 对应游戏按键 |
| --- | --- | --- |
| `ps4` | 原版 | ✕ / ○ / □ / △ |
| `swap-ab` | 仅 A/B | ○ / ✕ / □ / △ |
| `swap-xy` | 仅 X/Y | ✕ / ○ / △ / □ |
| `xbox` | A/B 和 X/Y | ○ / ✕ / △ / □ |

亚洲版游戏通常使用 ○ 确认、✕ 返回，勾选 A/B 互换后对应实体 A/B。角色命名屏幕键盘使用实体 A 选择、B 取消、X 删除、Y 或 Start 完成。键盘菜单方向为 I/K/J/L，左 Shift 为 ○，空格为 ✕。

```powershell
python .\run_windows.py --game "C:\Games\CUSA03023" --resolution 1080p --fps 60 --language zh-cn --controller-layout xbox --windowed
python .\run_windows.py --game "C:\Games\CUSA03023" --resolution 4k --fullscreen
python .\run_windows.py --game "C:\Games\CUSA03023" --fps 60 --fullscreen --vsync --sync-refresh
python .\run_windows.py --game "C:\Games\CUSA03023" --check
python .\run_windows.py --game "C:\Games\CUSA03023" --prepare-only
```

省略语言、帧率、手柄方案和显示模式会沿用已保存选择；省略 `--resolution` 会保留 `bbport.ini` 的自定义画质。显式分辨率档位只更新输出、预设与缩放路径，不重置其他效果。GUI 保存只提交用户修改字段，避免覆盖游戏内设置。

## 分辨率、超分和帧率

GUI 的输出尺寸与质量档位独立，可选 720p、1080p、1440p 和 4K。CLI 另提供便捷档位：

| `--resolution` | 输出 | 预设 |
| --- | --- | --- |
| `1080p` | 1920×1080 | Quality |
| `1440p` | 2560×1440 | Quality |
| `4k` | 3840×2160 | Balanced |
| `4k-quality` | 3840×2160 | Quality |
| `4k-native` | 3840×2160 | Native AA |

FSR 3.1 与 FSR 4 的 Quality/Balanced 等预设以较低场景分辨率重建输出；Native AA 使用原生场景尺寸。TAA 和关闭超分也使用原生场景尺寸。4K 输出不等于原生 4K 场景渲染，具体尺寸会显示在设置页。1080p 使用渲染器的动态缩放路径；其他输出默认通过启动补丁设置场景尺寸。

可选 FSR 3.1、FSR 4 v07 INT8、TAA 或关闭超分。**FSR 4.1.1 Windows 适配尚未完成，启动器禁止新选。** FSR 4 还需模型资源及 GPU 必需特性；独立基准通过不代表游戏内各预设已经验证。没有新增 DLSS 或帧生成实现。

帧率选项为 `--fps 30|60|90|uncap`。普通 30/60 使用 60 Hz vblank，90 使用 90 Hz；`uncap` 使用动态游戏时序和显示器节奏（当前上游实现最高 120 帧）。平稳 60 帧选项在内部使用 `uncap` 动态时序，但限制实际提交为 60 FPS；`launch.json` 分别记录用户选择的 `fps=60`、`patch_fps=uncap` 和 `target_fps=60`。运行日志中的 `vblank 480 Hz` 是内部调度频率，显示器为 120 Hz、游戏为 60 帧。90 和直接选择 `uncap` 仍为实验功能；60 帧目标约为 16.7 ms，每个场景的负载与加载仍会影响 Low。

画面设置还包括锐化、运动向量、响应遮罩、景深、运动模糊、SSAO、动态阴影、SSR、模型 LOD、显示帧率和跳过开场。进入游戏后可用 **Insert** 或 **L3+R3** 打开移植设置菜单；部分分辨率/预设变化需“应用并重启”，启动器会接收重启请求并保留选择。

## Windows 修改器

双击 `start_trainer.cmd` 打开中文修改器，或执行 `python bloodborne_trainer.py --gui`。先启动本项目的原生游戏程序，再扫描、连接并点击“应用设置”。支持生命/体力补满、血之回响数值和已有物品数量，连接本身不会启用功能。正常关闭或断开会还原指令；具体行为、范围、测试和社区来源见 [WINDOWS_TRAINER.md](WINDOWS_TRAINER.md)。

## 可选 FSR 4 v07 资源

FSR 3.1 无需单独模型。FSR 4 资源不在源码或本地 DLL 包中；在源码目录执行：

```powershell
python .\tools\fetch_fsr4_assets_windows.py --tools-dir "C:\msys64\ucrt64\bin"
```

下载器固定使用 Q2RTX 提交 `ae8d628fae208813172446d1e49ed94150b04658` 的 MIT 资源，涵盖六种预设及 1080/2160 tier，校验上游 manifest 的文件大小/SHA256、SPIR-V，并生成优化着色器。报告为 `fsr4_shaders/ASSET_INSTALL_REPORT.json`；该目录被 Git 忽略。工具使用 MSYS2 中的 `spirv-val` 等程序，请按实际安装位置设置 `--tools-dir`。下载工具不执行 GPU 测试。

FSR 4.1.1 上游捕获工具需要 Proton。本分支尚未完成原生 Windows 捕获/模型转换和对应 GPU 验证，不能用 v07 资源代替 4.1.1。

## 数据与本地运行包

| 路径 | 用途 |
| --- | --- |
| `bbport.ini` | 图形与游戏效果设置 |
| `user/launcher.json` | 游戏路径、语言、帧率、窗口、同步/平稳 60 帧和手柄选择 |
| `user/` | 存档、缓存和运行日志 |
| `out/windows-data/` | 从游戏生成的镜像、补丁和准备报告 |
| `out/windows-data/last-run.log` | GUI 启动日志 |
| `out/windows/` | 完整构建产物 |
| `dist/windows/` | 可选打包目录：bb-probe 与 DLL，加 启动游戏.exe / 修改器.exe 单文件启动器 |
| `fsr4_shaders/` | 单独下载的 FSR 4 资源 |

生成镜像含游戏代码，存档和配置也属于本机数据，不应加入源码提交。默认使用独立 `user/`，不会直接写入其他模拟器的存档目录。

本地打包命令（按实际 MSYS2 位置替换 `--prefix`）：

```powershell
python .\scripts\package_windows.py --prefix "C:\msys64\ucrt64"
```

默认只从 MSYS2 UCRT64 前缀收集 DLL；需要该前缀之外的 DLL（例如自编译的 FFmpeg）时，追加 `--dll-dir "<DLL 目录>" --extra-notice "<对应的许可文件>"`。

打包默认需要 PyInstaller（打包期依赖，需在运行该脚本的 Python 环境安装：`python -m pip install pyinstaller`；本次打包验证使用 6.22.3，MSYS2 仓库没有对应包）。不需要冻结时用 `--skip-frozen`，该路径不需要 PyInstaller。

脚本递归检查 PE 导入、收集所需 DLL 与许可（`bb-probe.exe` 与 DLL 保持原有的平铺布局），并用 PyInstaller 把 Python 启动调用链冻结成两个单文件 exe：

- `启动游戏.exe`：内嵌 `run_windows.py`、`windows_graphics*.py`、`scripts/`（prepare/link_libc/link_modules/content_profile/patches）与内置 `patches/Bloodborne.xml`。双击打开 GUI；命令行参数原样透传（如 `启动游戏.exe --check`）。准备步骤与游戏启动在 exe 内部派发执行，不再有可修改的 `.py`。
- `修改器.exe`：内嵌 `bloodborne_trainer.py` 与 `trainer_windows.py`，双击打开修改器窗口。

两个 exe 以所在目录为数据根：`user/`（存档、`launcher.json`、`trainer.json`）、`out/windows-data/`（生成的镜像、补丁与 `last-run.log`）和 `bbport.ini` 都在 exe 旁生成；把 exe 与 `bb-probe.exe` 放在同一目录（即 `dist/windows`）即可直接使用。`--skip-frozen` 只收集 DLL 与清单；`--clean` 在重建前清空旧的打包产物。修改代码后需重新打包，否则可能启动旧程序。这里的本地打包不表示仓库已提供二进制下载。

## 排查问题

启动失败时先查看 `out/windows-data/last-run.log`。缺游戏文件时检查所选目录及结构；版本拒绝时检查 `param.sfo` 和更新合并；DLL 缺失时从源码启动器运行，并确认 MSYS2 路径或本地 DLL 包完整。

2026-10-06 修复了全屏游戏内 Alt+Tab 的零尺寸图像创建问题。最小化、隐藏或全屏失去焦点时暂时跳过画面呈现，继续处理游戏的帧完成事件；窗口恢复后重新取得图像，必要时重建交换链。临时零尺寸不会覆盖上一份有效游戏图像尺寸。此行为兼容“平稳 60 帧（120 Hz 全屏）”，无需取消全屏或更改画质；切到后台不会暂停游戏逻辑。

GUI 现在使用隐藏的 `python.exe` 工作进程记录准备工具和原生游戏的 stdout/stderr；启动器仍可用 `pythonw.exe` 打开，但同目录必须保留 `python.exe`。旧版本只记录外层退出码 1，底层日志可能丢失。新版本保留原生退出码，23 可能表示 GPU 断言或游戏调试异常，应以日志中的 `GPU ... Critical` / `STOP:` 行确定原因。修改后须重新打包并重新打开启动器，才能使用新的程序和日志方案。

报告运行错误时附上显卡/驱动、当前输出和超分设置、场景、是否可复现及相关日志。发布日志前移除个人路径；不要附游戏文件或生成镜像。

Windows 稀疏共享内存使用 `SEC_RESERVE`，已提交页的内存承诺保留到进程退出，释放/复用时清零。长时间内存峰值和高负载 4K 表现仍需实测。测试通过、窗口初始化通过和低负载菜单 60 FPS 都不能代替关卡及长期运行验证。

平均显示 60 帧但手感不平稳时，先检查帧时间和显示刷新率。已经开启垂直同步也可能有不均匀帧间隔；本机的高精度等待和 120 Hz 平稳 60 帧方案改善了这种情况。NVIDIA 浮窗的 Low 公式/时间窗可能不同于独立采样，不能用单个数字替代场景测试。加载和首次着色器编译造成的长帧不会因锁 60 自动消失。
