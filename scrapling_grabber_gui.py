# -*- coding: utf-8 -*-
"""Scrapling 图片爬虫 - GUI 版本"""
import os
import sys
import time
import threading
import urllib.parse
import urllib.request
import ssl
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用 SSL 验证
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 浏览器请求头
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}

# 图片扩展名
IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.avif')

APP_VERSION = 'v2.8.6'

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.expanduser('~'), '.scrapling_grabber_config.json')


def load_config():
    """加载配置文件"""
    try:
        import json
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    """保存配置文件"""
    try:
        import json
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def safe_filename(name):
    """生成安全的文件名"""
    import re
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name[:80] if name else 'untitled'


def download_image(url, save_path, timeout=15):
    """下载单张图片"""
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            data = resp.read()
        with open(save_path, 'wb') as f:
            f.write(data)
        return len(data)
    except Exception as e:
        return None


class ScraplingGrabberGUI:
    """Scrapling 图片爬虫 GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title('Scrapling 图片爬虫 %s' % APP_VERSION)
        self.root.geometry('900x650')
        self.root.minsize(800, 550)

        self.is_running = False
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()  # 暂停标志
        self.cfg = load_config()

        self._create_widgets()
        self._load_settings()
        # 窗口关闭时保存设置
        self.root.protocol('WM_DELETE_WINDOW', self._on_closing)
        # 显示内核版本信息
        self._log('Scrapling 图片爬虫 %s' % APP_VERSION)
        self._log('Python 版本: %s' % sys.version.split()[0])
        try:
            import scrapling
            self._log('Scrapling 版本: %s' % getattr(scrapling, '__version__', '未知'))
        except Exception:
            self._log('Scrapling 版本: 未安装')

    def _load_url_history(self):
        """加载网址历史记录"""
        try:
            history = self.cfg.get('url_history', [])
            self.url_combo['values'] = history
        except Exception:
            pass

    def _save_url_history(self, url):
        """保存网址历史记录"""
        try:
            history = self.cfg.get('url_history', [])
            if url in history:
                history.remove(url)
            history.insert(0, url)
            history = history[:20]  # 最多保存20条
            self.cfg['url_history'] = history
            self.url_combo['values'] = history
            save_config(self.cfg)
        except Exception:
            pass

    def _load_settings(self):
        """从配置文件恢复上次的设置"""
        self.url_var.set(self.cfg.get('url', ''))
        default_dir = os.path.join(os.getcwd(), 'downloads')
        self.dir_var.set(self.cfg.get('save_dir') or default_dir)
        self.threads_var.set(self.cfg.get('threads', 8))
        self.timeout_var.set(self.cfg.get('timeout', 15))
        self.smart_filter_var.set(self.cfg.get('smart_filter', True))
        self.download_video_var.set(self.cfg.get('download_video', False))
        self.render_mode_var.set(self.cfg.get('render_mode', '直连模式'))
        self.grab_mode_var.set(self.cfg.get('grab_mode', '单页'))
        self.post_range_var.set(self.cfg.get('post_range', '20'))
        self.min_size_var.set(self.cfg.get('min_size', 0))

    def _save_settings(self):
        """保存当前设置到配置文件"""
        self.cfg.update({
            'url': self.url_var.get().strip(),
            'save_dir': self.dir_var.get().strip(),
            'threads': self.threads_var.get(),
            'timeout': self.timeout_var.get(),
            'smart_filter': self.smart_filter_var.get(),
            'download_video': self.download_video_var.get(),
            'render_mode': self.render_mode_var.get(),
            'grab_mode': self.grab_mode_var.get(),
            'post_range': self.post_range_var.get(),
            'min_size': self.min_size_var.get(),
        })
        save_config(self.cfg)

    def _on_closing(self):
        """窗口关闭时保存设置"""
        self._save_settings()
        self.root.destroy()

    def _create_widgets(self):
        """创建界面控件（按照web-grabber布局）"""
        # 主容器
        main_container = ttk.Frame(self.root)
        main_container.pack(fill='both', expand=True, padx=5, pady=5)

        # 顶部设置区域
        top_frame = ttk.Frame(main_container)
        top_frame.pack(fill='x', pady=(0, 5))

        # 底部内容区域（任务列表/日志/浏览器 三个页签）
        self.content_notebook = ttk.Notebook(main_container)
        self.content_notebook.pack(fill='both', expand=True)

        # 任务列表页签
        task_tab = ttk.Frame(self.content_notebook)
        self.content_notebook.add(task_tab, text='任务列表')

        # 运行日志页签
        log_tab = ttk.Frame(self.content_notebook)
        self.content_notebook.add(log_tab, text='运行日志')

        # 浏览器页签
        self.browser_frame = ttk.Frame(self.content_notebook)
        self.content_notebook.add(self.browser_frame, text='浏览器')
        self.browser_host = None
        self.browser_hwnd = None
        # 浏览器提示标签
        self.browser_hint = ttk.Label(self.browser_frame, text='点击「启动调试浏览器」按钮，浏览器将自动嵌入到这里', font=('Arial', 12))
        self.browser_hint.pack(expand=True)

        # ===== 顶部设置区域 =====
        # top_frame已经在上面定义了

        # 网址（带历史记录）
        url_frame = ttk.Frame(top_frame)
        url_frame.pack(fill='x', pady=1)
        ttk.Label(url_frame, text='网址:', width=6).pack(side='left')
        self.url_var = tk.StringVar()
        self.url_combo = ttk.Combobox(url_frame, textvariable=self.url_var, height=5, width=60)
        self.url_combo.pack(side='left', padx=3)
        # 收藏按钮
        ttk.Button(url_frame, text='收藏', command=self._favorite_url, width=6).pack(side='left', padx=3)
        self._load_url_history()

        # 保存目录
        dir_frame = ttk.Frame(top_frame)
        dir_frame.pack(fill='x', pady=1)
        ttk.Label(dir_frame, text='保存到:', width=6).pack(side='left')
        self.dir_var = tk.StringVar(value=os.path.join(os.getcwd(), 'downloads'))
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=60).pack(side='left', padx=3)
        ttk.Button(dir_frame, text='浏览', command=self._browse_dir, width=6).pack(side='left', padx=3)

        self.smart_filter_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dir_frame, text='智能过滤', variable=self.smart_filter_var).pack(side='left', padx=5)
        # 下载视频开关
        self.download_video_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dir_frame, text='下载视频', variable=self.download_video_var).pack(side='left', padx=5)

        self.incremental_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dir_frame, text='增量扫描', variable=self.incremental_var).pack(side='left', padx=5)

        self.force_rescan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dir_frame, text='强制重扫', variable=self.force_rescan_var).pack(side='left', padx=5)

        # 选项行
        opt_frame = ttk.Frame(top_frame)
        opt_frame.pack(fill='x', pady=2)

        ttk.Label(opt_frame, text='模式:').pack(side='left')
        self.grab_mode_var = tk.StringVar(value='单页')
        mode_combo = ttk.Combobox(opt_frame, textvariable=self.grab_mode_var, width=6, state='readonly')
        mode_combo['values'] = ('单页', '全站')
        mode_combo.pack(side='left', padx=(2, 10))

        ttk.Label(opt_frame, text='范围:').pack(side='left')
        self.post_range_var = tk.StringVar(value='20')
        ttk.Entry(opt_frame, textvariable=self.post_range_var, width=6).pack(side='left', padx=(2, 10))
        ttk.Label(opt_frame, text='页码(0=全部):').pack(side='left')
        self.page_num_var = tk.StringVar(value='0')
        ttk.Entry(opt_frame, textvariable=self.page_num_var, width=4).pack(side='left', padx=(2, 10))
        # （已去掉页码输入框）

        ttk.Label(opt_frame, text='最小图(KB):').pack(side='left')
        self.min_size_var = tk.IntVar(value=0)
        ttk.Spinbox(opt_frame, from_=0, to=10000, textvariable=self.min_size_var, width=5).pack(side='left', padx=(2, 10))

        ttk.Label(opt_frame, text='线程:').pack(side='left')
        self.threads_var = tk.IntVar(value=8)
        ttk.Spinbox(opt_frame, from_=1, to=32, textvariable=self.threads_var, width=4).pack(side='left', padx=(2, 10))

        ttk.Label(opt_frame, text='超时:').pack(side='left')
        self.timeout_var = tk.IntVar(value=15)
        ttk.Spinbox(opt_frame, from_=5, to=60, textvariable=self.timeout_var, width=4).pack(side='left', padx=(2, 10))

        ttk.Label(opt_frame, text='抓取:').pack(side='left')
        self.render_mode_var = tk.StringVar(value='直连模式')
        render_combo = ttk.Combobox(opt_frame, textvariable=self.render_mode_var, width=12, state='readonly')
        render_combo['values'] = ('直连模式', '浏览器渲染', '浏览器模式(CDP)')
        render_combo.pack(side='left', padx=(2, 10))

        # （智能过滤、增量扫描、强制重扫已移到保存目录行）

        # 按钮行
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill='x', pady=2)
        self.start_btn = ttk.Button(btn_frame, text='开始抓取', command=self._start_crawl)
        self.start_btn.pack(side='left', padx=3)
        self.pause_btn = ttk.Button(btn_frame, text='暂停', command=self._toggle_pause, state='disabled')
        self.pause_btn.pack(side='left', padx=3)
        self.stop_btn = ttk.Button(btn_frame, text='停止', command=self._stop_crawl, state='disabled')
        self.stop_btn.pack(side='left', padx=3)
        self.retry_btn = ttk.Button(btn_frame, text='重试失败', command=self._retry_failed, state='disabled')
        self.retry_btn.pack(side='left', padx=3)
        self.browser_mode_var = tk.BooleanVar(value=False)
        def _on_browser_mode_change():
            if self.browser_mode_var.get():
                self.render_mode_var.set('浏览器模式(CDP)')
            else:
                self.render_mode_var.set('直连模式')
        browser_check = ttk.Checkbutton(btn_frame, text='浏览器模式', variable=self.browser_mode_var, command=_on_browser_mode_change)
        browser_check.pack(side='left', padx=3)
        ttk.Label(btn_frame, text='浏览器:').pack(side='left', padx=(10, 2))
        self.browser_choice_var = tk.StringVar(value='Chrome')
        browser_combo = ttk.Combobox(btn_frame, textvariable=self.browser_choice_var, width=6, state='readonly')
        browser_combo['values'] = ('Chrome', 'Edge')
        browser_combo.pack(side='left', padx=2)
        self.browser_btn = ttk.Button(btn_frame, text='启动调试浏览器', command=self._launch_debug_browser)
        self.browser_btn.pack(side='left', padx=3)
        self.independent_btn = ttk.Button(btn_frame, text='独立窗口打开(登录/装插件)', command=self._open_independent_browser)
        self.independent_btn.pack(side='left', padx=3)

        # ===== 任务列表区域 =====
        task_frame = ttk.Frame(task_tab)
        task_frame.pack(fill='both', expand=True, padx=5, pady=5)

        # 任务列表表格
        tree_frame = ttk.Frame(task_frame)
        tree_frame.pack(fill='both', expand=True)
        cols = ('no', 'title', 'progress', 'speed', 'status', 'save_dir', 'url')
        self.task_tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=6)
        self.task_tree.heading('no', text='序号')
        # 序号列点击排序
        self._no_sort_state = 0  # 0=默认, 1=升序, 2=降序
        def sort_by_no():
            items = [(self.task_tree.set(item, 'no'), item) for item in self.task_tree.get_children('')]
            if self._no_sort_state == 0:
                # 升序
                items.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 0)
                self._no_sort_state = 1
            elif self._no_sort_state == 1:
                # 降序
                items.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 0, reverse=True)
                self._no_sort_state = 2
            else:
                # 恢复默认
                self._no_sort_state = 0
            for idx, (_, item) in enumerate(items):
                self.task_tree.move(item, '', idx)
        self.task_tree.heading('no', command=sort_by_no)
        self.task_tree.heading('title', text='帖子标题')
        self.task_tree.heading('progress', text='进度')
        self.task_tree.heading('speed', text='速度')
        self.task_tree.heading('status', text='状态')
        # 状态列点击排序
        self._sort_state = 0  # 0=默认, 1=未完成在前, 2=完成在前
        def sort_by_status():
            items = [(self.task_tree.set(item, 'status'), item) for item in self.task_tree.get_children('')]
            if self._sort_state == 0:
                # 未完成在前
                order = {'等待': 0, '抓取中': 1, '下载中': 2, '部分失败': 3, '失败': 4, '完成': 5}
                items.sort(key=lambda x: order.get(x[0], 99))
                self._sort_state = 1
            elif self._sort_state == 1:
                # 完成在前
                order = {'完成': 0, '部分失败': 1, '失败': 2, '下载中': 3, '抓取中': 4, '等待': 5}
                items.sort(key=lambda x: order.get(x[0], 99))
                self._sort_state = 2
            else:
                # 恢复默认（按序号）
                items.sort(key=lambda x: int(self.task_tree.set(x[1], 'no')) if self.task_tree.set(x[1], 'no').isdigit() else 0)
                self._sort_state = 0
            for idx, (_, item) in enumerate(items):
                self.task_tree.move(item, '', idx)
        self.task_tree.heading('status', command=sort_by_status)
        self.task_tree.column('no', width=35, anchor='center')
        self.task_tree.column('title', width=500, anchor='w')
        self.task_tree.column('progress', width=70, anchor='center')
        self.task_tree.column('speed', width=70, anchor='center')
        self.task_tree.column('status', width=70, anchor='center')
        self.task_tree.heading('save_dir', text='保存目录')
        self.task_tree.column('save_dir', width=0, stretch=False)  # 隐藏列
        self.task_tree.heading('url', text='帖子URL')
        self.task_tree.column('url', width=0, stretch=False)  # 隐藏列
        task_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=task_scroll.set)
        self.task_tree.pack(side='left', fill='both', expand=True)
        task_scroll.pack(side='right', fill='y')

        # 任务列表右键菜单
        self.task_context_menu = tk.Menu(self.task_tree, tearoff=0)
        self.task_context_menu.add_command(label='打开帖子链接', command=self._open_selected_post)
        self.task_context_menu.add_command(label='复制帖子链接', command=self._copy_selected_post_url)
        self.task_context_menu.add_command(label='打开保存目录', command=self._open_save_dir)
        self.task_context_menu.add_separator()
        self.task_context_menu.add_command(label='重试此任务', command=self._retry_selected_task)
        self.task_tree.bind('<Button-3>', self._show_task_context_menu)

        # 底部翻页和统计信息
        bottom_frame = ttk.Frame(task_frame)
        bottom_frame.pack(fill='x', pady=(3, 0))

        # 左侧统计信息
        self.task_stat_var = tk.StringVar(value='共0个 | 成功0 | 失败0 | 等待0 | 下载中0 | 总速度: 0 KB/s')
        ttk.Label(bottom_frame, textvariable=self.task_stat_var).pack(side='left', padx=5)
        # 用时显示
        self.timer_var = tk.StringVar(value='用时: 00:00')
        ttk.Label(bottom_frame, textvariable=self.timer_var).pack(side='left', padx=10)
        # 全局统计
        # 中间占位（让翻页控件往中间移动）
        ttk.Frame(bottom_frame, width=100).pack(side='right')

        # （已去掉分页控件，直接显示所有任务）

        # ===== 日志区域 =====
        log_frame = ttk.Frame(log_tab)
        log_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, wrap='word')
        self.log_text.pack(side='left', fill='both', expand=True)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side='right', fill='y')
        self.log_text.config(yscrollcommand=log_scroll.set)

        # （已去掉右下角的进度条和状态显示，但保留变量定义供代码引用）
        self.progress_var = tk.DoubleVar(value=0)
        self.stat_var = tk.StringVar(value='就绪')
        self.speed_var = tk.StringVar(value='')

    def _refresh_task_list(self):
        """刷新任务列表显示（直接显示所有任务）"""
        # 清空当前显示
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)

        # 显示所有任务
        for task in self.all_tasks:
            self.task_tree.insert('', 'end', values=task)

    def _show_task_context_menu(self, event):
        """显示任务列表右键菜单"""
        item = self.task_tree.identify_row(event.y)
        if item:
            self.task_tree.selection_set(item)
            self.task_context_menu.post(event.x_root, event.y_root)

    def _open_selected_post(self):
        """打开选中的帖子链接"""
        selected = self.task_tree.selection()
        if selected:
            values = self.task_tree.item(selected[0], 'values')
            # 优先从隐藏的url列（索引6）获取URL，如果没有则从第二列（索引1）获取
            url = ''
            if len(values) > 6 and values[6]:
                url = values[6]
            elif len(values) > 1 and values[1]:
                url = values[1]
            if url:
                import webbrowser
                webbrowser.open(url)

    def _copy_selected_post_url(self):
        """复制选中的帖子链接"""
        selected = self.task_tree.selection()
        if selected:
            values = self.task_tree.item(selected[0], 'values')
            # 优先从隐藏的url列（索引6）获取URL，如果没有则从第二列（索引1）获取
            url = ''
            if len(values) > 6 and values[6]:
                url = values[6]
            elif len(values) > 1 and values[1]:
                url = values[1]
            if url:
                self.clipboard_clear()
                self.clipboard_append(url)
                self._log('已复制帖子链接: %s' % url)

    def _open_save_dir(self):
        """打开保存目录"""
        import os
        # 优先使用当前选中任务的保存目录
        selected = self.task_tree.selection()
        if selected:
            item = selected[0]
            vals = self.task_tree.item(item, 'values')
            if len(vals) > 5 and vals[5] and os.path.exists(vals[5]):
                os.startfile(vals[5])
                return
        # 如果没有选中任务或任务保存目录不存在，使用全局保存目录
        save_dir = self.dir_var.get().strip()
        if save_dir and os.path.exists(save_dir):
            os.startfile(save_dir)
        else:
            self._log('保存目录不存在: %s' % save_dir)

    def _get_progress_file(self, save_dir):
        """获取进度文件路径"""
        import os
        return os.path.join(save_dir, 'scrapling_progress.json')

    def _load_progress(self, save_dir):
        """加载抓取进度，返回已完成的帖子URL集合"""
        import os
        import json
        progress_file = self._get_progress_file(save_dir)
        if not os.path.exists(progress_file):
            return set()
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            completed_urls = set(data.get('completed_urls', []))
            self._log('加载进度: 已完成 %d 个帖子' % len(completed_urls))
            return completed_urls
        except Exception as e:
            self._log('加载进度失败: %s' % e)
            return set()

    def _save_progress(self, save_dir, completed_urls):
        """保存抓取进度"""
        import os
        import json
        import time
        progress_file = self._get_progress_file(save_dir)
        try:
            os.makedirs(save_dir, exist_ok=True)
            data = {
                'completed_urls': list(completed_urls),
                'total': len(completed_urls),
                'last_update': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log('保存进度失败: %s' % e)

    def _mark_post_completed(self, save_dir, post_url, completed_urls):
        """标记一个帖子为已完成，并保存进度"""
        completed_urls.add(post_url)
        # 每完成10个帖子保存一次进度，避免频繁IO
        if len(completed_urls) % 10 == 0:
            self._save_progress(save_dir, completed_urls)

    def _retry_selected_task(self):
        """重试选中的任务"""
        selected = self.task_tree.selection()
        if selected:
            values = self.task_tree.item(selected[0], 'values')
            if len(values) > 1 and values[1]:
                self._log('重试任务: %s' % values[1])

    def _update_task_stat(self):
        """更新任务统计信息"""
        # 直接从任务列表统计，不需要维护self.all_tasks
        total = 0
        success = 0
        fail = 0
        waiting = 0
        downloading = 0
        total_speed = 0.0
        for item in self.task_tree.get_children():
            vals = self.task_tree.item(item, 'values')
            if len(vals) > 4:
                total += 1
                status = vals[4]
                if status in ('完成', '成功'):
                    success += 1
                elif status in ('失败', '部分失败'):
                    fail += 1
                elif status == '等待':
                    waiting += 1
                elif '下载中' in status or '抓取中' in status:
                    downloading += 1
                    # 只计算当前正在下载的任务的速度
                    if len(vals) > 3 and vals[3]:
                        speed_str = str(vals[3])
                        try:
                            if 'KB/s' in speed_str:
                                speed_val = float(speed_str.replace('KB/s', '').strip())
                                total_speed += speed_val
                            elif 'MB/s' in speed_str:
                                speed_val = float(speed_str.replace('MB/s', '').strip())
                                total_speed += speed_val * 1024
                        except (ValueError, AttributeError):
                            pass
        # 格式化总速度
        if total_speed >= 1024:
            total_speed_str = '%.1f MB/s' % (total_speed / 1024)
        else:
            total_speed_str = '%.0f KB/s' % total_speed
        self.task_stat_var.set('共%d个 | 成功%d | 失败%d | 等待%d | 下载中%d | 总速度: %s' % (total, success, fail, waiting, downloading, total_speed_str))

    def _open_independent_browser(self):
        """独立窗口打开浏览器（用于登录/装插件）"""
        import subprocess
        import os

        # 先清理残留进程，确保9222端口能正常监听
        self._kill_stale_debug_browser()
        import time
        time.sleep(1)

        user_data_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'debug_profile')
        os.makedirs(user_data_dir, exist_ok=True)

        # 尝试启动Chrome
        chrome_paths = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]

        for chrome_path in chrome_paths:
            if os.path.exists(chrome_path):
                subprocess.Popen([
                    chrome_path,
                    '--remote-debugging-port=9222',
                    '--remote-allow-origins=*',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--user-data-dir=' + user_data_dir,
                ])
                self._log('已独立窗口启动 Chrome（9222端口），可登录/装插件')
                return

        # 尝试启动Edge
        edge_paths = [
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        ]

        for edge_path in edge_paths:
            if os.path.exists(edge_path):
                subprocess.Popen([
                    edge_path,
                    '--remote-debugging-port=9222',
                    '--remote-allow-origins=*',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--user-data-dir=' + user_data_dir,
                ])
                self._log('已独立窗口启动 Edge（9222端口），可登录/装插件')
                return

        self._log('未找到 Chrome 或 Edge 浏览器')

    def _favorite_url(self):
        """收藏当前网址"""
        url = self.url_var.get().strip()
        if not url:
            self._log('请先输入网址')
            return
        # 保存到收藏列表
        if 'favorites' not in self.cfg:
            self.cfg['favorites'] = []
        if url not in self.cfg['favorites']:
            self.cfg['favorites'].append(url)
            save_config(self.cfg)
            self._log('已收藏: %s' % url)
            # 更新下拉列表
            self._update_url_combo()
        else:
            self._log('该网址已收藏')

    def _update_url_combo(self):
        """更新网址下拉列表"""
        history = self.cfg.get('url_history', [])
        favorites = self.cfg.get('favorites', [])
        # 收藏的网址放在最前面，标记★
        all_urls = ['★ ' + u for u in favorites] + [u for u in history if u not in favorites]
        self.url_combo['values'] = all_urls

    def _browse_dir(self):
        """浏览保存目录"""
        directory = filedialog.askdirectory(title='选择保存目录')
        if directory:
            self.dir_var.set(directory)

    def _log(self, msg):
        """输出日志"""
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.insert('end', '[%s] %s\n' % (timestamp, msg))
        self.log_text.see('end')
        self.root.update_idletasks()

    def _start_crawl(self):
        """开始抓取"""
        # 清空任务列表
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        # 禁用重试失败按钮
        if hasattr(self, 'retry_btn'):
            self.retry_btn.config(state='disabled')
        # 更新任务统计
        self._update_task_stat()
        try:
            url = self.url_var.get().strip()
            if url:
                self._save_url_history(url)
            save_dir = self.dir_var.get().strip()

            if not url:
                messagebox.showwarning('提示', '请输入网址')
                return
            if not save_dir:
                messagebox.showwarning('提示', '请选择保存目录')
                return

            # 保存设置
            self._save_settings()

            # 如果勾选了浏览器模式，确保抓取模式是CDP
            if self.browser_mode_var.get():
                self.render_mode_var.set('浏览器模式(CDP)')
            # CDP模式下自动检测并启动调试浏览器（无论通过复选框还是下拉框选择）
            if self.render_mode_var.get() == '浏览器模式(CDP)':
                if not self._is_debug_browser_running():
                    self._log('未检测到调试浏览器，正在自动启动...')
                    self._launch_debug_browser()
                    # 等待浏览器启动
                    import time
                    for i in range(10):
                        time.sleep(1)
                        if self._is_debug_browser_running():
                            self._log('调试浏览器启动成功')
                            break
                    else:
                        self._log('警告：调试浏览器启动超时，请手动点"启动调试浏览器"按钮')

            self.is_running = True
            self.stop_flag.clear()
            self.start_btn.config(state='disabled')
            self.pause_btn.config(state='normal', text='暂停')
            self.stop_btn.config(state='normal')
            self.pause_flag.clear()  # 清除暂停标志
            self.log_text.delete('1.0', 'end')
            self._log('开始抓取...')

            thread = threading.Thread(target=self._crawl_worker, args=(url, save_dir), daemon=True)
            thread.start()
        except Exception as e:
            import traceback
            self._log('启动失败: %s' % e)
            self._log('详细错误: %s' % traceback.format_exc())
            self._finish_crawl()

    def _toggle_pause(self):
        """切换暂停/继续状态"""
        if self.pause_flag.is_set():
            self.pause_flag.clear()
            self.pause_btn.config(text='暂停')
            self._log('继续下载...')
        else:
            self.pause_flag.set()
            self.pause_btn.config(text='继续')
            self._log('已暂停，点击继续恢复下载...')

    def _stop_crawl(self):
        """停止抓取"""
        self.stop_flag.set()
        self.pause_flag.clear()  # 清除暂停标志
        self._log('已请求停止，正在取消下载任务...')
        # 取消线程池中未开始的任务
        if hasattr(self, '_dl_executor') and self._dl_executor:
            self._dl_executor.shutdown(wait=False, cancel_futures=True)
        self.stop_btn.config(state='disabled')
        if hasattr(self, 'pause_btn'):
            self.pause_btn.config(state='disabled', text='暂停')
        # 停止后启用重试失败按钮
        if hasattr(self, 'retry_btn'):
            self.retry_btn.config(state='normal')
        # 启用开始按钮
        if hasattr(self, 'start_btn'):
            self.start_btn.config(state='normal')

    def _fetch_page(self, url, timeout=15):
        """抓取网页，支持直连、浏览器渲染、CDP浏览器模式，返回 (html, page)"""
        render_mode = self.render_mode_var.get()
        html = ''
        if render_mode == '浏览器模式(CDP)':
            # CDP浏览器模式：连接调试浏览器（9222端口），自动启动，导航到URL后获取HTML
            import requests
            import json
            import time
            # 自动检测并启动调试浏览器
            if not self._is_debug_browser_running():
                self._log('未检测到调试浏览器（9222端口），正在自动启动...')
                self._launch_debug_browser()
                # 等待浏览器启动（最多12秒）
                for _i in range(12):
                    time.sleep(1)
                    if self._is_debug_browser_running():
                        self._log('调试浏览器已就绪')
                        break
                else:
                    raise Exception('调试浏览器启动超时，请手动点击"启动调试浏览器"按钮后重试')
            try:
                import websocket
                # 获取浏览器级调试连接（用于创建/关闭标签页）
                ver_resp = requests.get('http://127.0.0.1:9222/json/version', timeout=5)
                browser_ws_url = ver_resp.json().get('webSocketDebuggerUrl')
                if not browser_ws_url:
                    raise Exception('无法获取浏览器调试地址')

                # 创建独立标签页（避免多线程共用标签页互相干扰）
                bws = websocket.create_connection(browser_ws_url, timeout=15)

                def _send_browser_cmd(cmd_id, method, params=None):
                    cmd = {'id': cmd_id, 'method': method}
                    if params:
                        cmd['params'] = params
                    bws.send(json.dumps(cmd))
                    while True:
                        msg = json.loads(bws.recv())
                        if msg.get('id') == cmd_id:
                            return msg

                target_res = _send_browser_cmd(1, 'Target.createTarget', {'url': 'about:blank'})
                target_id = target_res.get('result', {}).get('targetId', '')
                if not target_id:
                    bws.close()
                    raise Exception('创建独立标签页失败')

                # 从标签页列表中找到新标签页的调试地址
                tab_ws_url = None
                for _try in range(20):
                    try:
                        tabs = requests.get('http://127.0.0.1:9222/json', timeout=5).json()
                        for t in tabs:
                            if t.get('id') == target_id and t.get('webSocketDebuggerUrl'):
                                tab_ws_url = t['webSocketDebuggerUrl']
                                break
                    except Exception:
                        pass
                    if tab_ws_url:
                        break
                    time.sleep(0.3)
                if not tab_ws_url:
                    try:
                        _send_browser_cmd(99, 'Target.closeTarget', {'targetId': target_id})
                    except Exception:
                        pass
                    bws.close()
                    raise Exception('无法获取新标签页的调试地址')

                ws = websocket.create_connection(tab_ws_url, timeout=timeout + 10)

                # 辅助函数：发送CDP命令并等待对应ID的响应（忽略事件消息）
                def send_cdp(cmd_id, method, params=None):
                    cmd = {'id': cmd_id, 'method': method}
                    if params:
                        cmd['params'] = params
                    ws.send(json.dumps(cmd))
                    while True:
                        msg = json.loads(ws.recv())
                        if msg.get('id') == cmd_id:
                            return msg
                        # 事件消息，继续等待

                # 先导航到用户输入的URL
                self._log('CDP浏览器模式: 正在导航到 %s' % url[:80])
                nav_result = send_cdp(1, 'Page.navigate', {'url': url})

                # 启用页面事件监听
                try:
                    send_cdp(10, 'Page.enable')
                except Exception:
                    pass

                # 等待页面加载事件（最多等待15秒）
                load_event_detected = False
                wait_start = time.time()
                while time.time() - wait_start < 15:
                    try:
                        ws.settimeout(1)
                        msg = json.loads(ws.recv())
                        if msg.get('method') == 'Page.loadEventFired':
                            load_event_detected = True
                            break
                    except Exception:
                        # 超时继续等待
                        pass
                ws.settimeout(None)

                # 如果没有检测到加载事件，额外等待3秒
                if not load_event_detected:
                    time.sleep(3)
                else:
                    # 检测到加载事件后，额外等待2秒确保动态内容加载
                    time.sleep(2)

                # 多次滚动页面，触发懒加载图片
                try:
                    for scroll_round in range(3):
                        # 滚动到页面底部
                        send_cdp(2 + scroll_round * 2, 'Runtime.evaluate', {
                            'expression': 'window.scrollTo(0, document.body.scrollHeight)',
                            'returnByValue': True
                        })
                        time.sleep(2)
                        # 滚动到页面中间
                        send_cdp(2 + scroll_round * 2 + 1, 'Runtime.evaluate', {
                            'expression': 'window.scrollTo(0, document.body.scrollHeight / 2)',
                            'returnByValue': True
                        })
                        time.sleep(1)
                    # 最后滚动回顶部
                    send_cdp(100, 'Runtime.evaluate', {
                        'expression': 'window.scrollTo(0, 0)',
                        'returnByValue': True
                    })
                    time.sleep(1)
                except Exception:
                    pass

                # 获取页面HTML
                result = send_cdp(4, 'Runtime.evaluate', {
                    'expression': 'document.documentElement.outerHTML',
                    'returnByValue': True
                })
                ws.close()

                # 关闭独立标签页
                try:
                    _send_browser_cmd(2, 'Target.closeTarget', {'targetId': target_id})
                    bws.close()
                except Exception:
                    pass

                if 'result' in result and 'result' in result['result']:
                    html = result['result']['result'].get('value', '')
                if not html:
                    raise Exception('无法获取页面HTML')
                self._log('CDP浏览器模式: 已获取页面HTML (长度=%d)' % len(html))
            except Exception as e:
                raise Exception('CDP浏览器模式连接失败: %s，请先启动调试浏览器（9222端口）' % e)
        elif render_mode == '浏览器渲染':
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = None
                try:
                    browser = p.chromium.launch(headless=True, channel='chrome')
                except Exception:
                    try:
                        browser = p.chromium.launch(headless=True, channel='msedge')
                    except Exception:
                        browser = p.chromium.launch(headless=True)
                page_obj = browser.new_page()
                page_obj.goto(url, timeout=timeout * 1000, wait_until='networkidle')
                try:
                    # 等待页面初始加载
                    page_obj.wait_for_timeout(3000)
                    # 多次滚动页面，触发懒加载图片
                    for scroll_round in range(3):
                        # 滚动到页面底部
                        page_obj.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                        page_obj.wait_for_timeout(2000)
                        # 滚动到页面中间
                        page_obj.evaluate('window.scrollTo(0, document.body.scrollHeight / 2)')
                        page_obj.wait_for_timeout(1000)
                    # 最后滚动回顶部
                    page_obj.evaluate('window.scrollTo(0, 0)')
                    page_obj.wait_for_timeout(1000)
                except Exception:
                    pass
                html = page_obj.content()
                browser.close()
        else:
            import requests
            import re
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, verify=False)
            # 优先从HTML meta标签中提取编码
            html_content = resp.content
            detected_encoding = None
            try:
                # 尝试从meta标签中提取charset
                meta_match = re.search(r'charset=["\']?([\w-]+)', html_content[:2000].decode('ascii', errors='ignore'), re.IGNORECASE)
                if meta_match:
                    detected_encoding = meta_match.group(1).decode('ascii', errors='ignore')
            except Exception:
                pass
            # 如果没有检测到，使用requests的自动检测
            if not detected_encoding:
                detected_encoding = resp.apparent_encoding
            # 对于中文网站，优先尝试GBK
            if detected_encoding and detected_encoding.lower() in ('iso-8859-1', 'windows-1252', 'ascii'):
                detected_encoding = 'gbk'
            # 如果编码还是None，使用utf-8作为默认
            if not detected_encoding:
                detected_encoding = 'utf-8'
            try:
                html = html_content.decode(detected_encoding, errors='replace')
            except (LookupError, UnicodeDecodeError):
                # 如果解码失败，尝试GBK
                try:
                    html = html_content.decode('gbk', errors='replace')
                except Exception:
                    html = resp.text
        from scrapling import Selector
        page = Selector(html)
        return html, page

    def _extract_post_links(self, page, base_url):
        """从列表页提取帖子链接"""
        import re
        from urllib.parse import urljoin, urlparse
        links = set()
        base_domain = urlparse(base_url).netloc.replace('www.', '')

        # 常见的详情页链接模式（包含Discuz等论坛模式）
        detail_patterns = [
            r'/\d+\.html', r'/article/\d+', r'/post/\d+', r'/photos/\d+',
            r'/album/\d+', r'/cos/\d+', r'/meinv/\d+', r'/content/\d+',
            r'/show/\d+', r'/view/\d+', r'/detail/\d+', r'/p/\d+',
            # Discuz论坛模式
            r'thread-\d+-\d+-\d+\.html',
            r'viewthread\.php\?tid=\d+',
            # PHPWind论坛模式
            r'read-htm-tid-\d+\.html',
            # 其他论坛模式
            r'/t/\d+', r'/topic/\d+', r'/threads/\d+',
        ]

        # 从 a 标签提取
        a_tags = page.css('a')
        for a in a_tags:
            href = a.attrib.get('href', '')
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            full_url = urljoin(base_url, href)
            url_lower = full_url.lower()
            # 同域名
            if base_domain not in full_url:
                continue
            # 过滤导航链接
            if any(kw in url_lower for kw in ['/category', '/tag', '/page', '/index', '/about', '/contact', '/login', '/register', '/search']):
                continue
            # 匹配详情页模式
            if any(re.search(pattern, url_lower) for pattern in detail_patterns):
                links.add(full_url)
            # 或者链接包含数字且不是导航页
            elif re.search(r'/\d+', url_lower) and not any(kw in url_lower for kw in ['/page/', '/list/']):
                links.add(full_url)

        return sorted(list(links))

    def _update_task(self, task_id, **kwargs):
        """更新任务列表"""
        try:
            values = list(self.task_tree.item(task_id, 'values'))
            for key, val in kwargs.items():
                if key == 'progress':
                    values[2] = val
                elif key == 'speed':
                    values[3] = val
                elif key == 'status':
                    values[4] = val
                elif key == 'title':
                    values[1] = val
                elif key == 'save_dir':
                    values[5] = val
                elif key == 'url':
                    values[6] = val
            self.task_tree.item(task_id, values=values)
            # 更新任务统计
            self._update_task_stat()
        except Exception:
            pass

    def _retry_failed(self):
        """重试失败的任务"""
        if self.is_running:
            messagebox.showwarning('提示', '正在抓取中，请先停止')
            return

        failed_tasks = []
        for item in self.task_tree.get_children():
            vals = self.task_tree.item(item, 'values')
            status = vals[4] if len(vals) > 4 else ''
            # 重试"失败"和"部分失败"的任务
            if status in ('失败', '部分失败'):
                failed_tasks.append((item, vals))

        if not failed_tasks:
            self._log('没有失败的任务')
            return

        self._log('准备重试 %d 个失败任务...' % len(failed_tasks))

        # 收集失败任务的URL
        retry_urls = []
        for item, vals in failed_tasks:
            # 优先从隐藏的url列（索引6）获取URL，如果没有则从第二列（索引1）获取
            url = ''
            if len(vals) > 6 and vals[6]:
                url = vals[6]
            elif len(vals) > 1 and vals[1]:
                url = vals[1]
            if url and url.startswith('http'):
                retry_urls.append(url)
                # 重置任务状态（保留所有列）
                save_dir = vals[5] if len(vals) > 5 else ''
                post_url = vals[6] if len(vals) > 6 else url
                self.task_tree.item(item, values=(vals[0], vals[1], '0/0', '0 KB/s', '等待', save_dir, post_url))

        if not retry_urls:
            self._log('没有找到有效的任务URL')
            return

        # 保存设置
        self._save_settings()

        self.is_running = True
        self.stop_flag.clear()
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')

        save_dir = self.dir_var.get().strip()
        max_threads = int(self.threads_var.get() or '8')
        timeout = int(self.timeout_var.get() or '15')
        min_size = int(self.min_size_var.get() or '0')

        # 在线程中重试失败任务
        def retry_worker():
            try:
                total = len(retry_urls)
                success_count = 0
                fail_count = 0
                for i, url in enumerate(retry_urls):
                    if self.stop_flag.is_set():
                        self._log('已停止重试')
                        break
                    self._log('[%d/%d] 重试: %s' % (i + 1, total, url[:80]))
                    try:
                        # 找到对应的任务ID
                        task_id = None
                        for item, vals in failed_tasks:
                            if len(vals) > 1 and vals[1] == url:
                                task_id = item
                                break
                        result = self._crawl_single_page(url, save_dir, max_threads, timeout, min_size, task_id=task_id)
                        # _crawl_single_page返回的是(success, fail, skipped)元组
                        if result and len(result) >= 2 and result[0] > 0:
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        fail_count += 1
                        self._log('重试失败: %s' % e)
                self._log('重试完成: 成功%d个, 失败%d个' % (success_count, fail_count))
            except Exception as e:
                import traceback
                self._log('重试出错: %s' % e)
                self._log('详细错误: %s' % traceback.format_exc())
            finally:
                self._finish_crawl()

        thread = threading.Thread(target=retry_worker, daemon=True)
        thread.start()

    def _is_debug_browser_running(self):
        """检测9222端口是否有调试浏览器在运行"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', 9222))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _kill_stale_debug_browser(self):
        """杀掉占用debug_profile目录但未开启调试端口的残留Chrome进程"""
        import subprocess
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like '*WebGrabber*debug_profile*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps],
                timeout=15, capture_output=True
            )
            self._log('已清理占用调试配置目录的残留Chrome进程')
            return True
        except Exception as e:
            self._log('清理残留Chrome进程失败: %s' % e)
            return False

    def _launch_debug_browser(self):
        """启动调试浏览器（9222端口）"""
        import subprocess
        import os
        import shutil

        # 先检测是否已经在运行
        if self._is_debug_browser_running():
            self._log('调试浏览器已经在运行（9222端口），无需重复启动')
            return

        # 9222未监听时，先杀掉占用调试配置目录的残留Chrome进程（避免复用旧进程导致调试端口不生效）
        self._kill_stale_debug_browser()
        import time
        time.sleep(1)

        # 使用独立的调试配置目录（Chrome 136+使用默认User Data目录时调试端口不生效）
        user_data_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'debug_profile')
        os.makedirs(user_data_dir, exist_ok=True)

        # 获取用户选择的浏览器
        browser_choice = getattr(self, 'browser_choice_var', None)
        choice = browser_choice.get() if browser_choice else 'Chrome'

        # Chrome路径
        chrome_paths = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]

        # Edge路径
        edge_paths = [
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        ]

        # 根据用户选择确定启动顺序
        if choice == 'Chrome':
            browser_paths = chrome_paths
        elif choice == 'Edge':
            browser_paths = edge_paths
        else:
            browser_paths = chrome_paths + edge_paths

        browser_path = None
        browser_name = None

        # 优先用Chrome
        for path in chrome_paths:
            if os.path.exists(path):
                browser_path = path
                browser_name = 'Chrome'
                break

        # 其次用Edge
        if not browser_path:
            for path in edge_paths:
                if os.path.exists(path):
                    browser_path = path
                    browser_name = 'Edge'
                    break

        if not browser_path:
            self._log('未找到Chrome或Edge浏览器，请手动启动调试浏览器')
            return

        # 构建启动命令
        cmd = [
            browser_path,
            '--remote-debugging-port=9222',
            '--remote-allow-origins=*',
            '--no-first-run',
            '--no-default-browser-check',
            '--user-data-dir=%s' % user_data_dir,
        ]

        # 尝试自动加载用户默认Chrome里的油猴(Tampermonkey)扩展
        try:
            default_chrome_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
            tm_dir = os.path.join(default_chrome_dir, 'Default', 'Extensions', 'dhdgffkkebhmkfjojejmpbldmpobfkfo')
            if os.path.exists(tm_dir):
                versions = [d for d in os.listdir(tm_dir) if os.path.isdir(os.path.join(tm_dir, d))]
                if versions:
                    # 取版本号最大的
                    versions.sort()
                    tm_ext = os.path.join(tm_dir, versions[-1])
                    cmd.append('--load-extension=%s' % tm_ext)
                    self._log('已自动加载油猴(Tampermonkey)扩展: %s' % tm_ext)
                    # 复制油猴脚本数据到独立配置目录
                    src_data = os.path.join(default_chrome_dir, 'Default', 'Local Extension Settings', 'dhdgffkkebhmkfjojejmpbldmpobfkfo')
                    dst_data = os.path.join(user_data_dir, 'Default', 'Local Extension Settings', 'dhdgffkkebhmkfjojejmpbldmpobfkfo')
                    if os.path.exists(src_data):
                        try:
                            if os.path.exists(dst_data):
                                shutil.rmtree(dst_data)
                            os.makedirs(os.path.dirname(dst_data), exist_ok=True)
                            shutil.copytree(src_data, dst_data, ignore=shutil.ignore_patterns('LOCK', '*.log'))
                            self._log('已复制油猴脚本数据到调试配置')
                        except Exception as e:
                            self._log('复制油猴脚本数据失败: %s（可在调试浏览器里手动安装油猴）' % e)
        except Exception as e:
            self._log('自动加载油猴失败: %s（可在调试浏览器里手动安装油猴）' % e)

        # 启动浏览器
        self._log('正在启动%s调试浏览器（9222端口）...' % browser_name)
        try:
            proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            self._log('%s调试浏览器已启动（PID=%d），正在嵌入...' % (browser_name, proc.pid))
            # 延迟嵌入浏览器窗口
            self.root.after(3000, lambda: self._embed_browser())
        except Exception as e:
            self._log('启动调试浏览器失败: %s' % e)

    def _embed_browser(self):
        """把浏览器窗口嵌入到软件里"""
        try:
            import ctypes
            from ctypes import wintypes

            # 查找浏览器窗口
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            GetClassName = ctypes.windll.user32.GetClassNameW
            GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

            found_hwnd = None
            browser_choice = getattr(self, 'browser_choice_var', None)
            choice = browser_choice.get() if browser_choice else 'Chrome'

            def enum_callback(hwnd, lParam):
                nonlocal found_hwnd
                if not IsWindowVisible(hwnd):
                    return True
                length = GetWindowTextLength(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buf, length + 1)
                title = buf.value
                # 精确查找Chrome或Edge主窗口
                class_buf = ctypes.create_unicode_buffer(256)
                GetClassName(hwnd, class_buf, 256)
                class_name = class_buf.value
                # Chrome和Edge的主窗口类名都是Chrome_WidgetWin_1
                is_chrome = class_name == 'Chrome_WidgetWin_1' and ('Chrome' in title or 'Google Chrome' in title or '新标签页' in title)
                is_edge = class_name == 'Chrome_WidgetWin_1' and ('Edge' in title or 'Microsoft Edge' in title or '新建标签页' in title)
                # 根据用户选择过滤
                if choice == 'Chrome' and not is_chrome:
                    return True
                if choice == 'Edge' and not is_edge:
                    return True
                if (is_chrome or is_edge) and len(title) > 0:
                    found_hwnd = hwnd
                    return False
                return True

            EnumWindows(EnumWindowsProc(enum_callback), 0)

            if not found_hwnd:
                self._log('未找到浏览器窗口，稍后重试...')
                self.root.after(2000, self._embed_browser)
                return

            self.browser_hwnd = found_hwnd

            # 获取宿主窗口句柄
            self.browser_frame.update_idletasks()
            host_hwnd = self.browser_frame.winfo_id()

            # 嵌入浏览器窗口
            SetParent = ctypes.windll.user32.SetParent
            SetParent(found_hwnd, host_hwnd)

            # 调整浏览器窗口大小（多次调整确保生效）
            MoveWindow = ctypes.windll.user32.MoveWindow
            self.browser_frame.update_idletasks()
            self.browser_frame.update()
            width = self.browser_frame.winfo_width()
            height = self.browser_frame.winfo_height()
            # 第一次调整
            MoveWindow(found_hwnd, 0, 0, width, height, True)
            # 延迟第二次调整，确保嵌入后大小正确
            self.root.after(100, lambda: self._resize_browser())
            self.root.after(500, lambda: self._resize_browser())

            self._log('浏览器已嵌入到「浏览器」页签')
            self.browser_hint.pack_forget()  # 隐藏提示标签
            self.content_notebook.select(2)  # 切换到浏览器页签

            # 绑定窗口大小变化事件
            self.browser_frame.bind('<Configure>', self._on_browser_resize)

        except Exception as e:
            self._log('嵌入浏览器失败: %s' % e)

    def _resize_browser(self):
        """调整浏览器窗口大小以适应宿主窗口"""
        if self.browser_hwnd:
            try:
                import ctypes
                MoveWindow = ctypes.windll.user32.MoveWindow
                self.browser_frame.update_idletasks()
                self.browser_frame.update()
                width = self.browser_frame.winfo_width()
                height = self.browser_frame.winfo_height()
                if width > 0 and height > 0:
                    MoveWindow(self.browser_hwnd, 0, 0, width, height, True)
            except Exception:
                pass

    def _on_browser_resize(self, event):
        """浏览器宿主窗口大小变化时调整浏览器窗口"""
        if self.browser_hwnd:
            try:
                import ctypes
                MoveWindow = ctypes.windll.user32.MoveWindow
                # 延迟调整，避免频繁调整
                if hasattr(self, '_resize_timer') and self._resize_timer:
                    self.root.after_cancel(self._resize_timer)
                self._resize_timer = self.root.after(50, lambda: MoveWindow(self.browser_hwnd, 0, 0, event.width, event.height, True))
            except Exception:
                pass

    def _crawl_worker(self, url, save_dir):
        """抓取工作线程"""
        try:
            from scrapling import Selector
        except ImportError as e:
            self._log('错误: Scrapling 未安装 - %s' % e)
            import traceback
            self._log('详细错误: %s' % traceback.format_exc())
            self._finish_crawl()
            return

        max_threads = self.threads_var.get()
        timeout = self.timeout_var.get()
        grab_mode = self.grab_mode_var.get()
        # 解析范围，支持"20"或"15-60"两种格式
        range_str = self.post_range_var.get().strip() or '20'
        range_start = 0
        range_end = 20
        if '-' in range_str:
            try:
                parts = range_str.split('-')
                range_start = max(0, int(parts[0].strip()) - 1)  # 转换为0-based索引
                range_end = int(parts[1].strip())
                self._log('范围: 第%d到第%d个帖子' % (range_start + 1, range_end))
            except Exception:
                range_start = 0
                range_end = 20
        else:
            try:
                range_end = int(range_str)
            except Exception:
                range_end = 20
        post_range = range_end  # 最大帖子数用range_end
        min_size = self.min_size_var.get()

        self._log('=' * 50)
        self._log('Scrapling 图片爬虫 %s' % APP_VERSION)
        self._log('=' * 50)
        self._log('目标网址: %s' % url)
        self._log('保存目录: %s' % save_dir)
        self._log('抓取模式: %s' % grab_mode)
        self._log('下载线程: %d' % max_threads)
        self._log('')

        # 启动计时器
        self._crawl_start_time = time.time()
        self._timer_running = True
        self._update_timer()

        # 清空任务列表
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)

        if grab_mode == '全站':
            self._crawl_whole_site(url, save_dir, max_threads, timeout, post_range, min_size)
        else:
            self._crawl_single_page(url, save_dir, max_threads, timeout, min_size, task_id=None)

        # 停止计时器
        self._timer_running = False
        self._finish_crawl()

    def _update_timer(self):
        """更新计时器"""
        if not hasattr(self, '_timer_running') or not self._timer_running:
            return
        elapsed = int(time.time() - self._crawl_start_time)
        mins = elapsed // 60
        secs = elapsed % 60
        self.timer_var.set('用时: %02d:%02d' % (mins, secs))
        self.root.after(1000, self._update_timer)

    def _extract_next_page(self, page, base_url):
        """从列表页提取下一页链接（支持文本、class、URL模式、页码数字链接）"""
        import re
        from urllib.parse import urljoin, urlparse
        base_domain = urlparse(base_url).netloc.replace('www.', '')

        # 常见的下一页链接文本
        next_texts = ['下一页', '下页', 'next', 'Next', '>', '»', '后一页', '后页']

        # 常见的分页URL模式
        page_patterns = [
            r'[?&]page=(\d+)',
            r'/page/(\d+)',
            r'/index_(\d+)\.html',
            r'[?&]pagenum=(\d+)',
            r'[?&]p=(\d+)',
            r'/list_(\d+)\.html',
            r'/page_(\d+)\.html',
            r'[?&]page_no=(\d+)',
            r'[?&]pg=(\d+)',
            r'/(\d+)\.html$',
        ]

        a_tags = page.css('a')

        # 1. 先找"下一页"文本或class=next的链接
        for a in a_tags:
            text = (a.text or '').strip()
            href = a.attrib.get('href', '')
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            full_url = urljoin(base_url, href)
            if base_domain not in full_url:
                continue
            for nt in next_texts:
                if nt in text:
                    return full_url
            cls = a.attrib.get('class', '')
            if 'next' in cls.lower():
                return full_url

        # 2. 从所有链接中收集分页链接，找"当前页+1"的页码
        current_page = 1
        for pattern in page_patterns:
            m = re.search(pattern, base_url)
            if m:
                current_page = int(m.group(1))
                break

        next_page_url = None
        min_next_page = None
        for a in a_tags:
            href = a.attrib.get('href', '')
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            full_url = urljoin(base_url, href)
            if base_domain not in full_url:
                continue
            for pattern in page_patterns:
                m = re.search(pattern, full_url)
                if m:
                    page_num = int(m.group(1))
                    if page_num > current_page:
                        if min_next_page is None or page_num < min_next_page:
                            min_next_page = page_num
                            next_page_url = full_url
                    break

        if next_page_url:
            return next_page_url

        # 3. 尝试构造下一页URL（当前URL带页码模式时）
        if current_page > 0:
            next_page = current_page + 1
            for pattern in page_patterns:
                if re.search(pattern, base_url):
                    next_url = re.sub(pattern, lambda m: m.group(0).replace(m.group(1), str(next_page)), base_url)
                    return next_url

        return None

    def _crawl_whole_site(self, url, save_dir, max_threads, timeout, post_range, min_size):
        """全站抓取：列表页翻页+进详情页抓取"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        # 解析范围，支持"20"或"15-60"两种格式
        range_str = self.post_range_var.get().strip() or '20'
        range_start = 0
        range_end = post_range
        if '-' in range_str:
            try:
                parts = range_str.split('-')
                range_start = max(0, int(parts[0].strip()) - 1)  # 转换为0-based索引
                range_end = int(parts[1].strip())
            except Exception:
                range_start = 0
                range_end = post_range

        # 分页翻页，收集所有帖子链接
        all_post_links = []
        current_url = url
        page_num = 1
        max_pages = 50  # 最多翻50页

        # 如果指定了页码，就只翻到指定页码
        page_filter_num = 0
        try:
            if hasattr(self, 'page_num_var') and self.page_num_var:
                page_filter_num = int(self.page_num_var.get() or '0')
        except Exception:
            page_filter_num = 0
        if page_filter_num > 0:
            max_pages = page_filter_num
            self._log('指定只抓取第%d页' % page_filter_num)

        while current_url and page_num <= max_pages:
            if self.stop_flag.is_set():
                self._log('已停止')
                break

            # 如果已经收集到足够的帖子，就停止翻页
            if len(all_post_links) >= post_range:
                self._log('已收集到 %d 个帖子，停止翻页' % len(all_post_links))
                break

            self._log('正在分析第 %d 页: %s' % (page_num, current_url))
            try:
                html, page = self._fetch_page(current_url, timeout)
            except Exception as e:
                self._log('第 %d 页抓取失败: %s' % (page_num, e))
                break

            post_links = self._extract_post_links(page, current_url)
            self._log('第 %d 页识别到 %d 个帖子链接（累计 %d 个）' % (page_num, len(post_links), len(all_post_links) + len(post_links)))
            if len(post_links) == 0:
                self._log('警告：当前页没有识别到任何帖子链接，可能是网站结构不匹配')
                break

            # 将当前页的帖子链接添加到总列表
            all_post_links.extend(post_links)

            # 如果指定了页码，只抓取指定页，不翻页
            if page_filter_num > 0:
                self._log('指定只抓取第%d页，停止翻页' % page_filter_num)
                break

            # 提取下一页链接
            next_url = self._extract_next_page(page, current_url)
            if next_url and next_url != current_url:
                self._log('找到下一页: %s' % next_url)
                current_url = next_url
                page_num += 1
            else:
                self._log('没有下一页了，停止翻页（当前页识别到 %d 个帖子）' % len(post_links))
                break

        # 去重（最严格的去重逻辑，确保同一个帖子绝对不会被下载多遍）
        self._log('开始去重（共 %d 个链接）...' % len(all_post_links))
        seen_urls = set()
        unique_all_post_links = []
        duplicate_count = 0
        for i, link in enumerate(all_post_links):
            # 每处理100个链接输出一次进度
            if (i + 1) % 100 == 0:
                self._log('  去重进度: %d/%d（已去重 %d 个）' % (i + 1, len(all_post_links), duplicate_count))
            # 简化去重逻辑：直接用链接小写作为去重依据（更快）
            dedup_key = link.lower().strip()
            # 对于Discuz论坛的thread-xxx-1-1.html，提取帖子ID作为去重依据
            if 'thread-' in dedup_key:
                import re as _re
                m = _re.search(r'thread-(\d+)-', dedup_key)
                if m:
                    dedup_key = 'thread:' + m.group(1)
            if dedup_key not in seen_urls:
                seen_urls.add(dedup_key)
                unique_all_post_links.append(link)
            else:
                duplicate_count += 1
        all_post_links = unique_all_post_links
        self._log('去重完成：去重前 %d 个，去重后 %d 个（过滤掉 %d 个重复）' % (len(all_post_links) + duplicate_count, len(all_post_links), duplicate_count))

        # （页码过滤已移到翻页逻辑中，指定页码时只翻到指定页码）

        # 根据范围选择帖子
        self._log('开始范围选择（共 %d 个帖子，范围: %d-%d）...' % (len(all_post_links), range_start + 1, range_end))
        if range_start > 0 or range_end < len(all_post_links):
            post_links = all_post_links[range_start:range_end]
            self._log('准备抓取第%d到第%d个（共%d个）...' % (range_start + 1, min(range_end, len(all_post_links)), len(post_links)))
        else:
            post_links = all_post_links[:post_range]
            self._log('准备抓取前 %d 个...' % len(post_links))
        self._log('范围选择完成，共 %d 个帖子待下载' % len(post_links))

        # 增量扫描：跳过已完成的帖子
        completed_urls = set()
        if hasattr(self, 'incremental_var') and self.incremental_var.get() and not (hasattr(self, 'force_rescan_var') and self.force_rescan_var.get()):
            completed_urls = self._load_progress(save_dir)
            if completed_urls:
                original_count = len(post_links)
                post_links = [link for link in post_links if link not in completed_urls]
                skipped_count = original_count - len(post_links)
                if skipped_count > 0:
                    self._log('增量扫描: 跳过 %d 个已完成的帖子，剩余 %d 个待下载' % (skipped_count, len(post_links)))
        elif hasattr(self, 'force_rescan_var') and self.force_rescan_var.get():
            self._log('强制重扫: 不跳过已完成的帖子，重新抓取全部')

        if not post_links:
            self._log('未识别到帖子链接，回退为单页抓取')
            self._crawl_single_page(url, save_dir, max_threads, timeout, min_size, task_id=None)
            return

        # 添加任务到任务列表
        self._log('开始添加任务到任务列表（共 %d 个）...' % len(post_links))
        task_ids = []
        for i, post_url in enumerate(post_links):
            task_id = self.task_tree.insert('', 'end', values=(i + 1, post_url, '0/0', '0 KB/s', '等待', '', post_url))
            task_ids.append(task_id)
        self._log('任务列表添加完成，共 %d 个任务' % len(task_ids))
        # 更新任务统计
        self._update_task_stat()

        # 并发抓取多个帖子
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        success_count = 0
        fail_count = 0
        count_lock = threading.Lock()

        def crawl_single_post(index, post_url, task_id):
            """抓取单个帖子"""
            nonlocal success_count, fail_count
            if self.stop_flag.is_set():
                return
            # 检查暂停标志
            while self.pause_flag.is_set() and not self.stop_flag.is_set():
                time.sleep(0.5)
            if self.stop_flag.is_set():
                return
            self._log('[%d/%d] 正在抓取: %s' % (index + 1, len(post_links), post_url))
            self._update_task(task_id, status='抓取中')
            try:
                # 抓取帖子页面
                post_html, post_page = self._fetch_page(post_url, timeout)

                # 提取帖子标题
                title = ''
                try:
                    title_elem = post_page.css('title')
                    if title_elem:
                        title = title_elem[0].text.strip()
                except Exception:
                    pass
                import re
                title = re.sub(r'[\\/:*?"<>|]', '_', title)
                title = title[:80] if title else 'untitled'
                self._update_task(task_id, title=title)

                # 创建保存目录
                post_save_dir = os.path.join(save_dir, domain, title)
                os.makedirs(post_save_dir, exist_ok=True)
                # 更新任务的保存目录（用于右键打开保存目录）
                self._update_task(task_id, save_dir=post_save_dir)

                # 提取图片并下载
                img_urls = self._extract_images_from_page(post_page, post_url, post_html)
                self._log('  提取到 %d 张图片' % len(img_urls))
                self._update_task(task_id, progress='0/%d' % len(img_urls))

                if img_urls:
                    success, fail, skipped = self._download_image_list(img_urls, post_save_dir, max_threads, min_size, task_id)
                    with count_lock:
                        success_count += success
                        fail_count += fail
                    # 根据下载结果判断状态
                    total_processed = success + fail + skipped
                    if fail == 0 and skipped == 0:
                        self._update_task(task_id, status='完成')
                    elif fail == 0 and skipped > 0:
                        self._update_task(task_id, status='完成(跳过%d张)' % skipped)
                    elif fail > 0 and success > 0:
                        self._update_task(task_id, status='部分失败')
                    else:
                        self._update_task(task_id, status='失败')
                    # 标记帖子为已完成（增量扫描）
                    if success > 0:
                        self._mark_post_completed(save_dir, post_url, completed_urls)
                else:
                    self._update_task(task_id, status='无图片')

            except Exception as e:
                self._log('  抓取失败: %s' % e)
                self._update_task(task_id, status='失败')
                with count_lock:
                    fail_count += 1

        # 使用线程池并发下载
        self._log('开始并发下载，线程数=%d，共%d个帖子' % (max_threads, len(post_links)))
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = []
            for i, (post_url, task_id) in enumerate(zip(post_links, task_ids)):
                if self.stop_flag.is_set():
                    break
                future = executor.submit(crawl_single_post, i, post_url, task_id)
                futures.append(future)

            # 等待所有任务完成
            for future in as_completed(futures):
                if self.stop_flag.is_set():
                    break
                try:
                    future.result()
                except Exception as e:
                    self._log('任务异常: %s' % e)

        self._log('全站抓取完成: 成功 %d, 失败 %d' % (success_count, fail_count))
        # 保存最终进度
        if completed_urls:
            self._save_progress(save_dir, completed_urls)
            self._log('进度已保存: 共 %d 个已完成帖子' % len(completed_urls))
        # 任务完成后启用重试失败按钮
        if hasattr(self, 'retry_btn'):
            self.retry_btn.config(state='normal')
        # 更新任务统计
        self._update_task_stat()

    def _extract_images_from_page(self, page, url, html):
        """从页面提取图片链接"""
        import re
        img_urls = set()
        smart_filter = self.smart_filter_var.get()

        # 只过滤明确的无关图片目录，不过滤基于关键词的图片（避免误过滤正常图片）
        SKIP_DIRS = [
            # Discuz论坛表情目录
            '/static/image/smiley/',
            # Discuz论坛公共图片目录（图标、在线状态、按钮等）
            '/static/image/common/',
            # Discuz论坛头像
            '/uc_server/avatar.php',
        ]

        def try_add(img_url):
            if not img_url or img_url.startswith('data:') or img_url.startswith('about:') or img_url == 'blank':
                return
            # 过滤模板残留（如 {{src}}、{src}）
            if '{{' in img_url or '}}' in img_url or '{' in img_url or '}' in img_url:
                return
            full_url = urllib.parse.urljoin(url, img_url)
            url_lower = full_url.lower()
            # 智能过滤：只过滤明确的无关图片目录
            if smart_filter:
                for skip_dir in SKIP_DIRS:
                    if skip_dir in url_lower:
                        return
            # SVG通常是图标，过滤掉
            if url_lower.endswith('.svg'):
                return
            # 只认为常见的图片格式是图片，根据下载视频开关决定是否提取视频
            IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif', '.tiff', '.tif', '.ico']
            VIDEO_EXTS = ['.mp4', '.avi', '.mkv', '.flv', '.wmv', '.mov', '.rmvb', '.rm', '.3gp', '.ts', '.m4v']
            download_video = self.download_video_var.get()
            # 如果URL以图片扩展名结尾，认为是图片
            if any(url_lower.endswith(ext) for ext in IMAGE_EXTS):
                img_urls.add(full_url)
            # 如果URL以视频扩展名结尾，根据下载视频开关决定是否提取
            elif any(url_lower.endswith(ext) for ext in VIDEO_EXTS):
                if download_video:
                    img_urls.add(full_url)
                else:
                    return
            # 如果URL没有明确的扩展名，但是在img标签中，且不是html/php等，也认为是图片
            elif not any(url_lower.endswith(ext) for ext in ['.html', '.htm', '.php', '.asp', '.jsp', '.aspx', '.css', '.js']):
                img_urls.add(full_url)

        # 从 img 标签提取
        try:
            imgs = page.css('img')
            for img in imgs:
                for attr in ['src', 'data-src', 'data-original', 'data-lazy-src', 'data-bg', 'data-lazy', 'data-actual',
                             'data-url', 'data-image', 'data-photo', 'data-img', 'data-pic', 'data-file', 'data-origin',
                             'data-real', 'data-source', 'data-href', 'data-link', 'data-thumb', 'data-preview',
                             'data-large', 'data-big', 'data-full', 'data-origin-src', 'data-original-src']:
                    val = img.attrib.get(attr, '')
                    if val:
                        try_add(val)
        except Exception:
            pass

        # 正则兜底
        try:
            patterns = [
                r'["\']((?:https?:)?//[^"\']+\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^"\']*)?)["\']',
                r'(?:src|data-src|data-original)\s*=\s*["\']([^"\']+)["\']',
            ]
            for pattern in patterns:
                for m in re.findall(pattern, html, re.IGNORECASE):
                    if isinstance(m, tuple):
                        m = m[0]
                    try_add(m)
        except Exception:
            pass

        # 调试日志：输出提取到的图片数量
        self._log('图片提取: 共提取到 %d 张图片' % len(img_urls))
        if smart_filter:
            self._log('智能过滤: 已开启，过滤目录: %s' % ', '.join(SKIP_DIRS[:5]))
        return list(img_urls)

    def _download_image_list(self, img_urls, save_dir, max_threads, min_size, task_id=None):
        """下载图片列表，返回 (成功数, 失败数, 跳过数)"""
        # 统一过滤无效URL（about:blank、模板残留等）
        img_urls = [u for u in img_urls if u and not u.startswith('about:') and '{{' not in u and '}}' not in u]
        import requests
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self._log('开始下载: 共 %d 张图片，最小尺寸: %d KB，线程数: %d' % (len(img_urls), min_size, max_threads))
        os.makedirs(save_dir, exist_ok=True)
        success = 0
        fail = 0
        skipped = 0
        total_bytes = 0
        start_time = time.time()

        def download_one(idx, img_url):
            nonlocal success, fail, skipped, total_bytes
            # 保存原始URL
            original_url = img_url
            # 尝试将缩略图URL转换为原图URL
            img_url_lower = img_url.lower()
            thumb_patterns = [
                ('_thumb.', '.'),
                ('_small.', '.'),
                ('_middle.', '.'),
                ('_mini.', '.'),
                ('/thumb/', '/i/'),
                ('/small/', '/i/'),
                ('/middle/', '/i/'),
                ('!thumb', ''),
                ('!small', ''),
                ('!middle', ''),
            ]
            for pattern, replacement in thumb_patterns:
                if pattern in img_url_lower:
                    img_url = img_url_lower.replace(pattern, replacement)
                    break
            # 重试机制：最多重试3次
            max_retries = 3
            for retry in range(max_retries):
                try:
                    # 去掉stream=True，直接用resp.content
                    resp = requests.get(img_url, headers=BROWSER_HEADERS, timeout=30, verify=False)
                    # HTTP状态码检查
                    if resp.status_code != 200:
                        if retry < max_retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            fail += 1
                            self._log('下载失败[HTTP %d][%d/%d]: %s' % (resp.status_code, success + fail + skipped, len(img_urls), img_url[:80]))
                            if task_id:
                                self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                            return
                    content = resp.content
                    # 最小图片过滤
                    if min_size > 0 and len(content) < min_size * 1024:
                        # 图片太小，先重试一次，确认是不是下载不完整
                        if retry < max_retries - 1:
                            time.sleep(1)
                            continue
                        # 重试后还是很小，才跳过
                        skipped += 1
                        self._log('跳过[过小 %.1fKB < %dKB][%d/%d]: %s' % (len(content)/1024, min_size, success + fail + skipped, len(img_urls), img_url[:80]))
                        # 更新任务进度（跳过的也算处理过）
                        if task_id:
                            self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                        return
                    # 确定扩展名
                    ext = '.jpg'
                    url_lower = img_url.lower()
                    for e in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif']:
                        if e in url_lower:
                            ext = e
                            break
                    filename = 'img_%03d%s' % (idx + 1, ext)
                    filepath = os.path.join(save_dir, filename)
                    # 确保保存目录存在
                    os.makedirs(save_dir, exist_ok=True)
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    success += 1
                    total_bytes += len(content)
                    # 更新任务进度
                    if task_id:
                        elapsed = max(time.time() - start_time, 0.1)
                        speed = (total_bytes / 1024) / elapsed
                        self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)),
                                         speed='%.0f KB/s' % speed)
                    return  # 下载成功，退出重试循环
                except Exception as e:
                    if retry < max_retries - 1:
                        # 重试前等待1秒
                        time.sleep(1)
                        continue
                    else:
                        # 最后一次重试还是失败
                        fail += 1
                        self._log('下载失败[%d/%d] (重试%d次): %s - %s' % (success + fail + skipped, len(img_urls), max_retries, img_url[:100], str(e)[:150]))
                        # 更新任务进度
                        if task_id:
                            self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                        return

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = []
            for idx, img_url in enumerate(img_urls):
                futures.append(executor.submit(download_one, idx, img_url))
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    fail += 1
                    self._log('任务异常: %s' % str(e)[:100])

        self._log('下载完成: 成功 %d, 失败 %d, 跳过 %d, 总计 %d' % (success, fail, skipped, len(img_urls)))
        return success, fail, skipped

    def _crawl_single_page(self, url, save_dir, max_threads, timeout, min_size, task_id=None):
        """单页抓取"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        self.stat_var.set('正在抓取网页...')
        self._log('[1/3] 正在请求网页 (超时%d秒)...' % timeout)
        start_time = time.time()

        try:
            html, page = self._fetch_page(url, timeout)
        except Exception as e:
            self._log('抓取失败: %s' % e)
            import traceback
            self._log('详细错误: %s' % traceback.format_exc())
            return

        crawl_time = time.time() - start_time
        self._log('抓取完成，耗时: %.2f 秒' % crawl_time)

        # 提取帖子标题，创建保存目录
        title = ''
        try:
            title_elem = page.css('title')
            if title_elem:
                title = title_elem[0].text.strip()
        except Exception:
            pass
        import re
        title = re.sub(r'[\\/:*?\"<>|]', '_', title)
        title = title[:80] if title else 'untitled'
        save_dir = os.path.join(save_dir, domain, title)
        os.makedirs(save_dir, exist_ok=True)
        self._log('保存到: %s' % save_dir)
        # 更新任务的保存目录
        if task_id:
            self._update_task(task_id, save_dir=save_dir)

        if self.stop_flag.is_set():
            self._log('已停止')
            return

        # 提取图片链接
        self.stat_var.set('正在提取图片链接...')
        self._log('[2/3] 正在提取图片链接...')
        img_urls = self._extract_images_from_page(page, url, html)
        self._log('提取到 %d 张图片' % len(img_urls))

        if not img_urls:
            self._log('没有找到图片')
            if task_id:
                self._update_task(task_id, status='无图片')
            return

        # 下载图片
        self.stat_var.set('正在下载图片...')
        self._log('[3/3] 正在下载 %d 张图片...' % len(img_urls))
        if task_id:
            self._update_task(task_id, status='下载中')

        success, fail, skipped = self._download_image_list(img_urls, save_dir, max_threads, min_size, task_id)

        # 更新统计信息
        self.stat_total.set('图片总数: %d' % len(img_urls))
        self.stat_done.set('已下载: %d/%d' % (success, len(img_urls)))
        self.stat_success.set('成功: %d' % success)
        self.stat_fail.set('失败: %d' % fail)

        if task_id:
            if fail == 0:
                self._update_task(task_id, status='完成')
            else:
                self._update_task(task_id, status='部分失败')

        self._log('下载完成: 成功 %d, 失败 %d' % (success, fail))
        self.stat_var.set('完成 - 成功 %d/%d' % (success, len(img_urls)))

    def _finish_crawl(self):
        """完成抓取"""
        self.is_running = False
        self.start_btn.config(state='normal')
        self.pause_btn.config(state='disabled', text='暂停')
        self.stop_btn.config(state='disabled')
        self.pause_flag.clear()
        if self.stop_flag.is_set():
            self.stat_var.set('已停止')


def main():
    root = tk.Tk()
    app = ScraplingGrabberGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
