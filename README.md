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

## 使用说明

1. 输入目标网址（列表页 URL）
2. 选择保存目录
3. 设置抓取模式（普通网站用直连；懒加载/反爬网站用浏览器渲染；需要登录或油猴的用 CDP）
4. 点「开始抓取」

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

- v2.8.6（最新）：修复 CDP 模式多线程共用标签页冲突（每个线程独立标签页）
- 完整迭代历史：v1.1.0 → v2.8.6
