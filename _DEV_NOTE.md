# Scrapling 图片爬虫 - 开发交接笔记（v2.12.7）

## v2.12.7 修复（内嵌浏览器图标缺失——自动重排，不用手动拖窗口）
- **现象**：嵌入后图标/快捷方式缺失，**手动拖动窗口尺寸即恢复** → 不是渲染问题，是嵌入尺寸同步问题
- **根因**：_embed_browser 嵌入时浏览器页签还未显示（select(2) 在最后），winfo_width/height 拿到 1x1 废尺寸 → Chrome 被 MoveWindow 成异常布局，图标图层不绘制；后续无有效尺寸变化触发重排
- **修复**：①嵌入前先 select(2) 切到浏览器页签取真实尺寸；②嵌入后 150/500/1500ms 三次"尺寸抖动"（-1px 再恢复）制造真实 WM_SIZE 强制 Chrome 重新布局（等效自动"拖动窗口"）；③RedrawWindow 强制立即重绘
- **结论**：之前几版 GPU/后台节流参数方向都错，此版才是根因修复

## v2.12.6 修复（内嵌浏览器元素缺失，方向修正）
- **关键认知**：v2.12.4/2.12.5 的 --disable-gpu 系列没用 → 不是 GPU 问题
- **真根因**：Chrome 被 SetParent 嵌入后，系统判定窗口"被遮挡/不可见"（occluded）→ Chrome 按后台窗口节流渲染与资源加载 → favicon/快捷方式图标不绘制、严重时整页黑屏
- **修复**：启动参数加 `--disable-backgrounding-occluded-windows`（强制嵌入窗口按前台渲染）+ `--disable-renderer-backgrounding`，保留 GPU 组合；3 处启动路径

## v2.12.5 修复（内嵌浏览器图标/图层缺失，未完全解决）
- **现象**：内嵌浏览器（SetParent 嵌入 Tkinter）页面主体能显示，但部分 UI 元素渲染缺失——地址栏右侧图标空白、快捷方式图标只剩"推"/叉号
- **根因**：Chrome 被 SetParent 嵌入另一进程窗口后，GPU 合成（compositing）失效导致部分图层不绘制；v2.12.4 的 --disable-gpu 单独不够
- **修复**：启动参数再补 `--disable-gpu-compositing`（强制软件合成），与 --disable-gpu 组合（Chrome/Edge/独立窗口 3 处启动路径）——SetParent 嵌入 Chrome 的成熟方案

## v2.12.4 修复（浏览器黑屏/渲染故障）
- **现象**：内置调试浏览器偶发整个页面主体变深灰/黑屏，只残留书签栏和快捷方式文字（间歇性，CDP 截图证实网页内容未渲染，浏览器 UI 正常）
- **根因**：Chrome 远程调试模式下 GPU 硬件加速渲染偶发崩溃（合成进程故障）
- **修复**：调试浏览器启动参数加 `--disable-gpu`（爬虫浏览器不需要硬件加速，CPU 渲染稳定）；Chrome/Edge 两条启动路径 + 独立窗口路径共 3 处
- **保留**：书签/快捷方式为用户登录 Google 账号后同步，属正常使用（未加 --disable-sync）

## v2.12.3 新增（AI 可见）
1. **新增 get_browser_view 工具**：AI 现在能"看见"页面！CDP 截当前页 → 压缩 → 喂给本地视觉模型（同一 llama-server，mmproj 已加载，不用第二个模型）→ 模型描述页面内容/布局。问"看看这个页面""这个站怎么样""页面上有什么"直接答（实测准确描述测试页：标题/卡片/甚至识别出是占位符）
2. 截图自动保存 `~/AppData/Local/WebGrabber/screenshots/`，视觉推理约 20-30 秒

## v2.12.2 新增（AI 助手更智能）
1. **get_browser_info 工具**：CDP 直查 9222——标签页列表（标题+URL）+ 当前页图片数（Runtime.evaluate 统计 img 标签）。问"浏览器上有几张图""现在看的是什么页"可直接答（实测 xchina 页准确返回 22 张图）
2. **set_filter 兜底收紧**：没明确说开/关智能过滤、没给 KB 值时，不再假装"已更新"，返回"请明确过滤设置"并给示例
3. **start_crawl 智能补位**：说"这个页面/这个站/当前页"时模型直接调 start_crawl（url 可空），执行器自动用当前网址（对话提取 → url_var 两级兜底）；工具描述加场景引导
4. 实测：问"浏览器上有几张图"→ 答"22 张"；说"这个页面图片抓取"→ 自动抓当前页

