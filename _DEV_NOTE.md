# Scrapling 图片爬虫 - 开发交接笔记（截至 v3.1.13）

## v3.1.13 新增（「范围」拆成起始/终止两个输入框）

**需求**：用户贴了高级面板第 1 排的截图（`范围: [10-50]`），要求「分成 2 个，前面一个填开始、后面一个填终止」。

**改法**
- UI（`opt_frame` 第 1 排）：单个 `Entry(width=4)` 换成 起始框 `width=3` + 一个 `Muted.TLabel('-')` + 终止框 `width=4`；
  变量 `post_range_var` → `post_range_start_var` / `post_range_end_var`（默认 `'1'` / `'20'`）。
  实测这排最右端 650px（可用 964），面板 reqwidth 仍 882，不影响 980 默认窗口。
- 解析集中在模块级两个纯函数（好单测）：
  - `parse_range_pair(start_text, end_text, default_end=20)` → `(起始, 终止)`，1-based 闭区间。
    留空/非数字/≤0 都回退默认（起始 1、终止 20）；起始 > 终止时**自动对调**；
    另外兼容「把旧格式 `15-60` 整段粘进起始框」。
  - `split_legacy_range(text, default_end=20)`：旧配置单值 → 两值（`'20'`→`(1,20)`、`'15-60'`→`(15,60)`）。
- 类内 `_post_range_values()` 返回 `(起始-1, 终止)`（直接给列表切片用），
  `_crawl_worker` 与 `_crawl_whole_site` **两处共用**（原来这段解析逻辑在两处各写了一遍，随手统一了）。
- 配置：存 `post_range_start` / `post_range_end`；加载时优先读新键、缺失就用 `split_legacy_range(cfg['post_range'])` 拆。
  保存时 `self.cfg.pop('post_range', None)` 清掉旧键（`cfg.update()` 是合并语义，不清就永远留在配置文件里）。
- 日志口径不变：`范围: 第N到第M个帖子`（只在起始 > 1 时打，跟旧行为一致），`_crawl_whole_site` 里的
  「开始范围选择（共 X 个帖子，范围: N-M）」照旧。

**验证**
- `_v3113_unit.py`：`parse_range_pair` 14 例（空/非数字/0/负数/小数/填反/空格/大数字/None/旧格式粘入）、
  `split_legacy_range` 7 例、真 GUI 配置往返（旧 `post_range='15-60'` 载入 → 两框 15/60；改 5/80 存盘 → 重载 5/80；
  旧键已清理）→ **29/29 通过**
- `_v3113_layout.py`：980 与 1936 两档、暗/浅色共 4 张截图；第 1 排最右端 650 ≤ 964、`adv_frame.reqwidth=882` 不变
- `_codecheck_v3113.py`：exe 内嵌代码 **45 项全过**；`_v3113_exe_smoke.py`：真实点击展开面板截图确认两个框可见
  - ⚠ 冒烟第一次点击**没展开**（窗口未被前台激活时首击只激活窗口）→ 加「点完按卡片底色采样判断是否展开、
    最多重试 3 次」的循环后稳定通过。
  - ⚠ 核对脚本里「旧版本号已清除」这项**必须用精确匹配**（`'v3.1.12' in ss`）：v3.1.12 起
    `_extract_card_links` 的 docstring 里写着「（v3.1.12 新增…）」，用子串匹配会误报 ❌。

## v3.1.12 新增（列表页自动进帖子抓内容图）

**问题**：用户问「打开一个列表页，能不能自动抓该页所有帖子的内容图，而不是列表上的标题图」。
软件本来就有「全站」模式（`_crawl_whole_site` = 列表页翻页 + 进详情页抓），但对这个站完全失效。

**站点结构（实测 xchina.co）**
- 列表页 `/photos/series-<hex>.html`：一页 11 个帖子，分页 `/photos/series-<hex>/<n>.html`（该系列共 63 页）
- 帖子 `/photo/id-<hex>.html`：**每页只给 15 张**，站内分页 `/photo/id-<hex>/<n>.html`（该帖 8 页 / 109 张）
- 图片 `img.xchina.io/photos/<id>/00001_600x0.webp` → 原图同目录 `00001.jpg`（v3.1.11 的规则正好能升级）
- 注意目录有 `photos/` 与 `photos2/` 两种，编号 4 位 / 5 位都出现过

**为什么失效**：`_extract_post_links` 老的 `detail_patterns` 对 `/photo/id-<hex>.html` 命中 **0 个**，
反而把分页 `/photos/series-xxx/2.html` 当成帖子（命中 `/\d+\.html`）→ 收集不到帖子 →
回退 `_crawl_single_page` → 抓到的就是列表页上的封面缩略图。

