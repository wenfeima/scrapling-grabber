# Scrapling 图片爬虫 GUI

基于 Python + Tkinter + Scrapling 的图片抓取工具，支持从论坛、图片站批量抓取帖子图片。

## 功能特性

- **三种抓取模式**
  - 直连模式：requests 直连请求（带浏览器指纹伪装）
  - 浏览器渲染：Playwright 无头浏览器，自动滚动加载懒加载图片
  - 浏览器模式(CDP)：连接调试浏览器（自动启动，自动加载油猴 Tampermonkey 扩展），支持需要登录/油猴脚本的网站
- **全站抓取**：列表页翻页识别（Discuz、PHPWind、数字分页 list_N.html 等多种模式）+ 进详情页抓图
- **多线程下载**：线程数可调，失败自动重试，下载不完整自动识别
- **智能过滤**：过滤论坛表情/图标/头像等无关图片，支持缩略图转原图
- **增量扫描**：记录抓取进度，已完成的帖子自动跳过；支持强制重扫
- **范围控制**：可指定抓取第 N 到第 M 个帖子，或指定页码
- **任务管理**：任务列表实时显示进度/速度/状态，支持暂停、停止、重试失败、右键打开保存目录/帖子链接
- **下载视频开关**：可选下载帖子中的 MP4 等视频
- **AI 智能过滤（v2.9.0 新增）**：本地加载 Qwen 视觉模型（GGUF），AI 判断每张下载的图片是"正文图"还是"无关图"（logo/图标/表情/横幅/截图等），自动删除无关图。无需联网、无需 Ollama，软件直接调用本机 llama.cpp 服务
- **AI 生成提示词（v2.10.0 新增）**：AI 判断的同时为每张正文图生成**中英文双语绘图提示词**（中文详细描述 + 英文 SD tag），保存为图片同名的 .txt 文件，方便直接整合进 ComfyUI 提示词插件使用
- **设置窗口（v2.10.1 新增）**：网址栏后的「设置」按钮收纳不常改的配置（保存目录、AI 模型/视觉模块/服务程序路径、端口），主界面只保留每次都要操作的控件
- **AI 辅助分析抓取（v2.11.0 新增）**：规则识别不到帖子链接/图片时，自动调用本地模型分析页面 URL 规律，按规律提取；分析结果按站点缓存，下次直接套用
- **下载前 AI 预筛（v2.11.0 新增）**：可选开关，下载前只对"规则拿不准"的 URL 调模型判断（装饰特征直接剔除、明显正文直接保留，不耗多余算力）
- **AI 对话页签（v2.11.0 新增）**：底部新增「AI对话」页签，可直接与本地模型对话（上下文条数可在设置窗口调），并自动记录每次 AI 调用（过滤判断/提示词生成/规律分析/预筛）的请求与回复，带清除按钮

## 使用说明

1. 输入目标网址（列表页 URL）
2. 点「设置」选择保存目录（主界面只读显示，改目录需进设置窗口）
3. 设置抓取模式（普通网站用直连；懒加载/反爬网站用浏览器渲染；需要登录或油猴的用 CDP）
4. 点「开始抓取」

### AI 智能过滤（可选功能）

1. 在「AI 操作行」选择模型预设（内置4B（6G显存）适合小显存机器；内置9B（12G显存）效果更好），或点「设置」→「自定义」手动指定模型路径
2. 勾选「启用AI过滤」，可同时勾选「AI生成提示词」（每张正文图输出中英文提示词，存同名 txt）
3. 点「启动AI服务」，等待状态变为「运行中」（首次启动需加载模型约 10 秒）
4. 正常抓取即可，下载完成后自动逐张 AI 判断并删除无关图；勾选「抓取完自动停止」可在抓取结束后自动停止 AI 服务释放显存

**提示词 txt 格式**（img_001.jpg → img_001.txt）：
```
# 中文提示词
（详细中文描述：人物特征、服装、场景、光线、镜头焦距光圈等）

# 英文 Tag
masterpiece, best quality, 1girl, ...（SD 风格英文 tag）
```

**模型要求**：
- 需要 GGUF 格式的 Qwen 视觉模型（主模型 + mmproj 视觉模块各一个）
- 需要 llama.cpp 官方预编译版 `llama-server.exe`（CUDA 版，默认路径为 `L:\工作流\千问无审查模型配置\llama-b9297-bin-win-cuda-12.4-x64\`，可在面板中修改）
- AI 判断速度取决于显卡：RTX 4070 约 10-20 秒/张，GTX 1660 约 80-100 秒/张

### CDP 模式（浏览器模式）说明

- 勾选「浏览器模式」自动切换到 CDP，开始抓取时自动启动调试浏览器（独立配置目录 `%LOCALAPPDATA%\WebGrabber\debug_profile`）
- 会自动从默认 Chrome 加载 Tampermonkey（油猴）扩展及其脚本数据
- 若自动加载失败，可在调试浏览器里手动安装一次油猴（配置会保留）

## 环境要求

- Python 3.10+
- 依赖：scrapling、lxml、cssselect、curl_cffi、playwright、patchright、browserforge、websocket-client

## 打包

```bash
pyinstaller --onefile --windowed --collect-all scrapling --collect-all lxml --collect-all cssselect --collect-all curl_cffi --collect-all playwright --collect-all patchright --collect-all browserforge --collect-all websocket --hidden-import scrapling --hidden-import lxml --hidden-import cssselect --hidden-import curl_cffi --hidden-import playwright --hidden-import patchright --hidden-import browserforge --hidden-import websocket --name "Scrapling图片爬虫_GUI" scrapling_grabber_gui.py
```

## 版本

- v2.11.0（最新）：AI 辅助分析抓取（规则抓不到时模型分析 URL 规律+站点缓存复用）；下载前 AI 预筛（只筛规则拿不准的图）；AI 对话页签（直接与本地模型对话+自动记录所有 AI 调用，上下文条数可设置）
- v2.10.1：界面重构——网址栏后新增「设置」按钮，保存目录与 AI 模型路径等配置收进设置窗口；主界面保留 AI 操作行（启用AI过滤/AI生成提示词/模型预设/启动服务）；新增「抓取完自动停止」选项（抓取结束自动释放显存）；模型预设名改为按显存区分（内置4B（6G显存）/内置9B（12G显存））
- v2.10.0：新增 AI 生成提示词（中英文双语，同名 txt 保存）
- v2.9.0：新增 AI 智能过滤（本地 Qwen 视觉模型，自动删除无关图），支持模型预设切换
- v2.8.6：修复 CDP 模式多线程共用标签页冲突（每个线程独立标签页）
- 完整迭代历史：v1.1.0 → v2.10.1
