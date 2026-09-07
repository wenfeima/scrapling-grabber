# Scrapling 图片爬虫 - 开发交接笔记（v2.12.2）

## v2.12.2 新增（AI 助手更智能）
1. **新增 get_browser_info 工具**：模型现在能看到浏览器！CDP 直查 9222——标签页列表（标题+URL）+ 当前页图片数（Runtime.evaluate 统计 img 标签）。用户问"浏览器上有几张图""现在看的是什么页"可直接回答（实测 xchina 页准确返回 22 张图）
2. **set_filter 兜底收紧**：用户没明确说开/关智能过滤、没给 KB 值时，不再假装"已更新"（原来会拿当前值报成功，误导用户），改为返回"请明确过滤设置"并给示例
3. **start_crawl 智能补位**：用户说"这个页面/这个站/当前页"时，模型直接调 start_crawl（url 可空），执行器自动用当前网址（对话里提取 → url_var 兜底两级）；工具描述加了场景引导（抓取→start_crawl、查浏览器→get_browser_info、设过滤→set_filter）
4. 实测两个场景修复：问"浏览器上有几张图"→ 模型答"22 张"；说"这个页面图片抓取"→ 自动抓当前页

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