**改法**
- 新增模块级 `url_shape(path)` + `_URL_SHAPE_ID_RE`：把路径归一化成形态模板
  （`/photo/id-6a98940bb9a27.html` → `/photo/id-<ID>.html`、`.../2.html` → `/.../<N>.html`）。
  ⚠ 必须先 `lower()` 再替换，否则 `'<ID>'` 会被 lower 成 `'<id>'`（单测抓出来的）。
- 新增 `_extract_card_links(page, base_url, html)`：卡片式条目判据，须同时满足 ——
  ① 同域名 ② 链接自身或内部含图（`<img>` 或 `background-image`）
  ③ 不在 pager/pagination/menu/nav/footer/header/breadcrumb 容器内
  ④ 形态在页面出现 ≥3 次（不足放宽到 2）⑤ 形态 ≠ 当前页形态（挡掉「相关分类/同类列表页」）。
  实测该列表页：精确 11 个帖子、0 误抓；侧栏 88 条 `/photos/series-*.html` 卡片数为 0 → 全被挡掉。
- `_extract_post_links(page, base_url, html=None)`：**卡片结果优先**，为空才回退老的 URL 形态规则
  （论坛站列表条目常常没图，卡片判据会失效，老规则必须留着）。调用处 `_crawl_whole_site` 补传 `html`。
- 新增 `_expand_post_pages(base_url, page, html, timeout, img_urls)`：站内翻页。
  找「自身分页」链接（路径 == 当前页去 `.html` + `/<数字>.html`）后**取最大页码**
  （⚠ 分页条只渲染首尾几页，实测只有 1/2/3/8，数链接个数会少算），第 2..N 页逐页抓取合并去重，
  连续 2 页没有新图就停，另有「最多页」上限兜底。返回**有序**列表（`set` 判重 + `list` 保序，
  否则下载顺序会乱）。CDP 模式直接返回（`_fetch_page` 内部已按同一开关翻过，避免翻两遍）。
- `crawl_single_post` 接入 `_expand_post_pages`（放在 `_extract_images_from_page` 之后）。
  **只在全站模式的帖子任务里翻页**，单页模式不动 —— 否则用户用单页模式打开列表页会一次抓 63 页封面图。
- `auto_page_var`（「自动翻页抓全部」）默认 `False` → **`True`**，站内翻页由它控制；
  检测到本页还有后续页但开关关着时打一行「本页还有 N 页…站内翻页未启用」提示。
- **修一个既有 bug**：增量扫描把帖子全跳过时 `post_links` 会变空，原代码走
  「未识别到帖子链接，回退为单页抓取」→ 把列表页当单页再抓一遍封面图。现在区分
  「识别不到」（才回退）与「识别到了但都已抓过」（提示 + 直接结束，要重抓得勾「强制重扫」）。
- `_extract_images_from_page` 提取阶段新增噪声过滤：第三方统计/广告域名（googletagmanager 等）、
  `/gtag/`、`/images/sites/`、`/images/empty`、`favicon`、`/qrcode`；无扩展名的兜底分支改用
  **路径**判断静态资源（`core-state.js?v=…`、`beacon.min.js/v31ed…` 这类以前会被当成图片）。
  实测一页能少抓十几张无关文件。

**验证**
- `_v3112_unit.py`：形态归一化 5 例 + 真实列表页 11 帖 + 老规则回归 + 翻页/最多页/无新图即停/
  CDP 跳过/开关关闭 + 增量短路 + 强制重扫 → **29/29 通过**
- `_v3112_real.py`：真机跑通完整链路 —— 列表页 11 帖 → 帖子翻 8 页合并 141 张、其中 **109 张**可升级原图、抽查原图 HTTP 200
- `_v3112_offline.py`：用真机抓下的 HTML 离线验证噪声过滤（29 → 17 张，相册 16 张全保留）
- `_codecheck_v3112.py`：exe 内嵌代码 **42 项全过**；`_v3112_layout.py`：面板 reqwidth 仍 882、
  A 行右端 579 ≤ 964、各默认值正确
- ⚠ 收尾时用户的代理被关（10808/10809 都不通、直连也不通），最后的真机复跑做不了，改用离线 HTML 验证

## v3.1.11 新增（抓取原图：缩略图地址 → 原图地址）

**问题**：用户发现抓下来的图比浏览器「另存为」小很多。实测原因：相册页只暴露缩略图地址，
如 `https://img.xchina.io/photos2/<id>/0001_600x0.webp`（600×800 / 49KB），
同目录 `0001.jpg` 才是原图（1800×2400 / 519KB）。页面 HTML 里根本没有原图地址（照片是
`<div role="img" style="background-image:url(...)">`），只能按命名规律猜。

