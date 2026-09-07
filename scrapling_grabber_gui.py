# -*- coding: utf-8 -*-
"""Scrapling 图片爬虫 - GUI 版本"""
import os
import sys
import time
import threading
import subprocess
import glob
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

APP_VERSION = 'v2.11.0'

# ===== AI 过滤配置 =====
AI_DEFAULT_PORT = 8080
# llama-server 可执行文件（官方预编译版）
AI_SERVER_DEFAULT = r'L:\工作流\千问无审查模型配置\llama-b9297-bin-win-cuda-12.4-x64\llama-server.exe'
# 模型预设：名称 -> (主模型, 视觉模型)
AI_MODEL_PRESETS = {
    '内置4B（6G显存）': (
        r'L:\ComfyUI\ComfyUI\models\LLM\Qwen3.5-4B-Q4_K_M.gguf',
        r'L:\ComfyUI\ComfyUI\models\LLM\Qwen3.5-4B-mmproj-BF16.gguf',
    ),
    '内置9B（12G显存）': (
        r'L:\ComfyUI\ComfyUI\models\LLM\Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf',
        r'L:\ComfyUI\ComfyUI\models\LLM\mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf',
    ),
    '自定义': (None, None),
}
# AI 判断提示词（正文图保留，无关图删除；水印不影响）
AI_JUDGE_PROMPT = ('这是网页抓取的一张图片。请判断它属于哪一类：'
                   '"正文"（人物写真、主题摄影、插画、风景等帖子正文内容）'
                   '或"无关"（logo、图标、表情包、按钮、横幅、纯色背景、文字截图等页面装饰元素）。'
                   '注意：图片带水印或网站标记不影响判断，内容为写真/主题图的仍属于正文。'
                   '只回答两个字：正文 或 无关')

# AI 判断 + 提示词生成（启用"AI生成提示词"时使用）
AI_PROMPT_PROMPT = ('这是网页抓取的一张图片。请完成两项任务：\n'
                    '1. 判断图片类别："正文"（人物写真、主题摄影、插画、风景等帖子正文内容）'
                    '或"无关"（logo、图标、表情包、按钮、横幅、文字截图等页面装饰元素），带水印不影响判断；\n'
                    '2. 如果属于"正文"，为这张图生成一份 AI 绘图提示词，用于图像生成模型复现这张图。\n'
                    '严格按以下格式输出（只输出以下三行，不要输出其他内容）：\n'
                    '类别: 正文 或 无关\n'
                    '中文: 详细的中文提示词，包含人物外貌特征、服装、姿态、表情、场景、光线氛围，'
                    '以及镜头焦距、光圈等专业摄影描述\n'
                    '英文: 英文逗号分隔的提示词tag，适合Stable Diffusion风格，'
                    '如 masterpiece, best quality, 1girl, detailed face 等\n'
                    '示例：\n'
                    '类别: 正文\n'
                    '中文: 一个18岁的东亚女孩，椭圆形脸型，深棕色眼睛直视镜头，自然水润妆容，穿着白色吊带裙，'
                    '站在海边沙滩上，金色阳光洒在脸上，背景是蓝色海洋和天空，镜头采用85mm焦距，光圈设置为f/1.8，'
                    '浅景深，柔和逆光，皮肤质感细腻\n'
                    '英文: masterpiece, best quality, 1girl, chinese girl, long black hair, brown eyes, white sundress, '
                    'beach, ocean, sunlight, backlight, 85mm, f1.8, bokeh, detailed skin, looking at viewer')
# 启用提示词时模型输出的最大 token 数
AI_PROMPT_MAX_TOKENS = 800

# AI 辅助分析：从页面 URL 样本中找出目标链接规律（规则抓不到时使用）
AI_ANALYZE_PROMPT = ('我是网页抓取工具，规则识别不到目标链接，需要你帮忙从 URL 样本中找出规律。\n'
                     '下面是页面中提取到的 URL 样本（每行一个），其中一部分是目标链接，其余是导航/装饰链接。\n'
                     '目标类型：{target_desc}\n'
                     '请找出能匹配目标链接的正则表达式（Python re 风格，只写表达式本身）。\n'
                     '注意：数字ID的长度可能变化，优先用 + 或 * 而不是固定的 {n} 数量。\n'
                     '输出严格按以下两行（没有就写"无"）：\n'
                     '链接正则: <正则表达式>\n'
                     '特征描述: <一句话说明目标链接的特征>\n'
                     '要求：正则必须能匹配样本中的目标链接，且尽量不匹配导航/装饰链接。\n'
                     'URL样本：\n{urls}')