## v2.12.1 修复（内置浏览器）
1. **"Chrome 未正确关闭/要恢复页面吗？"**：启动调试浏览器前自动清理 debug_profile 会话残留（Last Session/Last Tabs/Current Session/Current Tabs + Default/Session + Default/Snapshots），启动参数加 `--disable-session-crashed-bubble`，不再弹恢复条、不再恢复一堆旧标签（内嵌和独立窗口两处启动都改了）
2. **网址带中文尾巴 404**：新增 `_clean_url()`，抓取前自动去掉粘贴带进来的尾部中文（如从对话复制时带的"的图"），日志会提示清理前后的网址；纯 ASCII / 合法中文路径不受影响

## v2.12.0 新增（AI 助手模式，第一版可用）
1. **AI 助手模式**：AI 对话页签可直接提要求操作软件，如"帮我抓取这个站""现在什么状态""把保存目录改到 L:/tu"
2. **11 个工具**：start_crawl / stop_crawl / pause_crawl / resume_crawl / retry_failed / get_status / get_task_list / set_save_dir / set_filter / get_settings / open_save_dir
3. **协议**：模型输出 `[工具:名称 参数JSON]`，最多 5 轮工具循环，执行结果回喂给模型总结
4. **参数兜底**：Qwen 3.5 4B 常丢 JSON 参数 → 执行器自动从用户消息提取 URL / 路径 / 模式 / 线程数 / 过滤值（模型只做意图识别）
5. **连续失败保护**：同一工具同样错误连续 2 次自动中断，防止死循环
6. **UI**：工具调用/结果显示为橙色，对话页签提示文字更新

## 实测验证（真实模型 + 真实抓取）
- 协议测试 5 项全过：提要求→工具调用 ✓ 状态→get_status ✓ 纯聊天不调工具 ✓ 多轮回喂总结 ✓ 缺网址会询问 ✓
- 端到端：向 AI 说"帮我抓取 https://www.tuiimg.com/meinv/，单页，线程4" → 模型调 start_crawl → 真实下载 22 张图片 ✓

## 修复的 v2.11.0 遗留 bug
- `_crawl_single_page` 引用未定义的 stat_total/stat_done/stat_success/stat_fail（旧版统计变量残留）→ 单页模式抓取必崩溃，已删除残留引用，AI 过滤提示改走日志

## 模型/服务环境（不变）
- 模型：`L:\ComfyUI\ComfyUI\models\LLM\Qwen3.5-4B-Q4_K_M.gguf` + `Qwen3.5-4B-mmproj-BF16.gguf`
- llama-server：`L:\工作流\千问无审查模型配置\llama-b9297-bin-win-cuda-12.4-x64\llama-server.exe`
- 启动参数：`-ngl 999 -c 8192 --parallel 1 --image-min-tokens 1024 --cache-ram 0 --reasoning off --host 127.0.0.1 --port 8080`

## 开发/打包环境（台式机）
- 台式机无独立 Python，沙箱 Python 3.14.7（含 scrapling 0.4.15）；打包仍用笔记本 py -3.10（PyInstaller --onefile --windowed --collect-all scrapling）
- 若需台式机本地打包：先验证 PyInstaller 对 Python 3.14 + scrapling 0.4.15 的兼容性

## 下一步规划
- 工具扩充（用户提需求再定）：AI 筛选过滤触发、生成提示词批量、分析页面结构工具等
- AI 对话页签体验打磨：流式输出、工具执行进度、设置窗口"助手模式"开关
- 远期（已定）：套壳浏览器（登录 API/Cookie/Token 提取）、网页游戏修改器（与爬虫共用 CDP 通道）

## 关键代码位置（scrapling_grabber_gui.py）
- AI_TOOL_DESC：助手工具说明（发给模型）
- _ai_parse_tool_call / _ai_extract_url / _ai_extract_path / _ai_last_user_text：协议解析+参数兜底
- _ai_execute_tool：工具执行器（安全白名单 + 参数校验）
- _ai_assistant_chat：多轮工具循环（5轮上限 + 连续失败保护）
- _ai_tool_status / _ai_tool_task_list：get_status / get_task_list 实现
- AI 对话页签：底部 notebook 第 4 个 tab（tool tag 橙色显示）