**改法**（`_download_image_list` 内 `download_one`）：
- 新增模块级 `_ORIG_SUFFIX_RE` + `orig_url_candidates(url)`：把 `xxx_<宽>x<高>.<ext>` 形式的
  预览地址扩成候选列表 `[xxx.jpg, xxx.<原格式>, 原地址]`。宽 ≥30 且（高 ≥30 或 高==0，
  站点用 0 表示高度自适应）；base 末段为空/尺寸不合理时不动原地址。
- `download_one` 从 `candidates[0]` 开始试，每个候选最多 3 次重试，全试完才判这张失败；
  取到原图失败就自动回退预览，**不会因为猜错而整批失败**。已确认是"明确否定"的响应
  （404/403、200 但内容不是图片）直接换下一个候选，不再傻等 3 次重试（原来每个候选重试
  3 次会让整批慢很多）。
- 新增模块级 `looks_like_media(data)`（文件头魔数：JPEG/PNG/GIF/BMP/RIFF+WEBP/ftyp/TIFF）。
  **这个必须有**：这类 CDN 对不存在的文件返回 **200 + 一小段 HTML**（实测
  `/photos2/<id>/0001.webp` 就是 200 + text/html），只看状态码会把 HTML 当图片存下来。
- 失败兜底修复：原来的浏览器通道兜底（`_cdp_download_image`）因为引用了尚未赋值的
  `filepath`，`NameError` 被 `except: pass` 吞掉，等于从来没生效过。现在抽成局部函数
  `_cdp_fallback(url, idx)`（自己按后缀算文件名），HTTP 通道的失败/异常两条路径都会调用它。
- UI：高级面板 C 行最前面加勾选框「抓取原图」（`orig_img_var`，默认 True，存 `cfg['orig_img']`）。
  关掉就退回 v3.1.10 行为（只下预览图）。C 行最右端 800px、面板 reqwidth 仍 882（功能入口那排
  仍是最宽的），980 默认窗口放得下。
- 日志：每张图会打「原图不可用(原因)，回退预览图: <url>」，下载末尾汇总一行
  「原图替换: N 张取到原图[，M 张原图地址不可用已回退预览图]」。

**验证**：`_origtest.py`（候选规则 9 例 + 文件头 10 例 + 真站探测）、`_orige2e.py`
（桩网络 18 项：命中原图/回 200+HTML 回退/404 回退/关开关/异常换候选/过小跳过/普通地址不变），
`_origreal.py` 真机下 8 张：**8/8 全部 1800×2400、合计 2802KB（对照组预览图 228KB，12.3 倍）**。

## v3.x 交接补充（v3.0.0 → v3.1.13）

> 仓库 git 历史里 v3.1.x 的逐版细节没留（只有 v3.0.0 两条提交 + 最后一次 v3.1.10），这里按「发布版本 → 实际改动」补齐；
> 依据是各版 exe 的内嵌代码解包核对（逐版探测标志性方法/常量存在性）+ 改造过程记录，不是回忆推测。

