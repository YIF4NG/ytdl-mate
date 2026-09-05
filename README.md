# YT下载助手

一个面向 Windows 用户的中文 yt-dlp 图形界面。粘贴链接、选择画质和保存位置，即可下载视频或提取音频，无需手写命令。

**当前版本：1.0.1 · Windows 10 / 11 x64 · Python + Tkinter**

## 功能

| 功能 | 说明 |
| --- | --- |
| 视频下载 | 支持单个链接、多个链接和播放列表；多个链接依次处理 |
| 画质选择 | 最佳、4K、1080p、720p、480p，按视频源实际提供的格式选择 |
| 视频容器 | 默认 MKV（画质优先），可切换 MP4（兼容优先） |
| 音频提取 | 支持 MP3、M4A |
| 字幕与媒体信息 | 可选下载中英字幕（含网站提供的自动字幕）、嵌入封面与信息 |
| 登录信息 | 支持 Chrome、Edge、Firefox，以及 Netscape 格式的 `cookies.txt` |
| 链接解析 | 查看视频标题、实际可用分辨率或播放列表条目数 |
| 下载状态 | 显示进度、速度、预计剩余时间，支持查看和复制日志 |
| 任务操作 | 支持取消、断点续传，以及打开成品或保存文件夹 |
| 设置记忆 | 自动保存常用选项和 Cookie 文件路径 |

播放列表在首次使用时默认关闭；启用后，开始下载前会再次确认。续传是否成功取决于网站支持及已有临时文件。

## 快速开始

### 1. 准备运行工具

轻量版 EXE 已包含图形界面运行所需的 Python 环境，**使用 EXE 不需要安装 Python**，但不附带以下下载工具：

| 工具 | 用途 |
| --- | --- |
| `yt-dlp.exe` | 解析链接、下载媒体，必需 |
| `ffmpeg.exe`、`ffprobe.exe` | 合并视频、处理字幕和转换音频，必需，且两者必须放在同一个目录 |
| `deno.exe` 或 `node.exe` | 为需要 JavaScript 运行时的网站提供支持，例如 YouTube |

**Windows x64 下载链接：**