# AI 下载前预筛：仅依据 URL 判断正文图/装饰图（文本模式，速度快）
AI_PRESCREEN_PROMPT = ('以下每行是一个图片URL（来自网页抓取）。请逐行判断：'
                       '它是帖子"正文图"（写真、摄影、插画等帖子内容）还是"装饰"'
                       '（logo、图标、头像、按钮、表情、横幅、广告）。只依据URL的路径和文件名特征判断。\n'
                       '逐行输出，每行只写两个字：下  或  跳过\n'
                       'URL列表：\n{urls}')

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
        self.root.geometry('900x740')
        self.root.minsize(800, 550)

        self.is_running = False
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()  # 暂停标志
        self.cfg = load_config()

        # AI 过滤状态
        self.ai_proc = None          # llama-server 进程
        self.ai_ok = False           # 服务是否就绪
        self.ai_cache = {}           # 图片路径 -> 判断结果缓存
        self._ai_state = '未启动'     # 服务状态（工作线程写入，主线程轮询显示）
        self.ai_toggle_btn = None    # 设置窗口里的启停按钮（打开设置窗口时才创建）
        self.ai_status_var = None    # 设置窗口里的状态标签
        self.settings_win = None     # 设置窗口句柄

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
        # AI 过滤设置（旧预设名自动回退到新默认）
        preset = self.cfg.get('ai_preset', '内置4B（6G显存）')
        if preset not in AI_MODEL_PRESETS:
            preset = '内置4B（6G显存）'
        self.ai_filter_var.set(self.cfg.get('ai_filter', False))
        self.ai_prompt_var.set(self.cfg.get('ai_prompt', False))
        self.ai_auto_stop_var.set(self.cfg.get('ai_auto_stop', False))
        self.ai_prescreen_var.set(self.cfg.get('ai_prescreen', False))
        self.ai_preset_var.set(preset)
        self.ai_model_var.set(self.cfg.get('ai_model', ''))
        self.ai_mmproj_var.set(self.cfg.get('ai_mmproj', ''))
        self.ai_server_var.set(self.cfg.get('ai_server', AI_SERVER_DEFAULT))
        self.ai_port_var.set(self.cfg.get('ai_port', AI_DEFAULT_PORT))
        self.ai_chat_ctx_var.set(self.cfg.get('ai_chat_ctx', 12))
        self._ai_apply_preset()

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
            # AI 过滤设置
            'ai_filter': self.ai_filter_var.get(),
            'ai_prompt': self.ai_prompt_var.get(),
            'ai_auto_stop': self.ai_auto_stop_var.get(),
            'ai_prescreen': self.ai_prescreen_var.get(),
            'ai_preset': self.ai_preset_var.get(),
            'ai_model': self.ai_model_var.get().strip(),
            'ai_mmproj': self.ai_mmproj_var.get().strip(),
            'ai_server': self.ai_server_var.get().strip(),
            'ai_port': self.ai_port_var.get(),
            'ai_chat_ctx': self.ai_chat_ctx_var.get(),
        })
        save_config(self.cfg)

    # ===== AI 智能过滤方法 =====
    def _ai_apply_preset(self):
        """按预设自动填充模型路径"""
        name = self.ai_preset_var.get()
        m, v = AI_MODEL_PRESETS.get(name, (None, None))
        if m:
            self.ai_model_var.set(m)
        if v:
            self.ai_mmproj_var.set(v)

    def _browse_ai_file(self, var_name):
        """浏览选择模型/服务文件"""
        path = filedialog.askopenfilename(title='选择文件', filetypes=[('模型/程序', '*.gguf *.exe'), ('所有文件', '*.*')])
        if path:
            getattr(self, var_name).set(path)

    def _ai_update_status(self, text, color='#888'):
        if self.ai_status_var is not None:
            self.ai_status_var.set(text)
        if self.ai_toggle_btn is not None:
            running = self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)
            self.ai_toggle_btn.config(text='停止AI服务' if running else '启动AI服务')

    def _ai_toggle_server(self):
        """启动/停止 AI 服务"""
        if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
            self._stop_ai_server()
        else:
            self._start_ai_server()

    def _start_ai_server(self):
        """启动 llama-server 本地服务"""
        if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
            return
        server = self.ai_server_var.get().strip() or AI_SERVER_DEFAULT
        model = self.ai_model_var.get().strip()
        mmproj = self.ai_mmproj_var.get().strip()
        if not os.path.exists(server):
            self._log('AI服务: 找不到 llama-server.exe：%s' % server)
            self._ai_update_status('服务程序不存在')
            return
        if not os.path.exists(model) or not os.path.exists(mmproj):
            self._log('AI服务: 模型文件不存在，请检查主模型/视觉模块路径')
            self._ai_update_status('模型文件不存在')
            return
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
        except Exception:
            port = AI_DEFAULT_PORT
        args = [server, '-m', model, '--mmproj', mmproj,
                '-ngl', '999', '-c', '8192', '--parallel', '1',
                '--image-min-tokens', '1024', '--cache-ram', '0',
                '--reasoning', 'off',
                '--host', '127.0.0.1', '--port', str(port)]
        try:
            CREATE_NO_WINDOW = 0x08000000
            self.ai_proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._log('AI服务: 启动失败: %s' % e)
            self._ai_update_status('启动失败')
            return
        self._log('AI服务: 正在启动（加载模型约10秒）...')
        self._ai_update_status('启动中...')
        self._ai_state = '启动中'
        threading.Thread(target=self._ai_wait_ready, args=(port,), daemon=True).start()
        self.root.after(500, self._ai_poll_status)

    def _ai_wait_ready(self, port):
        """工作线程：轮询服务就绪状态（只写普通属性，不碰 tkinter）"""
        import requests
        for _ in range(90):
            time.sleep(1)
            if self.ai_proc is None or self.ai_proc.poll() is not None:
                self._ai_state = '启动失败'
                return
            try:
                r = requests.get('http://127.0.0.1:%d/health' % port, timeout=2)
                if r.status_code == 200:
                    self.ai_ok = True
                    self._ai_state = '运行中'
                    return
            except Exception:
                pass
        self._ai_state = '启动超时'

    def _ai_poll_status(self):
        """主线程轮询：把工作线程的 _ai_state 更新到界面"""
        if self._ai_state == '启动中':
            self.root.after(500, self._ai_poll_status)
            return
        if self._ai_state == '启动失败':
            self._log('AI服务: 启动失败（进程退出）')
        elif self._ai_state == '启动超时':
            self._log('AI服务: 启动超时，请检查模型文件是否损坏或端口被占用')
        elif self._ai_state == '运行中':
            self._log('AI服务: 已就绪')
        self._ai_update_status(self._ai_state)

    def _stop_ai_server(self):
        """停止 AI 服务"""
        if self.ai_proc:
            try:
                self.ai_proc.terminate()
            except Exception:
                pass
            try:
                self.ai_proc.kill()
            except Exception:
                pass
        self.ai_proc = None
        self.ai_ok = False
        self._ai_state = '已停止'
        self._ai_update_status('已停止')
        self._log('AI服务: 已停止')

    def _ai_server_ok(self):
        """检查服务是否可用，不可用时提示"""
        if self.ai_ok:
            return True
        self._log('AI过滤: AI服务未运行，请先点击「启动AI服务」（或关闭AI过滤开关）')
        return False

    def _ai_judge_one(self, img_path):
        """单张图片 AI 判断。
        返回 '正文' / '无关' / '保留(...)'（仅过滤模式）；
        启用提示词时返回 {'cat': ..., 'cn': ..., 'en': ...}"""
        if img_path in self.ai_cache:
            return self.ai_cache[img_path]
        import requests
        import base64
        use_prompt = bool(self.ai_prompt_var.get())
        result = '保留(错误)' if not use_prompt else {'cat': '保留(错误)', 'cn': '', 'en': ''}
        try:
            with open(img_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(img_path)[1].lower().lstrip('.') or 'jpg'
            if ext == 'jpeg':
                ext = 'jpeg'
            url = 'data:image/%s;base64,%s' % (ext, b64)
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
            prompt_text = AI_PROMPT_PROMPT if use_prompt else AI_JUDGE_PROMPT
            max_tokens = AI_PROMPT_MAX_TOKENS if use_prompt else 128
            self._ai_log_chat('req', '[图片判断] %s\n%s' % (os.path.basename(img_path), prompt_text))
            r = requests.post(
                'http://127.0.0.1:%d/v1/chat/completions' % port,
                json={'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': url}},
                    {'type': 'text', 'text': prompt_text}]}],
                    'max_tokens': max_tokens, 'temperature': 0.1},
                timeout=300)
            if r.status_code == 200:
                content = (r.json()['choices'][0]['message'].get('content') or '').strip()
                self._ai_log_chat('resp', content or '(空回复)')
                if use_prompt:
                    result = self._ai_parse_prompt(content)
                elif '无关' in content:
                    result = '无关'
                elif '正文' in content:
                    result = '正文'
                else:
                    result = '保留(未知:%s)' % content[:10]
            else:
                if use_prompt:
                    result = {'cat': '保留(HTTP%d)' % r.status_code, 'cn': '', 'en': ''}
                else:
                    result = '保留(HTTP%d)' % r.status_code
        except Exception as e:
            if use_prompt:
                result = {'cat': '保留(错误)', 'cn': '', 'en': ''}
            else:
                result = '保留(错误)'
        self.ai_cache[img_path] = result
        return result

    @staticmethod
    def _ai_parse_prompt(content):
        """解析提示词模式输出：类别/中文/英文 三行格式，返回 dict"""
        cat = '保留(未知)'
        cn = ''
        en = ''
        for line in content.splitlines():
            line = line.strip()
            if line.startswith('类别'):
                val = line.split(':', 1)[1].strip() if ':' in line else ''
                if '无关' in val:
                    cat = '无关'
                elif '正文' in val:
                    cat = '正文'
            elif line.startswith('中文'):
                cn = line.split(':', 1)[1].strip() if ':' in line else ''
            elif line.startswith('英文'):
                en = line.split(':', 1)[1].strip() if ':' in line else ''
        if cat == '保留(未知)':
            # 容错：模型没按格式输出时回退到关键词判断
            if '无关' in content:
                cat = '无关'
            elif '正文' in content:
                cat = '正文'
        return {'cat': cat, 'cn': cn, 'en': en}

    def _ai_log_chat(self, role, content):
        """记录一次 AI 对话到「AI对话」页签：req=发给模型的请求，resp=模型回复"""
        try:
            ts = time.strftime('%H:%M:%S')
            if role == 'req':
                self.ai_chat_text.insert('end', '[%s] → 模型:\n' % ts, 'req')
            else:
                self.ai_chat_text.insert('end', '[%s] ← 模型:\n' % ts, 'resp')
            self.ai_chat_text.insert('end', (content or '') + '\n', role)
            self.ai_chat_text.insert('end', '-' * 70 + '\n', 'sep')
            self.ai_chat_text.see('end')
        except Exception:
            pass

    def _ai_clear_chat(self):
        """清空 AI 对话记录"""
        try:
            self.ai_chat_text.delete('1.0', 'end')
        except Exception:
            pass
        self._ai_chat_history = []

    def _ai_chat_send(self):
        """AI 对话：发送用户消息并显示模型回复（带最近上下文）"""
        text = self.ai_chat_input.get().strip()
        if not text:
            return
        if not (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
            self._log('AI对话: AI服务未运行，请先点击「启动AI服务」')
            return
        self.ai_chat_input.delete(0, 'end')
        self._ai_log_chat('req', text)
        self._ai_chat_history.append({'role': 'user', 'content': text})
        import requests
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
            ctx = int(self.ai_chat_ctx_var.get() or 12)
            messages = self._ai_chat_history[-ctx:]  # 上下文条数可设置（设置窗口）
            r = requests.post(
                'http://127.0.0.1:%d/v1/chat/completions' % port,
                json={'messages': messages, 'max_tokens': 1024, 'temperature': 0.7},
                timeout=300)
            if r.status_code == 200:
                content = (r.json()['choices'][0]['message'].get('content') or '').strip()
                self._ai_log_chat('resp', content or '(空回复)')
                self._ai_chat_history.append({'role': 'assistant', 'content': content})
            else:
                self._ai_log_chat('resp', '(HTTP %d)' % r.status_code)
        except Exception as e:
            self._ai_log_chat('resp', '(调用失败: %s)' % e)

    def _ai_call_text(self, prompt_text, max_tokens=300, timeout=120):
        """通用文本调用本地模型，返回模型输出字符串（失败返回空串）"""
        import requests
        self._ai_log_chat('req', prompt_text)
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
            r = requests.post(
                'http://127.0.0.1:%d/v1/chat/completions' % port,
                json={'messages': [{'role': 'user', 'content': prompt_text}],
                      'max_tokens': max_tokens, 'temperature': 0.1},
                timeout=timeout)
            if r.status_code == 200:
                content = (r.json()['choices'][0]['message'].get('content') or '').strip()
                self._ai_log_chat('resp', content or '(空回复)')
                return content
            self._ai_log_chat('resp', '(HTTP %d)' % r.status_code)
        except Exception as e:
            self._ai_log_chat('resp', '(调用失败: %s)' % e)
        return ''

    def _ai_analyze_patterns(self, samples, target_desc):
        """让模型分析 URL 样本，返回 {'regex':..., 'desc':..., 'hits':n}；失败返回 None"""
        if not samples:
            return None
        seen = set()
        uniq = []
        for s in samples:
            s = (s or '').strip()
            if s and s not in seen:
                seen.add(s)
                uniq.append(s)
            if len(uniq) >= 120:
                break
        if not uniq:
            return None
        import re as _re
        text = AI_ANALYZE_PROMPT.replace('{target_desc}', target_desc).replace('{urls}', '\n'.join(uniq))
        out = self._ai_call_text(text, max_tokens=200, timeout=300)
        if not out:
            return None
        regex = ''
        desc = ''
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('链接正则'):
                regex = line.split(':', 1)[1].strip() if ':' in line else ''
            elif line.startswith('特征描述'):
                desc = line.split(':', 1)[1].strip() if ':' in line else ''
        if not regex or regex == '无':
            return None
        try:
            _re.compile(regex)
        except Exception:
            return None
        hit = [s for s in uniq if _re.search(regex, s)]
        if not hit:
            # 泛化：把固定长度 {n} 换成 + 再试（模型常猜错位数）
            gen = _re.sub(r'\{(\d+)\}', '+', regex)
            if gen != regex:
                try:
                    _re.compile(gen)
                    hit2 = [s for s in uniq if _re.search(gen, s)]
                    if hit2:
                        regex = gen
                        hit = hit2
                except Exception:
                    pass
        # 命中 0 也接受：正则合法即可，最终以实际提取结果为准
        return {'regex': regex, 'desc': desc, 'hits': len(hit)}

    def _get_site_patterns(self, domain):
        """取站点缓存的 AI 分析规律（按域名）"""
        return (self.cfg.get('ai_patterns') or {}).get(domain)

    def _save_site_patterns(self, domain, patterns):
        """保存站点 AI 分析规律到配置（按域名，跨会话复用）"""
        self.cfg.setdefault('ai_patterns', {})[domain] = patterns
        save_config(self.cfg)

    def _ai_prescreen_urls(self, img_urls):
        """下载前 AI 预筛：装饰特征直接剔除，明显正文直接保留，规则拿不准的才调模型"""
        if not img_urls:
            return img_urls
        GOOD_HINTS = ['/photo', '/upload', '/images/', '/img', '/pic', '/202', '/20', '/file', '/i/', '/data/']
        BAD_HINTS = ['smiley', '/common/', 'avatar', 'logo', 'icon', 'button', 'banner', 'emoji']
        keep = []
        suspicious = []
        for u in img_urls:
            uu = u.lower()
            if any(d in uu for d in BAD_HINTS):
                self._log('  预筛剔除[装饰特征]: %s' % u[:70])
                continue  # 规则明确是装饰 → 直接不下
            if any(g in uu for g in GOOD_HINTS):
                keep.append(u)  # 规则明确是正文 → 直接下，不耗算力
            else:
                suspicious.append(u)  # 规则拿不准 → 交给 AI
        if not suspicious:
            return img_urls
        self._log('下载前AI预筛: %d 张规则拿不准，调用模型判断...' % len(suspicious))
        ai_keep = set()
        BATCH = 30
        for i in range(0, len(suspicious), BATCH):
            batch = suspicious[i:i + BATCH]
            text = AI_PRESCREEN_PROMPT.replace('{urls}', '\n'.join(batch))
            out = self._ai_call_text(text, max_tokens=len(batch) * 4 + 20, timeout=300)
            lines = [l.strip() for l in (out or '').splitlines() if l.strip()]
            for idx, url in enumerate(batch):
                verdict = lines[idx] if idx < len(lines) else ''
                if '跳过' in verdict:
                    self._log('  预筛剔除[AI判定装饰]: %s' % url[:70])
                    continue
                ai_keep.add(url)  # 模型没给判定行的默认保留（宁多下不误杀）
        kept = keep + [u for u in suspicious if u in ai_keep]
        self._log('下载前AI预筛完成: 保留 %d，剔除 %d' % (len(kept), len(img_urls) - len(kept)))
        return kept

    def _ai_filter_images(self, save_dir, task_id=None):
        """对已下载图片做 AI 过滤：删除无关图，可选生成提示词 txt，返回删除数量"""
        if not self._ai_server_ok():
            return 0
        files = sorted(glob.glob(os.path.join(save_dir, 'img_*.*')))
        if not files:
            return 0
        use_prompt = bool(self.ai_prompt_var.get())
        self._log('AI过滤: 开始判断 %d 张图片（本地模型，速度较慢，请耐心等待）...' % len(files))
        if use_prompt:
            self._log('AI提示词: 已开启，每张图将生成中英文提示词（耗时更长，约1-2分钟/张）')
        removed = 0
        kept = 0
        prompt_cnt = 0
        for i, fp in enumerate(files, 1):
            if self.stop_flag.is_set():
                self._log('AI过滤: 已停止')
                break
            self.stat_var.set('AI过滤中 %d/%d ...' % (i, len(files)))
            result = self._ai_judge_one(fp)
            name = os.path.basename(fp)
            if use_prompt:
                cat = result.get('cat', '保留(错误)') if isinstance(result, dict) else result
            else:
                cat = result
            if cat == '无关':
                try:
                    os.remove(fp)
                    removed += 1
                    self._log('AI过滤: [%d/%d] 删除 %s（无关图）' % (i, len(files), name))
                except Exception:
                    self._log('AI过滤: [%d/%d] %s 删除失败' % (i, len(files), name))
            else:
                kept += 1
                if use_prompt and isinstance(result, dict):
                    if result.get('cn') or result.get('en'):
                        if self._ai_save_prompt(fp, result):
                            prompt_cnt += 1
                            self._log('AI过滤: [%d/%d] 保留 %s（已生成提示词）' % (i, len(files), name))
                        else:
                            self._log('AI过滤: [%d/%d] 保留 %s（%s）' % (i, len(files), name, cat))
                    else:
                        self._log('AI过滤: [%d/%d] 保留 %s（%s，无提示词）' % (i, len(files), name, cat))
                else:
                    self._log('AI过滤: [%d/%d] 保留 %s（%s）' % (i, len(files), name, cat))
        self._log('AI过滤完成: 保留 %d 张，删除 %d 张%s' % (kept, removed, '，生成提示词 %d 份' % prompt_cnt if prompt_cnt else ''))
        if task_id:
            self._update_task(task_id, status='完成')
        return removed

    def _ai_save_prompt(self, img_path, result):
        """把提示词结果保存为同名 txt（img_001.jpg -> img_001.txt）"""
        try:
            txt_path = os.path.splitext(img_path)[0] + '.txt'
            cn = (result.get('cn') or '').strip()
            en = (result.get('en') or '').strip()
            lines = []
            if cn:
                lines.append('# 中文提示词')
                lines.append(cn)
                lines.append('')
            if en:
                lines.append('# 英文 Tag')
                lines.append(en)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return True
        except Exception:
            return False

    def _on_closing(self):
        """窗口关闭时保存设置"""
        self._save_settings()
        if self.ai_proc:
            try:
                self.ai_proc.terminate()
            except Exception:
                pass
            try:
                self.ai_proc.kill()
            except Exception:
                pass
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

        # AI 对话页签（可直接与本地模型对话 + 自动记录每次 AI 调用）
        ai_tab = ttk.Frame(self.content_notebook)
        self.content_notebook.add(ai_tab, text='AI对话')
        ai_top = ttk.Frame(ai_tab)
        ai_top.pack(fill='x', pady=2, padx=4)
        ttk.Button(ai_top, text='清除', width=6, command=self._ai_clear_chat).pack(side='left')
        ttk.Label(ai_top, text='（蓝色=发给模型的请求，绿色=模型回复；下方输入框可直接与本地模型对话）', foreground='#999').pack(side='left', padx=8)
        self.ai_chat_text = tk.Text(ai_tab, wrap='word', font=('Consolas', 9))
        ai_scroll = ttk.Scrollbar(ai_tab, command=self.ai_chat_text.yview)
        self.ai_chat_text.configure(yscrollcommand=ai_scroll.set)
        ai_scroll.pack(side='right', fill='y')
        self.ai_chat_text.pack(side='left', fill='both', expand=True)
        self.ai_chat_text.tag_configure('req', foreground='#1a56db')
        self.ai_chat_text.tag_configure('resp', foreground='#0d7a3d')
        self.ai_chat_text.tag_configure('sep', foreground='#bbbbbb')
        # 对话输入框
        ai_input_frame = ttk.Frame(ai_tab)
        ai_input_frame.pack(fill='x', pady=3, padx=4)
        self.ai_chat_input = ttk.Entry(ai_input_frame)
        self.ai_chat_input.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.ai_chat_input.bind('<Return>', lambda e: self._ai_chat_send())
        ttk.Button(ai_input_frame, text='发送', width=6, command=self._ai_chat_send).pack(side='left')
        self._ai_chat_history = []

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
        # 设置按钮（模型/保存路径等不常改的配置）
        ttk.Button(url_frame, text='设置', command=self._open_settings, width=6).pack(side='left', padx=3)
        self._load_url_history()

        # 保存目录（只读显示，修改在设置窗口）
        dir_frame = ttk.Frame(top_frame)
        dir_frame.pack(fill='x', pady=1)
        ttk.Label(dir_frame, text='保存到:', width=6).pack(side='left')
        self.dir_var = tk.StringVar(value=os.path.join(os.getcwd(), 'downloads'))
        ttk.Label(dir_frame, textvariable=self.dir_var, foreground='#555').pack(side='left')

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

        # AI 操作行（模型路径等配置在设置窗口）
        ai_opt = ttk.Frame(top_frame)
        ai_opt.pack(fill='x', pady=1)
        self.ai_filter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_opt, text='启用AI过滤', variable=self.ai_filter_var).pack(side='left')
        self.ai_prompt_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_opt, text='AI生成提示词', variable=self.ai_prompt_var).pack(side='left', padx=(8, 0))
        self.ai_auto_stop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_opt, text='抓取完自动停止', variable=self.ai_auto_stop_var).pack(side='left', padx=(8, 0))
        self.ai_prescreen_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_opt, text='下载前AI预筛', variable=self.ai_prescreen_var).pack(side='left', padx=(8, 0))
        ttk.Label(ai_opt, text='模型:').pack(side='left', padx=(10, 2))
        self.ai_preset_var = tk.StringVar(value='内置4B（6G显存）')
        preset_combo = ttk.Combobox(ai_opt, textvariable=self.ai_preset_var, width=24, state='readonly')
        preset_combo['values'] = list(AI_MODEL_PRESETS.keys())
        preset_combo.pack(side='left', padx=2)
        preset_combo.bind('<<ComboboxSelected>>', lambda e: self._ai_apply_preset())
        self.ai_toggle_btn = ttk.Button(ai_opt, text='启动AI服务', command=self._ai_toggle_server, width=12)
        self.ai_toggle_btn.pack(side='left', padx=6)
        self.ai_status_var = tk.StringVar(value=self._ai_state)
        ttk.Label(ai_opt, textvariable=self.ai_status_var, foreground='#888').pack(side='left')

        # AI 模型/服务路径变量（控件在设置窗口）
        self.ai_model_var = tk.StringVar()
        self.ai_mmproj_var = tk.StringVar()
        self.ai_server_var = tk.StringVar(value=AI_SERVER_DEFAULT)
        self.ai_port_var = tk.IntVar(value=AI_DEFAULT_PORT)
        # AI 对话上下文条数（设置窗口）
        self.ai_chat_ctx_var = tk.IntVar(value=12)

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

    def _open_settings(self):
        """打开设置窗口：保存目录/线程/超时/最小图 + AI 模型与服务配置"""
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title('设置')
        win.geometry('640x320')
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        win.protocol('WM_DELETE_WINDOW', self._close_settings)

        # ===== 常规 =====
        gen = ttk.LabelFrame(win, text='常规')
        gen.pack(fill='x', padx=8, pady=6)
        r1 = ttk.Frame(gen)
        r1.pack(fill='x', padx=6, pady=3)
        ttk.Label(r1, text='保存目录:').pack(side='left')
        ttk.Entry(r1, textvariable=self.dir_var, width=48).pack(side='left', padx=2)
        ttk.Button(r1, text='浏览', width=5, command=self._browse_dir).pack(side='left')

        # ===== AI 模型与服务 =====
        ai = ttk.LabelFrame(win, text='AI 模型与服务（本地 Qwen）')
        ai.pack(fill='x', padx=8, pady=6)
        r4 = ttk.Frame(ai)
        r4.pack(fill='x', padx=6, pady=3)
        ttk.Label(r4, text='主模型:').pack(side='left')
        ttk.Entry(r4, textvariable=self.ai_model_var, width=48).pack(side='left', padx=2)
        ttk.Button(r4, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_model_var')).pack(side='left')
        r5 = ttk.Frame(ai)
        r5.pack(fill='x', padx=6, pady=2)
        ttk.Label(r5, text='视觉模块:').pack(side='left')
        ttk.Entry(r5, textvariable=self.ai_mmproj_var, width=48).pack(side='left', padx=2)
        ttk.Button(r5, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_mmproj_var')).pack(side='left')
        r6 = ttk.Frame(ai)
        r6.pack(fill='x', padx=6, pady=2)
        ttk.Label(r6, text='服务程序:').pack(side='left')
        ttk.Entry(r6, textvariable=self.ai_server_var, width=42).pack(side='left', padx=2)
        ttk.Button(r6, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_server_var')).pack(side='left')
        ttk.Label(r6, text='端口:').pack(side='left', padx=(10, 2))
        ttk.Spinbox(r6, from_=1024, to=65535, textvariable=self.ai_port_var, width=6).pack(side='left')
        ttk.Label(r6, text='对话上下文(条):').pack(side='left', padx=(10, 2))
        ttk.Spinbox(r6, from_=1, to=100, textvariable=self.ai_chat_ctx_var, width=5).pack(side='left')

        # 底部按钮
        btn_row = ttk.Frame(win)
        btn_row.pack(fill='x', pady=8)
        ttk.Button(btn_row, text='关闭', command=self._close_settings).pack(side='right', padx=10)

    def _close_settings(self):
        """关闭设置窗口并保存设置"""
        self._save_settings()
        if self.settings_win is not None:
            try:
                self.settings_win.destroy()
            except Exception:
                pass
        self.settings_win = None

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
                # ===== AI 辅助分析（规则抓不到时） =====
                from urllib.parse import urlparse as _up, urljoin as _uj
                domain = _up(current_url).netloc.replace('www.', '')
                patterns = self._get_site_patterns(domain)
                if patterns and patterns.get('link_regex'):
                    import re as _re
                    try:
                        found = [_uj(current_url, m) for m in _re.findall(patterns['link_regex'], html) if m]
                        post_links = list(dict.fromkeys(found))
                        self._log('AI缓存规律命中: 提取到 %d 个帖子链接' % len(post_links))
                    except Exception as e:
                        self._log('AI缓存规律应用失败: %s' % e)
                if len(post_links) == 0 and (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
                    self._log('规则识别失败，调用本地模型分析帖子链接规律（首次较慢，之后自动用缓存）...')
                    samples = []
                    try:
                        for a in page.css('a'):
                            h = a.attrib.get('href', '') or ''
                            if h and not h.startswith('javascript:') and not h.startswith('#'):
                                samples.append(_uj(current_url, h))
                    except Exception:
                        pass
                    result = self._ai_analyze_patterns(samples, '帖子/详情页链接（包含数字ID或特定路径的详情页）')
                    if result:
                        self._log('模型分析规律: %s（样本命中 %d 个）' % (result['regex'], result['hits']))
                        self._save_site_patterns(domain, {'link_regex': result['regex']})
                        import re as _re
                        try:
                            found = [_uj(current_url, m) for m in _re.findall(result['regex'], html) if m]
                            post_links = list(dict.fromkeys(found))
                            self._log('按模型规律提取到 %d 个帖子链接' % len(post_links))
                        except Exception as e:
                            self._log('按模型规律提取失败: %s' % e)
                    else:
                        self._log('模型未能分析出有效规律（可稍后重试）')
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
                if not img_urls:
                    # ===== AI 辅助分析（规则提取不到图片时） =====
                    from urllib.parse import urlparse as _up2, urljoin as _uj2
                    import re as _re2
                    domain2 = _up2(post_url).netloc.replace('www.', '')
                    patterns2 = self._get_site_patterns(domain2)
                    if patterns2 and patterns2.get('img_regex'):
                        try:
                            found = [_uj2(post_url, m) for m in _re2.findall(patterns2['img_regex'], post_html) if m]
                            img_urls = list(dict.fromkeys(found))
                            self._log('  AI缓存规律命中: 提取到 %d 张图片' % len(img_urls))
                        except Exception as e:
                            self._log('  AI缓存规律应用失败: %s' % e)
                    if not img_urls and (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
                        self._log('  规则提取不到图片，调用本地模型分析图片链接规律（首次较慢，之后自动用缓存）...')
                        samples = []
                        try:
                            for m in _re2.findall(r'["\']((?:https?:)?//[^"\']+\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^"\']*)?)["\']', post_html, _re2.IGNORECASE):
                                samples.append(_uj2(post_url, m))
                        except Exception:
                            pass
                        result2 = self._ai_analyze_patterns(samples, '图片链接（图片文件URL，通常是带图片扩展名的直链）')
                        if result2:
                            self._log('  模型分析规律: %s（样本命中 %d 个）' % (result2['regex'], result2['hits']))
                            self._save_site_patterns(domain2, {'img_regex': result2['regex']})
                            try:
                                found = [_uj2(post_url, m) for m in _re2.findall(result2['regex'], post_html) if m]
                                img_urls = list(dict.fromkeys(found))
                                self._log('  按模型规律提取到 %d 张图片' % len(img_urls))
                            except Exception as e:
                                self._log('  按模型规律提取失败: %s' % e)
                        else:
                            self._log('  模型未能分析出有效图片规律（可稍后重试）')
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
        # 下载前 AI 预筛（可选）：只对规则拿不准的 URL 调模型，拿得准的不消耗算力
        if getattr(self, 'ai_prescreen_var', None) is not None and self.ai_prescreen_var.get():
            if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
                try:
                    img_urls = self._ai_prescreen_urls(img_urls)
                except Exception as e:
                    self._log('下载前AI预筛出错（忽略，继续下载）: %s' % e)
            else:
                self._log('下载前AI预筛: AI服务未运行，跳过预筛')
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

        # AI 智能过滤（可选，未启用或服务未启动则自动跳过）
        if self.ai_filter_var.get():
            removed = self._ai_filter_images(save_dir, task_id)
            if removed:
                self.stat_done.set('已下载: %d/%d（AI过滤删除 %d）' % (success, len(img_urls), removed))

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
        # 可选：抓取完成后自动停止 AI 服务，释放显存/内存
        if getattr(self, 'ai_auto_stop_var', None) is not None and self.ai_auto_stop_var.get():
            if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
                self._stop_ai_server()
                self._log('AI服务: 已自动停止（抓取完成，释放显存）')


def main():
    root = tk.Tk()
    app = ScraplingGrabberGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