### 发布顺序与内容
- **v3.0.0**（2026-09-08 / 09-14，两条提交）：CDP 直读 + 自动翻页 + 视频轮播 + 伪装嗅探；修复模型路径/下拉框 bug，自定义模型点选 + 自适应，复用外部 LLM 服务，新增 AI 状态灯
- **v3.1.0**：新增 WASM 内存扫描（先是独立窗口，后按要求并入游戏修改器的统一扫描：`_ec_fill` 改走 `ec_tree_segs` 的 iid→segs 映射，WASM 段统一表示成 `['__wasm', memIdx, type, offset]`，过滤/对比/写入/锁定全复用）；新增深色科技蓝/浅色双主题 `_apply_widget_theme` + 底部状态栏
- **v3.1.1**：顶部设置区从 6 行精简为「网址行 + 可折叠高级选项面板 `_toggle_advanced`」；修复 ttk clam 勾选框选中后视觉无变化（显式配 `indicatorforeground` + 选中态 `indicatorbackground`）；「保存到」改可点击链接 `Link.TLabel`
- **v3.1.2**：顶部工具行压成一行 —— `opt.pack(in_=other_frame)` 复用同一批控件在两种排布间切换 + `Row.TButton` 系列紧凑样式（`width=-1` 破 ttk 最小宽度）+ 宽度自适应三件套（`_apply_opt_layout` / `_measure_inline_need` / `_opt_recheck`）
- **v3.1.3**：下载容错 —— `IMAGE_HEADERS`（图片专用请求头，绕开图床 CDN 的 403）+ `HttpSessions`（直连/系统代理双通道会话池，直连通道 `trust_env=False`）+ `http_get()`；`_download_image_list` 增加 `referer`
- **v3.1.4**：功能审计；修 `_open_save_dir` 被重复定义（后者覆盖前者 → 任务列表右键不再优先打开该任务目录）、设置窗口恢复保存目录历史下拉（`dir_combo` / `_dir_refresh_combo`）
- **v3.1.5 / v3.1.6**：`_launch_debug_browser` 重写为三分支 —— ①已嵌入且窗口有效 → 静默跳过 ②桌面有顶层可见窗口 → 嵌入 ③端口通但窗口看不见（残留）→ 清理残留 + 等端口释放 + 重启 + 嵌入；新增 `_embedded_browser_alive`（`EnumWindows` 只枚举顶层窗口，已嵌入的浏览器必须用 `IsWindow+IsWindowVisible` 判断，否则会被误判成残留反复杀重启）；与「独立窗口」共用同一套 helper，顺带修掉选 Edge 也只会启动 Chrome 的死变量
- **v3.1.7**：「高级选项」挪到「设置」后面；功能入口 8 个按钮收进面板；新增 `_panel_need_width`（把面板所需宽度并进启动 autosize/minsize）
- **v3.1.8**：参数行并入面板（`opt_frame` 变成 `adv_frame` 的子控件）；运行控制行按需出现（`_show_run_bar` / `_sync_run_bar`，`_finish_crawl` → `after(300, _sync_run_bar)`）；**删除**整套宽度自适应机制（`_apply_opt_layout` / `_measure_inline_need` / `_pack_opt_row` / `_opt_need_width` / `opt_sep` 等）
- **v3.1.9**：顶部留白收紧（`top_frame.pady/ipady`、`url_frame.pady`、`TNotebook.tabmargins` 三处）
- **v3.1.10**：面板排版放宽（行距/分隔条/AI 开关拆两排）+ 新样式 `Feature.TButton` + 功能入口按钮右对齐
- **v3.1.11**：抓取原图（`orig_url_candidates` / `looks_like_media` / `_cdp_fallback` + 「抓取原图」勾选框），详见上节
- **v3.1.12**：列表页自动进帖子抓内容图（`url_shape` / `_extract_card_links` / `_expand_post_pages` + 卡片判据替换形态规则 + 增量短路 bug 修复），详见上节
- **v3.1.13**：「范围」拆成起始/终止两个输入框（`parse_range_pair` / `split_legacy_range` / `_post_range_values` + 配置键拆成 `post_range_start`/`post_range_end`），详见上节

### 当前顶部结构（v3.1.13）
`url_frame`（行1：网址 + 收藏 / 设置 / 高级选项 ▾ / 开始抓取）→ `btn_frame`（**默认不 pack**：暂停/停止/重试失败）→ `adv_frame`（可折叠面板：抓取参数 / 功能入口 / 智能过滤 / AI / 转换+性能 / 浏览器模式）。
标签条高度约 36px 由 `TNotebook.Tab` 的 `padding=(14,6)` 决定，改 `tabmargins` 或 `TNotebook.padding` 对标签条高度无效。

### v3.x 新增代码位置
- 主题：`_apply_widget_theme` / `THEMES` / `_apply_theme`（切换主题要重新 `.configure(text=...)` 手动改过文案的按钮）
- 顶部布局：`_toggle_advanced` / `_show_run_bar` / `_sync_run_bar`
- 下载：`IMAGE_HEADERS` / `HttpSessions` / `http_get` / `_download_image_list` / `_cdp_download_image`
- 原图推导（v3.1.11）：`_ORIG_SUFFIX_RE` / `orig_url_candidates` / `looks_like_media` / `_download_image_list._cdp_fallback`
- 列表页/帖子（v3.1.12）：`url_shape` / `_extract_card_links` / `_extract_post_links` / `_expand_post_pages` / `_crawl_whole_site` / `crawl_single_post` 内的调用
- 「范围」解析（v3.1.13）：`parse_range_pair` / `split_legacy_range` / `_post_range_values`（`_crawl_worker` 与 `_crawl_whole_site` 共用）
- 调试浏览器：`_launch_debug_browser` / `_open_independent_browser` / `_embed_browser` / `_debug_browser_visible_pid` / `_embedded_browser_alive` / `_prepare_debug_profile` / `_find_browser_exe` / `_wait_debug_port_free`
- 游戏修改：`_open_game_mod_window` / `_ai_ec_scan` / `_ai_ec_edit` / `_ai_ec_lock` / `_wasm_boot` / `_ec_assign_expr`
- 目录历史：`_dir_remember` / `_dir_refresh_combo` / `_on_dir_pick` / `cfg['save_dirs']`

