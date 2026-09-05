# YT下载助手

一个面向普通 Windows 用户的 yt-dlp 图形界面。粘贴链接、选择画质和保存位置后即可下载，不需要手写命令。

## 快速开始

1. 双击 `YT下载助手.exe`。
2. 粘贴视频链接；需要确认标题或播放列表数量时，点“解析链接”。
3. 选择视频画质或音频格式，再选择保存位置。
4. 点“开始下载”。完成后可直接打开文件或文件夹。

## 功能

- 支持单视频、多链接和播放列表（播放列表默认关闭，避免误下载）。
- 视频支持最佳、4K、1080p、720p 和 480p 优先目标。
- 默认使用对高画质、封面和字幕更稳的 MKV；高级选项中可切换为 MP4 兼容模式。
- 音频支持 MP3 与 M4A。
- 可选中英字幕、封面与媒体信息。
- 可读取 Chrome、Edge 或 Firefox 的登录信息；浏览器读取失败时可导入 Netscape cookies.txt。
- 解析单个视频后显示实际可用分辨率，方便检查会员画质是否生效。
- 显示进度、速度、预计剩余时间和详细日志。
- 支持取消任务、续传、打开成品或保存文件夹。
- 自动记住常用选项和 Cookie 文件路径；不保存视频链接或将 Cookie 内容写入设置。任务使用临时副本，结束后清理，不回写原文件。

## Bilibili 会员画质与 Chrome 登录

选择“不使用”时，yt-dlp 会以未登录状态访问，可能拿不到账号可观看的高画质。选择“最佳”只能在网站实际返回的格式中挑选，不能增加账号权限。

如果 Chrome 报“无法复制 Cookie 数据库”，请先保存浏览器中的工作并完全退出 Chrome 后重试。若报 DPAPI / 解密失败，可能是浏览器加密方式不兼容；仅关闭浏览器未必能解决。

1. 在 Chrome 中打开 Bilibili，确认登录的是可观看所需画质的大会员账号。
2. 使用 [yt-dlp 官方 FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) 列出的 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 扩展，在 Bilibili 页面仅导出 `bilibili.com` 的 Netscape 格式 `cookies.txt`。
3. 打开“高级选项”，把“登录信息”切换为“Cookie 文件”，点“选择 cookies.txt…”。
4. 粘贴视频链接并点“解析链接”，检查显示的可用画质，然后开始下载。Cookie 文件模式不会再尝试读取 Chrome 数据库。

也可以在 Firefox 中登录 Bilibili，然后选择 Firefox。Cookie 文件失效后需要重新导出；文件格式有效不等于账号登录或会员状态一定有效。

Cookie 文件相当于登录凭证，只在本机保存，不要上传或分享。软件使用临时副本，正常完成、取消或失败后清理；强制结束进程或断电时可能残留系统临时文件。

若提示 HTTP 412，说明网站拒绝了请求。先在浏览器中确认同一视频可以正常播放，完成网站要求的验证，再更新本站 Cookie 或稍后重试。

## 运行要求

应用启动时会按顺序查找：

1. 应用旁边的 `tools` 文件夹；
2. 应用所在文件夹；
3. 系统环境变量中的 `yt-dlp.exe`、`ffmpeg.exe`、`ffprobe.exe` 和 JavaScript 运行时。

本机已经安装这些工具时，可直接运行 `YT下载助手.exe`。若要制作免安装目录，把 `yt-dlp.exe`、`ffmpeg.exe`、`ffprobe.exe` 和 `deno.exe` 放入应用旁边的 `tools` 文件夹即可。yt-dlp 当前建议 Deno 2.3 或更高版本以获得完整的 YouTube 支持；应用也会同时启用检测到的 Node.js 22+ 作为备用。设置保存在 `%APPDATA%\YT下载助手`，不会写入应用目录。

本次交付的是轻量版应用，不重复附带 yt-dlp、FFmpeg 或 JavaScript 运行时。本机已有的工具会被自动识别。应用由本地构建且未做商业代码签名，因此 Windows 可能显示“未知发布者”；源码一并提供，便于检查和继续修改。

## 从源码运行

源码要求 Windows 10/11 x64、Python 3.10 或更高版本，并需要 Tkinter（python.org 的官方 Windows 安装包默认包含）。

```powershell
python .\src\app.py
```

## 测试

```powershell
python -m unittest discover -s .\tests -v
```

## 打包

首次打包需要联网安装固定版本的 PyInstaller。PowerShell 执行策略阻止直接运行脚本时，可使用下面的命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

脚本会先运行自动测试，随后打包并对 EXE 做启动冒烟测试。成品位于 `release\1.0.1\YT下载助手.exe`，同目录还会生成 SHA-256 校验文件。

## 使用提醒

请只下载你有权保存的内容，并遵守网站条款与所在地法律。登录信息在本机读取，由 yt-dlp 用于请求对应网站；不会将 Cookie 内容写入应用设置或复制的日志。