| 工具 | 下载入口 | 下载后如何放置 |
| --- | --- | --- |
| yt-dlp | [直接下载 yt-dlp.exe](https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe) · [官方发布页](https://github.com/yt-dlp/yt-dlp/releases/latest) | 将 `yt-dlp.exe` 放入应用旁的 `tools` 文件夹 |
| FFmpeg | [下载 Windows ZIP 包](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip) · [Gyan 构建下载页](https://www.gyan.dev/ffmpeg/builds/) | 解压后，将 `bin` 中的 `ffmpeg.exe` 和 `ffprobe.exe` 一起放入 `tools` |
| ffprobe | 与上面的 FFmpeg ZIP 包一同提供，无需单独下载 | 使用同一包中的 `ffprobe.exe`，与 `ffmpeg.exe` 放在同一目录 |
| Deno | [下载 Windows x64 ZIP 包](https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip) · [官方发布页](https://github.com/denoland/deno/releases/latest) | 解压后，将 `deno.exe` 放入 `tools` |

FFmpeg 官方提供源码，并在[官方下载页](https://ffmpeg.org/download.html)列出 Windows 编译包提供方；上面的 Gyan 链接就是其中之一。Deno 的平台文件名可在[官方安装说明](https://docs.deno.com/runtime/getting_started/installation/#manual-download)中核对。

最直接的配置方式是在应用旁新建 `tools` 文件夹：

```text
YT下载助手/
├── YT下载助手-1.0.1.exe
└── tools/
    ├── yt-dlp.exe
    ├── ffmpeg.exe
    ├── ffprobe.exe
    └── deno.exe
```

应用也会查找自身目录、部分常见安装位置和系统 `PATH`，并支持 `tools/ffmpeg/bin/` 形式的目录。已经安装工具时，可先启动应用，点击右上角的 **检查工具** 查看识别到的路径和版本。

### 2. 开始下载

1. 双击 `YT下载助手-1.0.1.exe`（自行构建的文件名为 `YT下载助手.exe`）。
2. 粘贴视频链接；批量下载时建议一行一个链接。
3. 按需点击 **解析链接**，查看标题和可用画质。
4. 选择 **视频** 或 **仅音频**，设置画质、容器或音频格式，以及保存位置。
5. 需要播放列表、字幕或登录信息时，展开 **高级选项**。
6. 点击 **开始下载**，完成后可直接 **打开文件** 或 **打开文件夹**。

画质选项表示格式选择偏好，不会把低分辨率视频提升为高清；实际结果由视频源、登录状态和账号权限决定。

## 登录与 Bilibili 会员画质

需要登录才能访问的内容，可在 **高级选项 → 登录信息** 中选择已登录的浏览器。选择“不使用”时，以未登录状态请求网站。

如果浏览器 Cookie 读取失败，也可以使用 Cookie 文件：

1. 在 Chrome 中安装 [Get cookies.txt LOCALLY（Chrome 应用商店）](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)。这是 [yt-dlp 官方 FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) 列出的第三方扩展。
2. 在浏览器中登录目标网站，确认该账号可以播放所需内容和画质。
3. 保持目标网站页面打开，点击扩展图标，将当前网站的 Cookie 导出为 **Netscape** 格式的 `cookies.txt`。例如下载 Bilibili 视频时，仅导出 `bilibili.com` 的 Cookie。
4. 回到下载助手，把 **登录信息** 切换为 **Cookie 文件**，点击 **选择 cookies.txt…** 并选中刚导出的文件。
5. 重新点击 **解析链接**，检查可用画质后开始下载。

文件模式会直接使用所选文件，不再读取浏览器 Cookie 数据库。Cookie 过期后需要重新导出；格式检查通过不代表登录或会员状态仍然有效。

Cookie 文件包含登录凭证，请勿上传到 GitHub 或分享。应用只保存文件路径，执行任务时使用临时副本，不回写原文件；正常结束、取消或失败后会清理副本，强制结束进程或断电时可能残留临时文件。

## 常见问题

### 提示缺少 yt-dlp 或 FFmpeg

点击 **检查工具** 查看缺失项，把对应程序放进应用旁的 `tools` 文件夹，再重新启动应用。`ffmpeg.exe` 和 `ffprobe.exe` 必须位于同一目录；只有其中一个时，应用会阻止开始下载。

### Chrome 提示“无法复制 Cookie 数据库”或解密失败

数据库占用时，可先保存浏览器中的工作并完全退出 Chrome，再重试。DPAPI 或解密失败不一定能通过关闭浏览器解决，可改用 **Cookie 文件**，或在 Firefox 中登录后选择 Firefox。

### 选择“最佳”仍然没有 4K 或会员画质

“最佳”只会从网站返回的格式中选择。请确认视频本身提供对应画质、当前账号拥有观看权限，并在更换登录信息后重新解析。

### 出现 HTTP 412 或其他网站拒绝请求的提示

先在浏览器中确认同一视频可以正常播放，完成网站要求的验证，再更新该网站的 Cookie 或稍后重试。详细日志可用于进一步排查。

### 设置保存在哪里？

设置保存在 `%APPDATA%\YT下载助手\settings.json`，包括保存目录、常用下载选项和 Cookie 文件路径；视频链接与 Cookie 内容不会写入该设置文件。

### 如何更新下载工具？

退出正在进行的任务后，替换应用识别到的 `yt-dlp.exe` 或其他工具，再重启应用检查版本。工具独立于图形界面维护，应用不会自动下载或更新它们。

## 从源码运行

环境要求：Windows 10 / 11 x64、Python 3.10 或更高版本，并带有 Tkinter。下载所需的外部工具与 EXE 版相同；从源码运行时，应用目录为 `source/`，可将工具放入 `source/tools/`。

以下命令均在仓库根目录执行：

```powershell
python .\source\src\app.py
```

图形界面源码使用 Python 标准库；`requirements-build.txt` 中的 PyInstaller 仅用于打包 EXE。

### 运行测试

```powershell
python -m unittest discover -s .\source\tests -v
```

### 构建 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\source\build.ps1
```

构建脚本会创建独立虚拟环境、安装固定版本的 PyInstaller、运行自动测试、打包 EXE，并检查界面能否初始化和正常退出。首次构建需要联网安装构建依赖。

输出文件：

```text
source/release/1.0.1/
├── YT下载助手.exe
└── SHA256SUMS.txt
```

已安装构建依赖时，可在构建命令末尾加上 `-SkipInstall` 跳过安装步骤。构建结果仍是轻量版，不会打包外部下载工具。

## 源码结构

```text
source/
├── src/
│   ├── app.py                 # 中文界面、任务调度和设置管理
│   └── core.py                # 工具查找、下载参数、进度解析与日志脱敏
├── tests/                     # 核心逻辑和界面行为测试
├── assets/                    # 应用图标
├── tools/                     # 图标生成、Tcl/Tk 构建辅助脚本
├── build.ps1                  # 构建与启动检查
├── requirements-build.txt     # 构建依赖
├── version_info.txt           # Windows 可执行文件版本信息
└── THIRD_PARTY_NOTICES.md      # 第三方工具说明
```

## 第三方说明

本项目提供图形界面，媒体解析与下载由 yt-dlp 执行，音视频处理由 FFmpeg 完成，JavaScript 支持由 Deno 或 Node.js 提供。具体网站支持情况取决于所用工具版本和网站状态。

第三方工具适用各自的许可与分发条款；如果自行制作包含这些工具的便携包，请一并满足对应的许可要求。详见 [第三方工具说明](source/THIRD_PARTY_NOTICES.md)。