### v3.x 期间的坑（务必遵守）
- **同一文件不要并行发多个 Edit**：会互相覆盖（工具报成功但改动丢失），必须串行改 + 改完 grep 核对落点。
- **exe 内嵌代码核对**：`CArchiveReader(exe).extract('scrapling_grabber_gui')` 返回的字节**直接** `marshal.loads` 即可（6.x 不写文件）；**不要**自己按 toc 里的 offset seek（那读到的是 bootloader 机器码）。递归收集 `co_consts` 时**必须同时递归 tuple/frozenset/list**，否则 `self._cfg('TNotebook', tabmargins=...)` 这类 kwarg 名会漏 → 误报"配置没生效"。
- **老 exe 可能读不出来**：v3.0.0 那个 exe 是另一套 Python 环境打的，`marshal.loads` 报 `bad marshal data`；核对不到不代表操作错了。
- **打包**：`--workpath` 给一个**全新不存在**的目录（沙箱 safe-delete 会在清理 >50 文件时报错 rc=1，而 rc=1 时 exe 仍是上一次的旧产物，靠 mtime 识破）；正在运行的 exe 会锁住 dist 目录，改版本号 + 新目录打包，别动用户正在用的文件。
- **exe 冒烟**：给子进程 `USERPROFILE=<临时目录>` 隔离配置；窗口用 `FindWindowW(None, '全能网页助手 vX.Y.Z')` 按标题找（onefile 的 `Popen.pid` 是 bootloader 父进程，按 pid 比归属永远不匹配）；截图/点击前先 `SetWindowPos(HWND_TOPMOST)`，点击必须 `SetCursorPos` + `mouse_event`（给 Tk 发 `PostMessage` 不生效）。

## v2.12.27 新增（AI对话磁吸窗 + Cocos引擎扫描）
- **AI对话磁吸窗**：AI 行新增「AI对话」按钮，点一下贴合主窗口右侧（360px 宽、高度跟主窗），再点隐藏；与游戏修改窗口同款机制（拖动100px内吸回、拖远自由、主窗移动实时跟随/轮询兜底）
- 对话逻辑完全复用：发送走 `_ai_chat_send_from`（页签+磁吸窗共用），截图走 `_ai_add_shot`，清空双窗口同步
- **Cocos 引擎专项扫描**：首次扫描检测 `window.cc` → 遍历 `cc.director.getScene()` 场景树（深15）→ cc 对象树（深12）→ window（深6）兜底；路径支持调用段 `getScene()`（`__r` resolve 统一用于过滤/回读，`_ec_assign_expr` 用于修改/锁定）
- 实测：命运挑战游戏（Cocos）搜20命中5处、搜0命中20+处，路径求值正确
- 按钮顺序：AI对话 在 游戏修改 左边
- v2.12.26 修复回顾：Windows拖动窗口时 Configure 的 e.x_root 为0 → 用 winfo 查询+150ms轮询兜底；进度文件挪到 %LOCALAPPDATA%\WebGrabber\progress

## v2.12.26 完善（游戏修改窗口：磁吸跟随修复 + 进度文件挪位）
- **磁吸跟随修复**：Windows 拖动窗口时 Tk `<Configure>` 的 e.x_root 为 0/无效 → 改用 `winfo_x()/winfo_y()` 实时查询坐标（Configure 事件触发时跟随）+ 150ms 轮询兜底（`_on_root_configure` + `_poll_game_snap`）
- **贴合状态**：`_ec_docked` 标志——点按钮贴边=True；拖走超过边缘100px=False（自由）；松手在100px内自动吸回
- **高度跟随主窗口**：`_snap_game_win` 高度=主窗口高度（min 300），宽度 320
- **进度文件挪位**：`scrapling_progress.json` → `%LOCALAPPDATA%\WebGrabber\progress\progress_{目录hash}.json`（用户经常清空保存目录，进度不能再放里面）
- 拖动小窗放大列宽自适应（`_on_game_win_configure` path列=宽-95）
- 按钮/窗口名去掉"EC"

## v2.12.25 完善（游戏修改：磁吸+窄窗+resize 自适应）
- **磁吸**：窗口贴主窗口右边缘无缝隙（`_snap_game_win` 320x470，x=rx+rw+0）；主窗口移动/缩放时跟随（`_on_root_configure`，只绑一次）
- **窄窗重排**：320px 宽，顶部两行（数值+首次/再次扫描 / 清除+命中数），底部（新值+修改/锁定/解锁）
- **独立拖动放大自适应**：窗口被拖走后放大，路径列宽跟随 `_on_game_win_resize`（path = 宽-95，最小120）
- **基地址说明**：路径持久化 = 网页版基地址。保存变量路径（window.a.b.c），页面刷新/重开网页结构不变则自动回读+恢复锁定（`_ai_ec_reload`）。随机变量名/动态数组下标的游戏需特征重定位（未做）

## v2.12.24 完善（游戏修改：贴合窗口 + 状态持久化 + 改名）
- **贴合窗口**：点「游戏修改」按钮 → 窗口贴合主窗口右侧显示；再点隐藏（withdraw 复用，`_toggle_game_mod_window` / `_snap_game_win`）
- **持久化**：扫描路径+锁定项保存到配置（ec_scan_paths/ec_lock），重开窗口自动回读路径当前值（`_ai_ec_reload`）并恢复锁定，**免重新搜索**；隐藏时锁定保持运行
- **改名**：按钮/窗口标题去掉"EC"，直接叫「游戏修改」「游戏数值修改」（用户嫌 EC 看不懂）
- 首次扫描/再次扫描/锁定/清除 都会同步保存配置

## v2.12.23 新功能（网页游戏修改：AI run_js + EC 模式）
- **需求**：内置浏览器打开网页游戏后，①AI 对话直接叫大模型改；②手动修改也要，EC（Cheat Engine）模式最好
- **AI 路**：新增工具 `[工具:run_js {"code":"..."}]` → CDP Runtime.evaluate 在活跃标签页执行 JS（返回值/异常描述，`_ai_execute_js`）；AI_TOOL_DESC 加工具+场景（改金币/血量/得分）
- **EC 路**：主界面 AI 操作行新增「游戏修改(EC)」按钮 → `_open_game_mod_window` 独立窗口：
  - 首次扫描（递归遍历 window 变量，深度≤6，匹配数值，最多1000命中/显示500）
  - 再次扫描（按上次命中路径重新取值过滤）
  - 双击/选中改值（`_ai_ec_edit`，路径赋值）
  - 锁定/解锁（`_ai_ec_lock`，setInterval 200ms 定时重写，关窗自动解锁）
- **限制**：只对纯前端逻辑的网页游戏有效；服务器校验/WebAssembly 混淆的改不了
- 结构：`_ai_ec_scan`(first/filter) / `_ai_ec_edit` / `_ai_ec_lock` + UI 方法 `_ec_*`

## v2.12.22 修复（Chrome 每次启动弹"要恢复页面吗"）
- **根因**：调试浏览器 Popen 启动后进程引用丢失，软件退出时只杀 AI 进程、没关调试浏览器 → 浏览器残留被判定"未正确关闭"，下次启动弹恢复气泡
- **修复1**：`_on_closing` 退出时用 PowerShell `CloseMainWindow()`（WM_CLOSE）优雅关闭 9222+debug_profile 的 chrome/msedge 进程 → 正常关闭标记，不再弹
- **修复2**：三处启动参数补 `--disable-features=InfiniteSessionRestore`（配合已有 --disable-session-crashed-bubble 双保险）

## v2.12.21 修复（最大化后无法还原）
- **现象**：点最大化后点还原/拖拽没反应（用户怀疑跑大模型时 UI 被拖住；也是 Tk 在 Windows 的已知问题）
- **修复**：绑定 `F11` 切换最大化/还原、`Esc` 强制恢复 900x740（`_toggle_maximize` / `_restore_window`，返回 'break' 阻断默认）
- 若真是推理满载导致 UI 卡顿：等推理结束/停 AI 服务即恢复

## v2.12.20 修复（截图对话的AI不会调用工具/改策略）
- **问题**：用户「截图给AI」→ 模型只会给通用教程（开发者工具/插件/截图裁剪），不会调用 start_crawl/ai_adjust_crawl 调整抓取策略
- **根因**：`_ai_vision_chat`（截图识别路径）只发 user 消息（文本+图片），**没带 system 工具提示**，模型不知道自己是爬虫助手、不知道有工具
- **修复1**：`_ai_vision_chat` 加 system 消息（AI_TOOL_DESC + 截图说明），并接入工具调用循环（解析[工具:]→执行→[工具结果]→再请求，最多5轮）
- **修复2**：AI_TOOL_DESC 规则6：明确"下载/抓取/下大图"= 软件抓图请求，直接调 start_crawl/ai_adjust_crawl；禁止教外部方法

## v2.12.19 修复（手动清理没效果）
- **问题**：设置窗口点「清理」无反应——手动清理复用了 `_clean_screenshots(200)`，少于200张直接 return
- **修复**：`_clear_screenshots_manual` 改为**全部清空**（自动保留200张是防累积，手动按钮直接清空），日志提示删除张数
- 注：v2.12.18 发布时 exe 上传中断（assets=0），v2.12.18 未补传，功能由 v2.12.19 覆盖

## v2.12.18 修复（设置窗口三处）
- **删除底部「关闭」按钮**：与右上角 X 同走 `_close_settings`，冗余，只留 X
- **修「临时截图」地址不显示**：`shot_var` 局部变量被 GC → Entry 空白；改为实例变量 `self.shot_dir_var`
- **浏览初始目录**：保存目录/AI模型/服务程序 三个 `filedialog` 均加 `initialdir`（定位到当前值所在位置）
- **硬件信息**：台式机 RTX 4070 SUPER 12G；`L:\llama\models\` 有 Gemma-4-12B Q4_0+mmproj-F16（适合12G）与 Qwen3.6-35B-A3B（需18-20G，跑不动）。用户经验：Gemma 内存占用/速度优于千问。**模型配置未改动**（用户仅询问）

## v2.12.17 修复（设置窗口「临时截图」重复两行）
- **问题**：v2.12.16 设置窗口出现两行「临时截图」——我新增的 r2 与源码遗留的 r1b 残代码重复
- **根因**：r1b 是早期遗留 UI，引用的 `_open_shot_dir`/`_clean_shots_now` 方法根本不存在（点按钮会报错），且未在 v2.12.16 检查时发现
- **修复**：删除 r1b 残代码，保留完整实现的 r2（路径只读显示 + 打开 + 清理，方法 `_open_screenshots_dir`/`_clear_screenshots_manual`）
- **教训**：改 UI 前先 grep 目标控件是否已存在；v2.12.16 已带 bug 发布，用 v2.12.17 覆盖

## v2.12.16 调整（设置窗口：截图路径+打开+清理；修复对话上下文看不见）
- **需求**：设置里加临时截图路径显示+打开+清理按钮；「对话上下文(条)」被挤出窗口看不见
- **设置窗口重排**：宽 640→780、高 320→400；「服务程序」行拆出第二行（端口+对话上下文），不再超宽
- **常规区新增「临时截图」行**：路径只读显示（%LOCALAPPDATA%\WebGrabber\screenshots）+ 「打开」按钮（os.startfile 打开目录）+ 「清理」按钮（手动触发保留200张清理）
- **新增**：`_open_screenshots_dir()`、`_clear_screenshots_manual()`（清理前后计数并写日志）

## v2.12.15 新功能（截图目录自动清理）
- **需求**：截图保存（chat_*/view_*.jpg）会无限累积变大
- **新增**：`_clean_screenshots(max_keep=200)` —— 截图目录只保留最近 200 张，超出按修改时间删最旧
- **接入**：`_ai_capture_shot`（截图给AI）与 `_ai_browser_view`（get_browser_view）保存后自动调用
- 清理时运行日志提示"截图目录已自动清理: 保留最近 200 张，删除 X 张旧截图"

## v2.12.14 新功能（AI 工具 ai_adjust_crawl：看图调整抓取策略）
- **需求**：页面明明有图但抓取不到——用户只需说"帮我调整抓取策略"，AI 自动看图并调整
- **新增工具**：`ai_adjust_crawl {"url":可选}`（已注册 AI_TOOL_DESC + _ai_execute_tool）
- **执行链**：取浏览器当前页HTML → 初始提取 → `_ai_analyze_page_strategy`（截图+DOM线索→视觉模型→JSON策略）→ 按策略滚动N轮触发懒加载 → 重新提取 → 返回"调整前X张→调整后Y张"
- **目标URL优先浏览器当前活跃标签**（避免模型传入 example.com 假URL）
- **实测**：用户说"这个页面明明有图但抓取不到，帮我调整抓取策略" → 模型 3.7s 正确调用 ai_adjust_crawl
- **用法**：AI对话页签直接发"这个页面有图但抓不到，帮我调整抓取策略"即可，无需手动截图

## v2.12.13 新功能（AI对话页签「截图给AI」）
- **需求**：AI 对话页签里截图给 AI 识别并对话（让 AI 看到用户看到的页面）
- **新增**：`_ai_capture_shot`（CDP截图→JPEG压缩→保存）+ `_ai_add_shot`（按钮回调，截图加入待发送）+ `_ai_vision_chat`（text+image 一次视觉对话，结果进历史便于追问）；`_ai_chat_send` 支持带图发送
- **UI**：AI对话输入框左侧新增「截图给AI」按钮；`self._ai_pending_image` 存待发送截图，发送后清空
- **实测通过**：xchina photo 页截图(1024x503, 52KB) → 模型 42s 输出详细页面描述（双图布局/人物/水印/界面元素）
- **用法**：AI对话页签 → 点「截图给AI」（日志显示已添加截图）→ 输入问题 → 发送 → 模型看图回答；识别结果进入历史可继续文本追问

## v2.12.12 新功能（AI 看图调整抓取策略）
- **需求**：浏览器打开页面正常显示，但规则提取不到/太少图片——让 AI 看图判断加载方式并自动调整
- **新增**：`_ai_analyze_page_strategy`（截图当前页 + DOM图片线索 → 视觉模型 → JSON策略：has_images/strategy/scroll_times/note）+ `_scroll_debug_browser`（CDP滚动N轮）+ `_fetch_current_tab_html` + `_collect_image_clues` + `_ai_adjust_extract`（执行策略重新提取）
- **接入**：单页模式提取 <3 张且 AI 服务运行中 → 自动启动 AI 看图 → 按策略滚动/重新提取
- **实测通过**：xchina photo 页 DOM 线索 20img+20背景+30懒加载 → 模型输出 {"has_images":true,"strategy":"scroll","scroll_times":5} 耗时 18.9s
- **全站模式**：已有文本规律分析（_ai_analyze_patterns + 缓存），两种 AI 路径互补

## v2.12.11 修复（浏览器模式抓取触发 CF 1005 封禁）
- **现象**：内置浏览器手动打开 xchina 正常，点抓取就 Cloudflare Error 1005（ASN 36352 被封 = 用户全局代理机房出口）
- **根因**：CDP 抓取用 Target.createTarget 新建标签页 → 立即 Page.navigate → 快速滚动 → bot 特征明显 → CF 判定自动化 → ASN 级封禁，连原标签页也 1005
- **修复**：`_fetch_page` CDP 分支**优先复用已打开的现有标签页**——URL 完全匹配则不导航（页面已在内存，直接滚动+取 DOM，完全绕开封禁）；同域标签则在该标签内导航（保留会话）；找不到才走原新建逻辑。加 `_cdp_fetch_lock` 串行化多线程取页；复用标签不关闭用户标签页
- **实测通过**：复用 xchina 标签 HTML 457KB 无 CF 错误，50 张图
- **注意**：若用户重启浏览器后 ASN 仍被封（打开页面本身就 1005），复用无效，需换代理/等解封

## v2.12.10 修复（内嵌浏览器图标缺失——v2.2.6 方案移植，用户指路）
- 用户翻出 v2.2.6 时代同问题解决记录：**极小尺寸强制重排 → 连续调整10次 → 第5次后枚举所有子窗口同步调整**
- 之前漏的关键：**Chrome 内层渲染子窗口**（EnumChildWindows）——只 MoveWindow 主窗口，内层窗口不更新
- **修复**：新增 `_aggressive_resize()`：先缩到 1/3 极小尺寸强制重排 → 连续 10 次调整到目标尺寸 → 第 5 次起 EnumChildWindows 所有子窗口同步 MoveWindow
- 时序：三次抖动 150/600/1800ms → 隐藏-显示 2500ms → 激进重排 3000ms → CDP 刷新 4000ms

## v2.12.9 修复（内嵌浏览器图标缺失——隐藏-显示强制重绘）
- v2.12.8 无效原因：抖动恢复原尺寸 = 回到"坏状态"；用户拖动是**停在新的尺寸**才保持正常
- **修复**：嵌入后 2.5 秒执行 ShowWindow(SW_HIDE) → 400ms 后 SW_SHOW —— Windows 级强制全量重绘，与尺寸无关，等效且强于拖动
- 抖动改为缩小 120px + 间隔 500ms（慢速真实变化，避免被 Chrome 合并忽略）
- 时序：150/600/1800ms 三次抖动 → 2500ms 隐藏-显示强制重绘 → 3500ms CDP 刷新
- 若仍无效 = Chrome 151 嵌入渲染硬 bug，需换架构（CDP 截图轮询显示）

## v2.12.8 修复（内嵌浏览器图标缺失——组合拳，仍无效）
- v2.12.7 抖动无效原因：-1px 立即恢复，两个 MoveWindow 连发，Chrome 视为"尺寸未变"忽略（用户手动拖动是持续真实尺寸变化才触发重排）
- **修复①**：抖动改为"缩小60px → 延迟120ms → 恢复"，真实尺寸变化等效拖动
- **修复②**：嵌入后 2.5 秒用 CDP 自动 `Page.reload` 刷新页面一次，强制全量重绘（favicon/快捷方式必出）
- 3 次抖动（150/600/1800ms）+ 1 次刷新，启动即自动完成，无需手动拖

## v2.12.7 修复（内嵌浏览器图标缺失——自动重排，未完全解决）
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
