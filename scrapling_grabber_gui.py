# -*- coding: utf-8 -*-
"""Scrapling 图片爬虫 - GUI 版本"""
import os
import re
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

# 图片专用请求头：CDN 会看 Accept / Sec-Fetch-* 判断是不是真浏览器在取图，
# 用文档头（Sec-Fetch-Dest: document）会被 Cloudflare 判成爬虫直接 403
IMAGE_HEADERS = {
    'User-Agent': BROWSER_HEADERS['User-Agent'],
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Language': BROWSER_HEADERS['Accept-Language'],
    'Sec-Fetch-Dest': 'image',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-site',
}

# ===== 原图地址推导（v3.1.11）=====
# 不少相册页只暴露缩略图地址，形如 https://img.xchina.io/photos2/<id>/0001_600x0.webp，
# 而同一目录下的 0001.jpg 才是原图（实测 1800x2400 / 520KB，预览只有 600x800 / 49KB）。
# 页面里拿不到原图地址，只能按命名规律猜，所以必须允许回退。
_ORIG_SUFFIX_RE = re.compile(
    r'^(?P<base>.+?)[_-](?P<w>\d{1,5})x(?P<h>\d{1,5})'
    r'(?P<ext>\.(?:jpe?g|png|webp|avif|gif|bmp))$', re.IGNORECASE)


def orig_url_candidates(url):
    """把「预览图地址」扩成按优先级排的候选列表：原图.jpg → 原图(原格式) → 原地址（兜底）。

    猜出来的原图不保证存在（别的站点可能只有预览版），调用方必须按顺序回退。
    """
    fallback = [url]
    try:
        sp = urllib.parse.urlsplit(url)
        m = _ORIG_SUFFIX_RE.match(sp.path)
        if not m:
            return fallback
        base = m.group('base')
        if not base.rsplit('/', 1)[-1]:
            return fallback
        w, h = int(m.group('w')), int(m.group('h'))
        # 尺寸要像个真实尺寸：宽 >=30，高 >=30 或 0（站点用 0 表示"高度自适应"）
        if w < 30 or (h != 0 and h < 30):
            return fallback
        cands = []
        for ext in ('.jpg', m.group('ext')):
            cand = urllib.parse.urlunsplit((sp.scheme, sp.netloc, base + ext, sp.query, ''))
            if cand not in cands and cand != url:
                cands.append(cand)
        cands.append(url)
        return cands
    except Exception:
        return fallback


# ===== 列表页条目形态归一化（v3.1.12）=====
# 判断"列表页里哪些链接才是同一个列表的条目"时，要先抹掉 ID/页码再比形态：
#   /photo/id-6a98940bb9a27.html        -> /photo/id-<ID>.html
#   /photos/series-66600a3a227ee/2.html -> /photos/series-<ID>/<N>.html
_URL_SHAPE_ID_RE = re.compile(r'[0-9a-f]{8,}', re.IGNORECASE)


def url_shape(path):
    """把 URL 路径归一化成「形态模板」（ID 号段/纯数字都替换成占位符）

    列表页上的帖子条目必然同型（同一个模板反复出现），导航/分页则不然，
    所以形态既用来「选条目」，也用来「排除与当前页同型的同类列表页」。
    """
    p = (path or '').lower()
    p = _URL_SHAPE_ID_RE.sub('<ID>', p)
    p = re.sub(r'\d+', '<N>', p)
    return p


def looks_like_media(data):
    """按文件头判断是不是图片/视频。

    猜原图地址猜错时，这类 CDN 常回 **200 + 一小段 HTML**（实测 xchina 的
    /photos2/<id>/0001.webp 就是 200 + text/html），只看状态码会把 HTML 当图片存下来，
    所以必须验魔数。MP4/AVIF/HEIC 都是 ftyp 开头（视频会被后面的伪装嗅探改名 .mp4）。
    """
    if not data or len(data) < 12:
        return False
    head = data[:16]
    if head[:2] == b'\xff\xd8':                         # JPEG
        return True
    if head[:8] == b'\x89PNG\r\n\x1a\n':                # PNG
        return True
    if head[:6] in (b'GIF87a', b'GIF89a'):              # GIF
        return True
    if head[:2] == b'BM':                               # BMP
        return True
    if head[:4] == b'RIFF' and data[8:12] == b'WEBP':   # WebP
        return True
    if head[4:8] == b'ftyp':                            # AVIF / HEIC / MP4
        return True
    if head[:4] in (b'II*\x00', b'MM\x00*'):            # TIFF
        return True
    return False


# ===== 「范围」输入框解析（v3.1.13：原来一个框填 "20" / "15-60"，现拆成起始/终止两个框）=====
def parse_range_pair(start_text, end_text, default_end=20):
    """把「范围」的两个框解析成 (起始序号, 终止序号)，都是 1-based、闭区间。

    留空 / 非法 / 小于 1 一律回退到默认值（起始 1、终止 default_end）；
    填反了（起始 > 终止）自动对调，免得用户手误导致一个帖子都抓不到。
    """
    def _num(text, default):
        try:
            v = int(str(text).strip())
        except Exception:
            return default
        return v if v > 0 else default

    s_text = str(start_text).strip()
    e_text = str(end_text).strip()
    # 兼容：有人会把老的 "15-60" 整段粘进起始框，那就当成区间读
    if '-' in s_text and not e_text:
        a, _, b = s_text.partition('-')
        s_text, e_text = a, b
    s = _num(s_text, 1)
    e = _num(e_text, default_end)
    if s > e:
        s, e = e, s
    return s, e


def split_legacy_range(text, default_end=20):
    """把旧配置里的单框值转成 (起始, 终止)：'20' → (1, 20)，'15-60' → (15, 60)。"""
    t = str(text or '').strip()
    if '-' in t:
        a, _, b = t.partition('-')
        return parse_range_pair(a, b, default_end)
    return parse_range_pair('1', t, default_end)


# ===== 「页码」输入框解析（v3.1.14：与「范围」同款，拆成起始/终止两个框）=====
def parse_page_range(start_text, end_text):
    """把「页码」两个框解析成 (起始页, 终止页)，1-based、闭区间；终止页 0 表示「不限」。

    与 parse_range_pair 的区别只有一点：终止框留空（或填 0 / 非法值）= 不限制，
    保持老用户「自动一路翻到底」的习惯；起始框留空按第 1 页算。
    填反了（起始 > 终止）自动对调，免得一个页都抓不到。
    """
    def _num(text, default):
        try:
            v = int(str(text).strip())
        except Exception:
            return default
        return v if v > 0 else default

    s_text = str(start_text).strip()
    e_text = str(end_text).strip()
    # 兼容：把老的 "3-8" 整段粘进起始框
    if '-' in s_text and not e_text:
        a, _, b = s_text.partition('-')
        s_text, e_text = a, b
    s = _num(s_text, 1)
    e = 0 if not e_text else _num(e_text, 0)
    if e and s > e:
        s, e = e, s
    return s, e


def split_legacy_page_range(text):
    """旧配置里的单框页码 → (起始, 终止)：'0'/空 → (1, 0) 不限，'5' → (1, 5)，'3-8' → (3, 8)。"""
    t = str(text or '').strip()
    if '-' in t:
        a, _, b = t.partition('-')
        return parse_page_range(a, b)
    return parse_page_range('1', t)


class HttpSessions:
    """会话池：直连 / 系统代理 两条通道，自动择优并记住上次成功的那条。

    注意：Windows 上 requests 会通过 urllib.getproxies() 读注册表里的代理设置
    （即使没有任何 HTTP_PROXY 环境变量）。注册表里留着已失效的代理
    （例如 127.0.0.1:10809 但代理软件没开）时，所有请求都会抛 ProxyError，
    所以直连通道必须 trust_env=False，并显式清空 proxies。
    """
    _lock = threading.Lock()
    _sessions = {}
    _preferred = None

    @classmethod
    def get(cls, use_env_proxy):
        with cls._lock:
            key = bool(use_env_proxy)
            if key not in cls._sessions:
                cls._sessions[key] = cls._build(key)
            return cls._sessions[key]

    @staticmethod
    def _build(use_env_proxy):
        import requests
        s = requests.Session()
        s.trust_env = bool(use_env_proxy)
        if not use_env_proxy:
            s.proxies = {'http': None, 'https': None}
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=64, max_retries=0)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        return s

    @classmethod
    def order(cls):
        """上次成功的通道优先，避免每次都先白等一轮超时"""
        if cls._preferred is None:
            return (False, True)
        return (cls._preferred, not cls._preferred)

    @classmethod
    def mark(cls, use_env_proxy):
        cls._preferred = bool(use_env_proxy)


def http_get(url, headers=None, timeout=30, referer=None, allow_proxy_fallback=True):
    """带代理容错 + 会话复用的 GET，返回 requests.Response。

    顺序：先直连（避开注册表里的失效代理）→ 直连网络层失败再退回系统代理
    （用户挂着可用代理访问受限站点时仍然能下）。两条都失败时抛出最后一次异常。
    """
    import requests
    hdrs = dict(BROWSER_HEADERS if headers is None else headers)
    if referer:
        hdrs.setdefault('Referer', referer)
    modes = HttpSessions.order() if allow_proxy_fallback else (False,)
    last_exc = None
    for use_env_proxy in modes:
        sess = HttpSessions.get(use_env_proxy)
        try:
            # (连接超时, 读取超时)：连接阶段短一些，直连不通能快速切到代理通道
            resp = sess.get(url, headers=hdrs, timeout=(10, timeout), verify=False)
            HttpSessions.mark(use_env_proxy)
            return resp
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.exceptions.SSLError) as e:
            last_exc = e
            continue
    raise last_exc


# 图片扩展名
IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.avif')

APP_VERSION = 'v3.1.14'
APP_NAME = '全能网页助手'

# ===== 界面主题（深色科技蓝 / 浅色简约，可一键切换）=====
UI_FONT = 'Microsoft YaHei UI'
FONT_UI = (UI_FONT, 9)
FONT_UI_BOLD = (UI_FONT, 9, 'bold')
FONT_TITLE = (UI_FONT, 13, 'bold')
FONT_MONO = ('Consolas', 9)

THEMES = {
    # 深色科技蓝（默认）
    'dark': {
        'bg': '#0d1220',          # 窗口底色
        'surface': '#151c2c',     # 面板/卡片
        'border': '#242e44',      # 描边
        'input': '#0f1626',       # 输入框
        'fg': '#e8edf7',          # 主文字
        'muted': '#8a97b0',       # 次要文字
        'accent': '#3b82f6',      # 主色（科技蓝）
        'accent_active': '#2f6fe4',
        'accent_fg': '#ffffff',
        'btn': '#1e2739',
        'btn_active': '#2a3752',
        'btn_pressed': '#34446a',
        'btn_disabled_bg': '#171e2d',
        'btn_disabled_fg': '#5b6780',
        'head_bg': '#1b2438',     # 表头
        'select': '#1e3a5f',      # 选中
        'success': '#22c55e',
        'warn': '#f59e0b',
        'danger': '#ef4444',
        'danger_active': '#dc2626',
        'text_bg': '#0f1523',     # 日志/对话区
        'bubble_req': '#1d2c4a',  # 我的气泡
        'bubble_resp': '#1b3327',  # AI 气泡
        'tag_ts': '#7c89a4', 'tag_req': '#7cb0ff', 'tag_resp': '#5fd08a',
        'tag_tool': '#f0b429', 'tag_sep': '#3a4661',
    },
    # 浅色简约
    'light': {
        'bg': '#eef1f7',
        'surface': '#ffffff',
        'border': '#dbe1ec',
        'input': '#ffffff',
        'fg': '#1f2937',
        'muted': '#6b7280',
        'accent': '#2563eb',
        'accent_active': '#1d4ed8',
        'accent_fg': '#ffffff',
        'btn': '#f1f4fa',
        'btn_active': '#e3e9f5',
        'btn_pressed': '#d6dff0',
        'btn_disabled_bg': '#f5f6f9',
        'btn_disabled_fg': '#a8b0bd',
        'head_bg': '#f3f5fa',
        'select': '#dbe7ff',
        'success': '#16a34a',
        'warn': '#d97706',
        'danger': '#dc2626',
        'danger_active': '#b91c1c',
        'text_bg': '#ffffff',
        'bubble_req': '#e3f2fd',
        'bubble_resp': '#e8f5e9',
        'tag_ts': '#999999', 'tag_req': '#1a56db', 'tag_resp': '#0d7a3d',
        'tag_tool': '#b45309', 'tag_sep': '#bbbbbb',
    },
}


def ver_gt(a, b):
    """版本号比较：a > b 返回 True（支持 1.2.3 / 1.2.3-beta 形式）"""
    def tup(v):
        out = []
        for x in str(v).replace('-', '.').split('.'):
            if x.isdigit():
                out.append(int(x))
            else:
                out.append(x)
        return out
    return tup(a) > tup(b)

# ===== AI 过滤配置 =====
AI_DEFAULT_PORT = 8080
# llama-server 可执行文件（官方预编译版）
AI_SERVER_DEFAULT = r'L:\工作流\千问无审查模型配置\llama-b9375-cuda13\llama-server.exe'

# 云端 API 服务商预设（选服务商自动填 API 地址）
AI_PROVIDERS = {
    '智谱开放平台': 'https://open.bigmodel.cn/api/paas/v4',
    '硅基流动': 'https://api.siliconflow.cn/v1',
    '深度求索(DeepSeek)': 'https://api.deepseek.com/v1',
    'OpenRouter': 'https://openrouter.ai/api/v1',
    'OpenAI': 'https://api.openai.com/v1',
    'Ollama(本地)': 'http://127.0.0.1:11434/v1',
    '自定义': '',
}
# 模型预设：名称 -> (主模型, 视觉模型)
AI_MODEL_PRESETS = {
    '内置4B（无审查·6G显存）': (
        r'L:\ComfyUI\ComfyUI\models\LLM\Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf',
        r'L:\ComfyUI\ComfyUI\models\LLM\mmproj-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-BF16.gguf',
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

# ===== WASM 内存扫描（网页游戏修改器）=====
# 支持的数据类型（typed array 名称）
WASM_TYPES = ('i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'f32', 'f64')
WASM_TYPE_SIZE = {'i8': 1, 'u8': 1, 'i16': 2, 'u16': 2, 'i32': 4, 'u32': 4, 'f32': 4, 'f64': 8}

# 注入页面的引导脚本：枚举 WASM 线性内存（WebAssembly.Memory / Emscripten HEAPU8.buffer）。
# 缓存的是 Memory 对象本身而非 buffer —— memory.grow() 后旧 buffer 会 detach，
# 所以每次读写都要重新取 .buffer。结果存 window.__wgWasm，页面刷新后自动重建（幂等）。
WASM_BOOT_JS = r'''
if(!window.__wgFind){window.__wgFind=function(){
 var out=[],seen=[];
 function addMem(m){
  if(!m)return;var b=null;
  try{b=m.buffer;}catch(e){return;}
  if(!b||b.byteLength<4096)return;
  for(var i=0;i<out.length;i++){if(out[i].m===m)return;}
  /* 若已按裸 ArrayBuffer 登记过同一块内存，换成 Memory 条目（能跟随 grow） */
  for(var j=out.length-1;j>=0;j--){if(out[j].ab&&out[j].ab===b){out.splice(j,1);}}
  out.push({m:m});}
 function addBuf(b){
  if(!b||b.byteLength<65536)return;
  for(var i=0;i<out.length;i++){var e=out[i];var eb=null;
   try{eb=e.m?e.m.buffer:e.ab;}catch(err){}
   if(eb===b)return;}
  out.push({ab:b});}
 function look(o,d){
  if(d>3||o===null||o===undefined||out.length>=64)return;
  try{if(o instanceof WebAssembly.Memory){addMem(o);return;}}catch(e){}
  if(typeof o!=='object')return;
  if(o===document||o===navigator||o===location||o===history||o===performance)return;
  if(seen.indexOf(o)>=0)return;seen.push(o);
  if(seen.length>4000)return;
  var ks;try{ks=Object.keys(o);}catch(e){return;}
  if(ks.length>500)ks=ks.slice(0,500);
  for(var i=0;i<ks.length;i++){try{var v=o[ks[i]];
   if(v instanceof WebAssembly.Memory){addMem(v);continue;}
   if(v instanceof ArrayBuffer){addBuf(v);continue;}
   if(v&&typeof v==='object'&&v.buffer instanceof ArrayBuffer&&v.byteLength!==undefined){addBuf(v.buffer);continue;}
   look(v,d+1);
  }catch(e){}}
 }
 try{look(window,0);}catch(e){}
 try{var cand=[window.wasmMemory,(window.Module&&window.Module.wasmMemory),window.__wasmMemory];
  for(var i=0;i<cand.length;i++){var c=cand[i];
   if(c instanceof WebAssembly.Memory){addMem(c);}
   else if(c instanceof ArrayBuffer){addBuf(c);}}}catch(e){}
 try{var h=[window.HEAPU8,window.HEAPU32,window.HEAPF32,window.HEAPF64];
  for(var j=0;j<h.length;j++){if(h[j]&&h[j].buffer instanceof ArrayBuffer){addBuf(h[j].buffer);}}}catch(e){}
 return out;};}
if(!window.__wgMem){window.__wgMem=function(){
 var W=window.__wgWasm;
 if(!W||!W.m||!W.m.length){W=window.__wgWasm={m:window.__wgFind(),t:Date.now()};}
 return W;};}
if(!window.__wgBuf){window.__wgBuf=function(i){
 var W=window.__wgMem();var e=W.m[i];if(!e)return null;
 try{return e.m?e.m.buffer:e.ab;}catch(err){return null;}};}
if(!window.__wgRead){window.__wgRead=function(i,t,o){
 var b=window.__wgBuf(i);if(!b)return null;
 var d=new DataView(b);
 try{switch(t){
  case 'i8':return d.getInt8(o);
  case 'u8':return d.getUint8(o);
  case 'i16':return d.getInt16(o,true);
  case 'u16':return d.getUint16(o,true);
  case 'i32':return d.getInt32(o,true);
  case 'u32':return d.getUint32(o,true);
  case 'f32':return d.getFloat32(o,true);
  case 'f64':return d.getFloat64(o,true);}}catch(e){return null;}
 return null;};}
if(!window.__wgWrite){window.__wgWrite=function(i,t,o,v){
 var b=window.__wgBuf(i);if(!b)return null;
 var d=new DataView(b);
 try{switch(t){
  case 'i8':d.setInt8(o,v);break;
  case 'u8':d.setUint8(o,v);break;
  case 'i16':d.setInt16(o,v,true);break;
  case 'u16':d.setUint16(o,v,true);break;
  case 'i32':d.setInt32(o,v,true);break;
  case 'u32':d.setUint32(o,v,true);break;
  case 'f32':d.setFloat32(o,v,true);break;
  case 'f64':d.setFloat64(o,v,true);break;
  default:return null;}}catch(e){return null;}
 return window.__wgRead(i,t,o);};}
true;
'''

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
    """下载单张图片（直连优先，避开系统里的失效代理）"""
    try:
        resp = http_get(url, headers=IMAGE_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.content
        with open(save_path, 'wb') as f:
            f.write(data)
        return len(data)
    except Exception as e:
        return None


class ScraplingGrabberGUI:
    """Scrapling 图片爬虫 GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title('%s %s' % (APP_NAME, APP_VERSION))
        self.root.geometry('980x800')
        self.root.minsize(860, 640)
        # Windows 上 Tk 最大化后还原失灵的兜底：F11 切换最大化/还原，Esc 强制恢复原尺寸
        self.root.bind('<F11>', self._toggle_maximize)
        self.root.bind('<Escape>', self._restore_window)

        self.is_running = False
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()  # 暂停标志
        self.cfg = load_config()
        # AI 过滤状态
        self.ai_proc = None          # llama-server 进程
        self._ai_busy = False
        self.ai_ok = False           # 服务是否就绪
        self.ai_cache = {}           # 图片路径 -> 判断结果缓存
        self._ai_state = '未启动'     # 服务状态（工作线程写入，主线程轮询显示）
        self.ai_toggle_btn = None    # 设置窗口里的启停按钮（打开设置窗口时才创建）
        self.ai_status_var = None    # 设置窗口里的状态标签
        self.settings_win = None     # 设置窗口句柄

        self._setup_theme()
        self._create_widgets()
        self._load_settings()
        # 窗口关闭时保存设置
        self.root.protocol('WM_DELETE_WINDOW', self._on_closing)
        # 新开软件自动清理残留 llama-server（上次异常退出/手动启动留下的常驻进程）
        self.root.after(1200, self._kill_stale_llama)
        # 显示内核版本信息
        self._log('%s %s' % (APP_NAME, APP_VERSION))
        self._log('Python 版本: %s' % sys.version.split()[0])
        try:
            import scrapling
            self._log('Scrapling 版本: %s' % getattr(scrapling, '__version__', '未知'))
        except Exception:
            self._log('Scrapling 版本: 未安装')

    # ===== 界面主题 =====
    def _setup_theme(self):
        """初始化主题（默认深色科技蓝，配置记住上次选择）"""
        name = self.cfg.get('ui_theme') or 'dark'
        if name not in THEMES:
            name = 'dark'
        self.theme_name = name
        try:
            self.style = ttk.Style(self.root)
        except Exception:
            self.style = ttk.Style()
        try:
            self.style.theme_use('clam')  # clam 支持自定义配色，其他主题改不动
        except Exception:
            pass
        try:
            self.root.option_add('*Font', FONT_UI)
        except Exception:
            pass
        self._apply_theme()

    def _cfg(self, name, **kw):
        """安全设置 ttk 样式（个别选项在部分 Tk 版本不支持，跳过该选项即可）"""
        try:
            self.style.configure(name, **kw)
            return
        except Exception:
            pass
        for k, v in kw.items():
            try:
                self.style.configure(name, **{k: v})
            except Exception:
                pass

    def _map(self, name, **kw):
        try:
            self.style.map(name, **kw)
            return
        except Exception:
            pass
        for k, v in kw.items():
            try:
                self.style.map(name, **{k: v})
            except Exception:
                pass

    def _apply_theme(self):
        """应用当前主题：ttk 控件样式 + 原生 tk 控件配色"""
        p = THEMES.get(self.theme_name, THEMES['dark'])
        self.palette = p
        try:
            self.root.configure(background=p['bg'])
        except Exception:
            pass

        # ---- 全局默认：面板底色统一，控件自动融入卡片 ----
        self._cfg('.', background=p['surface'], foreground=p['fg'],
                  fieldbackground=p['input'], bordercolor=p['border'],
                  troughcolor=p['bg'], focuscolor=p['accent'],
                  selectbackground=p['select'], selectforeground=p['fg'],
                  font=FONT_UI, borderwidth=1)
        self._cfg('TFrame', background=p['surface'], borderwidth=0, relief='flat')
        self._cfg('Card.TFrame', background=p['surface'], borderwidth=1,
                  relief='solid', bordercolor=p['border'])
        self._cfg('Header.TFrame', background=p['surface'], borderwidth=0, relief='flat')
        self._cfg('TLabel', background=p['surface'], foreground=p['fg'])
        self._cfg('Muted.TLabel', foreground=p['muted'])
        self._cfg('Danger.TLabel', foreground=p['danger'])
        self._cfg('Title.TLabel', font=FONT_TITLE, foreground=p['accent'])
        self._cfg('Link.TLabel', foreground=p['accent'],
                  font=(UI_FONT, 9, 'underline'))

        # ---- 按钮：主色 / 危险色 / 普通 ----
        self._cfg('TButton', background=p['btn'], foreground=p['fg'],
                  bordercolor=p['border'], lightcolor=p['btn'], darkcolor=p['btn'],
                  padding=(6, 4), anchor='center', relief='flat', focuscolor=p['accent'])
        self._map('TButton',
                  background=[('active', p['btn_active']), ('pressed', p['btn_pressed']),
                              ('disabled', p['btn_disabled_bg'])],
                  foreground=[('disabled', p['btn_disabled_fg'])],
                  bordercolor=[('focus', p['accent'])])
        for sname, base, active in (('Accent.TButton', 'accent', 'accent_active'),
                                    ('Danger.TButton', 'danger', 'danger_active')):
            self._cfg(sname, background=p[base], foreground=p['accent_fg'],
                      bordercolor=p[base], lightcolor=p[base], darkcolor=p[base],
                      padding=(6, 4), anchor='center', relief='flat')
            self._map(sname,
                      background=[('active', p[active]), ('pressed', p[active]),
                                  ('disabled', p['btn_disabled_bg'])],
                      foreground=[('disabled', p['btn_disabled_fg'])])

        # ---- 顶部工具行专用：紧凑按钮（取消 clam 的等宽下限 width=-1，并收紧内边距，
        #      让「运行控制 + 工具入口 + 抓取参数 + 浏览器/高级」能挤进同一行且不留空档）----
        _row_pad = (4, 2)
        self._cfg('Row.TButton', background=p['btn'], foreground=p['fg'],
                  bordercolor=p['border'], lightcolor=p['btn'], darkcolor=p['btn'],
                  width=-1, padding=_row_pad, anchor='center', relief='flat',
                  focuscolor=p['accent'])
        self._map('Row.TButton',
                  background=[('active', p['btn_active']), ('pressed', p['btn_pressed']),
                              ('disabled', p['btn_disabled_bg'])],
                  foreground=[('disabled', p['btn_disabled_fg'])],
                  bordercolor=[('focus', p['accent'])])
        for sname, base, active in (('Row.Accent.TButton', 'accent', 'accent_active'),
                                    ('Row.Danger.TButton', 'danger', 'danger_active')):
            self._cfg(sname, background=p[base], foreground=p['accent_fg'],
                      bordercolor=p[base], lightcolor=p[base], darkcolor=p[base],
                      width=-1, padding=_row_pad, anchor='center', relief='flat')
            self._map(sname,
                      background=[('active', p[active]), ('pressed', p[active]),
                                  ('disabled', p['btn_disabled_bg'])],
                      foreground=[('disabled', p['btn_disabled_fg'])])

        # ---- 高级面板「功能入口」：比紧凑按钮大一档、加粗、带主色描边，右侧对齐看起来更醒目 ----
        self._cfg('Feature.TButton', background=p['btn_active'], foreground=p['fg'],
                  bordercolor=p['accent'], lightcolor=p['btn_active'], darkcolor=p['btn_active'],
                  width=-1, padding=(16, 6), anchor='center', relief='flat',
                  font=(UI_FONT, 10, 'bold'), focuscolor=p['accent'])
        self._map('Feature.TButton',
                  background=[('active', p['btn_pressed']), ('pressed', p['btn_pressed']),
                              ('disabled', p['btn_disabled_bg'])],
                  foreground=[('disabled', p['btn_disabled_fg'])],
                  bordercolor=[('active', p['accent'])])

        # ---- 输入框 / 下拉 / 数字框 ----
        common = dict(fieldbackground=p['input'], foreground=p['fg'],
                      background=p['input'], bordercolor=p['border'],
                      insertcolor=p['fg'], padding=(5, 4), relief='flat')
        for wname, extra in (('TEntry', {}), ('TCombobox', {'arrowcolor': p['fg']}),
                             ('TSpinbox', {'arrowcolor': p['fg']})):
            self._cfg(wname, **dict(common, **extra))
            self._map(wname, bordercolor=[('focus', p['accent'])],
                      fieldbackground=[('readonly', p['input'])])
        # 顶部工具行专用的紧凑输入控件（与紧凑按钮同高，省宽度）
        row_common = dict(common, padding=(4, 2))
        for wname, extra in (('Row.TEntry', {}), ('Row.TCombobox', {'arrowcolor': p['fg']})):
            self._cfg(wname, **dict(row_common, **extra))
            self._map(wname, bordercolor=[('focus', p['accent'])],
                      fieldbackground=[('readonly', p['input'])])

        # ---- 复选框 / 单选（勾 mark 用 indicatorforeground 画，必须显式给出）----
        for wname in ('TCheckbutton', 'TRadiobutton'):
            self._cfg(wname, background=p['surface'], foreground=p['fg'],
                      indicatorcolor=p['input'], indicatorbackground=p['input'],
                      indicatorforeground=p['accent'],
                      bordercolor=p['border'], focuscolor=p['surface'])
            self._map(wname, indicatorcolor=[('selected', p['accent'])],
                      indicatorbackground=[('selected', p['accent']),
                                           ('pressed', p['btn_active']),
                                           ('active', p['btn_active'])],
                      indicatorforeground=[('selected', p['accent_fg']),
                                           ('disabled', p['muted'])],
                      background=[('active', p['surface'])],
                      foreground=[('disabled', p['muted'])])

        # ---- 标签页 ----
        self._cfg('TNotebook', background=p['bg'], bordercolor=p['border'], tabmargins=(2, 1, 2, 0))
        self._cfg('TNotebook.Tab', background=p['surface'], foreground=p['muted'],
                  bordercolor=p['border'], padding=(14, 6), font=FONT_UI)
        self._map('TNotebook.Tab',
                  background=[('selected', p['accent']), ('active', p['btn_active'])],
                  foreground=[('selected', p['accent_fg']), ('active', p['fg'])],
                  bordercolor=[('selected', p['accent'])])

        # ---- 分组框 ----
        self._cfg('TLabelframe', background=p['surface'], bordercolor=p['border'], relief='solid')
        self._cfg('TLabelframe.Label', background=p['surface'], foreground=p['accent'], font=FONT_UI_BOLD)
        self._cfg('TSeparator', background=p['border'])

        # ---- 表格 ----
        self._cfg('Treeview', background=p['surface'], fieldbackground=p['surface'],
                  foreground=p['fg'], bordercolor=p['border'], rowheight=26, relief='flat')
        self._cfg('Treeview.Heading', background=p['head_bg'], foreground=p['muted'],
                  font=FONT_UI_BOLD, bordercolor=p['border'], relief='flat', padding=(6, 5))
        self._map('Treeview', background=[('selected', p['select'])],
                  foreground=[('selected', p['fg'])])
        self._map('Treeview.Heading', background=[('active', p['btn_active'])])

        # ---- 滚动条 / 进度条 ----
        for wname in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
            self._cfg(wname, background=p['btn'], troughcolor=p['surface'],
                      bordercolor=p['border'], arrowcolor=p['fg'], relief='flat', borderwidth=0)
            self._map(wname, background=[('active', p['btn_active'])])
        self._cfg('TProgressbar', background=p['accent'], troughcolor=p['surface'],
                  bordercolor=p['border'], lightcolor=p['accent'], darkcolor=p['accent'])

        # ---- 原生控件（Text / Listbox / Canvas / Menu）----
        self._apply_widget_theme()

    def _apply_widget_theme(self, widget=None):
        """递归给原生 tk 控件上色（ttk 样式管不到它们）"""
        p = getattr(self, 'palette', THEMES['dark'])
        if widget is None:
            widget = self.root
        stack = [widget]
        while stack:
            w = stack.pop()
            try:
                if isinstance(w, (tk.Tk, tk.Toplevel)):
                    w.configure(background=p['bg'])
                elif isinstance(w, tk.Text):
                    w.configure(background=p['text_bg'], foreground=p['fg'],
                                insertbackground=p['fg'], selectbackground=p['select'],
                                selectforeground=p['fg'], relief='flat', borderwidth=0,
                                highlightthickness=1, highlightbackground=p['border'],
                                highlightcolor=p['border'])
                    # 对话气泡 / 日志高亮跟随主题
                    for tag, key, val in (
                            ('ts', 'foreground', p['tag_ts']),
                            ('req', 'foreground', p['tag_req']),
                            ('resp', 'foreground', p['tag_resp']),
                            ('tool', 'foreground', p['tag_tool']),
                            ('sep', 'foreground', p['tag_sep']),
                            ('req_bubble', 'background', p['bubble_req']),
                            ('resp_bubble', 'background', p['bubble_resp']),
                            ('user', 'background', p['bubble_req']),
                            ('assistant', 'background', p['bubble_resp']),
                    ):
                        try:
                            w.tag_configure(tag, **{key: val})
                        except Exception:
                            pass
                elif isinstance(w, tk.Listbox):
                    w.configure(background=p['input'], foreground=p['fg'],
                                selectbackground=p['select'], selectforeground=p['fg'],
                                relief='flat', borderwidth=1, highlightthickness=1,
                                highlightbackground=p['border'], highlightcolor=p['border'])
                elif isinstance(w, tk.Canvas):
                    w.configure(background=p['surface'], highlightthickness=0)
                elif isinstance(w, tk.Menu):
                    w.configure(background=p['surface'], foreground=p['fg'],
                                activebackground=p['accent'], activeforeground=p['accent_fg'],
                                borderwidth=1, relief='flat', activeborderwidth=0)
            except Exception:
                pass
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass

    def _toggle_theme(self):
        """深浅主题一键切换"""
        self.theme_name = 'light' if self.theme_name == 'dark' else 'dark'
        self.cfg['ui_theme'] = self.theme_name
        save_config(self.cfg)
        self._apply_theme()
        try:
            self.theme_btn.configure(
                text='切换深色' if self.theme_name == 'light' else '切换浅色')
        except Exception:
            pass
        try:
            self._log('界面主题已切换：%s' % ('浅色简约' if self.theme_name == 'light' else '深色科技蓝'))
        except Exception:
            pass

    def _dir_remember(self, path=None):
        """把目录记进历史（最近 12 个，当前值排最前）"""
        d = (path or self.dir_var.get()).strip()
        if not d:
            return
        d = os.path.normpath(d)
        hist = [x for x in getattr(self, '_dir_history', []) if os.path.normpath(x) != d]
        self._dir_history = ([d] + hist)[:12]

    def _dir_refresh_combo(self):
        """刷新设置窗口里的保存目录下拉（历史目录，最多 12 个，当前值排最前）"""
        combo = getattr(self, 'dir_combo', None)
        if combo is None:
            return
        try:
            if not combo.winfo_exists():
                return
        except Exception:
            self.dir_combo = None
            return
        try:
            self._dir_remember(self.dir_var.get())
            combo['values'] = list(self._dir_history)
        except Exception:
            pass

    def _on_dir_pick(self):
        """从下拉里选了历史目录 → 记为最近使用并立即保存设置"""
        try:
            self._dir_remember(self.dir_var.get())
            self._save_settings()
            self._dir_refresh_combo()
            self._log('保存目录已切换为: %s' % self.dir_var.get())
        except Exception:
            pass

    def _toggle_advanced(self):
        """展开/收起顶部高级选项面板"""
        if getattr(self, '_adv_packed', False):
            self.adv_frame.pack_forget()
            self.adv_toggle_btn.configure(text='高级选项 ▾')
            self._adv_packed = False
        else:
            self.adv_frame.pack(fill='x', pady=(6, 4))
            self.adv_toggle_btn.configure(text='收起选项 ▴')
            self._adv_packed = True
            # 面板比工具行宽：把窗口最小宽度抬到能完整显示面板，避免展开后被右侧切掉
            try:
                need = int(self.adv_frame.winfo_reqwidth()) + 44
                if need > 880:
                    self.root.minsize(need, 640)
            except Exception:
                pass

    # ===== 运行控制行（暂停/停止/重试失败）的显隐 =====
    def _show_run_bar(self, show=True):
        """运行控制行平时隐藏（顶部只留网址那一行）；
        开始抓取时自动出现，任务结束且没有可重试任务时自动收起"""
        bf = getattr(self, 'btn_frame', None)
        if bf is None:
            return

        def _apply():
            try:
                adv = getattr(self, 'adv_frame', None)
                if show:
                    if not bf.winfo_manager():
                        if adv is not None and adv.winfo_manager():
                            bf.pack(fill='x', pady=(3, 1), before=adv)
                        else:
                            bf.pack(fill='x', pady=(3, 1))
                    self._run_bar_visible = True
                else:
                    if bf.winfo_manager():
                        bf.pack_forget()
                    self._run_bar_visible = False
            except Exception:
                pass

        # 可能从工作线程调用：统一回到主线程再动控件
        try:
            self.root.after(0, _apply)
        except Exception:
            _apply()

    def _sync_run_bar(self):
        """运行中、或列表里还有失败任务可重试 → 保持显示；否则收起
        （顺带把「重试失败」按钮校准成：真的存在失败任务才可用）"""
        show = bool(getattr(self, 'is_running', False))
        if not show and getattr(self, 'retry_btn', None) is not None:
            try:
                has_failed = False
                for item in self.task_tree.get_children():
                    vals = self.task_tree.item(item, 'values')
                    if len(vals) > 4 and str(vals[4]) in ('失败', '部分失败'):
                        has_failed = True
                        break
                self.retry_btn.config(state=('normal' if has_failed else 'disabled'))
                show = has_failed
            except Exception:
                try:
                    show = str(self.retry_btn.cget('state')) != 'disabled'
                except Exception:
                    show = False
        self._show_run_bar(show)


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
        self._dir_history = list(self.cfg.get('save_dirs') or [])
        self.dir_var.set(os.path.normpath(self.cfg.get('save_dir') or default_dir))
        self._dir_remember(self.dir_var.get())
        self.threads_var.set(self.cfg.get('threads', 8))
        self.timeout_var.set(self.cfg.get('timeout', 15))
        self.smart_filter_var.set(self.cfg.get('smart_filter', True))
        self.download_video_var.set(self.cfg.get('download_video', False))
        self.render_mode_var.set(self.cfg.get('render_mode', '直连模式'))
        self.grab_mode_var.set(self.cfg.get('grab_mode', '单页'))
        # 范围（v3.1.13 起拆成起始/终止两个框；旧配置里的 '20' / '15-60' 自动拆开）
        _rng_s, _rng_e = split_legacy_range(self.cfg.get('post_range', '20'))
        self.post_range_start_var.set(self.cfg.get('post_range_start', _rng_s))
        self.post_range_end_var.set(self.cfg.get('post_range_end', _rng_e))
        # 页码（v3.1.14 起同样拆成两个框；旧键 page_num 的 '0'=不限 / '5' 自动转换）
        _pg_s, _pg_e = split_legacy_page_range(self.cfg.get('page_num', '0'))
        self.page_range_start_var.set(self.cfg.get('page_range_start', _pg_s))
        self.page_range_end_var.set(self.cfg.get('page_range_end', '' if not _pg_e else _pg_e))
        self.min_size_var.set(self.cfg.get('min_size', 0))
        if hasattr(self, 'convert_webp_var'):
            self.convert_webp_var.set(self.cfg.get('convert_webp', False))
            self.convert_avif_var.set(self.cfg.get('convert_avif', False))
            self.jpg_quality_var.set(self.cfg.get('jpg_quality', 90))
        if hasattr(self, 'orig_img_var'):
            self.orig_img_var.set(self.cfg.get('orig_img', True))
        # AI 过滤设置（旧预设名自动回退到新默认）
        preset = self.cfg.get('ai_preset', '内置4B（无审查·6G显存）')
        if preset not in AI_MODEL_PRESETS:
            preset = '内置4B（无审查·6G显存）'
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
        self.ai_mode_var.set(self.cfg.get('ai_mode', 'local'))
        self.ai_api_base_var.set(self.cfg.get('ai_api_base', ''))
        # 按地址反推服务商预设（命中则选中，否则自定义）
        cur_base = self.ai_api_base_var.get().strip().rstrip('/')
        matched = next((k for k, v in AI_PROVIDERS.items() if v and v == cur_base), '自定义')
        self.ai_provider_var.set(matched)
        # 各服务商独立配置（Key/LLM/VLM/模型列表），切服务商自动带上
        self._ai_providers_cfg = dict(self.cfg.get('ai_providers_cfg') or {})
        pcfg = self._ai_providers_cfg.get(matched) or {}
        self.ai_api_key_var.set(pcfg.get('key', self.cfg.get('ai_api_key', '')))
        self.ai_api_key_var.set(self.cfg.get('ai_api_key', ''))
        self.ai_api_model_var.set(pcfg.get('llm', self.cfg.get('ai_api_model', '')))
        self.ai_api_vlm_var.set(pcfg.get('vlm', self.cfg.get('ai_api_vlm', '')))
        self._ai_api_models = list(pcfg.get('models') or self.cfg.get('ai_api_models') or [])
        self.ai_api_no_thinking_var.set(self.cfg.get('ai_api_no_thinking', False))
        self.ai_api_adv_var.set(self.cfg.get('ai_api_adv', False))
        self.ai_api_temperature_var.set(self.cfg.get('ai_api_temperature', 0.3))
        self.ai_api_max_tokens_var.set(self.cfg.get('ai_api_max_tokens', 1024))
        self._ai_apply_preset(auto=True)

    def _save_settings(self):
        """保存当前设置到配置文件"""
        # 先把当前服务商的 Key/模型配置归档
        self._save_provider_state()
        self.cfg.pop('post_range', None)   # 旧键（单框 "20"/"15-60"）已拆成下面两个
        self.cfg.pop('page_num', None)     # 旧键（单框 "0"/"5"）已拆成 page_range_*
        self.cfg.update({
            'url': self.url_var.get().strip(),
            'save_dir': os.path.normpath(self.dir_var.get().strip()),
            'save_dirs': list(getattr(self, '_dir_history', [])),
            'threads': self.threads_var.get(),
            'timeout': self.timeout_var.get(),
            'smart_filter': self.smart_filter_var.get(),
            'download_video': self.download_video_var.get(),
            'render_mode': self.render_mode_var.get(),
            'grab_mode': self.grab_mode_var.get(),
            'post_range_start': self.post_range_start_var.get(),
            'post_range_end': self.post_range_end_var.get(),
            'page_range_start': self.page_range_start_var.get(),
            'page_range_end': self.page_range_end_var.get(),
            'min_size': self.min_size_var.get(),
            'convert_webp': self.convert_webp_var.get(),
            'convert_avif': self.convert_avif_var.get(),
            'jpg_quality': self.jpg_quality_var.get(),
            'orig_img': getattr(self, 'orig_img_var', None) and self.orig_img_var.get(),
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
            'ai_mode': self.ai_mode_var.get(),
            'ai_api_base': self.ai_api_base_var.get().strip(),
            'ai_api_key': self.ai_api_key_var.get().strip(),
            'ai_api_model': self.ai_api_model_var.get().strip(),
            'ai_api_vlm': self.ai_api_vlm_var.get().strip(),
            'ai_api_models': list(getattr(self, '_ai_api_models', [])),
            'ai_providers_cfg': dict(getattr(self, '_ai_providers_cfg', {})),
            'ai_api_no_thinking': self.ai_api_no_thinking_var.get(),
            'ai_api_adv': self.ai_api_adv_var.get(),
            'ai_api_temperature': self.ai_api_temperature_var.get(),
            'ai_api_max_tokens': self.ai_api_max_tokens_var.get(),
        })
        save_config(self.cfg)

    # ===== AI 智能过滤方法 =====
    def _ai_apply_preset(self, auto=False):
        """按预设自动填充模型路径；预设路径失效自动扫描匹配；自定义弹窗点选"""
        name = self.ai_preset_var.get()
        m, v = AI_MODEL_PRESETS.get(name, (None, None))
        ok_m = m and os.path.exists(m)
        ok_v = v and os.path.exists(v)
        if ok_m:
            self.ai_model_var.set(m)
        if ok_v:
            self.ai_mmproj_var.set(v)
        if ok_m and ok_v:
            return
        # 预设路径失效（文件被移走/改名）：自动扫描模型目录重新配对
        if name != '自定义':
            found = self._ai_auto_find_model()
            if found:
                self.ai_model_var.set(found[0])
                self.ai_mmproj_var.set(found[1])
                self._log('AI服务: 预设路径失效，已自动匹配 → %s' % os.path.basename(found[0]))
                return
        if auto:
            return  # 启动自动加载阶段不弹窗
        # 自定义 / 自动匹配失败：弹窗让用户点选
        self._ai_pick_model_dialog()

    def _ai_auto_find_model(self):
        """扫描 LLM 模型目录，自动配对「主模型 + mmproj 视觉模块」；返回 (model, mmproj) 或 None"""
        for d in (r'L:\ComfyUI\ComfyUI\models\LLM',):
            if not os.path.isdir(d):
                continue
            try:
                files = os.listdir(d)
            except Exception:
                continue
            mmprojs = sorted(f for f in files
                             if f.lower().startswith('mmproj-') and f.lower().endswith('.gguf'))
            mains = sorted(f for f in files
                           if f.lower().endswith('.gguf') and not f.lower().startswith('mmproj-'))
            for mm in mmprojs:
                stem = mm[7:-4].lower()  # 去 mmproj- 前缀和 .gguf
                for suf in ('-bf16', '-fp16', '-f16', '-q8', '-q4'):
                    if stem.endswith(suf):
                        stem = stem[:-len(suf)]
                        break
                for main in mains:
                    mstem = main[:-4].lower()
                    if mstem == stem or mstem.startswith(stem):
                        return (os.path.join(d, main), os.path.join(d, mm))
        return None

    def _ai_pick_model_dialog(self):
        """自定义模型：连续弹窗点选 主模型 + 视觉模块（默认目录=LLM 模型目录）"""
        base = r'L:\ComfyUI\ComfyUI\models\LLM'
        m = filedialog.askopenfilename(
            title='选择主模型 (gguf)', initialdir=base if os.path.isdir(base) else None,
            filetypes=[('GGUF模型', '*.gguf'), ('所有文件', '*.*')])
        if not m:
            return
        self.ai_model_var.set(os.path.normpath(m))
        v = filedialog.askopenfilename(
            title='选择视觉模块 mmproj (gguf)', initialdir=os.path.dirname(m),
            filetypes=[('GGUF模型', '*.gguf'), ('所有文件', '*.*')])
        if v:
            self.ai_mmproj_var.set(os.path.normpath(v))

    def _browse_ai_file(self, var_name):
        """浏览选择模型/服务文件（初始目录=当前值所在目录）"""
        cur = getattr(self, var_name).get().strip()
        init = os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else None
        path = filedialog.askopenfilename(title='选择文件', initialdir=init,
                                          filetypes=[('模型/程序', '*.gguf *.exe'), ('所有文件', '*.*')])
        if path:
            getattr(self, var_name).set(os.path.normpath(path))
            # 选完主模型/视觉模块后，实时提示配对情况
            try:
                m = self.ai_model_var.get().strip()
                v = self.ai_mmproj_var.get().strip()
                if m and v and os.path.exists(m) and os.path.exists(v):
                    bad = self._ai_check_model_match(m, v)
                    if bad:
                        self._log('提示: 主模型与视觉模块可能不匹配 - %s' % '；'.join(bad))
            except Exception:
                pass

    def _ai_update_status(self, text, color='#888'):
        if self.ai_status_var is not None:
            self.ai_status_var.set(text)
        if self.ai_toggle_btn is not None:
            running = self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)
            self.ai_toggle_btn.config(text='停止AI服务' if running else '启动AI服务')
        self._ai_light(text)

    def _ai_light(self, text):
        """AI 服务状态灯：绿=运行中 黄=启动中 红=异常 灰=已停止/待启动"""
        if not getattr(self, 'ai_status_light', None):
            return
        t = text or ''
        if '运行中' in t:
            c = '#4caf50'
        elif '启动中' in t:
            c = '#ffc107'
        elif '已停止' in t or '待启动' in t:
            c = '#9e9e9e'
        elif ('失败' in t or '不存在' in t or '未运行' in t or '超时' in t
              or '未配置' in t or '错误' in t or '无法' in t):
            c = '#f44336'
        else:
            c = '#ff9800'
        try:
            self.ai_status_light.itemconfig(self._ai_light_ball, fill=c)
        except Exception:
            pass

    def _ai_toggle_server(self):
        """启动/停止 AI 服务"""
        if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
            self._stop_ai_server()
        else:
            self._start_ai_server()

    def _ai_check_model_match(self, model_path, mmproj_path):
        """校验主模型与视觉模块(mmproj)是否配对；返回问题描述列表（空=匹配）"""
        try:
            m = os.path.basename(model_path).lower()
            v = os.path.basename(mmproj_path).lower()
        except Exception:
            return []
        problems = []
        # 参数量对齐：4B/9B 等
        for tag in ('4b', '9b', '14b', '32b'):
            if tag in m and tag not in v:
                problems.append('主模型是 %s，但视觉模块名里没有 %s' % (tag.upper(), tag.upper()))
                break
        # 无审查/特殊版本标识对齐
        for tag in ('uncensored', 'hauhaucs', 'aggressive'):
            if (tag in m) != (tag in v):
                problems.append('主模型%s「%s」标识，视觉模块%s（可能配错模型组）' % (
                    '带' if tag in m else '不带', tag.upper(),
                    '也带' if tag in m else '没有'))
        return problems

    def _start_ai_server(self):
        """启动/连接 AI 服务：local=拉起llama-server；ollama=检查本机Ollama；api=测试云端连通"""
        if self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None):
            return
        self._ai_busy = False
        try:
            self._save_settings()  # 点启动即记住当前设置，不用再点保存按钮
        except Exception:
            pass
        mode = self.ai_mode_var.get()
        # 先探测本机是否已有 LLM 服务（外部程序已启动则直接复用，不重复拉起）
        try:
            _port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
        except Exception:
            _port = AI_DEFAULT_PORT
        if self._ai_probe_external(_port):
            self.ai_ok = True
            self._ai_state = '运行中'
            self._ai_update_status('运行中(外部服务)')
            self._log('AI服务: 端口%d已有 LLM 服务，直接复用（未启动新进程）' % _port)
            return
        if mode == 'api':
            base = self.ai_api_base_var.get().strip()
            key = self.ai_api_key_var.get().strip()
            model = (self.ai_api_model_var.get().strip()
                     or (getattr(self, '_ai_api_models', [None])[0]
                         if getattr(self, '_ai_api_models', []) else ''))
            if not base or not key or not model:
                self._log('AI服务(API): 请先在设置里填 API地址/Key/模型名')
                self._ai_update_status('API未配置')
                return
            # 连通测试：极短请求
            import requests
            url = base.rstrip('/')
            url = url if url.endswith('/chat/completions') else (
                url + '/chat/completions' if url.endswith('/v1') else url + '/v1/chat/completions')
            try:
                r = requests.post(url,
                                  json={'model': model, 'messages': [{'role': 'user', 'content': 'hi'}],
                                        'max_tokens': 4},
                                  headers={'Authorization': 'Bearer ' + key}, timeout=15)
                if r.status_code != 200:
                    self._log('AI服务(API): 连通测试失败 HTTP %d（%s）' % (r.status_code, r.text[:120]))
                    self._ai_update_status('API测试失败')
                    return
                self.ai_ok = True
                self._ai_state = '运行中'
                self._ai_update_status('运行中(API)')
                self._log('AI服务: 云端API已连通（%s）' % model)
            except Exception as e:
                self._log('AI服务(API): 连接失败: %s' % e)
                self._ai_update_status('API连接失败')
            return
        if mode == 'ollama':
            # Ollama 已由本机服务运行，只检查端口
            import requests
            try:
                port = int(self.ai_port_var.get() or 11434)
            except Exception:
                port = 11434
            try:
                r = requests.get('http://127.0.0.1:%d/v1/models' % port, timeout=5)
                if r.status_code != 200:
                    self._log('AI服务(Ollama): 端口%d无响应（HTTP %d），请先启动Ollama' % (port, r.status_code))
                    self._ai_update_status('Ollama未运行')
                    return
                names = [x.get('id', '') for x in r.json().get('data', [])][:8]
                self.ai_ok = True
                self._ai_state = '运行中'
                self._ai_update_status('运行中(Ollama)')
                self._log('AI服务: Ollama已连接（%s）' % (', '.join(names) if names else '端口%d' % port))
            except Exception as e:
                self._log('AI服务(Ollama): 连接失败: %s' % e)
                self._ai_update_status('Ollama未运行')
            return
        # local：拉起 llama-server
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
        mism = self._ai_check_model_match(model, mmproj)
        if mism:
            warn = ('主模型与视觉模块可能不匹配：\n'
                    + '\n'.join('· ' + s for s in mism)
                    + '\n\n配错会导致看图失败或模型加载报错。仍要强行启动吗？')
            if not messagebox.askyesno('模型不匹配警告', warn, parent=self.root):
                self._log('AI服务: 用户取消（模型不匹配）')
                self._ai_update_status('已取消')
                return
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
        except Exception:
            port = AI_DEFAULT_PORT
        args = [server, '-m', model, '--mmproj', mmproj,
                '-ngl', '999', '-c', '8192', '--parallel', '1',
                '--image-min-tokens', '1024', '--cache-ram', '0',
                '--flash-attn', '1',
                '--reasoning', 'off',
                '--host', '127.0.0.1', '--port', str(port)]
        try:
            CREATE_NO_WINDOW = 0x08000000
            logf = open(os.path.join(os.path.dirname(server), 'llama_server.log'), 'w')
            self.ai_proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW,
                                            stdout=logf, stderr=subprocess.STDOUT)
        except Exception as e:
            self._log('AI服务: 启动失败: %s' % e)
            self._ai_update_status('启动失败')
            return
        self._log('AI服务: 正在启动（加载模型约10秒）...')
        self._ai_update_status('启动中...')
        self._ai_state = '启动中'
        self._ai_fail_reason = ''
        threading.Thread(target=self._ai_wait_ready, args=(port,), daemon=True).start()
        self.root.after(500, self._ai_poll_status)

    def _ai_wait_ready(self, port):
        """工作线程：轮询服务就绪状态（只写普通属性，不碰 tkinter）"""
        try:
            import requests
        except Exception as ex:
            self._ai_state = '启动失败'
            self._ai_fail_reason = '缺少 requests 模块: %s' % ex
            return
        for _ in range(90):
            time.sleep(1)
            if self.ai_proc is None or self.ai_proc.poll() is not None:
                self._ai_state = '启动失败'
                self._ai_fail_reason = 'llama-server 进程退出'
                return
            try:
                r = requests.get('http://127.0.0.1:%d/health' % port, timeout=2)
                if r.status_code == 200:
                    self.ai_ok = True
                    self._ai_state = '运行中'
                    self._ai_fail_reason = ''
                    return
            except Exception:
                pass
        self._ai_state = '启动超时'
        self._ai_fail_reason = '90秒内未就绪'

    def _ai_poll_status(self):
        """主线程轮询：把工作线程的 _ai_state 更新到界面"""
        if self._ai_state == '启动中':
            self.root.after(500, self._ai_poll_status)
            return
        reason = getattr(self, '_ai_fail_reason', '')
        if self._ai_state == '启动失败':
            self._log('AI服务: 启动失败%s' % ('（%s）' % reason if reason else '（进程退出）'))
        elif self._ai_state == '启动超时':
            self._log('AI服务: 启动超时，请检查模型文件是否损坏或端口被占用')
        elif self._ai_state == '运行中':
            self._log('AI服务: 已就绪')
        self._ai_update_status(self._ai_state)

    def _ai_probe_external(self, port):
        """探测本机端口是否已有 LLM 服务在运行（/health 或 /v1/models 返回 200）"""
        try:
            import requests
            for path in ('/health', '/v1/models'):
                try:
                    r = requests.get('http://127.0.0.1:%d%s' % (port, path), timeout=2)
                    if r.status_code == 200:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _kill_stale_llama(self):
        """软件启动时：已有 LLM 服务在跑则保留并标记可用；否则清理残留 llama-server 进程"""
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
        except Exception:
            port = AI_DEFAULT_PORT
        if self._ai_probe_external(port):
            self.ai_ok = True
            self._ai_state = '运行中'
            self._ai_update_status('运行中(外部服务)')
            self._log('AI服务: 检测到已有 LLM 服务（端口%d），直接复用' % port)
            return
        try:
            import subprocess
            r = subprocess.run(['taskkill', '/F', '/IM', 'llama-server.exe'],
                               timeout=10, capture_output=True, text=True, errors='replace')
            out = (r.stdout or '').strip()
            if 'SUCCESS' in out:
                self._log('已自动清理残留 AI 服务进程（llama-server），如需使用 AI 请点「启动AI服务」')
        except Exception as e:
            self._log('清理残留 AI 服务进程失败: %s' % e)

    def _stop_ai_server(self):
        """停止 AI 服务：只终止本程序拉起的进程；外部 LLM 服务保留不杀"""
        external = self.ai_proc is None and getattr(self, 'ai_ok', False)
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
        self._log('AI服务: 已停止%s' % ('（外部服务保留运行）' if external else ''))

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
            ok, resp = self._ai_completion(
                {'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': url}},
                    {'type': 'text', 'text': prompt_text}]}],
                    'max_tokens': max_tokens, 'temperature': 0.1},
                timeout=300)
            if ok:
                content = (resp['choices'][0]['message'].get('content') or '').strip()
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
                    result = {'cat': '保留(调用失败)', 'cn': '', 'en': ''}
                else:
                    result = '保留(调用失败)'
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

    def _ai_log_chat(self, role, content, image_path=None):
        """记录一次 AI 对话到「AI对话」页签和磁吸窗：req=用户消息(右蓝气泡)，resp=模型回复(左绿气泡)
        image_path 存在时在内容前插入图片缩略图"""
        try:
            ts = time.strftime('%H:%M:%S')
            for txt in (self.ai_chat_text, getattr(self, 'ai_float_text', None)):
                if not txt:
                    continue
                try:
                    if role == 'req':
                        bubble, who = 'req_bubble', '你'
                    elif role == 'tool':
                        bubble, who = 'tool', '工具'
                    else:
                        bubble, who = 'resp_bubble', 'AI'
                    txt.insert('end', '  %s  %s\n' % (ts, who), 'ts')
                    if image_path:
                        self._ai_insert_thumb(txt, image_path)
                    txt.insert('end', (content or '') + '\n', bubble)
                    txt.insert('end', '\n')
                    txt.see('end')
                except Exception:
                    pass
        except Exception:
            pass

    def _ai_insert_thumb(self, txt, img_path):
        """在对话 Text 中插入图片缩略图（保持引用防GC回收）"""
        try:
            from PIL import Image
            from PIL import ImageTk
            img = Image.open(img_path)
            img.thumbnail((220, 220))
            photo = ImageTk.PhotoImage(img)
            if not hasattr(self, '_ai_float_images'):
                self._ai_float_images = []
            self._ai_float_images.append(photo)
            txt.image_create('end', image=photo)
            txt.insert('end', '\n')
        except Exception:
            pass

    def _ai_clipboard_image(self):
        """读取剪贴板图片（截图位图或复制的图片文件）→ (b64, path) 或 None"""
        try:
            from PIL import ImageGrab
            import io
            import base64
            img = ImageGrab.grabclipboard()
            # 情况1：复制的是图片文件（Windows返回文件路径列表）
            if isinstance(img, list) and img:
                img_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
                for fn in img:
                    fn = fn if isinstance(fn, str) else fn.decode('utf-8', errors='ignore')
                    if fn.lower().endswith(img_exts) and os.path.exists(fn):
                        with open(fn, 'rb') as f:
                            raw = f.read()
                        # 统一转JPEG
                        try:
                            pim = Image.open(io.BytesIO(raw)).convert('RGB')
                            pim.thumbnail((512, 512))
                            buf = io.BytesIO()
                            pim.save(buf, 'JPEG', quality=85)
                            data = buf.getvalue()
                        except Exception:
                            data = raw
                        b64 = base64.b64encode(data).decode()
                        return b64, fn
                return None
            # 情况2：截图位图
            if img is None or not hasattr(img, 'save'):
                return None
            img = img.convert('RGB')
            img.thumbnail((512, 512))
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
            os.makedirs(shot_dir, exist_ok=True)
            shot_path = os.path.join(shot_dir, 'clip_%s.jpg' % time.strftime('%Y%m%d_%H%M%S'))
            with open(shot_path, 'wb') as f:
                f.write(buf.getvalue())
            self._clean_screenshots(200)
            return b64, shot_path
        except Exception:
            return None

    def _ai_on_ctrl_v(self, entry):
        """AI输入框 Ctrl+V：剪贴板有图优先加图；无图正常粘贴文本"""
        shot = self._ai_clipboard_image()
        if shot:
            b64, path = shot
            self._ai_pending_image = {'b64': b64, 'path': path}
            self._ai_log_chat('req', '[已添加截图] 剪贴板截图已就绪，输入问题后点「发送」即可让AI看图回答')
            self._ai_show_shot_in_chat(path)
            return 'break'
        try:
            entry.event_generate('<<Paste>>')
        except Exception:
            pass
        return 'break'

    def _ai_on_drop_file(self, filenames):
        """拖拽图片文件到输入框：转base64加入待发送图片"""
        import base64, os
        img_exts = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
        for fn in filenames:
            if not fn:
                continue
            fn = fn if isinstance(fn, str) else fn.decode('gbk', errors='ignore')
            if fn.lower().endswith(img_exts):
                try:
                    with open(fn, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('ascii')
                    self._ai_pending_image = {'b64': b64, 'path': fn}
                    self._ai_log_chat('req', '[已添加图片] %s' % os.path.basename(fn))
                    self._ai_show_shot_in_chat(fn)
                    return
                except Exception as e:
                    self._log('拖拽图片失败: %s' % e)

    def _ai_paste_shot(self):
        """「粘贴」：读取剪贴板里的图片（如豆包选区/Win+Shift+S 截图）加入对话"""
        shot = self._ai_clipboard_image()
        if not shot:
            self._log('粘贴截图失败：剪贴板里没有图片（先用豆包选区或 Win+Shift+S 截图）')
            return
        b64, path = shot
        self._ai_pending_image = {'b64': b64, 'path': path}
        self._ai_log_chat('req', '[已添加截图] 剪贴板截图已就绪，输入问题后点「发送」即可让AI看图回答')
        self._ai_show_shot_in_chat(path)

    def _ai_region_shot(self):
        """「选区」：全屏遮罩 + 鼠标框选区域截图加入对话"""
        try:
            from PIL import ImageGrab, Image, ImageTk
            hides = []
            for w in (getattr(self, 'ai_float_win', None), self.root):
                try:
                    if w is not None and w.state() == 'normal':
                        hides.append(w)
                except Exception:
                    pass
            for w in hides:
                w.withdraw()
            self.root.update_idletasks()
            time.sleep(0.4)
            full = ImageGrab.grab().convert('RGB')
            for w in hides:
                try:
                    w.deiconify()
                except Exception:
                    pass
            wpx, hpx = full.size
            # 用 Tk 逻辑屏幕尺寸换算（自动含 DPI，比系统 API 可靠）
            tw = max(1, self.root.winfo_screenwidth())
            th = max(1, self.root.winfo_screenheight())
            if wpx == tw and hpx == th:
                scale_x = scale_y = 1.0
            else:
                scale_x = wpx / float(tw)
                scale_y = hpx / float(th)
            canvas_img = full.copy().resize((tw, th), Image.LANCZOS)
            mask = tk.Toplevel(self.root)
            mask.overrideredirect(True)
            mask.attributes('-topmost', True)
            mask.geometry('%dx%d+0+0' % (tw, th))
            cv = tk.Canvas(mask, width=tw, height=th, cursor='crosshair', highlightthickness=0)
            cv.pack()
            self._mask_photo = ImageTk.PhotoImage(canvas_img)
            cv.create_image(0, 0, anchor='nw', image=self._mask_photo)
            state = {'start': None, 'rect': None}

            def on_press(e):
                state['start'] = (e.x, e.y)
                state['rect'] = cv.create_rectangle(e.x, e.y, e.x, e.y,
                                                    outline='#ff3b30', width=2, fill='rgba(0,0,0,0)')

            def on_drag(e):
                if state['start'] and state['rect']:
                    cv.coords(state['rect'], state['start'][0], state['start'][1], e.x, e.y)

            def on_release(e):
                if not state['start']:
                    return
                x1, y1 = state['start']
                x2, y2 = e.x, e.y
                x1, x2 = sorted((x1, x2))
                y1, y2 = sorted((y1, y2))
                try:
                    mask.destroy()
                except Exception:
                    pass
                if x2 - x1 < 10 or y2 - y1 < 10:
                    self._log('选区截图已取消（区域太小）')
                    return
                px1, py1 = int(x1 * scale_x), int(y1 * scale_y)
                px2, py2 = int(x2 * scale_x), int(y2 * scale_y)
                crop = full.crop((px1, py1, px2, py2))
                self._log('选区: 屏幕%d x %d 遮罩%d x %d 裁剪(%d,%d)-(%d,%d) -> %d x %d'
                          % (wpx, hpx, tw, th, px1, py1, px2, py2, crop.size[0], crop.size[1]))
                import io
                import base64
                buf = io.BytesIO()
                crop.save(buf, 'JPEG', quality=90)
                b64 = base64.b64encode(buf.getvalue()).decode()
                shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
                os.makedirs(shot_dir, exist_ok=True)
                shot_path = os.path.join(shot_dir, 'region_%s.jpg' % time.strftime('%Y%m%d_%H%M%S'))
                with open(shot_path, 'wb') as f:
                    f.write(buf.getvalue())
                self._clean_screenshots(200)
                self._ai_pending_image = {'b64': b64, 'path': shot_path}
                self._ai_log_chat('req', '[已添加截图] 选区截图已就绪，输入问题后点「发送」即可让AI看图回答')
                self._ai_show_shot_in_chat(shot_path)

            def on_cancel(_=None):
                try:
                    mask.destroy()
                except Exception:
                    pass
                self._log('选区截图已取消')

            cv.bind('<ButtonPress-1>', on_press)
            cv.bind('<B1-Motion>', on_drag)
            cv.bind('<ButtonRelease-1>', on_release)
            mask.bind('<Escape>', on_cancel)
        except Exception as e:
            self._log('选区截图失败: %s' % e)

    def _build_character_tab(self):
        """角色聊天标签页（酒馆模式）"""
        tab = ttk.Frame(self.content_notebook)
        self.content_notebook.add(tab, text='角色聊天')

        # 顶部：角色选择
        top = ttk.Frame(tab)
        top.pack(fill='x', padx=4, pady=2)
        ttk.Label(top, text='角色:').pack(side='left')
        self.char_name_var = tk.StringVar(value='默认')
        self.char_combo = ttk.Combobox(top, textvariable=self.char_name_var, width=18, state='readonly')
        self.char_combo['values'] = ['默认', '新建角色...']
        self.char_combo.pack(side='left', padx=4)
        ttk.Button(top, text='导入角色卡', width=10, command=self._char_import).pack(side='left', padx=2)
        ttk.Button(top, text='保存角色', width=10, command=self._char_save).pack(side='left', padx=2)
        ttk.Button(top, text='删除角色', width=10, command=self._char_delete).pack(side='left', padx=2)

        # 人设提示词
        sys_frame = ttk.LabelFrame(tab, text='人设提示词（System Prompt）')
        sys_frame.pack(fill='x', padx=4, pady=2)
        self.char_sys_text = tk.Text(sys_frame, height=4, wrap='word', font=('Microsoft YaHei UI', 9))
        self.char_sys_text.pack(fill='x', padx=4, pady=2)
        self.char_sys_text.insert('1.0', '你是一个友好的AI助手，用自然、亲切的语气和用户对话。')

        # 对话区
        self.char_chat_text = tk.Text(tab, wrap='word', font=('Microsoft YaHei UI', 10))
        char_scroll = ttk.Scrollbar(tab, command=self.char_chat_text.yview)
        self.char_chat_text.configure(yscrollcommand=char_scroll.set)
        self.char_chat_text.tag_configure('ts', font=('Microsoft YaHei UI', 8), foreground='#999')
        self.char_chat_text.tag_configure('user', background='#e3f2fd', lmargin1=60, lmargin2=60, rmargin=10, spacing1=3, spacing3=3)
        self.char_chat_text.tag_configure('assistant', background='#e8f5e9', lmargin1=10, lmargin2=10, rmargin=60, spacing1=3, spacing3=3)
        self.char_chat_text.pack(side='top', fill='both', expand=True, padx=4)
        char_scroll.pack(side='right', fill='y')

        # 输入区
        input_frame = ttk.Frame(tab)
        input_frame.pack(fill='x', padx=4, pady=2)
        self.char_input = tk.Text(input_frame, height=2, wrap='word', font=('Microsoft YaHei UI', 10))
        self.char_input.pack(side='left', fill='x', expand=True)
        self.char_input.bind('<Return>', self._char_on_return)
        btn_frame = ttk.Frame(input_frame)
        btn_frame.pack(side='right', padx=4)
        ttk.Button(btn_frame, text='发送', command=self._char_send).pack(pady=2)
        ttk.Button(btn_frame, text='清空', command=lambda: self.char_chat_text.delete('1.0', 'end')).pack()

    def _char_import(self):
        """导入角色卡（JSON文件）"""
        pass

    def _char_save(self):
        """保存当前角色"""
        pass

    def _char_delete(self):
        """删除角色"""
        pass

    def _char_on_return(self, e):
        if e.state & 0x0004:  # Ctrl+Enter
            return
        self._char_send()
        return 'break'

    def _char_send(self):
        """发送角色聊天消息"""
        text = self.char_input.get('1.0', 'end').strip()
        if not text:
            return
        self.char_input.delete('1.0', 'end')
        self._char_log('你', text, 'user')
        sys_prompt = self.char_sys_text.get('1.0', 'end').strip()
        # 复用AI对话逻辑，注入人设
        self._char_reply(text, sys_prompt)

    def _char_log(self, role, text, tag):
        import datetime
        self.char_chat_text.insert('end', '[%s] ' % datetime.datetime.now().strftime('%H:%M:%S'), 'ts')
        self.char_chat_text.insert('end', role + ': ', tag)
        self.char_chat_text.insert('end', text + '\n\n', tag)
        self.char_chat_text.see('end')

    def _char_reply(self, user_text, sys_prompt):
        """调AI回复角色对话"""
        def worker():
            try:
                body = {
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': user_text},
                    ],
                    'max_tokens': 500,
                    'temperature': 0.8,
                    'stream': False,
                }
                resp = self._ai_completion(body, timeout=120)
                reply = resp['choices'][0]['message']['content']
                self._char_log('AI', reply, 'assistant')
            except Exception as e:
                self._char_log('系统', '错误: %s' % e, 'assistant')
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _open_sillytavern(self):
        """启动SillyTavern并打开内置浏览器，自动启动AI服务"""
        import os, subprocess, time
        # 先启动AI服务
        if not self._ai_server_ok():
            try:
                self._ai_toggle_server()
                # 等待启动
                for _ in range(30):
                    time.sleep(1)
                    if self._ai_server_ok():
                        break
            except Exception:
                pass
        st_dir = r'L:\SillyTavern-1.11.5整合包\SillyTavern-1.11.5'
        try:
            import requests as _rq
            _rq.get('http://127.0.0.1:8000', timeout=2)
            # 已在运行，不重复启动
        except Exception:
            try:
                subprocess.Popen(
                    ['node', 'server.js'],
                    cwd=st_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
                time.sleep(5)
            except Exception:
                pass
        time.sleep(3)
        # 用外部浏览器打开
        import webbrowser
        webbrowser.open('http://127.0.0.1:8000')

    def _ai_clear_chat(self):
        """清空 AI 对话记录（页签+磁吸窗）"""
        try:
            self.ai_chat_text.delete('1.0', 'end')
        except Exception:
            pass
        try:
            if getattr(self, 'ai_float_text', None):
                self.ai_float_text.delete('1.0', 'end')
        except Exception:
            pass
        self._ai_chat_history = []

    # ===== AI 助手模式：工具调用 =====
    AI_TOOL_DESC = (
        '你是「%s」的AI助手，能通过调用工具帮用户完成网页抓取、浏览器操作、游戏数值修改等任务。\n' % APP_NAME +
        '可用工具（严格用这个格式输出，一次只调用一个，参数必须带上）：\n'
        '  [工具:start_crawl {"url":"https://www.example.com/", "mode":"全站", "threads":8}]\n'
        '  [工具:stop_crawl {}]\n'
        '  [工具:pause_crawl {}]\n'
        '  [工具:resume_crawl {}]\n'
        '  [工具:retry_failed {}]\n'
        '  [工具:get_status {}]\n'
        '  [工具:get_task_list {"limit":10}]\n'
        '  [工具:set_save_dir {"path":"L:/tu"}]\n'
        '  [工具:set_filter {"smart_filter":true, "min_size":20}]\n'
        '  [工具:get_settings {}]\n'
        '  [工具:open_save_dir {}]\n'
        '  [工具:get_browser_info {}]\n'
        '  [工具:get_browser_view {"prompt":"关于页面你想问什么，可选"}]\n'
        '  [工具:ai_adjust_crawl {"url":"目标页面网址，可选，默认浏览器当前页"}]\n'
        '  [工具:run_js {"code":"要执行的JavaScript代码"}]\n'
        '  [工具:ec_scan {"value":984, "first":true}]\n'
        '  [工具:web_search {"query":"搜索关键词"}]\n'
        '  [工具:ec_set {"path":["cc","director","getScene()","节点名","属性名"],"value":999999}]\n'
        '  [工具:ec_lock {"path":["..."],"value":999999,"enable":true}]\n'
        '工具使用场景：\n'
        '- 用户想抓取/下载某个页面或网站的图片（如"抓取这个页面""这个站""这个页面图片抓取""下载图片"）→ 用 start_crawl；用户消息里可能只有网址没有"抓取"两个字，那也是在请求抓取\n'
        '- 用户问抓取进度/状态/剩多少 → 用 get_status\n'
        '- 用户问保存目录/配置/当前设置 → 用 get_settings\n'
        '- 用户问浏览器当前打开了什么页面/几张图/页面状态（如"浏览器上有几张图""现在看的是什么页"）→ 用 get_browser_info\n'
        '- 用户想让你看页面内容/画面（如"看看这个页面""这个站怎么样""页面上有什么""帮我看看现在这页"）→ 用 get_browser_view，会截屏并用视觉模型理解页面\n'
        '- 用户说页面明明有图但抓取不到/抓不到图片/提取太少/帮我调整抓取策略/怎么才能抓到（如"这个页面有图抓不到""帮我调整抓取策略""图片怎么抓不下来"）→ 用 ai_adjust_crawl，会自动截图分析页面图片加载方式（懒加载/属性/点击），滚动触发并重新提取，返回图片数量变化\n'
        '- 用户要求修改网页游戏里的数值/数据（如"把984改成999999""把金币改成999999""修改步数/血量/得分/剩余次数"）→ 用 ec_scan 定位变量，再用 ec_set 修改；不要用 run_js 改 DOM！\n'
        '- 用户问技术问题/不知道的方案/需要查资料（如"这个网站怎么爬""怎么绕过反爬""xx工具怎么用"）→ 用 web_search 联网搜索，根据结果回答\n'
        '网页游戏数值修改（EC模式）专规：\n'
        '1. 这类网页游戏（Canvas 渲染，Cocos Creator/Phaser/Unity-WebGL/自定义引擎都可能，且常嵌在 iframe 里）没有 DOM 文本节点，画面上的"剩余步数:984"是画布绘制出来的，document.querySelector / innerText / textContent 全部无效，禁止使用；\n'
        '2. 定位：不要判断游戏是什么引擎——直接 ec_scan {"value":用户要改的当前值,"first":true}，工具会自动进入同源iframe、自动识别 cc/game/Phaser/PIXI/THREE 等引擎挂载点、并递归 window，返回变量路径列表；如果无匹配，告诉用户可输入当前显示的数值再试，或等待游戏数值变化后再调 ec_scan 缩小范围；\n'
        '3. 修改：取 ec_scan 返回的 path 调 ec_set 赋新值；然后 ec_scan {"value":新值,"first":false} 验证是否生效；\n'
        '4. 锁定：想让数值一直保持（游戏会自动扣减），用 ec_lock enable=true；取消用 enable=false；\n'
        '5. 你要自己完成定位→修改→验证整个流程，不要问用户"变量路径是什么"；只有 ec_scan 确实无匹配时才询问用户当前数值或等待用户操作游戏后再再次扫描。\n'
        '规则：\n'
        '1. start_crawl 的 url 可以省略：用户说"这个页面/这个站/当前页/内置浏览器里的页面/抓正在看的图"时，直接调用 start_crawl（url 传空 {}），执行器会自动用主界面网址栏、或内置浏览器当前打开的页面地址，不需要反问用户网址是什么；只有执行器明确回复"找不到网址"时才问用户；\n'
        '2. 参数值必须是完整可用的值，例如路径用完整路径，不能省略；\n'
        '3. 工具执行后你会收到 [工具结果]，根据结果给用户简短中文回复；\n'
        '4. 不需要调用工具时直接正常回复用户；\n'
        '5. 只调用上面列出的工具，不要输出其他格式；\n'
        '6. 你是软件内置助手，用户打开软件就是为了抓图。用户说"下载/抓取/下这个页面的图/大图/所有图/怎么下"就是要用软件抓图，'
        '直接调用 start_crawl 或 ai_adjust_crawl 执行；'
        '禁止教用户用浏览器开发者工具、安装下载插件、截图裁剪等外部方法（软件自身就能完成抓取）。'
    )

    @staticmethod
    def _ai_parse_tool_call(text):
        """解析模型输出的工具调用 [工具:名称 参数JSON]，返回 (name, args) 或 None"""
        import re as _re
        m = _re.search(r'\[工具:([\w_]+)\s*(?:\s+(\{.*?\}))?\]', text, _re.S)
        if not m:
            return None
        name = m.group(1).strip()
        args = {}
        if m.group(2):
            try:
                args = json.loads(m.group(2))
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        return name, args

    def _ai_last_user_text(self):
        """取最近一条用户消息（工具参数兜底提取用）"""
        for m in reversed(self._ai_chat_history):
            if m.get('role') == 'user':
                return m.get('content', '')
        return ''

    @staticmethod
    def _ai_extract_url(text):
        """从文本提取第一个网址"""
        import re as _re
        m = _re.search(r'https?://[^\s，。；;""\']+', text)
        return m.group(0) if m else ''

    @staticmethod
    def _ai_extract_path(text):
        """从文本提取第一个盘符路径（Windows 或正斜杠写法）"""
        import re as _re
        m = _re.search(r'[A-Za-z]:[\\/][^\s，。；;""\']+', text)
        return m.group(0) if m else ''

    def _cdp_current_url(self):
        """读内置调试浏览器当前活跃标签页 URL；没开/无页面返回 ''"""
        try:
            import requests as _r
            tabs = _r.get('http://127.0.0.1:9222/json/list', timeout=3).json()
            pages = [t for t in tabs if t.get('type') == 'page' and t.get('url', '').startswith('http')]
            if not pages:
                return ''
            active = next((t for t in pages if t.get('active')), pages[0])
            return active.get('url', '') or ''
        except Exception:
            return ''

    def _http_get(self, url, timeout=30, headers=None):
        """带代理容错的 GET（统一走模块级 http_get：直连优先，失败再回退系统代理）"""
        return http_get(url, headers=headers, timeout=timeout)

    def _cdp_download_image(self, img_url, filepath):
        """浏览器通道下载图片。两级策略：
        1) 页内 fetch（同源最快，但跨域会被 CORS 挡）
        2) 新开标签页直接导航到图片 URL（顶级导航不受 CORS 限制），用
           Page.getResourceContent 抓主资源 base64 —— Cloudflare 拦 requests
           但放行真浏览器，这条通道最稳。成功返回 True"""
        import json as _json, base64 as _b64, time as _time
        import requests as _rq
        try:
            tabs = _rq.get('http://127.0.0.1:9222/json/list', timeout=3).json()
        except Exception:
            return False
        pages = [t for t in tabs if t.get('type') == 'page' and t.get('url', '').startswith('http')]
        if not pages:
            return False

        # ---- 尝试1：页内 fetch（带登录态/Cookie）----
        try:
            import websocket as _ws
            ws = _ws.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=60)
            fetch_js = """
            (async () => {
              try {
                const r = await fetch(%r, {credentials:'include'});
                if(!r.ok) return 'HTTP'+r.status;
                const buf = await r.arrayBuffer();
                let bin=''; const bytes=new Uint8Array(buf);
                for(let i=0;i<bytes.length;i++) bin+=String.fromCharCode(bytes[i]);
                return btoa(bin);
              } catch(e){ return 'ERR:'+e.message; }
            })()
            """ % img_url
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': fetch_js, 'awaitPromise': True, 'returnByValue': True}}))
            while True:
                msg = _json.loads(ws.recv())
                if msg.get('id') == 1:
                    break
            ws.close()
            val = msg.get('result', {}).get('result', {}).get('value', '')
            if val and not val.startswith('ERR') and not val.startswith('HTTP'):
                raw = _b64.b64decode(val)
                os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
                with open(filepath, 'wb') as f:
                    f.write(raw)
                return True
        except Exception:
            pass

        # ---- 尝试2：新标签页导航到图片 URL，抓主资源 ----
        tid = None
        try:
            from urllib.parse import quote as _q
            qurl = _q(img_url, safe=':/?&=')
            try:
                tgt = _rq.put('http://127.0.0.1:9222/json/new?' + qurl, timeout=8).json()
            except Exception:
                tgt = _rq.get('http://127.0.0.1:9222/json/new?' + qurl, timeout=8).json()
            tid = tgt.get('id')
            wsurl = tgt.get('webSocketDebuggerUrl')
            if not (tid and wsurl):
                return False
            import websocket as _ws
            ws = _ws.create_connection(wsurl, timeout=4)
            state = {'mid': 0}

            def rpc(method, params=None):
                state['mid'] += 1
                ws.send(_json.dumps({'id': state['mid'], 'method': method, 'params': params or {}}))
                return state['mid']

            raw = None
            deadline = _time.time() + 25
            while _time.time() < deadline and raw is None:
                frame = None
                try:
                    rid = rpc('Page.getResourceTree')
                    t0 = _time.time()
                    while _time.time() - t0 < 4:
                        try:
                            m = _json.loads(ws.recv())
                        except Exception:
                            break
                        if m.get('id') == rid:
                            frame = (m.get('result', {}).get('frameTree') or {}).get('frame') or {}
                            break
                except Exception:
                    pass
                if not frame:
                    _time.sleep(0.5)
                    continue
                if frame.get('url') == img_url:
                    try:
                        rid = rpc('Page.getResourceContent', {'frameId': frame.get('id'), 'url': img_url})
                        t0 = _time.time()
                        while _time.time() - t0 < 6:
                            try:
                                m = _json.loads(ws.recv())
                            except Exception:
                                break
                            if m.get('id') == rid:
                                got = m.get('result') or {}
                                if got.get('base64Encoded') and got.get('body'):
                                    raw = _b64.b64decode(got['body'])
                                break
                    except Exception:
                        pass
                else:
                    _time.sleep(0.6)  # 页面还在加载
            try:
                ws.close()
            except Exception:
                pass
            try:
                _rq.get('http://127.0.0.1:9222/json/close/' + tid, timeout=3)
            except Exception:
                pass
            if raw and len(raw) > 128:
                os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
                with open(filepath, 'wb') as f:
                    f.write(raw)
                return True
        except Exception:
            pass
        finally:
            if tid:
                try:
                    _rq.get('http://127.0.0.1:9222/json/close/' + tid, timeout=3)
                except Exception:
                    pass
        return False

    def _ai_execute_tool(self, name, args):
        """执行工具调用，返回 (ok, 结果文本)"""
        try:
            if name == 'web_search':
                q = str(args.get('query') or args.get('q') or '').strip()
                if not q:
                    return False, '缺少搜索关键词'
                try:
                    import requests as _r
                    r = _r.get('https://duckduckgo.com/html/', params={'q': q}, timeout=10,
                               headers={'User-Agent': 'Mozilla/5.0'})
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(r.text, 'html.parser')
                    results = []
                    for item in soup.select('.result')[:5]:
                        title = item.select_one('.result__title')
                        snippet = item.select_one('.result__snippet')
                        if title:
                            results.append((title.get_text(strip=True),
                                          snippet.get_text(strip=True) if snippet else ''))
                    if not results:
                        return False, '搜索无结果'
                    return True, '\n\n'.join('%s\n%s' % (t, s) for t, s in results)
                except Exception as e:
                    return False, '搜索失败: %s' % e
            if name == 'start_crawl':
                url = str(args.get('url') or '').strip()
                if not url:
                    url = self._ai_extract_url(self._ai_last_user_text())  # 参数兜底1：从用户消息提取
                if not url:
                    url = self.url_var.get().strip()  # 参数兜底2：主界面网址栏
                if not url:
                    url = self._cdp_current_url()  # 兜底3：读内置调试浏览器当前活跃页
                if not url:
                    return False, '缺少网址：主界面网址栏为空，内置浏览器(9222)也没有打开的页面。请先在内置浏览器打开目标页，或直接给我网址'
                if self.is_running:
                    return False, '当前已有抓取任务在运行，请先停止或等待完成'
                save_dir = str(args.get('save_dir') or '').strip() or self.dir_var.get().strip()
                mode = str(args.get('mode') or '').strip()
                threads = args.get('threads')
                if mode not in ('单页', '全站'):
                    txt = self._ai_last_user_text()  # 参数兜底：从用户消息提取模式/线程
                    import re as _re
                    if _re.search(r'单页|只抓(这|当前|一)?页|就?这页', txt):
                        mode = '单页'
                    elif _re.search(r'全站|全部|整站|所有页', txt):
                        mode = '全站'
                    else:
                        mode = self.grab_mode_var.get()
                    if threads is None:
                        m = _re.search(r'线程[数]?[=:：]?\s*(\d+)', txt) or _re.search(r'(\d+)\s*(个)?线程', txt)
                        if m:
                            try:
                                threads = int(m.group(1))
                            except Exception:
                                threads = None
                self.url_var.set(url)
                if save_dir:
                    self.dir_var.set(os.path.normpath(save_dir))
                if mode in ('单页', '全站'):
                    self.grab_mode_var.set(mode)
                if threads is not None:
                    try:
                        self.threads_var.set(max(1, min(32, int(threads))))
                    except Exception:
                        pass
                self._save_settings()
                self._start_crawl()
                return True, '已开始抓取 %s（模式:%s）' % (url, mode)
            if name == 'stop_crawl':
                self._stop_crawl()
                return True, '已请求停止抓取'
            if name == 'pause_crawl':
                if not self.pause_flag.is_set() and self.is_running:
                    self._toggle_pause()
                    return True, '已暂停抓取'
                return False, '当前没有可暂停的运行任务'
            if name == 'resume_crawl':
                if self.pause_flag.is_set():
                    self._toggle_pause()
                    return True, '已继续抓取'
                return False, '当前没有处于暂停状态的任务'
            if name == 'retry_failed':
                self._retry_failed()
                return True, '已触发重试失败任务'
            if name == 'get_status':
                return True, self._ai_tool_status()
            if name == 'get_task_list':
                return True, self._ai_tool_task_list(int(args.get('limit') or 10))
            if name == 'set_save_dir':
                path = str(args.get('path') or '').strip()
                if not path:
                    path = self._ai_extract_path(self._ai_last_user_text())  # 参数兜底：从用户消息提取
                if not path:
                    return False, '缺少路径参数 path，请重新调用 [工具:set_save_dir {"path":"L:/tu"}] 带上完整路径'
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    return False, '保存目录不可用: %s' % e
                self.dir_var.set(path)
                self._save_settings()
                return True, '保存目录已设置为 %s' % path
            if name == 'set_filter':
                sm = args.get('smart_filter')
                ms = args.get('min_size')
                if sm is None or ms is None:
                    txt = self._ai_last_user_text()  # 参数兜底：从用户消息解析
                    import re as _re
                    if sm is None:
                        if _re.search(r'关(掉|闭)?|关闭|去掉', txt):
                            sm = False
                        elif _re.search(r'开(启|着)?|打开|启用', txt):
                            sm = True
                    if ms is None:
                        m = _re.search(r'(\d+)\s*KB?', txt)
                        if m:
                            try:
                                ms = int(m.group(1))
                            except Exception:
                                ms = None
                changed = False
                if sm is not None:
                    self.smart_filter_var.set(bool(sm))
                    changed = True
                if ms is not None:
                    try:
                        self.min_size_var.set(int(ms))
                        changed = True
                    except Exception:
                        pass
                if not changed:
                    return False, '没有检测到需要设置的过滤项。请明确要设置的参数，例如："开启智能过滤"、"关闭智能过滤"、"最小图片大小 30KB"（工具格式 [工具:set_filter {"smart_filter":true,"min_size":30}]）'
                self._save_settings()
                return True, '过滤设置已更新（智能过滤:%s 最小大小:%sKB）' % (
                    self.smart_filter_var.get(), self.min_size_var.get())
            if name == 'get_settings':
                return True, (
                    '网址:%s | 保存目录:%s | 模式:%s | 线程:%s | 智能过滤:%s | '
                    '最小大小:%sKB | 抓取状态:%s' % (
                        self.url_var.get(), self.dir_var.get(), self.grab_mode_var.get(),
                        self.threads_var.get(), self.smart_filter_var.get(),
                        self.min_size_var.get(), '运行中' if self.is_running else '空闲'))
            if name == 'open_save_dir':
                self._open_save_dir()
                return True, '已打开保存目录'
            if name == 'get_browser_info':
                info = self._ai_browser_info()
                if info is None:
                    return True, '调试浏览器未运行（9222端口无响应），请先在"浏览器模式"下启动调试浏览器'
                return True, info
            if name == 'get_browser_view':
                return self._ai_browser_view(str(args.get('prompt') or '').strip())
            if name == 'ai_adjust_crawl':
                return True, self._ai_adjust_crawl_tool(str(args.get('url') or '').strip())
            if name == 'run_js':
                code = str(args.get('code') or '').strip()
                if not code:
                    return False, '缺少 code 参数，请重新调用 [工具:run_js {"code":"document.title"}]'
                return self._ai_execute_js(code)
            if name == 'ec_scan':
                # 游戏数值定位：首次=引擎对象树搜值；再次=按上次路径过滤
                try:
                    value = float(args.get('value'))
                except Exception:
                    return False, 'value 参数必须是数值，如 [工具:ec_scan {"value":984,"first":true}]'
                first = bool(args.get('first', True))
                if not first and not self.ec_scan_state:
                    return False, '还没有首次扫描结果，请先调用 ec_scan {"value":984,"first":true} 定位变量'
                hits = self._ai_ec_scan(value, None if first else self.ec_scan_state)
                if hits is None:
                    return False, '调试浏览器未运行（9222端口无响应），请先启动浏览器模式'
                self.ec_scan_state = [s for s, v in hits]
                self._ec_save_state()
                if not hits:
                    return True, 'EC扫描完成：值 %s 无匹配（已遍历Cocos场景树/引擎对象/window，number与string都搜了）' % value
                lines = ['EC扫描命中 %d 个（值 %s）：' % (len(hits), value)]
                for s, v in hits[:20]:
                    lines.append('  %s = %s' % ('.'.join(s), v))
                if len(hits) > 20:
                    lines.append('  ... 共 %d 个，可用 ec_set 按 path 修改' % len(hits))
                else:
                    lines.append('用 ec_set 按上面的 path 修改，例如 path 取第一行')
                return True, '\n'.join(lines)
            if name == 'ec_set':
                path = args.get('path')
                if not isinstance(path, list) or not path:
                    return False, 'path 必须是变量路径数组，如 [工具:ec_set {"path":["cc","director","getScene()","node","label"],"value":999999}]'
                try:
                    value = float(args.get('value'))
                except Exception:
                    return False, 'value 必须是数值'
                ok, text = self._ai_ec_edit(path, value)
                if not ok:
                    return False, '修改失败: %s' % text
                return True, '已把 %s 修改为 %s，可用 ec_scan {"value":%s,"first":false} 验证' % ('.'.join(path), value, value)
            if name == 'ec_lock':
                path = args.get('path')
                if not isinstance(path, list) or not path:
                    return False, 'path 必须是变量路径数组'
                try:
                    value = float(args.get('value'))
                except Exception:
                    value = None
                enable = bool(args.get('enable', True))
                if enable and value is None:
                    return False, 'enable=true 时 value 必填'
                if value is None:
                    value = 0
                ok, text = self._ai_ec_lock(path, value, enable)
                if ok:
                    return True, '已%s：%s 锁定为 %s（每200ms重写一次）' % ('锁定' if enable else '解锁', '.'.join(path), value)
                return False, '锁定操作失败: %s' % text
            return False, '未知工具: %s' % name
        except Exception as e:
            return False, '工具执行出错: %s' % e

    def _ai_browser_info(self):
        """查询调试浏览器当前状态：标签页列表 + 当前页图片数（供 get_browser_info 工具）"""
        import urllib.request as _ur
        import json as _json
        try:
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
        except Exception:
            return None
        pages = [t for t in tabs if t.get('type') == 'page']
        if not pages:
            return '调试浏览器运行中，但没有打开的网页标签'
        active = next((t for t in pages if t.get('active')), pages[0])
        lines = ['调试浏览器运行中，共 %d 个标签页' % len(pages)]
        for i, t in enumerate(pages[:8], 1):
            title = (t.get('title') or '').strip() or '(无标题)'
            lines.append('%d. %s | %s' % (i, title[:30], t.get('url', '')[:80]))
        if len(pages) > 8:
            lines.append('... 等共 %d 个' % len(pages))
        # 当前页图片数（CDP Runtime.evaluate）
        img_count = None
        try:
            import websocket as _ws
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=5)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                 'params': {'expression': 'document.querySelectorAll("img").length',
                                            'returnByValue': True}}))
            resp = _json.loads(ws.recv())
            ws.close()
            val = resp.get('result', {}).get('result', {}).get('value')
            if isinstance(val, int):
                img_count = val
        except Exception:
            pass
        if img_count is not None:
            lines.append('当前页(%s): %d 张图片' % (active.get('url', '')[:60], img_count))
        else:
            lines.append('当前页: %s' % active.get('url', ''))
        return '\n'.join(lines)

    def _ai_browser_view(self, prompt=''):
        """截取调试浏览器当前页截图 → 视觉模型理解 → 返回描述（get_browser_view 工具）"""
        import urllib.request as _ur
        import json as _json
        import base64 as _b64
        import io as _io
        import time as _time
        try:
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
        except Exception:
            return False, '调试浏览器未运行（9222端口无响应），请先在"浏览器模式"下启动调试浏览器'
        pages = [t for t in tabs if t.get('type') == 'page']
        if not pages:
            return False, '调试浏览器没有打开的网页'
        active = next((t for t in pages if t.get('active')), pages[0])
        # 1. CDP 截屏
        try:
            import websocket as _ws
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=15)
            ws.send(_json.dumps({'id': 1, 'method': 'Page.captureScreenshot',
                                 'params': {'format': 'png', 'captureBeyondViewport': False}}))
            resp = _json.loads(ws.recv())
            ws.close()
            png_b64 = resp.get('result', {}).get('data')
            if not png_b64:
                return False, '截图失败：%s' % resp.get('error', {}).get('message', '未知错误')
        except Exception as e:
            return False, '截图失败: %s' % e
        # 2. 缩放压缩（控制视觉 token）
        try:
            from PIL import Image
            img = Image.open(_io.BytesIO(_b64.b64decode(png_b64))).convert('RGB')
            img.thumbnail((1024, 1024))
            buf = _io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            jpg_b64 = _b64.b64encode(buf.getvalue()).decode()
            shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
            os.makedirs(shot_dir, exist_ok=True)
            shot_path = os.path.join(shot_dir, 'view_%s.jpg' % _time.strftime('%Y%m%d_%H%M%S'))
            with open(shot_path, 'wb') as f:
                f.write(buf.getvalue())
            self._clean_screenshots(200)
        except Exception as e:
            return False, '图片处理失败: %s' % e
        # 3. 视觉模型理解
        question = prompt or '简要描述这个网页页面的内容和布局：是什么网站、页面上有什么主要内容'
        body = {'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': question},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + jpg_b64}},
                ]}],
                'max_tokens': 600}
        ok, out = self._ai_completion(body, timeout=240)
        if not ok:
            return False, '视觉模型调用失败'
        desc = out['choices'][0]['message']['content'].strip()
        result = '已截取浏览器当前页(%s)并查看：\n%s\n（截图已保存: %s）' % (active.get('url', '')[:60], desc[:800], shot_path)
        return True, result

    def _ai_tool_status(self):
        """任务状态统计（供 get_status 工具）"""
        total = success = fail = waiting = downloading = 0
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
        return '抓取状态:%s | 任务总数:%d 成功:%d 失败:%d 等待:%d 下载中:%d' % (
            '运行中' if self.is_running else '空闲', total, success, fail, waiting, downloading)

    def _ai_tool_task_list(self, limit=10):
        """最近任务列表（供 get_task_list 工具）"""
        rows = []
        for item in self.task_tree.get_children():
            vals = self.task_tree.item(item, 'values')
            if len(vals) > 4:
                rows.append('  %s | %s | %s' % (vals[0], vals[1], vals[4]))
            if len(rows) >= limit:
                break
        if not rows:
            return '当前没有任务记录'
        return '最近任务：\n' + '\n'.join(rows)

    def _ai_assistant_chat(self, user_text):
        """AI 助手模式：多轮工具调用循环（最多5轮），返回模型最终回复"""
        self._ai_log_chat('req', user_text)
        self._ai_chat_history.append({'role': 'user', 'content': user_text})
        import requests
        import json
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
            ctx = int(self.ai_chat_ctx_var.get() or 12)
        except Exception:
            port = AI_DEFAULT_PORT
            ctx = 12
        messages = [{'role': 'system', 'content': self.AI_TOOL_DESC}]
        messages.extend(self._ai_chat_history[-ctx:])
        final = ''
        last_fail = None   # 连续失败保护：(name, error) 相同连续2次则中断
        for _ in range(5):
            try:
                ok, resp = self._ai_completion(
                    {'messages': messages, 'max_tokens': 1024, 'temperature': 0.3}, timeout=300)
                if not ok:
                    final = '(调用失败)'
                    break
                content = (resp['choices'][0]['message'].get('content') or '').strip()
            except Exception as e:
                final = '(调用失败: %s)' % e
                break
            tc = self._ai_parse_tool_call(content)
            if not tc:
                final = content
                break
            name, args = tc
            self._ai_log_chat('tool', '[工具调用] %s %s' % (name, json.dumps(args, ensure_ascii=False)))
            ok, result = self._ai_execute_tool(name, args)
            self._ai_log_chat('tool', '[工具结果] %s' % result)
            if not ok and last_fail == (name, result):
                final = '工具 %s 连续执行失败（%s），已停止尝试，请向用户说明情况并请其确认参数。' % (name, result)
                self._ai_log_chat('tool', final)
                self._ai_chat_history.append({'role': 'assistant', 'content': content})
                break
            last_fail = (name, result) if not ok else None
            messages.append({'role': 'assistant', 'content': content})
            messages.append({'role': 'user', 'content': '[工具结果] %s' % result})
            self._ai_chat_history.append({'role': 'assistant', 'content': content})
            self._ai_chat_history.append({'role': 'user', 'content': '[工具结果] %s' % result})
        if final:
            self._ai_log_chat('resp', final or '(空回复)')
            self._ai_chat_history.append({'role': 'assistant', 'content': final})

    def _clean_screenshots(self, max_keep=200):
        """清理截图目录：只保留最近 max_keep 张，超出的按时间删除最旧（自动调用，防无限累积）"""
        try:
            shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
            if not os.path.isdir(shot_dir):
                return
            files = [os.path.join(shot_dir, f) for f in os.listdir(shot_dir)
                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if len(files) <= max_keep:
                return
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            removed = 0
            for old in files[max_keep:]:
                try:
                    os.remove(old)
                    removed += 1
                except Exception:
                    pass
            if removed:
                self._log('截图目录已自动清理: 保留最近 %d 张，删除 %d 张旧截图' % (max_keep, removed))
        except Exception:
            pass

    def _ai_capture_shot(self):
        """CDP截取调试浏览器当前页 → JPEG压缩 → 返回 (base64, 保存路径)；失败返回 None"""
        import urllib.request as _ur
        import json as _json
        import base64 as _b64
        import io as _io
        import time as _time
        try:
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            pages = [t for t in tabs if t.get('type') == 'page']
            if not pages:
                return None
            active = next((t for t in pages if t.get('active')), pages[0])
            import websocket as _ws
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=15)
            ws.send(_json.dumps({'id': 1, 'method': 'Page.captureScreenshot', 'params': {'format': 'png'}}))
            resp = _json.loads(ws.recv())
            ws.close()
            png_b64 = resp.get('result', {}).get('data')
            if not png_b64:
                return None
            from PIL import Image
            img = Image.open(_io.BytesIO(_b64.b64decode(png_b64))).convert('RGB')
            img.thumbnail((512, 512))
            buf = _io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            b64 = _b64.b64encode(buf.getvalue()).decode()
            shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
            os.makedirs(shot_dir, exist_ok=True)
            shot_path = os.path.join(shot_dir, 'chat_%s.jpg' % _time.strftime('%Y%m%d_%H%M%S'))
            with open(shot_path, 'wb') as f:
                f.write(buf.getvalue())
            self._clean_screenshots(200)
            return b64, shot_path
        except Exception:
            return None

    def _ai_execute_js(self, code, timeout=8):
        """CDP 在活跃标签页执行 JS，返回 (ok, 结果文本)。网页游戏修改工具"""
        import json as _json
        import websocket as _ws
        try:
            pages = _json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5).read())
            pages = [t for t in pages if t.get('type') == 'page']
            if not pages:
                return False, '调试浏览器没有打开的网页'
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=timeout)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                'expression': code, 'returnByValue': True, 'awaitPromise': False}}))
            resp = _json.loads(ws.recv())
            ws.close()
            if 'error' in resp:
                return False, '执行失败: %s' % resp['error'].get('message', '?')
            r = resp.get('result', {})
            if 'exceptionDetails' in r:
                return False, 'JS异常: %s' % r['exceptionDetails'].get('exception', {}).get('description',
                    r['exceptionDetails'].get('text', '?'))[:300]
            val = r.get('result', {})
            if 'value' in val:
                return True, '执行成功: %s' % _json.dumps(val['value'], ensure_ascii=False)[:500]
            if 'description' in val:
                return True, '执行成功: %s' % val['description'][:500]
            return True, '执行成功（无返回值）'
        except Exception as e:
            return False, '执行JS失败: %s' % e

    # ===== EC 模式：网页游戏数值搜索/过滤/修改/锁定 =====
    def _ai_ec_scan(self, value, prev_segs=None, compare=None, unknown=False):
        """EC模式扫描：首次=iframe(若有)+多引擎(Cocos场景树/Phaser/全局game)→window；
        再次=按上次路径过滤。compare: None=精确值; 'unchanged'/'changed'/'increased'/'decreased'=变动对比。
        返回 [(segs列表, 当前值)]；segs 段为字符串键，特殊段 'name()' 表示调用方法，'frameN' 表示第N个iframe"""
        import json as _json
        import websocket as _ws
        # prev_segs 在 diff 模式下是 [[seg, oldval], ...]，精确模式下是 [seg, ...]
        prev = _json.dumps(prev_segs or [])
        resolve = ('function __r(seg){var cur=window;'
                   'for(var j=1;j<seg.length;j++){var k=seg[j];'
                   'if(k==="frame0"){cur=window;}'
                   'else if(typeof k==="string"&&k.slice(0,5)==="frame"){cur=window.frames[parseInt(k.slice(5),10)];}'
                   'else if(typeof k==="string"&&k.slice(-2)==="()"){cur=cur[k.slice(0,-2)]();}'
                   'else{cur=cur[k];}}return cur;}')
        if compare:
            # 变动对比模式：prev 是 [[seg, oldval], ...]
            cmp_js = {
                'unchanged': 'cur===old',
                'changed': 'typeof cur==="number"&&cur!==old',
                'increased': 'typeof cur==="number"&&cur>old',
                'decreased': 'typeof cur==="number"&&cur<old',
            }[compare]
            js = ('(function(){var prev=%(p)s;var out=[];'
                  'for(var i=0;i<prev.length;i++){try{'
                  'var seg=prev[i][0];var old=prev[i][1];var cur=__r(seg);'
                  'if(typeof cur!=="number")continue;'
                  'if(%(cmp)s){out.push({s:seg,v:cur});}'
                  '}catch(e){}}return out.slice(0,500);})()'
                  % {'p': prev, 'cmp': cmp_js})
        elif prev_segs:
            # 过滤模式：只对上次命中的路径重新取值判断（number/string 都支持）
            # prev 现在是 [[seg, oldval], ...]，取 seg
            js = ('(function(){var target=%(v)s;var tstr=String(target);var prev=%(p)s;var out=[];'
                  'for(var i=0;i<prev.length;i++){try{'
                  'var seg=prev[i][0];var cur=__r(seg);'
                  'if((typeof cur==="number"&&cur===target)||(typeof cur==="string"&&cur===tstr)){out.push({s:seg,v:cur});}'
                  '}catch(e){}}return out.slice(0,500);})()'
                  % {'v': repr(value), 'p': prev})
        else:
            # 首次扫描：先枚举同源iframe（webview壳游戏常嵌iframe），
            # 每个frame扫 Cocos场景树(深18)→cc/game对象树(深14)→window(深8)，number/string都搜
            _unk = 'true' if unknown else 'false'
            _v_js = 'null' if unknown else repr(value)
            js = ('(function(){var target=%(v)s;var tstr=String(target);var unk=%(unk)s;var hits=[];var seen=[];'
                  'function __push(seg,v){if(hits.length<500)hits.push({s:seg,v:v});}'
                  'function __walk(o,p,d,lim){'
                  'if(d>lim||o===null||hits.length>=500)return;var t=typeof o;'
                  'if(t==="number"){if(unk||o===target)__push(p,o);return;}'
                  'if(t==="string"){if(!unk&&o===tstr)__push(p,o);return;}'
                  'if(t!=="object")return;if(seen.indexOf(o)>=0)return;seen.push(o);'
                  'var ks=[];try{ks=Object.keys(o);}catch(e){return;}'
                  'for(var i=0;i<ks.length;i++){try{var k=ks[i];var v=o[k];'
                  'if(typeof v==="number"){if(unk||v===target)__push(p.concat([k]),v);}'
                  'else if(typeof v==="string"){if(!unk&&v===tstr)__push(p.concat([k]),v);}'
                  'else if(typeof v==="object"&&v!==null){__walk(v,p.concat([k]),d+1,lim);}'
                  '}catch(e){}}}'
                  'function __scanFrame(f,prefix){'
                  'try{var CC=f.cc||f.CocosEngine;'
                  'if(CC&&CC.director){var sc=CC.director.getScene();'
                  'if(sc){__walk(sc,prefix.concat(["cc","director","getScene()"]),0,18);}'
                  'if(unk||hits.length===0){__walk(CC,prefix.concat(["cc"]),0,14);}'
                  '}}catch(e){}'
                  'try{var rmKeys=["$gameActors","$gameParty","$gamePlayer","$gameTroop","$gameMap","$gameSwitches","$gameVariables"];'
                  'for(var ri=0;ri<rmKeys.length;ri++){try{var rm=f[rmKeys[ri]];if(rm){__walk(rm,prefix.concat([rmKeys[ri]]),0,10);}}catch(e){}}'
                  '}catch(e){}'
                  'try{var G=f.game||f.Game||f.Phaser||f.PIXI||f.THREE;'
                  'if(G){__walk(G,prefix.concat(["game"]),0,14);}}catch(e){}'
                  'try{__walk(f,prefix.concat(["window"]),0,8);}catch(e){}'
                  '}'
                  'var frames=[window];'
                  'try{var fs=document.querySelectorAll("iframe");'
                  'for(var i=0;i<fs.length&&i<8;i++){try{frames.push(fs[i].contentWindow);}catch(e){}}}catch(e){}'
                  'for(var i=0;i<frames.length;i++){try{__scanFrame(frames[i],["frame"+i]);}catch(e){}'
                  'if(!unk&&hits.length>0)break;}'
                  'return hits.slice(0,500);})()' % {'v': _v_js, 'unk': _unk})
        try:
            pages = _json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5).read())
            pages = [t for t in pages if t.get('type') == 'page']
            if not pages:
                return None
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=15)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                'expression': resolve + js, 'returnByValue': True}}))
            resp = _json.loads(ws.recv())
            ws.close()
            val = resp.get('result', {}).get('result', {}).get('value')
            if not isinstance(val, list):
                return []
            return [(h.get('s', []), h.get('v')) for h in val]
        except Exception:
            return None

    def _ec_assign_expr(self, segs, value):
        """生成给路径赋值的 JS 表达式（支持调用段 k() 与 iframe 段 frameN；末段为调用则不可赋值）
        特殊段：['__wasm', memIdx, type, offset] —— 写入 WASM 线性内存"""
        import json as _json
        # ---- WASM 线性内存写入 ----
        if segs and str(segs[0]) == '__wasm' and len(segs) >= 4:
            try:
                _mi = int(segs[1])
                _t = str(segs[2])
                _off = int(segs[3])
            except Exception:
                return 'null'
            if _t not in WASM_TYPE_SIZE:
                return 'null'
            return ('(function(){var v=%s;'
                    'var r=window.__wgWrite(%d,%r,%d,v);'
                    'return r;})()' % (_json.dumps(value), _mi, _t, _off))
        segj = _json.dumps(segs)
        return ('(function(){var seg=%s;var cur=window;'
                'for(var j=1;j<seg.length-1;j++){var k=seg[j];'
                'if(k==="frame0"){cur=window;}'
                'else if(typeof k==="string"&&k.slice(0,5)==="frame"){cur=window.frames[parseInt(k.slice(5),10)];}'
                'else if(typeof k==="string"&&k.slice(-2)==="()"){cur=cur[k.slice(0,-2)]();}'
                'else{cur=cur[k];}}'
                'var last=seg[seg.length-1];'
                'if(typeof last==="string"&&last.slice(-2)==="()"){return null;}'
                'cur[last]=%s;return cur[last];})()'
                % (segj, repr(value)))

    def _ai_ec_edit(self, segs, value):
        """EC模式修改：把变量路径（支持调用段）赋新值"""
        return self._ai_execute_js(self._ec_assign_expr(segs, value), timeout=8)

    def _ai_ec_lock(self, segs, value, enable, lock_key=None):
        """EC模式锁定：定时把变量重写为目标值（50ms高频，抗游戏每帧覆盖）。
        支持多数据独立锁定：lock_key 唯一标识一个锁，互不干扰（enable=False 只停该锁）"""
        expr = self._ec_assign_expr(segs, value)
        if lock_key is None:
            lock_key = '.'.join(str(s) for s in segs)
        if enable:
            js = ('window.__ecLocks=window.__ecLocks||{};'
                  'if(window.__ecLocks[%r]){clearInterval(window.__ecLocks[%r]);}'
                  'window.__ecLocks[%r]=setInterval(function(){try{%s;}catch(e1){}},50);'
                  'true;' % (lock_key, lock_key, lock_key, expr))
        else:
            js = ('window.__ecLocks=window.__ecLocks||{};'
                  'if(window.__ecLocks[%r]){clearInterval(window.__ecLocks[%r]);delete window.__ecLocks[%r];}'
                  'true;' % (lock_key, lock_key, lock_key))
        return self._ai_execute_js(js, timeout=8)

    def _ai_ec_reload(self, segs):
        """EC恢复：按保存的变量路径回读当前值（页面刷新后变量重建，路径一般仍有效）
        支持 WASM 段 ['__wasm', memIdx, type, offset]，走 __wgRead 回读"""
        import json as _json
        import websocket as _ws
        self._wasm_boot()   # 确保 WASM 读写助手已注入
        resolve = ('function __r(seg){'
                   'if(seg[0]==="__wasm"&&window.__wgRead){'
                   'return window.__wgRead(seg[1],seg[2],seg[3]);}'
                   'var cur=window;'
                   'for(var j=1;j<seg.length;j++){var k=seg[j];'
                   'if(k==="frame0"){cur=window;}'
                   'else if(typeof k==="string"&&k.slice(0,5)==="frame"){cur=window.frames[parseInt(k.slice(5),10)];}'
                   'else if(typeof k==="string"&&k.slice(-2)==="()"){cur=cur[k.slice(0,-2)]();}'
                   'else{cur=cur[k];}}return cur;}')
        js = ('(function(){var prev=%(p)s;var out=[];'
              'for(var i=0;i<prev.length;i++){try{'
              'var seg=prev[i];var cur=__r(seg);'
              'if(typeof cur==="number"||typeof cur==="string"){out.push({s:seg,v:cur});}'
              '}catch(e){}}return out.slice(0,500);})()'
              % {'p': _json.dumps(segs)})
        try:
            pages = _json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5).read())
            pages = [t for t in pages if t.get('type') == 'page']
            if not pages:
                return None
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=15)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                'expression': resolve + js, 'returnByValue': True}}))
            resp = _json.loads(ws.recv())
            ws.close()
            val = resp.get('result', {}).get('result', {}).get('value')
            if not isinstance(val, list):
                return []
            return [(h.get('s', []), h.get('v')) for h in val]
        except Exception:
            return None

    def _ai_add_shot(self):
        """「截图给AI」：剪贴板有图优先用剪贴板（豆包选区/Win+Shift+S）；否则截调试浏览器当前页；都没有则全屏"""
        if not (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
            self._log('AI对话: AI服务未运行，请先点击「启动AI服务」')
            return
        shot = self._ai_clipboard_image()
        src = '剪贴板'
        if not shot:
            shot = self._ai_capture_shot()
            src = '浏览器'
        if not shot:
            shot = self._ai_capture_fullscreen()
            src = '全屏'
        if not shot:
            self._log('截图给AI失败：剪贴板无图、浏览器未运行且全屏截图失败')
            return
        b64, path = shot
        self._ai_pending_image = {'b64': b64, 'path': path}
        self._ai_log_chat('req', '[已添加截图] %s截图已就绪，输入问题后点「发送」即可让AI看图回答' % src)
        self._ai_show_shot_in_chat(path)

    def _ai_show_shot_in_chat(self, path):
        """把截图缩略图嵌入对话记录（AI对话页签 + 磁吸窗），像正常聊天一样能看到图"""
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((240, 240))
            photo = ImageTk.PhotoImage(img)
            if not hasattr(self, '_ai_shot_images'):
                self._ai_shot_images = []
            self._ai_shot_images.append(photo)  # 保持引用，防被回收
            for txt in (self.ai_chat_text, getattr(self, 'ai_float_text', None)):
                if not txt:
                    continue
                try:
                    txt.image_create('end', image=photo)
                    txt.insert('end', '\n')
                    txt.see('end')
                except Exception:
                    pass
        except Exception:
            pass

    def _ai_capture_fullscreen(self):
        """截取整个屏幕（调试浏览器未运行时兜底）；自动隐藏AI窗避免截入自身"""
        try:
            import io
            import time
            import base64
            from PIL import ImageGrab
            hide = False
            if getattr(self, 'ai_float_win', None) is not None and self.ai_float_win.state() == 'normal':
                self.ai_float_win.withdraw()
                hide = True
            self.root.update_idletasks()
            time.sleep(0.35)
            try:
                img = ImageGrab.grab().convert('RGB')
            finally:
                if hide:
                    self.ai_float_win.deiconify()
            img.thumbnail((512, 512))
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
            os.makedirs(shot_dir, exist_ok=True)
            shot_path = os.path.join(shot_dir, 'full_%s.jpg' % time.strftime('%Y%m%d_%H%M%S'))
            with open(shot_path, 'wb') as f:
                f.write(buf.getvalue())
            self._clean_screenshots(200)
            return b64, shot_path
        except Exception:
            return None

    def _ai_stop_chat(self):
        """停止当前AI请求：直接kill llama-server，立即中断"""
        self._ai_stop_flag = True
        self._ai_busy = False
        try:
            self.ai_progress.stop()
        except Exception:
            pass
        if self.ai_mode_var.get() == 'local' and self.ai_proc and self.ai_proc.poll() is None:
            try:
                self.ai_proc.kill()
                self.ai_proc.wait(timeout=3)
            except Exception:
                pass
            self.ai_proc = None
            self.ai_ok = False
            self._ai_update_status('待启动')
        self._ai_log_chat('resp', '[已停止]')

    def _ai_idle_check(self):
        """3分钟空闲自动释放llama-server显存"""
        if getattr(self, '_ai_busy', False):
            return
        if self.ai_mode_var.get() != 'local':
            return
        if not (self.ai_proc and self.ai_proc.poll() is None):
            return
        idle = time.time() - getattr(self, '_ai_last_use', time.time())
        if idle > 180:
            try:
                self.ai_proc.kill()
                self.ai_proc.wait(timeout=3)
                self.ai_proc = None
                self.ai_ok = False
                self._ai_update_status('待启动')
                self._log('AI服务: 3分钟空闲，已自动释放显存')
            except Exception:
                pass

    def _ai_vision_chat(self, user_text, jpg_b64, shot_path):
        """带截图对话：截图+问题 → 模型看图回答，可调用工具（如 ai_adjust_crawl 调整抓取策略）"""
        import requests
        if getattr(self, '_ai_busy', False):
            self._ai_log_chat('resp', '[忙] AI正在处理上一个请求，请稍等几秒再发')
            return
        self._ai_busy = True
        self._ai_log_chat('req', '[截图识别] %s\n（截图: %s）' % (user_text, shot_path))
        self._ai_stop_flag = False
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
            ctx = int(self.ai_chat_ctx_var.get() or 12)
        except Exception:
            port = AI_DEFAULT_PORT
            ctx = 12
        sys_msg = (self.AI_TOOL_DESC +
                   '\n注意：当前对话已附加一张浏览器截图（你可以看图）。'
                   '用户想让软件抓取/下载图片或调整抓取策略时，必须调用工具执行，不要教用户手动操作。')
        messages = [{'role': 'system', 'content': sys_msg},
                    {'role': 'user', 'content': [
                        {'type': 'text', 'text': user_text},
                        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + jpg_b64}},
                    ]}]
        final = ''
        last_fail = None   # 连续失败保护
        self._ai_log_chat('resp', '[思考中... 视觉模型识别图片可能需要30-60秒]')
        for _ in range(5):
            try:
                body = {'messages': messages, 'max_tokens': 1024, 'temperature': 0.3}
                ok, resp = self._ai_completion(body, timeout=180)
                if not ok:
                    final = '(调用失败: %s)' % getattr(self, '_last_ai_error', '未知错误')
                    break
                content = (resp['choices'][0]['message'].get('content') or '').strip()
            except Exception as e:
                final = '(调用失败: %s)' % e
                break
            tc = self._ai_parse_tool_call(content)
            if not tc:
                final = content
                break
            name, args = tc
            self._ai_log_chat('tool', '[工具调用] %s %s' % (name, json.dumps(args, ensure_ascii=False)))
            ok, result = self._ai_execute_tool(name, args)
            self._ai_log_chat('tool', '[工具结果] %s' % result)
            if not ok and last_fail == (name, result):
                final = '工具 %s 连续执行失败（%s），已停止尝试，请向用户说明情况并请其确认参数。' % (name, result)
                break
            last_fail = (name, result) if not ok else None
            messages.append({'role': 'assistant', 'content': content})
            messages.append({'role': 'user', 'content': '[工具结果] %s' % result})
        if final:
            self._ai_log_chat('resp', final or '(空回复)')
            # 识别结果进历史，便于后续文本追问
            self._ai_chat_history.append({'role': 'user',
                                          'content': user_text + '（基于浏览器截图，截图已保存: %s）' % shot_path})
            self._ai_chat_history.append({'role': 'assistant', 'content': final})
        self._ai_busy = False
        # 视觉请求完成后清空llama-server上下文，释放显存KV cache（不重启进程）
        if self.ai_mode_var.get() == 'local' and self.ai_proc and self.ai_proc.poll() is None:
            try:
                import requests as _req
                port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
                _req.post('http://127.0.0.1:%d/reset' % port, timeout=5)
            except Exception:
                pass

    def _ai_chat_send(self):
        """AI 对话（页签版）：发送用户消息，模型可调用工具操作软件；若已添加截图则走看图识别"""
        self._ai_chat_send_from(self.ai_chat_input)

    def _ai_chat_send_from(self, entry):
        """AI 对话通用发送：entry 为输入框（页签或磁吸窗共用）"""
        text = entry.get().strip()
        if not text and not getattr(self, '_ai_pending_image', None):
            return
        if not (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
            self._log('AI对话: AI服务未运行，请先点击「启动AI服务」')
            return
        entry.delete(0, 'end')
        if getattr(self, '_ai_pending_image', None):
            pending = self._ai_pending_image
            self._ai_pending_image = None
            self._ai_vision_chat(text or '请识别这张截图并描述页面内容', pending['b64'], pending['path'])
        else:
            self._ai_assistant_chat(text)

    def _ai_completion(self, body, timeout=300):
        """统一 AI 请求路由：local（内置llama-server）/ ollama / api（云端OpenAI兼容）。

        body: 请求体（含 messages / max_tokens / temperature 等；api 与 ollama 模式自动补 model）
        返回 (ok, json_dict)；ok=False 时 json_dict 为 None
        """
        import requests
        mode = self.ai_mode_var.get()
        if mode == 'api':
            base = self.ai_api_base_var.get().strip().rstrip('/')
            if not base:
                return False, None
            if base.endswith('/chat/completions'):
                url = base
            elif base.endswith('/v1'):
                url = base + '/chat/completions'
            else:
                url = base + '/v1/chat/completions'
            body = dict(body)
            # 视觉请求（含 image_url）自动用 VLM 模型，其余用 LLM
            has_img = any(
                (isinstance(c, list) and any(
                    isinstance(x, dict) and x.get('type') == 'image_url' for x in c))
                for c in [m.get('content') for m in body.get('messages', [])])
            model = ((self.ai_api_vlm_var if has_img else self.ai_api_model_var).get().strip()
                     or (getattr(self, '_ai_api_models', [None])[0]
                         if getattr(self, '_ai_api_models', []) else '')
                     or 'gpt-4o-mini')
            body.setdefault('model', model)
            if self.ai_api_no_thinking_var.get():
                body.setdefault('thinking', {'type': 'disabled'})
            if self.ai_api_adv_var.get():
                body.setdefault('temperature', float(self.ai_api_temperature_var.get()))
                body.setdefault('max_tokens', int(self.ai_api_max_tokens_var.get()))
            headers = {'Authorization': 'Bearer ' + self.ai_api_key_var.get().strip(),
                       'Content-Type': 'application/json'}
            try:
                r = requests.post(url, json=body, headers=headers, timeout=timeout)
                if r.status_code != 200:
                    self._last_ai_error = 'HTTP %s: %s' % (r.status_code, r.text[:200])
                    return False, None
                self._last_ai_error = None
                return True, r.json()
            except Exception as e:
                self._last_ai_error = str(e)[:200]
                return False, None
            except Exception:
                return False, None
        # local / ollama：本地 OpenAI 兼容端点（Ollama 原生兼容 /v1）
        try:
            port = int(self.ai_port_var.get() or AI_DEFAULT_PORT)
        except Exception:
            port = AI_DEFAULT_PORT
        url = 'http://127.0.0.1:%d/v1/chat/completions' % port
        if mode == 'ollama' and self.ai_model_var.get().strip():
            body = dict(body)
            body.setdefault('model', self.ai_model_var.get().strip())
        try:
            r = requests.post(url, json=body, timeout=timeout)
            if r.status_code != 200:
                return False, None
            return True, r.json()
        except Exception:
            return False, None

    def _ai_call_text(self, prompt_text, max_tokens=300, timeout=120):
        """通用文本调用 AI（按接入方式路由），返回模型输出字符串（失败返回空串）"""
        self._ai_log_chat('req', prompt_text)
        ok, resp = self._ai_completion(
            {'messages': [{'role': 'user', 'content': prompt_text}],
             'max_tokens': max_tokens, 'temperature': 0.1}, timeout=timeout)
        if ok:
            content = (resp['choices'][0]['message'].get('content') or '').strip()
            self._ai_log_chat('resp', content or '(空回复)')
            return content
        self._ai_log_chat('resp', '(调用失败)')
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
        """窗口关闭时保存设置、优雅关闭调试浏览器和AI服务"""
        self._save_settings()
        # 优雅关闭调试浏览器（WM_CLOSE），避免下次启动 Chrome 弹"要恢复页面吗"
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*9222*' -and $_.CommandLine -like '*WebGrabber*debug_profile*' } | "
                 "ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; if ($p) { $p.CloseMainWindow() } }"],
                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
        if self.ai_proc:
            try:
                self.ai_proc.terminate()
            except Exception:
                pass
            try:
                self.ai_proc.kill()
            except Exception:
                pass
        # 兜底：清掉所有 llama-server 残留（防止历史会话/异常退出留下的常驻进程）
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'llama-server.exe'],
                           timeout=10, capture_output=True)
        except Exception:
            pass
        self.root.destroy()

    def _create_widgets(self):
        """创建界面控件（按照web-grabber布局）"""
        # 主容器
        main_container = ttk.Frame(self.root)
        main_container.pack(fill='both', expand=True, padx=8, pady=8)

        # 顶部设置区域（卡片式分组）
        top_frame = ttk.Frame(main_container, style='Card.TFrame')
        self.top_frame = top_frame
        top_frame.pack(fill='x', pady=(0, 3), ipadx=8, ipady=3)

        # 底部状态栏（先占住底部，页签再吃剩余空间，避免被挤出窗口）
        status_bar = ttk.Frame(main_container, style='Card.TFrame')
        status_bar.pack(side='bottom', fill='x', pady=(6, 0), ipady=4)

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
        self.browser_hint = ttk.Label(self.browser_frame, style='Muted.TLabel',
                                      text='点「高级选项 ▾ → 启动调试浏览器」，浏览器会自动嵌入到这里',
                                      font=(UI_FONT, 12))
        self.browser_hint.pack(expand=True)

        # AI 对话页签（可直接与本地模型对话 + 自动记录每次 AI 调用）
        ai_tab = ttk.Frame(self.content_notebook)
        self.content_notebook.add(ai_tab, text='AI对话')
        self._build_character_tab()
        ai_top = ttk.Frame(ai_tab)
        ai_top.pack(fill='x', pady=2, padx=4)
        ttk.Button(ai_top, text='清除', width=6, command=self._ai_clear_chat).pack(side='left')
        ttk.Label(ai_top, text='（蓝=发给模型，绿=模型回复，橙=工具执行；可直接提要求操作软件，如"抓取这个站"）', style='Muted.TLabel').pack(side='left', padx=8)
        self.ai_progress = ttk.Progressbar(ai_tab, mode='indeterminate')
        self.ai_progress.pack(side='top', fill='x', padx=4)
        self.ai_chat_text = tk.Text(ai_tab, wrap='word', font=('Consolas', 9))
        ai_scroll = ttk.Scrollbar(ai_tab, command=self.ai_chat_text.yview)
        self.ai_chat_text.configure(yscrollcommand=ai_scroll.set)
        self.ai_chat_text.tag_configure('ts', font=('Microsoft YaHei UI', 8), foreground='#999999')
        self.ai_chat_text.tag_configure('req_bubble', background='#e3f2fd', lmargin1=70, lmargin2=70, rmargin=10,
                                        spacing1=3, spacing3=3)
        self.ai_chat_text.tag_configure('resp_bubble', background='#e8f5e9', lmargin1=10, lmargin2=10, rmargin=70,
                                        spacing1=3, spacing3=3)
        self.ai_chat_text.tag_configure('tool', foreground='#b45309')
        self.ai_chat_text.tag_configure('req', foreground='#1a56db')
        self.ai_chat_text.tag_configure('resp', foreground='#0d7a3d')
        # 对话输入栏（放窗口底部，豆包式：输入框 + 下方按钮行）
        ai_input_frame = ttk.Frame(ai_tab)
        ai_input_frame.pack(side='bottom', fill='x', pady=3, padx=4)
        self.ai_chat_input = ttk.Entry(ai_input_frame)
        self.ai_chat_input.pack(side='top', fill='x')
        self.ai_chat_input.bind('<Return>', lambda e: self._ai_chat_send())
        self.ai_chat_input.bind('<Control-v>', lambda e: self._ai_on_ctrl_v(self.ai_chat_input))
        try:
            import windnd
            windnd.hook_dropfiles(self.ai_chat_input, func=self._ai_on_drop_file)
            windnd.hook_dropfiles(self.ai_chat_text, func=self._ai_on_drop_file)
        except Exception:
            pass
        ai_btn_row = ttk.Frame(ai_input_frame)
        ai_btn_row.pack(side='top', fill='x', pady=(3, 0))
        ttk.Button(ai_btn_row, text='截图给AI', width=8, command=self._ai_add_shot).pack(side='left', padx=(0, 4))
        ttk.Button(ai_btn_row, text='粘贴', width=6, command=self._ai_paste_shot).pack(side='left', padx=(0, 4))
        ttk.Button(ai_btn_row, text='选区', width=6, command=self._ai_region_shot).pack(side='left', padx=(0, 4))
        ttk.Button(ai_btn_row, text='清空', width=6, command=self._ai_clear_chat).pack(side='left', padx=(0, 4))
        ttk.Button(ai_btn_row, text='发送', width=6, command=self._ai_chat_send).pack(side='right')
        ttk.Button(ai_btn_row, text='停止', width=6, command=self._ai_stop_chat).pack(side='right', padx=(0, 4))
        # Text 最后 pack 吃剩余空间（先 pack 底栏，避免被 expand 挤到右下角）
        ai_scroll.pack(side='right', fill='y')
        self.ai_chat_text.pack(side='left', fill='both', expand=True)
        self._ai_chat_history = []
        self._ai_pending_image = None

        # ===== 顶部设置区域 =====
        # top_frame已经在上面定义了

        # ===== 顶部设置区（精简：2 行常用 + 工具栏 + 可折叠高级选项）=====

        # 行1：网址 + 主操作（开始抓取放最显眼位置）
        url_frame = ttk.Frame(top_frame)
        url_frame.pack(fill='x', pady=(0, 0))
        ttk.Label(url_frame, text='网址:', width=6).pack(side='left')
        self.url_var = tk.StringVar()
        self.url_combo = ttk.Combobox(url_frame, textvariable=self.url_var, height=5)
        self.url_combo.pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(url_frame, text='收藏', command=self._favorite_url, width=6).pack(side='left', padx=(0, 4))
        ttk.Button(url_frame, text='设置', command=self._open_settings, width=6).pack(side='left', padx=(0, 4))
        # 「高级选项」跟在「设置」后面（低频开关 + 功能入口都收进这个可展开面板）
        self.adv_toggle_btn = ttk.Button(url_frame, text='高级选项 ▾', command=self._toggle_advanced)
        self.adv_toggle_btn.pack(side='left', padx=(0, 8))
        self.start_btn = ttk.Button(url_frame, text='开始抓取', style='Accent.TButton', command=self._start_crawl)
        self.start_btn.pack(side='left')
        self._load_url_history()


        # 运行控制行（暂停/停止/重试失败）：默认整行隐藏，开始抓取时自动出现，任务结束自动收起
        self.btn_frame = ttk.Frame(top_frame)
        btn_frame = self.btn_frame
        self._run_bar_visible = False
        self.pause_btn = ttk.Button(btn_frame, text='暂停', style='Row.TButton', command=self._toggle_pause, state='disabled')
        self.pause_btn.pack(side='left')
        self.stop_btn = ttk.Button(btn_frame, text='停止', style='Row.Danger.TButton', command=self._stop_crawl, state='disabled')
        self.stop_btn.pack(side='left', padx=4)
        self.retry_btn = ttk.Button(btn_frame, text='重试失败', style='Row.TButton', command=self._retry_failed, state='disabled')
        self.retry_btn.pack(side='left')

        # ===== 可折叠高级选项面板（默认收起：抓取参数 + 功能入口 + 低频配置都在这里）=====
        adv_frame = ttk.Frame(top_frame)
        self.adv_frame = adv_frame
        self._adv_packed = False

        # 面板第 1 排：抓取参数（原先挤在工具行右侧，现收进面板）
        opt_frame = ttk.Frame(adv_frame)
        self.opt_frame = opt_frame
        ttk.Label(opt_frame, text='抓取参数:', style='Muted.TLabel').pack(side='left', padx=(0, 8))
        ttk.Label(opt_frame, text='模式:').pack(side='left')
        self.grab_mode_var = tk.StringVar(value='单页')
        mode_combo = ttk.Combobox(opt_frame, textvariable=self.grab_mode_var, width=5,
                                  state='readonly', style='Row.TCombobox')
        mode_combo['values'] = ('单页', '全站')
        mode_combo.pack(side='left', padx=(2, 10))
        ttk.Label(opt_frame, text='范围:').pack(side='left')
        # 起始 / 终止 两个框（v3.1.13 起，原来是单个框填 "20" 或 "15-60"）
        self.post_range_start_var = tk.StringVar(value='1')
        ttk.Entry(opt_frame, textvariable=self.post_range_start_var, width=3,
                  style='Row.TEntry').pack(side='left', padx=(2, 1))
        ttk.Label(opt_frame, text='-', style='Muted.TLabel').pack(side='left')
        self.post_range_end_var = tk.StringVar(value='20')
        ttk.Entry(opt_frame, textvariable=self.post_range_end_var, width=4,
                  style='Row.TEntry').pack(side='left', padx=(1, 10))
        ttk.Label(opt_frame, text='页码:').pack(side='left')
        # 起始 / 终止 两个框（v3.1.14 起，原来是单个框填 "0"=不限 / "5"=翻到第5页）
        self.page_range_start_var = tk.StringVar(value='1')
        ttk.Entry(opt_frame, textvariable=self.page_range_start_var, width=3,
                  style='Row.TEntry').pack(side='left', padx=(2, 1))
        ttk.Label(opt_frame, text='-', style='Muted.TLabel').pack(side='left')
        self.page_range_end_var = tk.StringVar(value='')   # 留空 = 不限（自动翻到底）
        ttk.Entry(opt_frame, textvariable=self.page_range_end_var, width=3,
                  style='Row.TEntry').pack(side='left', padx=(1, 4))
        ttk.Label(opt_frame, text='空=不限', style='Muted.TLabel').pack(side='left', padx=(0, 10))
        ttk.Label(opt_frame, text='抓取:').pack(side='left')
        self.render_mode_var = tk.StringVar(value='直连模式')
        render_combo = ttk.Combobox(opt_frame, textvariable=self.render_mode_var, width=13,
                                    state='readonly', style='Row.TCombobox')
        render_combo['values'] = ('直连模式', '浏览器渲染', '浏览器模式(CDP)')
        render_combo.pack(side='left', padx=(2, 10))
        ttk.Label(opt_frame, text='浏览器:').pack(side='left')
        self.browser_choice_var = tk.StringVar(value='Chrome')
        browser_combo = ttk.Combobox(opt_frame, textvariable=self.browser_choice_var, width=7,
                                     state='readonly', style='Row.TCombobox')
        browser_combo['values'] = ('Chrome', 'Edge')
        browser_combo.pack(side='left', padx=(2, 0))
        opt_frame.pack(fill='x', padx=(10, 10), pady=(2, 0))   # 面板第 1 排
        # 「独立窗口 / 启动调试浏览器 / 切换浅色」也在本面板（见下方 E 行）
        # 保存目录在「设置」窗口里配置，主界面不再重复展示
        self.dir_var = tk.StringVar(value=os.path.join(os.getcwd(), 'downloads'))

        def _dir_display(*_args):
            d = self.dir_var.get().strip()
            if d and d not in getattr(self, '_dir_history', []):
                self._dir_remember(d)
        self.dir_var.trace_add('write', _dir_display)

        # E 行：功能入口 + 浏览器工具（原先挤在工具行右侧，现统一收进这里）
        adv_e = ttk.Frame(adv_frame)
        adv_e.pack(fill='x', padx=(10, 10), pady=(10, 0))
        ttk.Label(adv_e, text='功能入口:', style='Muted.TLabel').pack(side='left', padx=(0, 6))
        # 按钮统一靠右排列、加大加粗（左边只留标题，看着不挤也更醒目）
        grp_tools = ttk.Frame(adv_e)
        grp_tools.pack(side='right')
        grp_entry = ttk.Frame(adv_e)
        grp_entry.pack(side='right', padx=(0, 24))
        for txt, cmd in (('AI对话', self._toggle_ai_float_window),
                         ('酒馆', self._open_sillytavern),
                         ('游戏修改', self._toggle_game_mod_window),
                         ('预约资料', self._open_appt_window),
                         ('自动填写', self._appt_fill)):
            ttk.Button(grp_entry, text=txt, style='Feature.TButton',
                       command=cmd).pack(side='left', padx=(0, 8))
        self.independent_btn = ttk.Button(grp_tools, text='独立窗口', style='Feature.TButton',
                                          command=self._open_independent_browser)
        self.independent_btn.pack(side='left', padx=(0, 8))
        self.browser_btn = ttk.Button(grp_tools, text='启动调试浏览器', style='Feature.TButton',
                                      command=self._launch_debug_browser)
        self.browser_btn.pack(side='left', padx=(0, 8))
        self.theme_btn = ttk.Button(grp_tools, style='Feature.TButton',
                                    text='切换浅色' if self.theme_name == 'dark' else '切换深色',
                                    command=self._toggle_theme)
        self.theme_btn.pack(side='left')

        # 分组分隔线：上面是「常用入口」，下面才是抓取选项
        adv_sep1 = ttk.Separator(adv_frame, orient='horizontal')
        adv_sep1.pack(fill='x', padx=(10, 10), pady=(10, 0))
        # A 行：过滤与翻页
        adv_a = ttk.Frame(adv_frame)
        adv_a.pack(fill='x', padx=(10, 10), pady=(10, 0))
        self.smart_filter_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_a, text='智能过滤', variable=self.smart_filter_var).pack(side='left')
        self.download_video_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_a, text='下载视频', variable=self.download_video_var).pack(side='left', padx=(18, 0))
        self.incremental_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_a, text='增量扫描', variable=self.incremental_var).pack(side='left', padx=(18, 0))
        self.force_rescan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_a, text='强制重扫', variable=self.force_rescan_var).pack(side='left', padx=(18, 0))
        self.auto_page_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_a, text='自动翻页抓全部', variable=self.auto_page_var).pack(side='left', padx=(18, 0))
        ttk.Label(adv_a, text='最多页:').pack(side='left', padx=(20, 4))
        self.auto_page_max_var = tk.IntVar(value=100)
        ttk.Spinbox(adv_a, from_=2, to=999, textvariable=self.auto_page_max_var, width=5).pack(side='left')
        # B 行：AI 选项（开关一排）
        adv_b = ttk.Frame(adv_frame)
        adv_b.pack(fill='x', padx=(10, 10), pady=(10, 0))
        self.ai_filter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_b, text='启用AI过滤', variable=self.ai_filter_var).pack(side='left')
        self.ai_prompt_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_b, text='AI生成提示词', variable=self.ai_prompt_var).pack(side='left', padx=(18, 0))
        self.ai_auto_stop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_b, text='抓取完自动停止', variable=self.ai_auto_stop_var).pack(side='left', padx=(18, 0))
        self.ai_prescreen_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_b, text='下载前AI预筛', variable=self.ai_prescreen_var).pack(side='left', padx=(18, 0))

        # B2 行：AI 模型与服务（单独一排，别挤在开关后面）
        adv_b2 = ttk.Frame(adv_frame)
        adv_b2.pack(fill='x', padx=(10, 10), pady=(10, 0))
        ttk.Label(adv_b2, text='模型:').pack(side='left', padx=(24, 4))
        self.ai_preset_var = tk.StringVar(value='内置4B（无审查·6G显存）')
        preset_combo = ttk.Combobox(adv_b2, textvariable=self.ai_preset_var, width=26, state='readonly')
        preset_combo['values'] = list(AI_MODEL_PRESETS.keys())
        preset_combo.pack(side='left', padx=(0, 10))
        preset_combo.bind('<<ComboboxSelected>>', lambda e: self._ai_apply_preset())
        self.ai_toggle_btn = ttk.Button(adv_b2, text='启动AI服务', command=self._ai_toggle_server, width=12)
        self.ai_toggle_btn.pack(side='left', padx=(0, 12))
        self.ai_status_var = tk.StringVar(value=self._ai_state)
        # AI 服务状态灯：绿=运行中 黄=启动中 红=异常 灰=已停止
        self.ai_status_light = tk.Canvas(adv_b2, width=16, height=16,
                                         highlightthickness=0, bg=self.palette['surface'])
        self.ai_status_light.pack(side='left', padx=(4, 6))
        self._ai_light_ball = self.ai_status_light.create_oval(2, 2, 14, 14,
                                                                fill='#9e9e9e', outline='#555555')
        ttk.Label(adv_b2, textvariable=self.ai_status_var, style='Muted.TLabel').pack(side='left')
        # C 行：格式转换与性能
        adv_c = ttk.Frame(adv_frame)
        adv_c.pack(fill='x', padx=(10, 10), pady=(10, 0))
        # 抓取原图：页面只给缩略图时改猜同目录原图地址（0001_600x0.webp → 0001.jpg），猜不到自动回退
        self.orig_img_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv_c, text='抓取原图', variable=self.orig_img_var).pack(side='left')
        self.convert_webp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_c, text='WEBP转JPG', variable=self.convert_webp_var).pack(side='left', padx=(18, 0))
        self.convert_avif_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv_c, text='AVIF转JPG', variable=self.convert_avif_var).pack(side='left', padx=(18, 0))
        ttk.Label(adv_c, text='JPG品质(1-100):').pack(side='left', padx=(20, 4))
        self.jpg_quality_var = tk.IntVar(value=90)
        ttk.Spinbox(adv_c, from_=1, to=100, textvariable=self.jpg_quality_var, width=4).pack(side='left')
        ttk.Label(adv_c, text='最小图(KB):').pack(side='left', padx=(18, 4))
        self.min_size_var = tk.IntVar(value=0)
        ttk.Spinbox(adv_c, from_=0, to=10000, textvariable=self.min_size_var, width=5).pack(side='left')
        ttk.Label(adv_c, text='线程:').pack(side='left', padx=(18, 4))
        self.threads_var = tk.IntVar(value=8)
        ttk.Spinbox(adv_c, from_=1, to=32, textvariable=self.threads_var, width=4).pack(side='left')
        ttk.Label(adv_c, text='超时:').pack(side='left', padx=(18, 4))
        self.timeout_var = tk.IntVar(value=15)
        ttk.Spinbox(adv_c, from_=5, to=60, textvariable=self.timeout_var, width=4).pack(side='left')
        # 分组分隔线：上面是抓取选项，下面是浏览器模式
        adv_sep2 = ttk.Separator(adv_frame, orient='horizontal')
        adv_sep2.pack(fill='x', padx=(10, 10), pady=(10, 0))
        # D 行：浏览器与保存路径
        adv_d = ttk.Frame(adv_frame)
        adv_d.pack(fill='x', padx=(10, 10), pady=(10, 0))
        self.browser_mode_var = tk.BooleanVar(value=False)
        def _on_browser_mode_change():
            if self.browser_mode_var.get():
                self.render_mode_var.set('浏览器模式(CDP)')
            else:
                self.render_mode_var.set('直连模式')
        ttk.Checkbutton(adv_d, text='浏览器模式', variable=self.browser_mode_var, command=_on_browser_mode_change).pack(side='left')
        ttk.Label(adv_d, text='（勾选后自动切到CDP抓取）', style='Muted.TLabel').pack(side='left', padx=(8, 0))

        # AI 模型/服务路径变量（控件在设置窗口）
        self.ai_model_var = tk.StringVar()
        self.ai_mmproj_var = tk.StringVar()
        self.ai_server_var = tk.StringVar(value=AI_SERVER_DEFAULT)
        self.ai_port_var = tk.IntVar(value=AI_DEFAULT_PORT)
        # AI 对话上下文条数（设置窗口）
        self.ai_chat_ctx_var = tk.IntVar(value=12)
        # AI 接入方式：local（内置本地）/ ollama / api（云端API）
        self.ai_mode_var = tk.StringVar(value='local')
        self.ai_provider_var = tk.StringVar(value='自定义')
        self.ai_api_base_var = tk.StringVar(value='')
        self.ai_provider_var = tk.StringVar(value='自定义')
        self.ai_api_key_var = tk.StringVar(value='')
        self.ai_api_model_var = tk.StringVar(value='')
        self.ai_api_vlm_var = tk.StringVar(value='')
        # API 高级项（模型列表、开关、参数）
        self._ai_api_models = []
        self.ai_api_no_thinking_var = tk.BooleanVar(value=False)
        self.ai_api_adv_var = tk.BooleanVar(value=False)
        self.ai_api_temperature_var = tk.DoubleVar(value=0.3)
        self.ai_api_max_tokens_var = tk.IntVar(value=1024)

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
        # 用时显示（改到底部状态栏，避免重复）
        self.timer_var = tk.StringVar(value='用时: 00:00')
        # 全局统计
        # 中间占位（让翻页控件往中间移动）
        ttk.Frame(bottom_frame, width=100).pack(side='right')

        # （已去掉分页控件，直接显示所有任务）

        # ===== 日志区域 =====
        log_frame = ttk.Frame(log_tab)
        log_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, wrap='word', font=FONT_MONO)
        self.log_text.pack(side='left', fill='both', expand=True)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side='right', fill='y')
        self.log_text.config(yscrollcommand=log_scroll.set)

        self.progress_var = tk.DoubleVar(value=0)
        self.stat_var = tk.StringVar(value='就绪')
        self.speed_var = tk.StringVar(value='')

        # ===== 底部状态栏 =====
        ttk.Label(status_bar, textvariable=self.stat_var, style='Muted.TLabel').pack(side='left', padx=(10, 0))
        ttk.Label(status_bar, textvariable=self.speed_var, style='Muted.TLabel').pack(side='right', padx=(0, 10))
        ttk.Label(status_bar, textvariable=self.timer_var, style='Muted.TLabel').pack(side='right', padx=(0, 14))
        # 构建完成后再统一上一次色（构建过程中新建的原生控件也跟上）
        self._apply_widget_theme()
        # 顶部已收成一行：抓取参数进了「高级选项」面板，运行控制行按需显隐，不再需要宽度自适应

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

    def _get_progress_file(self, save_dir):
        """进度文件放在软件数据目录（保存目录外），清空保存目录不影响断点续传"""
        import os
        import hashlib
        base = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                            'WebGrabber', 'progress')
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            base = save_dir
        key = hashlib.md5((save_dir or 'default').encode('utf-8')).hexdigest()[:12]
        return os.path.join(base, 'progress_%s.json' % key)

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
        """独立窗口打开浏览器（用于登录/装插件；不嵌入软件窗口）"""
        import subprocess

        # 先清理残留进程并等端口释放，确保9222端口能正常监听
        self._kill_stale_debug_browser()
        self._wait_debug_port_free()

        user_data_dir = self._debug_profile_dir()
        os.makedirs(user_data_dir, exist_ok=True)
        self._prepare_debug_profile(user_data_dir)

        browser_path, browser_name = self._find_browser_exe()
        if not browser_path:
            self._log('未找到 Chrome 或 Edge 浏览器')
            return

        try:
            subprocess.Popen([
                browser_path,
                '--remote-debugging-port=9222',
                '--remote-allow-origins=*',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-session-crashed-bubble',
                '--disable-features=InfiniteSessionRestore',
                '--disable-gpu',
                '--disable-gpu-compositing',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--user-data-dir=' + user_data_dir,
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 独立窗口是给用户自己操作（登录/装插件）的，不代表软件内的调试浏览器，
            # 清掉 PID 以免之后「启动调试浏览器」拿它来嵌入
            self._debug_browser_pid = None
            self._log('已独立窗口启动 %s（9222端口），可登录/装插件' % browser_name)
        except Exception as e:
            self._log('独立窗口启动浏览器失败: %s' % e)

    def _open_appt_window(self):
        """预约资料库窗口：姓名/身份证/手机/地址/数量，保存后供「自动填写」使用"""
        import tkinter.ttk as _ttk
        import tkinter.messagebox as _mb
        if getattr(self, 'appt_win', None) is not None and self.appt_win.winfo_exists():
            self.appt_win.lift()
            self.appt_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self.appt_win = win
        win.title('预约资料库')
        win.geometry('300x250+20+20')
        win.resizable(False, False)

        prof = dict(self.cfg.get('appt_profile') or {})
        fields = [
            ('name', '姓名', 18),
            ('idcard', '身份证号', 18),
            ('mobile', '手机号', 18),
            ('address', '地址', 22),
            ('count', '预约数量', 6),
        ]
        self.appt_vars = {}
        body = ttk.Frame(win)
        body.pack(fill='both', expand=True, padx=10, pady=8)
        for key, label, w in fields:
            row = ttk.Frame(body)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=8).pack(side='left')
            var = tk.StringVar(value=str(prof.get(key, '')))
            self.appt_vars[key] = var
            ttk.Entry(row, textvariable=var, width=w).pack(side='left', fill='x', expand=True)

        btns = ttk.Frame(win)
        btns.pack(fill='x', padx=10, pady=(0, 8))

        def _save():
            new = {k: v.get().strip() for k, v in self.appt_vars.items()}
            self.cfg['appt_profile'] = new
            save_config(self.cfg)
            self._log('预约资料已保存')
            _mb.showinfo('提示', '预约资料已保存', parent=win)

        def _fill_cur():
            _save()
            self._appt_fill()

        ttk.Button(btns, text='保存', width=6, command=_save).pack(side='left')
        ttk.Button(btns, text='保存并填写当前页', width=13, command=_fill_cur).pack(side='left', padx=4)
        ttk.Label(btns, text='（填写功能需浏览器模式已启动）', style='Muted.TLabel').pack(side='left')
        self._apply_widget_theme(win)

    def _appt_fill(self):
        """用预约资料自动填写当前浏览器页面的表单（工行/农行等预约页）"""
        prof = dict(self.cfg.get('appt_profile') or {})
        if not prof.get('name') or not prof.get('idcard'):
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请先在「预约资料」里填好姓名和身份证号')
            return
        import json as _json
        P = {k: v for k, v in prof.items()}
        js = r'''(function(){
          var P=%(P)s;
          var filled=[];
          function setField(els, value, kws, tag){
            if(!value)return;
            for(var i=0;i<els.length;i++){
              var el=els[i];
              if(el.disabled||el.readOnly)continue;
              var ph=String(el.placeholder||'').toLowerCase();
              var nm=String(el.name||el.id||'').toLowerCase();
              var ok=false;
              for(var j=0;j<kws.length;j++){if(ph.indexOf(kws[j])>=0||nm.indexOf(kws[j])>=0){ok=true;break;}}
              if(!ok)continue;
              try{
                var proto=el.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;
                var setter=Object.getOwnPropertyDescriptor(proto,'value').set;
                setter.call(el, value);
              }catch(e){el.value=value;}
              el.dispatchEvent(new Event('input',{bubbles:true}));
              el.dispatchEvent(new Event('change',{bubbles:true}));
              el.dispatchEvent(new Event('blur',{bubbles:true}));
              filled.push(tag+':'+(nm||ph));
              break;
            }
          }
          var els=Array.prototype.slice.call(document.querySelectorAll('input,textarea'));
          setField(els, P.name,    ['xingming','username','recvname','customer','姓名'], '姓名');
          setField(els, P.idcard,  ['idcard','idno','id_no','sfz','certno','certno','certificate','credential','身份证','证件','idnumber','id_number'], '身份证');
          setField(els, P.mobile,  ['mobile','mobilephone','phone','tel','contact','手机','电话','mobilephone'], '手机');
          setField(els, P.address, ['address','addr','detailaddr','recvaddr','收货','地址'], '地址');
          setField(els, P.count,   ['quantity','count','num','amount','数量'], '数量');
          return filled;
        })()''' % {'P': _json.dumps(P, ensure_ascii=False)}
        try:
            ok, text = self._ai_execute_js(js, timeout=8)
        except Exception as e:
            self._log('自动填写失败: %s' % e)
            return
        filled = []
        if ok and text.startswith('执行成功'):
            import json as _json2
            try:
                val = _json2.loads(text[len('执行成功: '):])
                if isinstance(val, list):
                    filled = val
            except Exception:
                pass
        self._log('自动填写完成，已填 %d 项: %s' % (len(filled), '、'.join(filled) if filled else '无'))
        if not filled:
            self._log('提示: 未匹配到可填字段，可能页面未打开或字段命名特殊，可开AI对话让AI帮填')

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

    def _toggle_maximize(self, event=None):
        """F11：切换最大化/还原（Windows 上 Tk 最大化后还原失灵的兜底）"""
        if self.root.state() == 'zoomed':
            self.root.state('normal')
            self.root.geometry('900x740')
        else:
            self.root.state('zoomed')
        return 'break'

    def _restore_window(self, event=None):
        """Esc：从最大化强制恢复原尺寸"""
        if self.root.state() == 'zoomed':
            self.root.state('normal')
            self.root.geometry('900x740')
        return 'break'

    def _browse_dir(self):
        """浏览保存目录（初始目录=当前值）"""
        cur = self.dir_var.get().strip()
        init = cur if cur and os.path.isdir(cur) else None
        directory = filedialog.askdirectory(title='选择保存目录', initialdir=init)
        if directory:
            self.dir_var.set(os.path.normpath(directory))
            self._save_settings()
            self._dir_refresh_combo()

    def _open_save_dir(self, _event=None):
        """打开保存目录：优先用任务列表里选中那条的目录，否则用全局保存目录（不存在则先创建）"""
        d = ''
        # 优先：任务列表里选中那一条的保存目录
        try:
            selected = self.task_tree.selection()
            if selected:
                vals = self.task_tree.item(selected[0], 'values')
                if len(vals) > 5 and str(vals[5]).strip():
                    d = str(vals[5]).strip()
        except Exception:
            pass
        if not d:
            d = self.dir_var.get().strip()
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '无法打开目录：%s\n%s' % (d, e))

    def _open_screenshots_dir(self):
        """打开临时截图目录"""
        shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
        try:
            os.makedirs(shot_dir, exist_ok=True)
            os.startfile(shot_dir)
        except Exception as e:
            self._log('打开截图目录失败: %s' % e)

    def _clear_screenshots_manual(self):
        """手动清理临时截图：全部清空（自动保留200张是防累积，手动按钮直接清空）"""
        shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
        removed = 0
        if os.path.isdir(shot_dir):
            for f in os.listdir(shot_dir):
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    try:
                        os.remove(os.path.join(shot_dir, f))
                        removed += 1
                    except Exception:
                        pass
        if removed:
            self._log('已手动清理临时截图: 删除 %d 张' % removed)
        else:
            self._log('临时截图目录为空，无需清理')

    def _open_settings(self):
        """打开设置窗口：保存目录/线程/超时/最小图 + AI 模型与服务配置"""
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title('设置')
        win.geometry('780x580')
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
        # 下拉=历史目录（可手输），历史由 _dir_remember 维护、存 cfg['save_dirs']
        self.dir_combo = ttk.Combobox(r1, textvariable=self.dir_var, width=56)
        self.dir_combo.pack(side='left', padx=2)
        self.dir_combo.bind('<<ComboboxSelected>>', lambda e: self._on_dir_pick())
        ttk.Button(r1, text='浏览', width=5, command=self._browse_dir).pack(side='left')
        ttk.Button(r1, text='打开', width=5, command=self._open_save_dir).pack(side='left', padx=(4, 0))
        self._dir_refresh_combo()
        r2 = ttk.Frame(gen)
        r2.pack(fill='x', padx=6, pady=3)
        ttk.Label(r2, text='临时截图:').pack(side='left')
        shot_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'screenshots')
        self.shot_dir_var = tk.StringVar(value=shot_dir)
        ttk.Entry(r2, textvariable=self.shot_dir_var, width=58, state='readonly').pack(side='left', padx=2)
        ttk.Button(r2, text='打开', width=5, command=self._open_screenshots_dir).pack(side='left')
        ttk.Button(r2, text='清理', width=6, command=self._clear_screenshots_manual).pack(side='left', padx=(4, 0))

        # ===== AI 模型与服务 =====
        ai = ttk.LabelFrame(win, text='AI 模型与服务（内置本地 / Ollama / 云端API 三选一）')
        ai.pack(fill='x', padx=8, pady=6)
        r3 = ttk.Frame(ai)
        r3.pack(fill='x', padx=6, pady=3)
        ttk.Label(r3, text='AI方式:').pack(side='left')
        ai_mode_combo = ttk.Combobox(r3, textvariable=self.ai_mode_var, width=16, state='readonly')
        ai_mode_combo['values'] = ('local', 'ollama', 'api')
        ai_mode_combo.pack(side='left', padx=2)
        ai_mode_combo.bind('<<ComboboxSelected>>', lambda e: self._ai_mode_changed())

        # 本地内置（llama-server）配置组
        self.ai_local_frame = ttk.Frame(ai)
        self.ai_local_frame.pack(fill='x', padx=6, pady=3)
        r4 = ttk.Frame(self.ai_local_frame)
        r4.pack(fill='x', pady=2)
        ttk.Label(r4, text='主模型:').pack(side='left')
        ttk.Entry(r4, textvariable=self.ai_model_var, width=60).pack(side='left', padx=2)
        ttk.Button(r4, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_model_var')).pack(side='left')
        r5 = ttk.Frame(self.ai_local_frame)
        r5.pack(fill='x', pady=2)
        ttk.Label(r5, text='视觉模块:').pack(side='left')
        ttk.Entry(r5, textvariable=self.ai_mmproj_var, width=60).pack(side='left', padx=2)
        ttk.Button(r5, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_mmproj_var')).pack(side='left')
        r6 = ttk.Frame(self.ai_local_frame)
        r6.pack(fill='x', pady=2)
        ttk.Label(r6, text='服务程序:').pack(side='left')
        ttk.Entry(r6, textvariable=self.ai_server_var, width=62).pack(side='left', padx=2)
        ttk.Button(r6, text='浏览', width=5, command=lambda: self._browse_ai_file('ai_server_var')).pack(side='left')

        # Ollama 配置组（模型名 + 端口）
        self.ai_ollama_frame = ttk.Frame(ai)
        self.ai_ollama_frame.pack(fill='x', padx=6, pady=3)
        r7 = ttk.Frame(self.ai_ollama_frame)
        r7.pack(fill='x', pady=2)
        ttk.Label(r7, text='模型名:').pack(side='left')
        ttk.Entry(r7, textvariable=self.ai_model_var, width=44).pack(side='left', padx=2)
        ttk.Label(r7, text='端口:').pack(side='left', padx=(12, 2))
        ttk.Spinbox(r7, from_=1024, to=65535, textvariable=self.ai_port_var, width=7).pack(side='left')
        ttk.Label(r7, text='(默认11434)').pack(side='left', padx=4)

        # 云端API 配置组（地址/Key/模型列表/开关）
        self.ai_api_frame = ttk.Frame(ai)
        self.ai_api_frame.pack(fill='x', padx=6, pady=3)
        r8 = ttk.Frame(self.ai_api_frame)
        r8.pack(fill='x', pady=2)
        ttk.Label(r8, text='服务商:').pack(side='left')
        self.ai_provider_btn = ttk.Button(r8, textvariable=self.ai_provider_var, width=16,
                                          command=self._ai_choose_provider)
        self.ai_provider_btn.pack(side='left', padx=2)
        ttk.Label(r8, text='API地址:').pack(side='left', padx=(10, 2))
        ttk.Entry(r8, textvariable=self.ai_api_base_var, width=36).pack(side='left', padx=2)
        r9 = ttk.Frame(self.ai_api_frame)
        r9.pack(fill='x', pady=2)
        ttk.Label(r9, text='API Key:').pack(side='left')
        self.ai_api_key_entry = ttk.Entry(r9, textvariable=self.ai_api_key_var, width=44, show='*')
        self.ai_api_key_entry.pack(side='left', padx=2)
        ttk.Button(r9, text='显示', width=4, command=self._ai_toggle_key_show).pack(side='left')
        r9b = ttk.Frame(self.ai_api_frame)
        r9b.pack(fill='x', pady=2)
        ttk.Checkbutton(r9b, text='关闭思维链', variable=self.ai_api_no_thinking_var).pack(side='left', padx=(0, 16))
        ttk.Checkbutton(r9b, text='启用高级参数', variable=self.ai_api_adv_var,
                        command=self._ai_adv_toggle).pack(side='left')
        # 高级参数行（默认隐藏）
        self.ai_adv_row = ttk.Frame(self.ai_api_frame)
        ttk.Label(self.ai_adv_row, text='温度:').pack(side='left')
        ttk.Spinbox(self.ai_adv_row, from_=0.0, to=2.0, increment=0.1,
                    textvariable=self.ai_api_temperature_var, width=5).pack(side='left', padx=2)
        ttk.Label(self.ai_adv_row, text='最大tokens:').pack(side='left', padx=(12, 2))
        ttk.Spinbox(self.ai_adv_row, from_=64, to=8192,
                    textvariable=self.ai_api_max_tokens_var, width=7).pack(side='left')
        # 模型选择：LLM（对话/分析）+ VLM（看图识别），自动从 API 拉取
        r10 = ttk.Frame(self.ai_api_frame)
        r10.pack(fill='x', pady=2)
        ttk.Label(r10, text='LLM模型:').pack(side='left')
        self.ai_model_combo = ttk.Combobox(r10, textvariable=self.ai_api_model_var, width=26)
        self.ai_model_combo.pack(side='left', padx=2)
        ttk.Label(r10, text='VLM模型:').pack(side='left', padx=(14, 2))
        self.ai_vlm_combo = ttk.Combobox(r10, textvariable=self.ai_api_vlm_var, width=26)
        self.ai_vlm_combo.pack(side='left', padx=2)
        r10b = ttk.Frame(self.ai_api_frame)
        r10b.pack(fill='x', pady=2)
        ttk.Button(r10b, text='获取模型', width=10, command=self._ai_fetch_models).pack(side='left')
        ttk.Button(r10b, text='手动添加', width=10, command=self._ai_add_model).pack(side='left', padx=(4, 0))
        ttk.Button(r10b, text='测试连接', width=10, command=self._ai_test_api).pack(side='left', padx=(4, 0))
        self.ai_fetch_status_var = tk.StringVar(value='')
        ttk.Label(r10b, textvariable=self.ai_fetch_status_var, foreground='#c00').pack(side='left', padx=6)
        self._refresh_api_models()
        if self.ai_api_adv_var.get():
            self.ai_adv_row.pack(fill='x', pady=2)

        # 公共：对话上下文
        r6b = ttk.Frame(ai)
        r6b.pack(fill='x', padx=6, pady=2)
        ttk.Label(r6b, text='端口:').pack(side='left')
        ttk.Spinbox(r6b, from_=1024, to=65535, textvariable=self.ai_port_var, width=7).pack(side='left', padx=2)
        ttk.Label(r6b, text='对话上下文(条):').pack(side='left', padx=(16, 2))
        ttk.Spinbox(r6b, from_=1, to=100, textvariable=self.ai_chat_ctx_var, width=6).pack(side='left')
        self._ai_mode_changed()

        # ===== 关于与更新 =====
        about = ttk.LabelFrame(win, text='关于与更新')
        about.pack(fill='x', padx=8, pady=6)
        r11 = ttk.Frame(about)
        r11.pack(fill='x', padx=6, pady=2)
        ttk.Label(r11, text='软件版本:').pack(side='left')
        ttk.Label(r11, text=APP_VERSION).pack(side='left', padx=2)
        ttk.Label(r11, text='    核心引擎(Scrapling):').pack(side='left')
        self.core_ver_var = tk.StringVar(value=self._get_scrapling_ver())
        ttk.Label(r11, textvariable=self.core_ver_var).pack(side='left', padx=2)
        ttk.Label(r11, text='    Python:').pack(side='left')
        ttk.Label(r11, text=sys.version.split()[0]).pack(side='left', padx=2)
        r12 = ttk.Frame(about)
        r12.pack(fill='x', padx=6, pady=2)
        ttk.Button(r12, text='检查更新', width=10, command=self._check_core_update).pack(side='left')
        self.core_update_status_var = tk.StringVar(value='')
        ttk.Label(r12, textvariable=self.core_update_status_var, style='Danger.TLabel').pack(side='left', padx=6)
        ttk.Label(r12, text='（检查核心引擎是否出新版，有则一键升级+重打包）', style='Muted.TLabel').pack(side='left', padx=6)
        # 新建的子窗口控件也要跟上主题
        self._apply_widget_theme(win)

    def _ai_provider_changed(self, e=None):
        """服务商预设：选中后自动填入 API 地址"""
        url = AI_PROVIDERS.get(self.ai_provider_var.get(), '')
        if url:
            self.ai_api_base_var.set(url)

    def _save_provider_state(self, name=None):
        """把当前 Key/LLM/VLM/模型列表 存入指定服务商配置（切走前调用）"""
        name = name or self.ai_provider_var.get()
        if not getattr(self, '_ai_providers_cfg', None):
            self._ai_providers_cfg = {}
        self._ai_providers_cfg[name] = {
            'key': self.ai_api_key_var.get().strip(),
            'llm': self.ai_api_model_var.get().strip(),
            'vlm': self.ai_api_vlm_var.get().strip(),
            'models': list(getattr(self, '_ai_api_models', [])),
        }

    def _load_provider_state(self, name):
        """切换服务商后加载其 Key/模型配置"""
        pcfg = getattr(self, '_ai_providers_cfg', {}).get(name) or {}
        self.ai_api_key_var.set(pcfg.get('key', ''))
        self.ai_api_model_var.set(pcfg.get('llm', ''))
        self.ai_api_vlm_var.set(pcfg.get('vlm', ''))
        self._ai_api_models = list(pcfg.get('models') or [])
        self._refresh_api_models()

    def _ai_choose_provider(self):
        """弹出服务商选择窗口：搜索+列表，选中自动填入API地址"""
        win = tk.Toplevel(self.settings_win)
        win.title('选择服务商')
        win.geometry('340x440')
        win.transient(self.settings_win)
        win.grab_set()
        win.resizable(False, False)
        search = ttk.Entry(win)
        search.pack(fill='x', padx=8, pady=(8, 4))
        search.insert(0, '搜索模型平台...')
        search.bind('<FocusIn>', lambda e: search.selection_range(0, 'end'))
        frame = ttk.Frame(win)
        frame.pack(fill='both', expand=True, padx=8, pady=4)
        lb = tk.Listbox(frame, font=('Microsoft YaHei UI', 10), activestyle='dotbox')
        sb = ttk.Scrollbar(frame, orient='vertical', command=lb.yview)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        names = list(AI_PROVIDERS.keys())

        def refresh(_=None):
            kw = search.get().strip().lower()
            if kw == '搜索模型平台...':
                kw = ''
            lb.delete(0, 'end')
            for n in names:
                if not kw or kw in n.lower() or kw in AI_PROVIDERS[n].lower():
                    lb.insert('end', n)
            cur = self.ai_provider_var.get()
            if cur in names:
                try:
                    lb.selection_set(names.index(cur))
                    lb.see(names.index(cur))
                except Exception:
                    pass

        def pick(_=None):
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if name == self.ai_provider_var.get():
                win.destroy()
                return
            # 保存当前服务商配置 → 切换 → 加载新服务商配置
            self._save_provider_state()
            url = AI_PROVIDERS.get(name, '')
            self.ai_provider_var.set(name)
            if url:
                self.ai_api_base_var.set(url)
            self._load_provider_state(name)
            win.destroy()

        def fill(_=None):
            refresh()
            pick()

        refresh()
        search.bind('<KeyRelease>', refresh)
        lb.bind('<<ListboxSelect>>', fill)
        lb.bind('<Double-Button-1>', pick)
        win.bind('<Escape>', lambda e: win.destroy())
        win.bind('<Return>', fill)
        self._apply_widget_theme(win)

    def _ai_toggle_key_show(self):
        """API Key 显示/掩码切换"""
        e = self.ai_api_key_entry
        if e is not None:
            e.config(show='' if e.cget('show') == '*' else '*')

    def _ai_adv_toggle(self):
        """高级参数行展开/收起"""
        if self.ai_api_adv_var.get():
            self.ai_adv_row.pack(fill='x', pady=2)
        else:
            self.ai_adv_row.pack_forget()

    def _ai_fetch_models(self):
        """从 API 自动拉取可用模型列表（GET /models）"""
        base = self.ai_api_base_var.get().strip().rstrip('/')
        key = self.ai_api_key_var.get().strip()
        if not base or not key:
            messagebox.showwarning('获取模型', '请先填写 API地址 和 API Key', parent=self.settings_win)
            return
        # 规范化 /models 地址：去掉 /chat/completions 尾巴；保持 /v1 或 /paas/v4
        if base.endswith('/chat/completions'):
            base = base[:base.rfind('/chat/completions')]
        url = base + '/models'
        self.ai_fetch_status_var.set('获取中...')
        threading.Thread(target=self._ai_fetch_models_worker, args=(url, key), daemon=True).start()

    def _ai_fetch_models_worker(self, url, key):
        """后台线程：GET /models 拉模型列表"""
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key,
                                                       'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = _json.loads(r.read())
            ids = [str(x.get('id')) for x in d.get('data', []) if x.get('id')]
            ids = sorted(set(ids))
            if not ids:
                self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                            messagebox.showinfo('获取模型', '接口返回空模型列表',
                                                                parent=self.settings_win)))
                return
            cur = self.ai_api_model_var.get().strip()
            cur_v = self.ai_api_vlm_var.get().strip()
            if cur not in ids:
                self.ai_api_model_var.set(ids[0])
            if cur_v not in ids:
                # 优先挑带视觉关键词的模型作 VLM 默认，否则取 LLM 之后的第一个
                vis = [x for x in ids if any(k in x.lower() for k in ('v', 'vision', 'vl', 'glm-4v'))]
                self.ai_api_vlm_var.set(vis[0] if vis else ids[min(1, len(ids) - 1)])
            self._ai_api_models = ids
            self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                        self._refresh_api_models(),
                                        messagebox.showinfo('获取模型',
                                                            '获取到 %d 个模型，已刷新列表\n%s'
                                                            % (len(ids), '、'.join(ids[:15]) + ('…' if len(ids) > 15 else '')),
                                                            parent=self.settings_win)))
        except Exception as e:
            self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                        messagebox.showerror('获取模型', '获取失败：%s\n\n'
                                                             '检查 API地址/Key 是否正确、服务是否支持 /models 接口；'
                                                             '不支持时可点「手动添加」。' % e,
                                                             parent=self.settings_win)))

    def _ai_add_model(self):
        """手动添加模型（服务不支持 /models 接口时兜底）"""
        from tkinter import simpledialog
        name = simpledialog.askstring('手动添加', '输入模型名（如 glm-4.7-flash、qwen-max）:',
                                      parent=self.settings_win)
        if not name or not name.strip():
            return
        name = name.strip()
        models = list(getattr(self, '_ai_api_models', []))
        if name not in models:
            models.append(name)
        if not self.ai_api_model_var.get().strip():
            self.ai_api_model_var.set(name)
        self._ai_api_models = models
        self._refresh_api_models()

    def _refresh_api_models(self):
        """刷新 LLM/VLM 下拉列表"""
        if not hasattr(self, 'ai_model_combo'):
            return
        models = list(getattr(self, '_ai_api_models', []))
        cur = self.ai_api_model_var.get().strip()
        cur_v = self.ai_api_vlm_var.get().strip()
        if not models and (cur or cur_v):
            models = [cur] if cur else [cur_v]
        self.ai_model_combo['values'] = tuple(models)
        self.ai_vlm_combo['values'] = tuple(models)
        if cur not in models and models:
            self.ai_api_model_var.set(models[0])
        if cur_v not in models and models:
            vis = [x for x in models if any(k in x.lower() for k in ('v', 'vision', 'vl', 'glm-4v'))]
            self.ai_api_vlm_var.set(vis[0] if vis else models[min(1, len(models) - 1)])

    def _ai_test_api(self):
        """测试 API 连通性：用当前 LLM 模型发最小请求"""
        base = self.ai_api_base_var.get().strip()
        key = self.ai_api_key_var.get().strip()
        model = self.ai_api_model_var.get().strip()
        if not base or not key or not model:
            messagebox.showwarning('测试连接', '请先填写 API地址、API Key 和 LLM模型',
                                   parent=self.settings_win)
            return
        self.ai_fetch_status_var.set('测试中...')
        threading.Thread(target=self._ai_test_api_worker, daemon=True).start()

    def _ai_test_api_worker(self):
        """后台线程：发最小请求并返回详细结果"""
        import requests
        import time
        base = self.ai_api_base_var.get().strip().rstrip('/')
        key = self.ai_api_key_var.get().strip()
        model = self.ai_api_model_var.get().strip()
        if base.endswith('/chat/completions'):
            url = base
        elif base.endswith('/v1'):
            url = base + '/chat/completions'
        else:
            url = base + '/v1/chat/completions'
        start = time.time()
        try:
            r = requests.post(url,
                              json={'model': model,
                                    'messages': [{'role': 'user', 'content': '你好，请只回复：连接成功'}],
                                    'max_tokens': 16, 'temperature': 0},
                              headers={'Authorization': 'Bearer ' + key}, timeout=30)
            cost = time.time() - start
            if r.status_code == 200:
                content = (r.json()['choices'][0]['message'].get('content') or '').strip()
                self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                            messagebox.showinfo('测试连接',
                                                                '✓ 连接成功（%.1f秒）\n模型回复：%s'
                                                                % (cost, content or '(空)'),
                                                                parent=self.settings_win)))
            else:
                err = (r.text or '')[:200].replace('\n', ' ')
                self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                            messagebox.showerror('测试连接',
                                                                '✗ 请求失败 HTTP %d\n%s\n\n'
                                                                '检查：Key是否正确、模型名是否存在' % (r.status_code, err),
                                                                parent=self.settings_win)))
        except Exception as e:
            self.root.after(0, lambda: (self.ai_fetch_status_var.set(''),
                                        messagebox.showerror('测试连接',
                                                            '✗ 连接失败：%s\n\n'
                                                            '检查：地址是否可访问（可能需要代理）' % e,
                                                            parent=self.settings_win)))

    def _ai_mode_changed(self):
        """AI 方式切换：显示对应配置组"""
        mode = self.ai_mode_var.get()
        for f, m in ((getattr(self, 'ai_local_frame', None), 'local'),
                     (getattr(self, 'ai_ollama_frame', None), 'ollama'),
                     (getattr(self, 'ai_api_frame', None), 'api')):
            if f is not None:
                if mode == m:
                    f.pack(fill='x', padx=6, pady=3)
                else:
                    f.pack_forget()

    # ===== 关于与更新 =====
    @staticmethod
    def _get_scrapling_ver():
        try:
            import scrapling
            return getattr(scrapling, '__version__', '未知')
        except Exception:
            return '未知'

    def _check_core_update(self):
        """检查核心引擎（Scrapling库）是否有新版本"""
        self.core_update_status_var.set('检查中...')
        threading.Thread(target=self._core_check_worker, daemon=True).start()

    def _core_check_worker(self):
        """后台线程：查 PyPI 最新版并对比本地"""
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request('https://pypi.org/pypi/scrapling/json',
                                         headers={'User-Agent': 'Mozilla/5.0'})
            d = _json.load(urllib.request.urlopen(req, timeout=12))
            latest = d['info']['version']
        except Exception as e:
            self.root.after(0, lambda: (self.core_update_status_var.set(''),
                                        messagebox.showinfo('检查更新',
                                                            '检查失败：无法访问 PyPI 网络（%s）' % e,
                                                            parent=self.settings_win)))
            return
        local = self._get_scrapling_ver()

        def done():
            self.core_update_status_var.set('')
            if ver_gt(latest, local):
                r = messagebox.askyesno(
                    '发现新版本',
                    '核心引擎 Scrapling 有新版本：\n当前 %s  →  最新 %s\n\n'
                    '是否立即更新？\n（自动升级库并重新打包 exe，约3分钟，'
                    '期间软件会退出后自动重启，需在开发机源码目录运行）' % (local, latest),
                    parent=self.settings_win)
                if r:
                    self._run_core_update()
            else:
                messagebox.showinfo('检查更新', '核心引擎已是最新版本（%s）' % local,
                                    parent=self.settings_win)
        self.root.after(0, done)

    def _find_source_file(self):
        """定位源码文件（开发机）：当前目录或 exe 的上级目录"""
        import os
        for c in (os.path.join(os.getcwd(), 'scrapling_grabber_gui.py'),
                  os.path.join(os.path.dirname(os.path.dirname(sys.executable)),
                               'scrapling_grabber_gui.py')):
            if os.path.exists(c):
                return c
        return None

    def _run_core_update(self):
        """一键更新：升级库 → 杀旧进程 → 重打包 → 覆盖L盘 → 自动重启"""
        src = self._find_source_file()
        if not src:
            messagebox.showwarning(
                '一键更新',
                '当前是打包版运行环境，无法自动更新。\n'
                '请到开发机源码目录（含 scrapling_grabber_gui.py 的文件夹）'
                '打开本软件后再点检查更新。',
                parent=self.settings_win)
            return
        self.core_update_status_var.set('更新中(1/3)：升级核心库...')
        threading.Thread(target=self._core_update_worker, args=(src,), daemon=True).start()

    def _core_update_worker(self, src):
        """后台线程：执行一键更新流程"""
        import os
        import subprocess
        import shutil
        import time
        base = os.path.dirname(src)
        exe_name = '%s_GUI_%s.exe' % (APP_NAME, APP_VERSION)
        dist_exe = os.path.join(base, 'dist', exe_name)

        def upd(text):
            self.root.after(0, lambda: self.core_update_status_var.set(text))

        def fail(msg):
            upd('更新失败')
            self.root.after(0, lambda: messagebox.showerror(
                '一键更新', msg, parent=self.settings_win))
        try:
            # 1. 升级核心库
            upd('更新中(1/3)：升级核心库...')
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'scrapling'],
                               cwd=base, capture_output=True, timeout=300, text=True)
            if r.returncode != 0:
                fail('pip 升级失败：\n%s' % ((r.stderr or r.stdout)[-500:]))
                return
            # 2. 杀旧进程（避免 exe 占用）
            subprocess.run(['powershell', '-Command',
                            "Get-Process -Name '*%s*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" % APP_NAME],
                           cwd=base, timeout=30)
            time.sleep(2)
            # 3. 重新打包
            upd('更新中(2/3)：重新打包exe（约2-3分钟）...')
            b = subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--onefile',
                                '--windowed', '--collect-all', 'scrapling',
                                '--name', exe_name[:-4], 'scrapling_grabber_gui.py'],
                               cwd=base, capture_output=True, timeout=900, text=True)
            if not os.path.exists(dist_exe):
                fail('重新打包失败：\n%s' % ((b.stderr or b.stdout)[-500:]))
                return
            # 4. 覆盖 L 盘存档
            upd('更新中(3/3)：同步L盘存档...')
            try:
                l_dst = r'L:\工作流\小工具\%s\%s' % (APP_NAME, APP_VERSION)
                os.makedirs(l_dst, exist_ok=True)
                if os.path.isdir(l_dst):
                    shutil.copy2(dist_exe, os.path.join(l_dst, exe_name))
                    shutil.copy2(src, os.path.join(l_dst, 'scrapling_grabber_gui.py'))
            except Exception:
                pass
            # 5. 自动重启
            upd('更新完成，重启中...')
            subprocess.Popen([dist_exe], cwd=base)
            self.root.after(800, lambda: (self.core_update_status_var.set('完成'),
                                          self._close_settings()))
        except Exception as e:
            fail('更新出错：%s' % e)

    def _toggle_game_mod_window(self):
        """点一下：EC窗口贴合主窗口右侧显示；再点：隐藏"""
        if getattr(self, 'game_win', None) is not None and self.game_win.winfo_exists():
            if self.game_win.state() == 'normal':
                self.game_win.withdraw()
                return
            self.game_win.deiconify()
            self._snap_game_win()
            return
        self._create_game_win()
        self._snap_game_win()

    def _snap_game_win(self):
        """游戏修改窗口磁吸主窗口右边缘（贴合无缝隙，高度与主窗口同长）"""
        try:
            self.root.update_idletasks()
            rx = self.root.winfo_x()
            ry = self.root.winfo_y()
            rw = self.root.winfo_width()
            rh = max(300, self.root.winfo_height())
            self.game_win.geometry('320x%d+%d+%d' % (rh, rx + rw, ry))
            self._ec_docked = True
        except Exception:
            pass

    def _on_root_configure(self, e):
        """主窗口移动/缩放：贴合状态的修改器/AI窗实时跟随（用winfo查询，不依赖e.x_root——Windows上它为0）"""
        try:
            if self.root.state() != 'normal':
                return  # 主窗口最小化/隐藏时不动子窗口，让修改器/AI窗独立留在桌面
            if (getattr(self, 'game_win', None) and self.game_win.winfo_exists()
                    and self.game_win.state() == 'normal' and getattr(self, '_ec_docked', False)):
                cur = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width())
                if cur != getattr(self, '_last_root_pos_game', None):
                    self._last_root_pos_game = cur
                    self._snap_game_win()
            if (getattr(self, 'ai_float_win', None) and self.ai_float_win.winfo_exists()
                    and self.ai_float_win.state() == 'normal' and getattr(self, '_ai_float_docked', False)):
                cur = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width())
                if cur != getattr(self, '_last_root_pos_ai', None):
                    self._last_root_pos_ai = cur
                    self._snap_ai_float_win()
        except Exception:
            pass

    def _poll_game_snap(self):
        """轮询兜底：Configure未触发时（如拖动中），贴合状态的窗口也跟随"""
        try:
            if self.root.state() != 'normal':
                pass  # 主窗口最小化时保持子窗口独立，不跟随
            else:
                if (getattr(self, 'game_win', None) and self.game_win.winfo_exists()
                        and self.game_win.state() == 'normal' and getattr(self, '_ec_docked', False)):
                    cur = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width())
                    if cur != getattr(self, '_last_root_pos_game', None):
                        self._last_root_pos_game = cur
                        self._snap_game_win()
                if (getattr(self, 'ai_float_win', None) and self.ai_float_win.winfo_exists()
                        and self.ai_float_win.state() == 'normal' and getattr(self, '_ai_float_docked', False)):
                    cur = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width())
                    if cur != getattr(self, '_last_root_pos_ai', None):
                        self._last_root_pos_ai = cur
                        self._snap_ai_float_win()
        except Exception:
            pass
        self.root.after(150, self._poll_game_snap)

    def _create_game_win(self):
        """EC 模式窗口：网页游戏数值 搜索→过滤→修改/锁定（Cheat Engine 风格）"""
        if getattr(self, 'game_win', None) is not None and self.game_win.winfo_exists():
            self.game_win.lift()
            self.game_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self.game_win = win
        win.title('游戏数值修改')
        win.geometry('320x600+0+0')
        # 不用 transient：Windows 下 transient 子窗口会跟随主窗口一起最小化/隐藏，
        # 主窗口最小化后修改器窗要能独立留在桌面

        self.ec_scan_state = None   # 上次命中路径列表 [(segs,...)]
        self.ec_locks = []          # 当前锁定项列表 [{'segs','value','key'}]
        self._ec_docked = False     # 是否贴合主窗口（拖走变False，松手靠近吸回）
        import tkinter.ttk as _ttk
        import tkinter.messagebox as _mb

        # 顶部：数值 + 扫描按钮（两行紧凑排版）
        top = ttk.Frame(win)
        top.pack(fill='x', padx=6, pady=6)
        ttk.Label(top, text='数值:').pack(side='left')
        self.ec_value_var = tk.StringVar(value='100')
        ttk.Entry(top, textvariable=self.ec_value_var, width=9).pack(side='left', padx=3)
        ttk.Button(top, text='首次扫描', width=7, command=self._ec_first_scan).pack(side='left', padx=1)
        ttk.Button(top, text='再次扫描', width=7, command=self._ec_next_scan).pack(side='left', padx=1)
        # 数据类型下拉
        self.ec_type_var = tk.StringVar(value='自动')
        ttk.Label(top, text='类型:').pack(side='left', padx=(8,2))
        ttk.Combobox(top, textvariable=self.ec_type_var, values=['自动','整数','浮点','字符串'], width=5, state='readonly').pack(side='left')
        top2 = ttk.Frame(win)
        top2.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Button(top2, text='清除结果', width=7, command=self._ec_clear).pack(side='left')
        ttk.Button(top2, text='未知初值', width=7, command=self._ec_unknown_scan).pack(side='left', padx=1)
        ttk.Button(top2, text='未变动', width=6, command=lambda: self._ec_diff_scan('unchanged')).pack(side='left', padx=1)
        ttk.Button(top2, text='已变动', width=6, command=lambda: self._ec_diff_scan('changed')).pack(side='left', padx=1)
        ttk.Button(top2, text='增加', width=6, command=lambda: self._ec_diff_scan('increased')).pack(side='left', padx=1)
        ttk.Button(top2, text='减少', width=6, command=lambda: self._ec_diff_scan('decreased')).pack(side='left', padx=1)
        self.ec_count_var = tk.StringVar(value='尚未扫描')
        ttk.Label(top2, textvariable=self.ec_count_var, style='Muted.TLabel').pack(side='left', padx=8)
        # WASM 线性内存：与 JS 变量扫描合并进同一流程（勾选即参与首次/再次/变动扫描）
        top3 = ttk.Frame(win)
        top3.pack(fill='x', padx=6, pady=(0, 2))
        self.ec_wasm_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top3, text='WASM内存', variable=self.ec_wasm_var).pack(side='left')
        self.ec_wasm_type_var = tk.StringVar(value='i32+f32')
        ttk.Combobox(top3, textvariable=self.ec_wasm_type_var, width=7, state='readonly',
                     values=['i32+f32', 'i32', 'f32', 'i32+f64', 'f64',
                             'u32', 'i16', 'u16', 'i8', 'u8', '全部']).pack(side='left', padx=2)
        ttk.Button(top3, text='高级', width=4, command=self._create_wasm_win).pack(side='left', padx=2)
        ttk.Label(top3, text='扫内存用', style='Muted.TLabel').pack(side='left', padx=4)

        # 上/下可拖拽分栏（PanedWindow，默认对半分）
        pane = ttk.PanedWindow(win, orient='vertical')
        pane.pack(fill='both', expand=True, padx=6, pady=(4, 0))

        # 上半区：搜索结果列表
        mid = ttk.Frame(pane)
        cols = ('path', 'value')
        self.ec_tree = ttk.Treeview(mid, columns=cols, show='headings', height=12)
        self.ec_tree.heading('path', text='变量路径')
        self.ec_tree.heading('value', text='当前值')
        self.ec_tree.column('path', width=210)
        self.ec_tree.column('value', width=70, anchor='center')
        self.ec_tree.pack(fill='both', expand=True)
        self.ec_tree.bind('<Double-1>', lambda e: self._ec_add_lock_from_selected())
        pane.add(mid, weight=1)

        # 下半区：锁定条目列表（CE 风格：#0列图片勾选框/路径/锁定值，点勾选框切换启用暂停）
        lock_frame = ttk.LabelFrame(pane, text='锁定条目（点启用列切换启用/暂停）')
        lcols = ('path', 'value')
        self.ec_lock_tree = ttk.Treeview(lock_frame, columns=lcols, show='tree headings', height=5)
        self.ec_lock_tree.heading('#0', text='启用')
        self.ec_lock_tree.heading('path', text='变量路径')
        self.ec_lock_tree.heading('value', text='锁定值')
        self.ec_lock_tree.column('#0', width=46, anchor='center')
        self.ec_lock_tree.column('path', width=180)
        self.ec_lock_tree.column('value', width=70, anchor='center')
        self.ec_lock_tree.pack(fill='both', expand=True)
        self.ec_lock_tree.bind('<Button-1>', self._ec_toggle_lock_click)
        self.ec_lock_tree.bind('<Double-1>', self._ec_edit_lock_value)
        lbtns = ttk.Frame(lock_frame)
        lbtns.pack(fill='x', side='bottom', pady=(2, 2))
        ttk.Button(lbtns, text='解锁选中', width=7, command=self._ec_unlock_selected).pack(side='left', padx=1)
        ttk.Button(lbtns, text='改值', width=5, command=self._ec_edit_lock_btn).pack(side='left', padx=1)
        ttk.Button(lbtns, text='启用全部', width=7, command=lambda: self._ec_lock_all(True)).pack(side='left', padx=1)
        ttk.Button(lbtns, text='暂停全部', width=7, command=lambda: self._ec_lock_all(False)).pack(side='left', padx=1)
        self.ec_lock_var = tk.StringVar(value='未锁定')
        ttk.Label(lbtns, textvariable=self.ec_lock_var, foreground='#c0392b').pack(side='left', padx=6)
        pane.add(lock_frame, weight=1)

        # 底部：新值 + 修改/锁定 + 加入即锁定开关
        bot = ttk.Frame(win)
        bot.pack(fill='x', padx=6, pady=6)
        ttk.Label(bot, text='新值:').pack(side='left')
        self.ec_newval_var = tk.StringVar(value='999999')
        ttk.Entry(bot, textvariable=self.ec_newval_var, width=9).pack(side='left', padx=3)
        ttk.Button(bot, text='修改', width=5, command=self._ec_edit_selected).pack(side='left', padx=1)
        ttk.Button(bot, text='锁定', width=5, command=lambda: self._ec_lock(True)).pack(side='left', padx=1)
        self.ec_lock_on_add_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bot, text='双击加入即锁定', variable=self.ec_lock_on_add_var).pack(side='left', padx=6)
        win.protocol('WM_DELETE_WINDOW', self._ec_close)
        # 主窗口移动跟随：Configure实时（winfo查询）+ 轮询兜底
        if not getattr(self, '_root_cfg_bound', False):
            self.root.bind('<Configure>', self._on_root_configure)
            self._root_cfg_bound = True
        if not getattr(self, '_snap_poll_started', False):
            self.root.after(150, self._poll_game_snap)
            self._snap_poll_started = True
        # 独立拖动/缩放：列宽自适应 + 松手靠近主窗口自动吸回
        win.bind('<Configure>', self._on_game_win_configure)
        # 打开时自动恢复上次扫描结果与锁定
        self.root.after(400, self._ec_restore_state)
        self._apply_widget_theme(win)

    def _on_game_win_configure(self, e):
        """窗口独立拖动/缩放：放大时路径列伸展；松手在边缘100px内自动吸回；拖远自由"""
        try:
            if e.widget != self.game_win:
                return
            gw = self.game_win
            w = e.width
            if w > 150:
                self.ec_tree.column('path', width=max(120, w - 95))
            # 位置变化时才判断
            gx, gy = gw.winfo_x(), gw.winfo_y()
            last = getattr(self, '_ec_last_xy', None)
            if last == (gx, gy):
                return
            self._ec_last_xy = (gx, gy)
            if gw.state() != 'normal':
                return
            rx, ry, rw = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width()
            rh = self.root.winfo_height()
            if abs(gx - (rx + rw)) <= 100 and gy + gw.winfo_height() > ry and gy < ry + rh:
                self._snap_game_win()
            else:
                self._ec_docked = False
        except Exception:
            pass

    # ===== AI对话磁吸窗（与游戏修改窗口同款贴合机制） =====
    def _toggle_ai_float_window(self):
        """点一下：AI对话窗贴合主窗口右侧显示；再点：隐藏"""
        if getattr(self, 'ai_float_win', None) is not None and self.ai_float_win.winfo_exists():
            if self.ai_float_win.state() == 'normal':
                self.ai_float_win.withdraw()
                return
            self.ai_float_win.deiconify()
            self._snap_ai_float_win()
            return
        self._create_ai_float_win()
        self._snap_ai_float_win()
        # 兜底：Windows 首次映射可能覆盖 geometry，延迟再贴一次
        self.ai_float_win.after(120, self._snap_ai_float_win)

    def _snap_ai_float_win(self):
        """AI对话窗磁吸主窗口右边缘（高度与主窗口同长）"""
        try:
            self.root.update_idletasks()
            rx = self.root.winfo_x()
            ry = self.root.winfo_y()
            rw = self.root.winfo_width()
            rh = max(300, self.root.winfo_height())
            self.ai_float_win.geometry('360x%d+%d+%d' % (rh, rx + rw, ry))
            self._ai_float_docked = True
        except Exception:
            pass

    def _create_ai_float_win(self):
        """AI对话磁吸窗：对话记录 + 输入发送/截图/清空（复用助手对话逻辑）"""
        win = tk.Toplevel(self.root)
        self.ai_float_win = win
        win.title('AI对话')
        win.geometry('420x600+0+0')
        # 不用 transient：Windows 会把 transient 窗口强制定位到父窗口中央，干扰磁吸
        self._ai_float_docked = False
        self._ai_float_last_xy = None

        # 顶部辅助栏：粘贴/选区/清空（底部只留输入+截图给AI+发送）
        topbar = ttk.Frame(win)
        topbar.pack(side='top', fill='x', padx=6, pady=(4, 0))
        ttk.Label(topbar, text='AI对话').pack(side='left')
        ttk.Button(topbar, text='清空', width=5, command=self._ai_clear_chat).pack(side='right', padx=1)
        ttk.Button(topbar, text='选区', width=5, command=self._ai_region_shot).pack(side='right', padx=1)
        ttk.Button(topbar, text='粘贴', width=5, command=self._ai_paste_shot).pack(side='right', padx=1)

        # 底部输入栏先 pack（Text 后 pack 吃剩余，避免被 expand 挤掉）
        bottom = ttk.Frame(win)
        bottom.pack(side='bottom', fill='x', padx=6, pady=6)
        self.ai_float_input = ttk.Entry(bottom)
        self.ai_float_input.pack(side='left', fill='x', expand=True)
        self.ai_float_input.bind('<Return>', lambda e: self._ai_chat_send_from(self.ai_float_input))
        self.ai_float_input.bind('<Control-v>', lambda e: self._ai_on_ctrl_v(self.ai_float_input))
        try:
            import windnd
            windnd.hook_dropfiles(self.ai_float_input, func=self._ai_on_drop_file)
            windnd.hook_dropfiles(self.ai_float_text, func=self._ai_on_drop_file)
        except Exception:
            pass
        ttk.Button(bottom, text='截图给AI', width=8,
                   command=self._ai_add_shot).pack(side='left', padx=(4, 0))
        ttk.Button(bottom, text='发送', width=6,
                   command=lambda: self._ai_chat_send_from(self.ai_float_input)).pack(side='left', padx=(4, 0))

        txt = tk.Text(win, wrap='word', font=('Consolas', 9))
        ai_scroll = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=ai_scroll.set)
        txt.pack(side='left', fill='both', expand=True)
        ai_scroll.pack(side='right', fill='y')
        txt.tag_configure('ts', font=('Microsoft YaHei UI', 8), foreground='#999999')
        txt.tag_configure('req_bubble', background='#e3f2fd', lmargin1=70, lmargin2=70, rmargin=10,
                          spacing1=3, spacing3=3)
        txt.tag_configure('resp_bubble', background='#e8f5e9', lmargin1=10, lmargin2=10, rmargin=70,
                          spacing1=3, spacing3=3)
        txt.tag_configure('tool', foreground='#b45309')
        txt.tag_configure('req', foreground='#1a56db')
        txt.tag_configure('resp', foreground='#0d7a3d')
        txt.tag_configure('sep', foreground='#bbbbbb')
        self.ai_float_text = txt

        win.protocol('WM_DELETE_WINDOW', self._ai_float_close)
        # 独立拖动/缩放：松手靠近主窗口自动吸回
        win.bind('<Configure>', self._on_ai_float_configure)
        # 主窗口移动跟随：Configure实时（winfo查询）+ 轮询兜底（与游戏修改窗共用）
        if not getattr(self, '_root_cfg_bound', False):
            self.root.bind('<Configure>', self._on_root_configure)
            self._root_cfg_bound = True
        if not getattr(self, '_snap_poll_started', False):
            self.root.after(150, self._poll_game_snap)
            self._snap_poll_started = True
        # 把页签已有对话同步过来
        try:
            txt.insert('1.0', self.ai_chat_text.get('1.0', 'end'))
        except Exception:
            pass
        self._apply_widget_theme(win)

    def _ai_float_close(self):
        """X 关闭 = 隐藏（贴合窗口复用）"""
        try:
            self.ai_float_win.withdraw()
        except Exception:
            pass

    def _on_ai_float_configure(self, e):
        """AI对话窗拖动/缩放：松手在边缘100px内自动吸回；拖远自由"""
        try:
            if e.widget != self.ai_float_win:
                return
            gw = self.ai_float_win
            gx, gy = gw.winfo_x(), gw.winfo_y()
            last = getattr(self, '_ai_float_last_xy', None)
            if last == (gx, gy):
                return
            self._ai_float_last_xy = (gx, gy)
            if gw.state() != 'normal':
                return
            rx, ry, rw = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width()
            rh = self.root.winfo_height()
            if abs(gx - (rx + rw)) <= 100 and gy + gw.winfo_height() > ry and gy < ry + rh:
                self._snap_ai_float_win()
            else:
                self._ai_float_docked = False
        except Exception:
            pass

    def _ec_close(self):
        """X 关闭 = 隐藏（贴合窗口复用）；锁定保持运行，重开自动恢复"""
        try:
            self._ec_locks_refresh()
            if self.ec_locks:
                self.ec_lock_var.set('已锁定（隐藏中，仍生效）')
        except Exception:
            pass
        try:
            self.game_win.withdraw()
        except Exception:
            pass

    def _ec_clear(self):
        self.ec_scan_state = None
        self.ec_locks = []
        try:
            self._ai_ec_lock([], 0, False, 'ALL')
        except Exception:
            pass
        for i in self.ec_tree.get_children():
            self.ec_tree.delete(i)
        self._ec_locks_refresh()
        self.ec_count_var.set('已清除')
        self.cfg.pop('ec_scan_paths', None)
        self.cfg.pop('ec_locks', None)
        save_config(self.cfg)

    def _ec_save_state(self):
        """保存扫描路径+锁定项到配置（重开/刷新后自动恢复，免重新搜索）"""
        try:
            if self.ec_scan_state:
                self.cfg['ec_scan_paths'] = [list(s) for s in self.ec_scan_state[:500]]
            else:
                self.cfg.pop('ec_scan_paths', None)
            if self.ec_locks:
                self.cfg['ec_locks'] = [{'segs': list(x['segs']), 'value': x['value'],
                                         'enabled': bool(x.get('enabled', True))} for x in self.ec_locks]
            else:
                self.cfg.pop('ec_locks', None)
            save_config(self.cfg)
        except Exception:
            pass

    def _ec_restore_state(self):
        """恢复上次扫描结果：回读路径当前值 + 自动恢复全部锁定"""
        self.ec_locks = []  # 每次打开重新恢复，避免重复追加
        paths = self.cfg.get('ec_scan_paths')
        locks = self.cfg.get('ec_locks') or []
        if paths:
            hits = self._ai_ec_reload([list(p) for p in paths])
            if hits:
                self.ec_scan_state = [s for s, v in hits]
                self._ec_fill(hits)
            elif hits is not None:
                self.ec_count_var.set('已恢复，但路径全部失效（页面可能已变），请重新扫描')
        if locks:
            restored = 0
            # 含 WASM 地址时先注入内存读写助手，否则锁定脚本找不到 __wgWrite
            if any(self._ec_is_wasm(list(lk.get('segs', []))) for lk in locks):
                self._wasm_boot()
            for lk in locks:
                try:
                    segs = list(lk.get('segs', []))
                    value = lk.get('value', 0)
                    enabled = bool(lk.get('enabled', True))
                    key = '.'.join(str(s) for s in segs)
                    if enabled:
                        self._ai_ec_lock(segs, value, True, key)
                    self.ec_locks.append({'segs': segs, 'value': value, 'key': key, 'enabled': enabled})
                    restored += 1
                except Exception:
                    pass
            if restored:
                self._ec_locks_refresh()
                self._log('EC锁定恢复: %d 项' % restored)

    def _ec_is_wasm(self, segs):
        """该路径段是否为 WASM 内存地址 ['__wasm', memIdx, type, offset]"""
        return bool(segs) and str(segs[0]) == '__wasm'

    def _ec_label(self, segs):
        """结果列表显示文本：WASM 显示地址，JS 显示变量路径"""
        if self._ec_is_wasm(segs) and len(segs) >= 4:
            return self._wasm_label(segs[1], segs[2], segs[3])
        return '.'.join(str(s) for s in segs)

    def _ec_wasm_types(self):
        """按界面选择返回要扫描的 WASM 数据类型"""
        if not getattr(self, 'ec_wasm_var', None) or not self.ec_wasm_var.get():
            return []
        sel = ''
        if getattr(self, 'ec_wasm_type_var', None):
            sel = (self.ec_wasm_type_var.get() or '').strip()
        return {'i32+f32': ['i32', 'f32'], 'i32+f64': ['i32', 'f64'],
                '全部': list(WASM_TYPES)}.get(sel, [sel if sel in WASM_TYPES else 'i32'])

    def _ec_scan_wasm(self, value, prev_wasm=None, compare=None, unknown=False):
        """扫描 WASM 线性内存（所有内存块 × 选中类型），返回 [(segs, value)]，与 JS 变量结果同构"""
        types = self._ec_wasm_types()
        if prev_wasm:
            # 过滤/对比模式：只处理上次命中过的类型，且忽略界面的开关
            types = sorted({str(s[2]) for (s, _v) in prev_wasm if str(s[2]) in WASM_TYPE_SIZE})
        elif not types:
            return []
        mems, _err = self._wasm_boot()
        if not mems:
            return []
        sample = 3000 if unknown else 20000
        out = []
        for (mi, _n, _k) in mems:
            for wt in types:
                if prev_wasm:
                    prev_t = [(int(s[3]), v) for (s, v) in prev_wasm
                              if int(s[1]) == int(mi) and str(s[2]) == wt]
                    if not prev_t:
                        continue
                else:
                    prev_t = None
                meta, res = self._wasm_scan(mi, wt, value=value, prev=prev_t, compare=compare,
                                            unknown=unknown, limit=800, sample=sample)
                if meta is None or not res:
                    continue
                for (o, v) in res:
                    out.append((self._wasm_segs(mi, wt, o), v))
            if len(out) >= 3000:
                break
        return out

    def _ec_fill(self, hits):
        """填充结果列表（JS 变量路径 + WASM 地址混排，用 iid→segs 映射保证选中可还原）"""
        for i in self.ec_tree.get_children():
            self.ec_tree.delete(i)
        self.ec_tree_segs = {}
        if not hits:
            self.ec_count_var.set('无匹配')
            return
        for segs, v in hits[:300]:
            label = self._ec_label(segs)
            if self._ec_is_wasm(segs):
                v = self._wasm_fmt_val(v, segs[2])
            iid = self.ec_tree.insert('', 'end', values=(label, v))
            self.ec_tree_segs[iid] = list(segs)
        nw = sum(1 for (s, _v) in hits if self._ec_is_wasm(s))
        txt = '命中 %d 个' % len(hits)
        if nw:
            txt += '（WASM %d）' % nw
        self.ec_count_var.set(txt)

    def _ec_do_scan(self, first):
        """统一扫描：JS 变量搜索 + WASM 线性内存搜索，结果合并进同一列表"""
        if getattr(self, '_ec_scanning', False):
            return
        self._ec_scanning = True
        try:
            import tkinter.messagebox as _mb
            try:
                value = float(self.ec_value_var.get().strip())
            except Exception:
                _mb.showwarning('提示', '请输入有效数值', parent=self.game_win)
                return
            if first:
                self.ec_count_var.set('扫描中…')
                try:
                    self.game_win.update_idletasks()
                except Exception:
                    pass
                hits = self._ai_ec_scan(value)
                if hits is None:
                    _mb.showwarning('提示', '调试浏览器未运行，请先启动浏览器模式', parent=self.game_win)
                    return
                merged = [(list(s), v) for (s, v) in hits]
                w_hits = self._ec_scan_wasm(value)
                if w_hits:
                    merged += w_hits
                    self._log('WASM内存命中 %d 个地址' % len(w_hits))
                self.ec_scan_state = merged
                self._ec_fill(merged)
            else:
                if not self.ec_scan_state:
                    _mb.showwarning('提示', '请先「首次扫描」', parent=self.game_win)
                    return
                prev = self.ec_scan_state
                js_prev = [(s, v) for (s, v) in prev if not self._ec_is_wasm(s)]
                w_prev = [(s, v) for (s, v) in prev if self._ec_is_wasm(s)]
                merged = []
                if js_prev:
                    r = self._ai_ec_scan(value, js_prev)
                    if r:
                        merged += [(list(s), v) for (s, v) in r]
                if w_prev:
                    merged += self._ec_scan_wasm(value, prev_wasm=w_prev)
                # 增量过滤为空时，自动全量重扫（游戏重建对象后旧路径会失效）
                if not merged:
                    r = self._ai_ec_scan(value) or []
                    merged = [(list(s), v) for (s, v) in r]
                    merged += self._ec_scan_wasm(value)
                self.ec_scan_state = merged
                self._ec_fill(merged)
        finally:
            self._ec_scanning = False
        self._ec_save_state()

    def _ec_diff_scan(self, compare):
        """变动过滤：JS 变量与 WASM 地址一起对比"""
        if getattr(self, '_ec_scanning', False):
            return
        self._ec_scanning = True
        try:
            import tkinter.messagebox as _mb
            if not self.ec_scan_state:
                _mb.showwarning('提示', '请先「首次扫描」', parent=self.game_win)
                return
            prev = self.ec_scan_state
            js_prev = [(s, v) for (s, v) in prev if not self._ec_is_wasm(s)]
            w_prev = [(s, v) for (s, v) in prev if self._ec_is_wasm(s)]
            merged = []
            if js_prev:
                r = self._ai_ec_scan(0, js_prev, compare=compare)
                if r:
                    merged += [(list(s), v) for (s, v) in r]
            if w_prev:
                merged += self._ec_scan_wasm(None, prev_wasm=w_prev, compare=compare)
            if not merged:
                _mb.showinfo('结果', '变动过滤后无结果（游戏可能重建了对象）\n请重新「首次扫描」当前数值',
                             parent=self.game_win)
                return
            self.ec_scan_state = merged
            self._ec_fill(merged)
            self._ec_save_state()
        finally:
            self._ec_scanning = False

    def _ec_unknown_scan(self):
        """未知初值：JS 变量枚举 + WASM 均匀采样，一起记录"""
        if getattr(self, '_ec_scanning', False):
            return
        self._ec_scanning = True
        try:
            import tkinter.messagebox as _mb
            self.ec_count_var.set('扫描中…')
            try:
                self.game_win.update_idletasks()
            except Exception:
                pass
            hits = self._ai_ec_scan(None, unknown=True)
            if hits is None:
                _mb.showwarning('提示', '调试浏览器未运行，请先启动浏览器模式', parent=self.game_win)
                return
            merged = [(list(s), v) for (s, v) in hits]
            merged += self._ec_scan_wasm(None, unknown=True)
            self.ec_scan_state = merged
            self._ec_fill(merged)
            self._ec_save_state()
        finally:
            self._ec_scanning = False

    def _ec_first_scan(self):
        self._ec_do_scan(True)

    def _ec_next_scan(self):
        self._ec_do_scan(False)

    def _ec_selected_segs(self):
        sel = self.ec_tree.selection()
        if not sel:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请先在列表中选中一个变量', parent=self.game_win)
            return None
        segs = getattr(self, 'ec_tree_segs', {}).get(sel[0])
        if segs is not None:
            return list(segs)
        # 兜底：从显示文本反解（兼容旧数据）
        path = self.ec_tree.item(sel[0], 'values')[0]
        if path.startswith('W#') and ' 0x' in path:
            try:
                head, addr = path.split(' 0x')
                mi = int(head.split(' ')[0][2:])
                wt = head.split(' ')[1]
                return ['__wasm', mi, wt, int(addr, 16)]
            except Exception:
                return None
        return ['window'] + path.split('.')[1:]

    def _ec_edit_selected(self):
        segs = self._ec_selected_segs()
        if not segs:
            return
        try:
            value = float(self.ec_newval_var.get().strip())
        except Exception:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请输入有效数值', parent=self.game_win)
            return
        if self._ec_is_wasm(segs):
            self._wasm_boot()   # 确保 WASM 读写助手已注入
        ok, msg = self._ai_ec_edit(segs, value)
        import tkinter.messagebox as _mb
        _mb.showinfo('结果', msg, parent=self.game_win)

    def _ec_add_lock_from_selected(self):
        """双击搜索结果行：按「新值」加入下方锁定列表（是否启动锁由勾选决定）"""
        segs = self._ec_selected_segs()
        if not segs:
            return
        try:
            value = float(self.ec_newval_var.get().strip())
        except Exception:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请输入有效数值', parent=self.game_win)
            return
        if self._ec_is_wasm(segs):
            self._wasm_boot()
        enabled = self.ec_lock_on_add_var.get()
        key = '.'.join(str(s) for s in segs)
        for item in self.ec_locks:
            if item['key'] == key:
                item['value'] = value
                item['enabled'] = enabled
                self._ai_ec_lock(item['segs'], value, enabled, key)
                break
        else:
            self.ec_locks.append({'segs': list(segs), 'value': value, 'key': key, 'enabled': enabled})
            self._ai_ec_lock(segs, value, enabled, key)
        self._ec_locks_refresh()
        self._log('EC加入锁定: %s = %s（%s）' % (key, value, '已启用' if enabled else '已暂停'))
        self._ec_save_state()

    def _ec_edit_lock_btn(self):
        """「改值」按钮：对锁定列表中选中的行改锁定值（双击的兜底方案）"""
        try:
            sel = self.ec_lock_tree.selection()
            if not sel:
                import tkinter.messagebox as _mb
                _mb.showinfo('提示', '请先在下方锁定列表中选中要改值的条目', parent=self.root)
                return
            idx = self._ec_lock_idx_by_iid(sel[0])
            self._ec_edit_lock_at(idx)
        except Exception as ex:
            self._log('改值失败: %s' % ex)

    def _ec_edit_lock_value(self, e=None):
        """双击锁定列表行：修改该条的锁定值（整行双击均可，不依赖选中状态）"""
        try:
            if e is None:
                sel = self.ec_lock_tree.selection()
                if not sel:
                    return
                iid = sel[0]
            else:
                if self.ec_lock_tree.identify_column(e.x) == '#0':
                    return  # 双击勾选框列=快速切换，不弹改值
                iid = self.ec_lock_tree.identify_row(e.y)
                if not iid:
                    return
            idx = self._ec_lock_idx_by_iid(iid)
            self._ec_edit_lock_at(idx)
        except Exception as ex:
            self._log('双击改值失败: %s' % ex)

    def _ec_edit_lock_at(self, idx):
        """按索引改某条锁定值：弹框输入新值，立即生效并保存"""
        if idx < 0 or idx >= len(self.ec_locks):
            self._log('改值索引无效: %s' % idx)
            return
        item = self.ec_locks[idx]
        import tkinter.simpledialog as _sd
        try:
            newv = _sd.askstring('修改锁定值', '变量: %s\n当前锁定值: %s\n\n新锁定值:' % (item['key'], item['value']),
                                 initialvalue=str(item['value']), parent=self.root)
        except Exception as ex:
            self._log('弹框失败: %s' % ex)
            return
        if newv is None:
            return
        try:
            v = float(newv.strip())
        except Exception:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请输入有效数值', parent=self.root)
            return
        try:
            item['value'] = v
            if item.get('enabled', True):
                if self._ec_is_wasm(item['segs']):
                    self._wasm_boot()
                self._ai_ec_lock(item['segs'], v, True, item['key'])
            self._ec_locks_refresh()
            self._log('EC锁定值修改: %s = %s' % (item['key'], v))
            self._ec_save_state()
        except Exception as ex:
            self._log('改值写入失败: %s' % ex)

    def _ec_lock(self, enable):
        """把搜索列表选中行加入/更新锁定（锁定条目显示在下半区）"""
        if not enable:
            return
        segs = self._ec_selected_segs()
        if not segs:
            return
        try:
            value = float(self.ec_newval_var.get().strip())
        except Exception:
            import tkinter.messagebox as _mb
            _mb.showwarning('提示', '请输入有效数值', parent=self.game_win)
            return
        if self._ec_is_wasm(segs):
            self._wasm_boot()
        key = '.'.join(str(s) for s in segs)
        for item in self.ec_locks:
            if item['key'] == key:
                item['value'] = value
                item['enabled'] = True
                self._ai_ec_lock(item['segs'], value, True, key)
                break
        else:
            self.ec_locks.append({'segs': list(segs), 'value': value, 'key': key, 'enabled': True})
            self._ai_ec_lock(segs, value, True, key)
        self._ec_locks_refresh()
        self._log('EC锁定: %s = %s（共%d项）' % (key, value, len(self.ec_locks)))
        self._ec_save_state()

    def _ec_check_images(self):
        """生成勾选框图片：启用=蓝底白勾，暂停=空框"""
        if getattr(self, '_chk_on', None) is not None:
            return
        self._chk_on = None
        self._chk_off = None
        try:
            from PIL import Image as _Img, ImageDraw as _Drw, ImageTk as _Tk
            def make(on):
                im = _Img.new('RGBA', (16, 16), (0, 0, 0, 0))
                d = _Drw.Draw(im)
                if on:
                    d.rounded_rectangle([1, 1, 15, 15], radius=3, fill='#0a84ff', outline='#0a84ff')
                    d.line([4, 8, 7, 11, 12, 5], fill='white', width=2)
                else:
                    d.rounded_rectangle([1, 1, 15, 15], radius=3, outline='#9aa0a6', width=1)
                return _Tk.PhotoImage(im)
            self._chk_on = make(True)
            self._chk_off = make(False)
        except Exception:
            self._chk_on = None
            self._chk_off = None

    def _ec_locks_refresh(self):
        """重绘下半区锁定条目列表"""
        try:
            for i in self.ec_lock_tree.get_children():
                self.ec_lock_tree.delete(i)
            if not self.ec_locks:
                self.ec_lock_var.set('未锁定')
                return
            self._ec_check_images()
            for item in self.ec_locks:
                enabled = item.get('enabled', True)
                img = self._chk_on if enabled else self._chk_off
                self.ec_lock_tree.insert('', 'end', image=img,
                                         values=('.'.join(str(s) for s in item['segs']), item['value']))
            active = sum(1 for x in self.ec_locks if x.get('enabled', True))
            self.ec_lock_var.set('已锁定 %d/%d 项' % (active, len(self.ec_locks)))
        except Exception:
            pass

    def _ec_lock_idx_by_iid(self, iid):
        """把 Treeview 行 iid 映射到 ec_locks 索引（用行序，不依赖 iid 格式）"""
        if not iid:
            return -1
        try:
            rows = self.ec_lock_tree.get_children()
            if iid in rows:
                return rows.index(iid)
            return int(iid[1:]) - 1
        except Exception:
            return -1

    def _ec_toggle_lock_click(self, e):
        """点锁定列表勾选框列（#0）：启用/暂停该锁"""
        row = self.ec_lock_tree.identify_row(e.y)
        col = self.ec_lock_tree.identify_column(e.x)
        if not row or col != '#0':
            return
        idx = self._ec_lock_idx_by_iid(row)
        if idx < 0 or idx >= len(self.ec_locks):
            return
        item = self.ec_locks[idx]
        item['enabled'] = not item.get('enabled', True)
        if item['enabled'] and self._ec_is_wasm(item['segs']):
            self._wasm_boot()
        if item['enabled']:
            self._ai_ec_lock(item['segs'], item['value'], True, item['key'])
        else:
            self._ai_ec_lock(item['segs'], item['value'], False, item['key'])
        self._ec_locks_refresh()
        self._ec_save_state()

    def _ec_unlock_selected(self):
        """解锁：删除锁定列表中选中的条目"""
        sel = self.ec_lock_tree.selection()
        if not sel:
            import tkinter.messagebox as _mb
            _mb.showinfo('提示', '请先在下方锁定列表中选中要解锁的条目', parent=self.root)
            return
        idx = self._ec_lock_idx_by_iid(sel[0])
        if idx < 0 or idx >= len(self.ec_locks):
            return
        item = self.ec_locks.pop(idx)
        self._ai_ec_lock(item['segs'], item['value'], False, item['key'])
        self._ec_locks_refresh()
        self._log('EC解锁: %s（剩余%d项）' % (item['key'], len(self.ec_locks)))
        self._ec_save_state()

    def _ec_lock_all(self, enable):
        """启用/暂停全部锁定（保留条目）"""
        for item in self.ec_locks:
            item['enabled'] = enable
            self._ai_ec_lock(item['segs'], item['value'], enable, item['key'])
        self._ec_locks_refresh()
        self._ec_save_state()

    # ==================================================================
    # WASM 线性内存扫描（Unity WebGL / Emscripten / Go / Rust 等网页游戏）
    # CE 风格：首次扫描 → 再次扫描/变动过滤 → 写入 / 锁定
    # 地址用 segs=['__wasm', memIdx, type, offset] 表示，
    # 写入与锁定复用 _ec_assign_expr / _ai_ec_edit / _ai_ec_lock 同一套机制
    # ==================================================================
    def _wasm_exec_js(self, code, timeout=30):
        """CDP 执行 JS 并返回结构化 value（与 _ai_execute_js 不同：返回原始对象而非文本）"""
        import json as _json
        try:
            import urllib.request as _ur
            import websocket as _ws
            pages = _json.loads(_ur.urlopen('http://127.0.0.1:9222/json/list', timeout=5).read())
            pages = [t for t in pages if t.get('type') == 'page']
            if not pages:
                return False, None, '调试浏览器没有打开的网页'
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=timeout)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                 'params': {'expression': code, 'returnByValue': True, 'awaitPromise': False}}))
            resp = _json.loads(ws.recv())
            try:
                ws.close()
            except Exception:
                pass
        except Exception as e:
            return False, None, '连接调试浏览器失败: %s' % e
        if 'error' in resp:
            return False, None, '执行失败: %s' % resp['error'].get('message', '?')
        r = resp.get('result', {})
        if 'exceptionDetails' in r:
            return False, None, 'JS异常: %s' % str(r['exceptionDetails'].get('exception', {}).get(
                'description', r['exceptionDetails'].get('text', '?')))[:300]
        return True, r.get('result', {}).get('value'), ''

    def _wasm_boot(self):
        """注入探测脚本并列出线性内存。返回 ([(idx, bytes, kind)], err)；失败首项为 None"""
        ok, _v, err = self._wasm_exec_js(WASM_BOOT_JS, timeout=20)
        if not ok:
            return None, err
        ok2, val, err2 = self._wasm_exec_js(
            '(function(){var W=window.__wgMem();var out=[];'
            'for(var i=0;i<W.m.length;i++){var e=W.m[i];var b=null;'
            'try{b=e.m?e.m.buffer:e.ab;}catch(err){}'
            'out.push({i:i,n:b?b.byteLength:0,k:e.m?"wasm":"buf"});}'
            'return out;})()', timeout=20)
        if not ok2:
            return None, err2
        return [(x.get('i', 0), x.get('n', 0), x.get('k', '?')) for x in (val or [])], ''

    def _wasm_scan_js(self, mem_idx, wtype, value=None, prev=None, compare=None,
                      unknown=False, byte_step=False, limit=2000, sample=20000):
        """构造扫描/过滤用的 JS（独立出来便于单独调试）"""
        import json as _json
        size = WASM_TYPE_SIZE[wtype]
        prevj = _json.dumps([{'o': int(o), 'v': v} for (o, v) in (prev or [])])
        tv = 'null' if (value is None or unknown) else _json.dumps(value)
        js = (
            '(function(){'
            'var W=window.__wgMem();'
            'var mi=%d,t=%s,unk=%s,limit=%d,sample=%d,size=%d,step1=%s,eps=%s;'
            'var prev=%s;var cmp=%s;var target=%s;'
            'var e=W.m[mi];'
            'if(!e)return {err:"内存索引不存在，请点刷新内存"};'
            'var b=null;try{b=e.m?e.m.buffer:e.ab;}catch(err){}'
            'if(!b||!b.byteLength)return {err:"内存已失效（页面可能已刷新），请点刷新内存"};'
            'var len=b.byteLength,dv=new DataView(b);'
            'function get(o){try{switch(t){'
            'case "i8":return dv.getInt8(o);'
            'case "u8":return dv.getUint8(o);'
            'case "i16":return dv.getInt16(o,true);'
            'case "u16":return dv.getUint16(o,true);'
            'case "i32":return dv.getInt32(o,true);'
            'case "u32":return dv.getUint32(o,true);'
            'case "f32":return dv.getFloat32(o,true);'
            'case "f64":return dv.getFloat64(o,true);}}catch(err){return null;}return null;}'
            'function eq(v){if(v===null||v===undefined)return false;'
            'if(t==="f32"||t==="f64"){if(!isFinite(v)||!isFinite(target))return false;'
            'return Math.abs(v-target)<=eps*Math.max(1,Math.abs(target));}'
            'return v===target;}'
            'var out=[];'
            'if(prev.length){'
            ' for(var i=0;i<prev.length;i++){'
            '  var o=prev[i].o,old=prev[i].v,cur=get(o);'
            '  if(cur===null||cur===undefined)continue;'
            '  var keep=false;'
            '  if(cmp){switch(cmp){'
            '   case "unchanged":keep=(cur===old);break;'
            '   case "changed":keep=(cur!==old);break;'
            '   case "increased":keep=(cur>old);break;'
            '   case "decreased":keep=(cur<old);break;}}'
            '  else{keep=eq(cur);}'
            '  if(keep)out.push({o:o,v:cur});'
            '  if(out.length>=limit)break;}'
            ' return {len:len,scanned:prev.length,out:out,mode:"filter",step:0};}'
            'var step=step1?1:size;'
            'if(unk){'
            ' var span=Math.floor((len-size)/sample)+1;'
            ' if(span>size){step=Math.floor(span/size)*size;}'
            ' if(step<size)step=size;'
            ' var total=0;'
            ' for(var o=0;o+size<=len&&out.length<sample;o+=step){'
            '  var v=get(o);if(v!==null)out.push({o:o,v:v});total++;}'
            ' return {len:len,scanned:total,out:out,mode:"sample",step:step};}'
            'var cnt=0;'
            'for(var o=0;o+size<=len;o+=step){cnt++;var v=get(o);'
            ' if(eq(v)){out.push({o:o,v:v});if(out.length>=limit)break;}}'
            'return {len:len,scanned:cnt,out:out,mode:"full",step:step};})()'
            % (int(mem_idx), _json.dumps(str(wtype)), 'true' if unknown else 'false',
               int(limit), int(sample), int(size), 'true' if byte_step else 'false',
               '1e-3', prevj, _json.dumps(compare or ''), tv))
        return js

    def _wasm_scan(self, mem_idx, wtype, value=None, prev=None, compare=None,
                   unknown=False, byte_step=False, limit=2000, sample=20000):
        """扫描/过滤 WASM 线性内存。
        prev: [(off, oldval)] 上次结果（含旧值，供变动对比）
        compare: None(精确) / unchanged / changed / increased / decreased
        unknown: 未知初值 → 均匀采样（内存太大无法全量保存）
        返回 (meta, hits)；hits=[(off, val)]；失败返回 (None, 错误文本)"""
        import json as _json
        if wtype not in WASM_TYPE_SIZE:
            return None, '不支持的数据类型: %s' % wtype
        js = self._wasm_scan_js(mem_idx, wtype, value=value, prev=prev, compare=compare,
                                unknown=unknown, byte_step=byte_step, limit=limit, sample=sample)
        ok, val, err = self._wasm_exec_js(js, timeout=30)
        if not ok:
            return None, err
        if not isinstance(val, dict):
            return None, '扫描返回异常（内存可能已被释放）'
        if val.get('err'):
            return None, str(val.get('err'))
        hits = [(h.get('o', 0), h.get('v')) for h in (val.get('out') or [])]
        meta = {'len': val.get('len', 0), 'scanned': val.get('scanned', 0),
                'mode': val.get('mode', ''), 'step': val.get('step', 0)}
        return meta, hits

    def _wasm_segs(self, mem_idx, wtype, off):
        """WASM 地址 → 统一路径段（供写入/锁定复用）"""
        return ['__wasm', int(mem_idx), str(wtype), int(off)]

    def _wasm_label(self, mem_idx, wtype, off):
        return 'W#%d %s 0x%08X' % (int(mem_idx), wtype, int(off))

    def _wasm_fmt_val(self, v, wtype):
        try:
            if v is None:
                return ''
            if wtype in ('f32', 'f64'):
                s = '%.6f' % float(v)
                return s.rstrip('0').rstrip('.') if '.' in s else s
            f = float(v)
            return str(int(f)) if f.is_integer() else str(v)
        except Exception:
            return str(v)

    def _create_wasm_win(self):
        """WASM 线性内存扫描窗口（独立于 JS 变量修改器，互不干扰）"""
        import tkinter.messagebox as _mb
        if getattr(self, 'wasm_win', None) is not None:
            try:
                if self.wasm_win.winfo_exists():
                    self.wasm_win.deiconify()
                    self.wasm_win.lift()
                    self.wasm_win.focus_set()
                    return
            except Exception:
                pass
        win = tk.Toplevel(self.root)
        self.wasm_win = win
        win.title('WASM 内存扫描')
        win.geometry('660x640+340+40')
        self.wasm_mems = getattr(self, 'wasm_mems', []) or []
        self.wasm_hits = getattr(self, 'wasm_hits', []) or []
        self.wasm_locks = getattr(self, 'wasm_locks', []) or []

        # ---- 第一行：内存选择 ----
        f1 = ttk.Frame(win)
        f1.pack(fill='x', padx=6, pady=(6, 3))
        ttk.Label(f1, text='线性内存:').pack(side='left')
        self.wasm_mem_var = tk.StringVar(value='未检测')
        self.wasm_mem_cb = ttk.Combobox(f1, textvariable=self.wasm_mem_var, width=26, state='readonly')
        self.wasm_mem_cb.pack(side='left', padx=3)
        ttk.Button(f1, text='刷新内存', width=8, command=lambda: self._wasm_refresh_mem()).pack(side='left', padx=2)
        ttk.Button(f1, text='重新注入', width=8,
                   command=lambda: self._wasm_refresh_mem(force=True)).pack(side='left', padx=2)

        # ---- 第二行：类型 + 数值 + 首次/再次 ----
        f2 = ttk.Frame(win)
        f2.pack(fill='x', padx=6, pady=2)
        ttk.Label(f2, text='类型:').pack(side='left')
        self.wasm_type_var = tk.StringVar(value='i32')
        ttk.Combobox(f2, textvariable=self.wasm_type_var, values=list(WASM_TYPES),
                     width=5, state='readonly').pack(side='left', padx=2)
        ttk.Label(f2, text='数值:').pack(side='left', padx=(8, 0))
        self.wasm_value_var = tk.StringVar(value='100')
        ttk.Entry(f2, textvariable=self.wasm_value_var, width=11).pack(side='left', padx=2)
        ttk.Button(f2, text='首次扫描', width=8, command=lambda: self._wasm_do_scan('first')).pack(side='left', padx=2)
        ttk.Button(f2, text='再次扫描', width=8, command=lambda: self._wasm_do_scan('next')).pack(side='left', padx=2)

        # ---- 第三行：未知初值 / 变动过滤 ----
        f3 = ttk.Frame(win)
        f3.pack(fill='x', padx=6, pady=2)
        ttk.Button(f3, text='未知初值', width=8, command=lambda: self._wasm_do_scan('unknown')).pack(side='left')
        ttk.Button(f3, text='未变动', width=6, command=lambda: self._wasm_do_scan('cmp', 'unchanged')).pack(side='left', padx=1)
        ttk.Button(f3, text='已变动', width=6, command=lambda: self._wasm_do_scan('cmp', 'changed')).pack(side='left', padx=1)
        ttk.Button(f3, text='增加', width=5, command=lambda: self._wasm_do_scan('cmp', 'increased')).pack(side='left', padx=1)
        ttk.Button(f3, text='减少', width=5, command=lambda: self._wasm_do_scan('cmp', 'decreased')).pack(side='left', padx=1)
        self.wasm_step_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f3, text='逐字节', variable=self.wasm_step_var).pack(side='left', padx=6)
        ttk.Button(f3, text='清空', width=5, command=self._wasm_clear).pack(side='left', padx=2)

        self.wasm_status_var = tk.StringVar(value='尚未扫描')
        ttk.Label(win, textvariable=self.wasm_status_var, style='Muted.TLabel').pack(anchor='w', padx=8, pady=(2, 0))

        # ---- 结果列表 ----
        mid = ttk.Frame(win)
        mid.pack(fill='both', expand=True, padx=6, pady=(3, 0))
        self.wasm_tree = ttk.Treeview(mid, columns=('addr', 'type', 'value'), show='headings', height=14)
        self.wasm_tree.heading('addr', text='地址')
        self.wasm_tree.heading('type', text='类型')
        self.wasm_tree.heading('value', text='当前值')
        self.wasm_tree.column('addr', width=120, anchor='w')
        self.wasm_tree.column('type', width=50, anchor='center')
        self.wasm_tree.column('value', width=140, anchor='center')
        vsb = ttk.Scrollbar(mid, orient='vertical', command=self.wasm_tree.yview)
        self.wasm_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.wasm_tree.pack(side='left', fill='both', expand=True)
        self.wasm_tree.bind('<Double-1>', lambda e: self._wasm_add_lock(True))

        # ---- 锁定列表 ----
        lf = ttk.LabelFrame(win, text='锁定条目（点启用列切换启用/暂停，双击改值）')
        lf.pack(fill='both', expand=True, padx=6, pady=(4, 0))
        self.wasm_lock_tree = ttk.Treeview(lf, columns=('addr', 'value'), show='tree headings', height=5)
        self.wasm_lock_tree.heading('#0', text='启用')
        self.wasm_lock_tree.heading('addr', text='地址')
        self.wasm_lock_tree.heading('value', text='锁定值')
        self.wasm_lock_tree.column('#0', width=46, anchor='center')
        self.wasm_lock_tree.column('addr', width=150)
        self.wasm_lock_tree.column('value', width=110, anchor='center')
        self.wasm_lock_tree.pack(fill='both', expand=True)
        self.wasm_lock_tree.bind('<Button-1>', self._wasm_toggle_lock_click)
        self.wasm_lock_tree.bind('<Double-1>', self._wasm_edit_lock_value)

        # ---- 底部：新值 + 写入/锁定 ----
        bot = ttk.Frame(win)
        bot.pack(fill='x', padx=6, pady=5)
        ttk.Label(bot, text='新值:').pack(side='left')
        self.wasm_newval_var = tk.StringVar(value='999999')
        ttk.Entry(bot, textvariable=self.wasm_newval_var, width=10).pack(side='left', padx=2)
        ttk.Button(bot, text='写入', width=5, command=self._wasm_write_selected).pack(side='left', padx=1)
        ttk.Button(bot, text='锁定', width=5, command=lambda: self._wasm_add_lock(True)).pack(side='left', padx=1)
        ttk.Button(bot, text='解锁选中', width=8, command=self._wasm_unlock_selected).pack(side='left', padx=1)
        self.wasm_lock_var = tk.StringVar(value='未锁定')
        ttk.Label(bot, textvariable=self.wasm_lock_var, foreground='#c0392b').pack(side='left', padx=6)

        win.protocol('WM_DELETE_WINDOW', self._wasm_close)
        self._apply_widget_theme(win)
        self.root.after(300, self._wasm_restore_state)

    def _wasm_refresh_mem(self, force=False, silent=False):
        """探测并列出页面里的 WASM 线性内存（silent=True 时不弹窗，用于后台自动探测）"""
        import tkinter.messagebox as _mb
        if force:
            try:
                self._wasm_exec_js('window.__wgWasm=null;true;', timeout=10)
            except Exception:
                pass
        mems, err = self._wasm_boot()
        if mems is None:
            self.wasm_mems = []
            try:
                self.wasm_mem_cb['values'] = []
                self.wasm_mem_var.set('未检测到 WASM 内存')
            except Exception:
                pass
            if silent:
                return []
            _mb.showwarning('提示',
                            '未检测到 WASM 内存：%s\n\n'
                            '请先启动浏览器模式并打开网页游戏，再点「刷新内存」。\n'
                            '（部分 Unity/Emscripten 游戏需等加载完成再探测）' % err,
                            parent=self.wasm_win)
            return []
        self.wasm_mems = mems
        labels = ['#%d · %s · %.1f MB' % (i, ('WASM' if k == 'wasm' else 'Buffer'), n / 1048576.0)
                  for (i, n, k) in mems]
        try:
            self.wasm_mem_cb['values'] = labels
            cur = self.wasm_mem_cb.current()
            if cur < 0 or cur >= len(labels):
                self.wasm_mem_cb.current(0)
        except Exception:
            pass
        self._log('WASM内存探测: %d 块' % len(mems))
        return mems

    def _wasm_cur_mem_idx(self):
        idx = None
        try:
            i = self.wasm_mem_cb.current()
            if 0 <= i < len(self.wasm_mems):
                idx = self.wasm_mems[i][0]
        except Exception:
            idx = None
        if idx is None and self.wasm_mems:
            idx = self.wasm_mems[0][0]
        return idx

    def _wasm_do_scan(self, mode, compare=None):
        """mode: first / next / unknown / cmp（cmp 需给 compare）"""
        import tkinter.messagebox as _mb
        if getattr(self, '_wasm_scanning', False):
            return
        self._wasm_scanning = True
        try:
            if not getattr(self, 'wasm_mems', None):
                if not self._wasm_refresh_mem(silent=True):
                    _mb.showwarning('提示',
                                    '未检测到 WASM 内存。\n请先启动浏览器模式、打开网页游戏，再点「刷新内存」。',
                                    parent=self.wasm_win)
                    return
            mi = self._wasm_cur_mem_idx()
            if mi is None:
                _mb.showwarning('提示', '请先选择要扫描的内存块', parent=self.wasm_win)
                return
            wt = self.wasm_type_var.get().strip()
            byte_step = bool(self.wasm_step_var.get())
            value, unknown, prev = None, False, None
            if mode == 'unknown':
                unknown = True
            else:
                txt = (self.wasm_value_var.get() or '').strip()
                if txt:
                    try:
                        value = float(txt)
                        if wt not in ('f32', 'f64') and float(value).is_integer():
                            value = int(value)
                    except Exception:
                        value = None
                if mode != 'cmp' and value is None:
                    _mb.showwarning('提示', '请输入要搜索的数值', parent=self.wasm_win)
                    return
            if mode == 'next' or mode == 'cmp':
                if not self.wasm_hits:
                    _mb.showwarning('提示', '请先做一次「首次扫描」或「未知初值」', parent=self.wasm_win)
                    return
                prev = [(h[2], h[3]) for h in self.wasm_hits]
            self.wasm_status_var.set('扫描中…')
            try:
                self.wasm_win.update_idletasks()
            except Exception:
                pass
            meta, res = self._wasm_scan(mi, wt, value=value, prev=prev, compare=compare,
                                        unknown=unknown, byte_step=byte_step)
            if meta is None:
                self.wasm_status_var.set('扫描失败')
                _mb.showwarning('提示', '扫描失败：%s' % res, parent=self.wasm_win)
                return
            self.wasm_hits = [(mi, wt, int(o), v) for (o, v) in res]
            self._wasm_fill()
            extra = ''
            if meta.get('mode') == 'sample':
                extra = '（均匀采样，步长%d字节，请继续用变动过滤收敛）' % meta.get('step', 0)
            elif meta.get('mode') == 'full' and len(res) >= 2000:
                extra = '（结果已达 2000 上限，请用「再次扫描」继续收敛）'
            self.wasm_status_var.set('命中 %d 个 / 扫描 %d 个地址%s'
                                     % (len(res), meta.get('scanned', 0), extra))
            self._wasm_save_state()
        finally:
            self._wasm_scanning = False

    def _wasm_fill(self):
        try:
            for i in self.wasm_tree.get_children():
                self.wasm_tree.delete(i)
            for (mi, wt, o, v) in self.wasm_hits[:3000]:
                self.wasm_tree.insert('', 'end', values=('0x%08X' % o, wt, self._wasm_fmt_val(v, wt)))
        except Exception:
            pass

    def _wasm_selected(self):
        import tkinter.messagebox as _mb
        sel = self.wasm_tree.selection()
        if not sel:
            _mb.showwarning('提示', '请先在结果列表中选中一个地址', parent=self.wasm_win)
            return None
        try:
            row = self.wasm_tree.index(sel[0])
        except Exception:
            row = -1
        if row < 0 or row >= len(self.wasm_hits):
            _mb.showwarning('提示', '结果已失效，请重新扫描', parent=self.wasm_win)
            return None
        return self.wasm_hits[row]

    def _wasm_read_newval(self, wtype):
        txt = (self.wasm_newval_var.get() or '').strip()
        try:
            v = float(txt)
            if wtype not in ('f32', 'f64') and float(v).is_integer():
                v = int(v)
            return v
        except Exception:
            return None

    def _wasm_write_selected(self):
        import tkinter.messagebox as _mb
        h = self._wasm_selected()
        if not h:
            return
        mi, wt, off, _old = h
        value = self._wasm_read_newval(wt)
        if value is None:
            _mb.showwarning('提示', '请输入有效的新值', parent=self.wasm_win)
            return
        self._wasm_boot()
        ok, msg = self._ai_ec_edit(self._wasm_segs(mi, wt, off), value)
        self._log('WASM写入 %s = %s → %s' % (self._wasm_label(mi, wt, off), value, msg))
        _mb.showinfo('结果', msg, parent=self.wasm_win)

    def _wasm_add_lock(self, enable=True):
        """把选中地址加入/更新锁定（每 50ms 重写，抗游戏每帧覆盖）"""
        import tkinter.messagebox as _mb
        h = self._wasm_selected()
        if not h:
            return
        mi, wt, off, _old = h
        value = self._wasm_read_newval(wt)
        if value is None:
            _mb.showwarning('提示', '请输入有效的锁定值', parent=self.wasm_win)
            return
        self._wasm_boot()
        segs = self._wasm_segs(mi, wt, off)
        key = '__wasm.%d.%s.%d' % (mi, wt, off)
        label = self._wasm_label(mi, wt, off)
        for item in self.wasm_locks:
            if item['key'] == key:
                item['value'] = value
                item['enabled'] = enable
                self._ai_ec_lock(segs, value, enable, key)
                break
        else:
            self.wasm_locks.append({'mi': mi, 't': wt, 'off': off, 'segs': segs,
                                    'value': value, 'key': key, 'label': label, 'enabled': enable})
            self._ai_ec_lock(segs, value, enable, key)
        self._wasm_locks_refresh()
        self._log('WASM锁定 %s = %s（%s，共%d项）'
                  % (label, value, '已启用' if enable else '已暂停', len(self.wasm_locks)))
        self._wasm_save_state()

    def _wasm_locks_refresh(self):
        try:
            for i in self.wasm_lock_tree.get_children():
                self.wasm_lock_tree.delete(i)
            if not self.wasm_locks:
                self.wasm_lock_var.set('未锁定')
                return
            self._ec_check_images()
            for item in self.wasm_locks:
                img = self._chk_on if item.get('enabled', True) else self._chk_off
                self.wasm_lock_tree.insert('', 'end', image=img,
                                           values=(item.get('label', item['key']), item['value']))
            active = sum(1 for x in self.wasm_locks if x.get('enabled', True))
            self.wasm_lock_var.set('已锁定 %d/%d 项' % (active, len(self.wasm_locks)))
        except Exception:
            pass

    def _wasm_lock_idx_by_iid(self, iid):
        if not iid:
            return -1
        try:
            rows = self.wasm_lock_tree.get_children()
            if iid in rows:
                return rows.index(iid)
            return int(iid[1:]) - 1
        except Exception:
            return -1

    def _wasm_toggle_lock_click(self, e):
        row = self.wasm_lock_tree.identify_row(e.y)
        col = self.wasm_lock_tree.identify_column(e.x)
        if not row or col != '#0':
            return
        idx = self._wasm_lock_idx_by_iid(row)
        if idx < 0 or idx >= len(self.wasm_locks):
            return
        item = self.wasm_locks[idx]
        item['enabled'] = not item.get('enabled', True)
        if item['enabled']:
            self._wasm_boot()
        self._ai_ec_lock(item['segs'], item['value'], item['enabled'], item['key'])
        self._wasm_locks_refresh()
        self._wasm_save_state()

    def _wasm_edit_lock_value(self, e=None):
        import tkinter.simpledialog as _sd
        import tkinter.messagebox as _mb
        try:
            if e is None:
                sel = self.wasm_lock_tree.selection()
                if not sel:
                    return
                iid = sel[0]
            else:
                if self.wasm_lock_tree.identify_column(e.x) == '#0':
                    return
                iid = self.wasm_lock_tree.identify_row(e.y)
                if not iid:
                    return
            idx = self._wasm_lock_idx_by_iid(iid)
            if idx < 0 or idx >= len(self.wasm_locks):
                return
            item = self.wasm_locks[idx]
            newv = _sd.askstring('修改锁定值',
                                 '地址: %s（%s）\n当前锁定值: %s\n\n新锁定值:'
                                 % (item.get('label', item['key']), item['t'], item['value']),
                                 initialvalue=str(item['value']), parent=self.wasm_win)
            if newv is None:
                return
            try:
                v = float(newv.strip())
                if item['t'] not in ('f32', 'f64') and float(v).is_integer():
                    v = int(v)
            except Exception:
                _mb.showwarning('提示', '请输入有效数值', parent=self.wasm_win)
                return
            item['value'] = v
            if item.get('enabled', True):
                self._wasm_boot()
                self._ai_ec_lock(item['segs'], v, True, item['key'])
            self._wasm_locks_refresh()
            self._wasm_save_state()
            self._log('WASM锁定值修改: %s = %s' % (item.get('label', item['key']), v))
        except Exception as ex:
            self._log('WASM改值失败: %s' % ex)

    def _wasm_unlock_selected(self):
        import tkinter.messagebox as _mb
        sel = self.wasm_lock_tree.selection()
        if not sel:
            _mb.showinfo('提示', '请先在下方锁定列表中选中要解锁的条目', parent=self.wasm_win)
            return
        idx = self._wasm_lock_idx_by_iid(sel[0])
        if idx < 0 or idx >= len(self.wasm_locks):
            return
        item = self.wasm_locks.pop(idx)
        self._ai_ec_lock(item['segs'], item['value'], False, item['key'])
        self._wasm_locks_refresh()
        self._wasm_save_state()
        self._log('WASM解锁: %s（剩余%d项）' % (item.get('label', item['key']), len(self.wasm_locks)))

    def _wasm_clear(self):
        self.wasm_hits = []
        self._wasm_fill()
        self.wasm_status_var.set('已清空')
        try:
            self.cfg.pop('wasm_hits', None)
            save_config(self.cfg)
        except Exception:
            pass

    def _wasm_close(self):
        """关闭=隐藏，锁定继续生效"""
        try:
            self.wasm_win.withdraw()
        except Exception:
            pass

    def _wasm_save_state(self):
        try:
            if self.wasm_hits:
                self.cfg['wasm_hits'] = [[int(m), str(t), int(o), v] for (m, t, o, v) in self.wasm_hits[:3000]]
            else:
                self.cfg.pop('wasm_hits', None)
            if self.wasm_locks:
                self.cfg['wasm_locks'] = [{'mi': int(x['mi']), 't': str(x['t']), 'off': int(x['off']),
                                           'value': x['value'], 'enabled': bool(x.get('enabled', True))}
                                          for x in self.wasm_locks]
            else:
                self.cfg.pop('wasm_locks', None)
            save_config(self.cfg)
        except Exception:
            pass

    def _wasm_restore_state(self):
        """重开窗口时恢复上次结果与锁定（页面刷新后需先探测内存）"""
        try:
            hits = self.cfg.get('wasm_hits') or []
            self.wasm_hits = []
            for h in hits:
                try:
                    self.wasm_hits.append((int(h[0]), str(h[1]), int(h[2]), h[3]))
                except Exception:
                    pass
            locks = self.cfg.get('wasm_locks') or []
            self.wasm_locks = []
            if locks:
                self._wasm_boot()
            for lk in locks:
                try:
                    mi, wt, off = int(lk['mi']), str(lk['t']), int(lk['off'])
                    segs = self._wasm_segs(mi, wt, off)
                    val = lk.get('value', 0)
                    enabled = bool(lk.get('enabled', True))
                    key = '__wasm.%d.%s.%d' % (mi, wt, off)
                    if enabled:
                        self._ai_ec_lock(segs, val, True, key)
                    self.wasm_locks.append({'mi': mi, 't': wt, 'off': off, 'segs': segs,
                                            'value': val, 'key': key,
                                            'label': self._wasm_label(mi, wt, off), 'enabled': enabled})
                except Exception:
                    pass
            self._wasm_fill()
            self._wasm_locks_refresh()
            if self.wasm_hits:
                self.wasm_status_var.set('已恢复 %d 个地址 / %d 个锁定' % (len(self.wasm_hits), len(self.wasm_locks)))
            self.wasm_mems = getattr(self, 'wasm_mems', []) or []
            if not self.wasm_mems:
                self._wasm_refresh_mem(silent=True)
        except Exception:
            pass

    def _close_settings(self):
        """关闭设置窗口并保存设置"""
        try:
            self._dir_remember(self.dir_var.get())
        except Exception:
            pass
        self._save_settings()
        if self.settings_win is not None:
            try:
                self.settings_win.destroy()
            except Exception:
                pass
        self.settings_win = None
        self.dir_combo = None

    def _log(self, msg):
        """输出日志"""
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.insert('end', '[%s] %s\n' % (timestamp, msg))
        self.log_text.see('end')
        self.root.update_idletasks()

    def _clean_url(self, url):
        """清理网址：去空白 + 去掉粘贴时带进来的尾部中文（如从对话复制时带的"的图"等）"""
        import re as _re
        if not url:
            return url
        url = url.strip()
        # 去掉末尾连续非ASCII字符（中文说明文字）
        cleaned = _re.sub(r'[^\x00-\x7F]+$', '', url).strip().rstrip('.,，。;；:：、')
        if cleaned and cleaned != url:
            self._log('已自动清理网址多余文字: %s → %s' % (url, cleaned))
            return cleaned
        return url

    def _start_crawl(self):
        """开始抓取"""
        # 清空任务列表
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        # 清空上一次的CDP直读原图缓存
        self._cdp_direct_urls = []
        # 禁用重试失败按钮
        if hasattr(self, 'retry_btn'):
            self.retry_btn.config(state='disabled')
        # 更新任务统计
        self._update_task_stat()
        try:
            url = self._clean_url(self.url_var.get())
            # CDP浏览器模式：强制用浏览器当前页，不导航、不跳转（避免把用户正在看的页跳走）
            if self.render_mode_var.get() == '浏览器模式(CDP)':
                cu = self._cdp_current_url()
                if cu:
                    cu = self._clean_url(cu)
                    self.url_var.set(cu)
                    url = cu
                    self._log('使用浏览器当前页: %s' % cu[:90])
            elif not url:
                cu = self._cdp_current_url()
                if cu:
                    self._log('网址栏为空，自动使用内置浏览器当前页: %s' % cu[:90])
                    self.url_var.set(cu)
                    url = self._clean_url(cu)
            if url:
                self.url_var.set(url)
            if url:
                self._save_url_history(url)
            save_dir = self.dir_var.get().strip()

            if not url:
                messagebox.showwarning('提示', '请输入网址，或先在内置浏览器打开目标页面')
                return
            if not save_dir:
                messagebox.showwarning('提示', '请选择保存目录')
                return

            # 保存设置
            self._save_settings()

            # CDP模式下自动检测并启动调试浏览器（尊重用户在下拉框的选择）
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
            self._show_run_bar(True)  # 运行控制行随抓取一起出现
            self.log_text.delete('1.0', 'end')
            self._log('开始抓取...')

            thread = threading.Thread(target=self._crawl_worker, args=(url, save_dir), daemon=True)
            thread.start()
        except Exception as e:
            import traceback
            self._log('启动失败: %s' % e)
            self._log('详细错误: %s' % traceback.format_exc())
            self._finish_crawl()

    def _return_focus_to_browser(self):
        """抓取开始后把焦点还给 Chrome，避免主程序抢焦点"""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd_found = []
            def enum_cb(hwnd, lparam):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        t = buf.value
                        if ('Chrome' in t or 'Edge' in t or 'xchina' in t.lower()) and '全能网页助手' not in t:
                            hwnd_found.append(hwnd)
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
            if hwnd_found:
                ctypes.windll.user32.SetForegroundWindow(hwnd_found[0])
        except Exception:
            pass

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
        self._log('抓取模式: %s' % render_mode)
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
                from urllib.parse import urlparse as _urlparse
                import threading
                # 全局锁：CDP 取页面串行化（多线程复用同一标签页时避免互踩）
                if not hasattr(self, '_cdp_fetch_lock'):
                    self._cdp_fetch_lock = threading.Lock()
                with self._cdp_fetch_lock:
                    # ===== 优先复用已打开的现有标签页（已通过站点CF验证，避免新标签导航触发反爬封禁）=====
                    reuse_ws_url = None
                    need_navigate = True
                    try:
                        _tabs = requests.get('http://127.0.0.1:9222/json', timeout=5).json()
                        _page_tabs = [t for t in _tabs if t.get('type') == 'page']
                        _target_domain = _urlparse(url).netloc
                        for _t in _page_tabs:
                            if _t.get('url', '').rstrip('/') == url.rstrip('/'):
                                reuse_ws_url = _t.get('webSocketDebuggerUrl')
                                need_navigate = False
                                break
                        if not reuse_ws_url:
                            for _t in _page_tabs:
                                if _urlparse(_t.get('url', '')).netloc == _target_domain and _t.get('url', '').startswith('http'):
                                    reuse_ws_url = _t.get('webSocketDebuggerUrl')
                                    break
                    except Exception:
                        pass

                    bws = None
                    target_id = ''
                    if reuse_ws_url:
                        # 复用现有标签页，不创建新标签
                        self._log('CDP浏览器模式: 复用已打开的浏览器标签页' + ('' if not need_navigate else '（导航到目标URL）'))
                        ws = websocket.create_connection(reuse_ws_url, timeout=timeout + 10)
                    else:
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

                    # 导航到用户输入的URL（复用标签且URL一致时跳过导航，避免触发反爬）
                    if need_navigate:
                        self._log('CDP浏览器模式: 正在导航到 %s' % url[:80])
                        send_cdp(1, 'Page.navigate', {'url': url})
                    else:
                        self._log('CDP浏览器模式: 当前标签页已是目标页面，直接提取')

                    # 启用页面事件监听
                    try:
                        send_cdp(10, 'Page.enable')
                    except Exception:
                        pass

                    # 等待页面加载事件（最多等待15秒；复用已打开标签页时跳过等待）
                    load_event_detected = not need_navigate
                    wait_start = time.time()
                    while not load_event_detected and time.time() - wait_start < 15:
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

                    # ===== 页面直读原图（油猴同款，站点无关）：扫渲染好的 <img>，srcset取最大+各data-*属性+去缩略图后缀 =====
                    try:
                        direct_js = r"""
                        (function(){
                          var out = [];
                          function norm(u){
                            if(!u) return null;
                            u = String(u).trim();
                            if(!u || u.indexOf('data:')===0 || u==='about:blank') return null;
                            try { u = new URL(u, location.href).href; } catch(e){ return null; }
                            u = u.replace(/-\d+x\d+\.(jpg|jpeg|png|webp|gif)/i, '.$1');
                            return u;
                          }
                          var seen = {};
                          function add(u){ u = norm(u); if(u && !seen[u]){ seen[u]=1; out.push(u); } }
                          var imgs = document.querySelectorAll('img');
                          for(var i=0;i<imgs.length;i++){
                            var im = imgs[i];
                            var ss = im.getAttribute('srcset');
                            if(ss && ss.indexOf(',')>=0){
                              var parts = ss.split(',').map(function(s){return s.trim();}).filter(Boolean);
                              parts.sort(function(a,b){
                                var ma=a.match(/\s([\d.]+)(w|x)$/), mb=b.match(/\s([\d.]+)(w|x)$/);
                                return (ma?parseFloat(ma[1]):1)-(mb?parseFloat(mb[1]):1);
                              });
                              var last = parts[parts.length-1];
                              if(last) add(last.split(' ')[0]);
                            }
                            var attrs = ['src','data-src','data-original','data-lazy-src','data-lazy','data-actual','data-url','data-image','data-photo','data-img','data-pic','data-file','data-origin','data-real','data-source','data-large','data-big','data-full','data-origin-src','data-original-src'];
                            for(var j=0;j<attrs.length;j++){ add(im.getAttribute(attrs[j])); }
                          }
                          // 补扫：很多站用 <div style="background-image:url(...)"> 当预览图
                          var divs = document.querySelectorAll('[style*="background-image"]');
                          for(var k=0;k<divs.length;k++){
                            var st = divs[k].style.backgroundImage || getComputedStyle(divs[k]).backgroundImage;
                            if(st && st.indexOf('url(')===0){
                              var m = st.match(/url\(["']?([^"')]+)["']?\)/);
                              if(m) add(m[1]);
                            }
                          }
                          // 补扫：<picture><source srcset> 和 <source srcset>
                          var sources = document.querySelectorAll('source[srcset]');
                          for(var s=0;s<sources.length;s++){ add(sources[s].getAttribute('srcset')); }
                          // 补扫：<video> 和 <video><source> 的视频地址
                          var vids = document.querySelectorAll('video[src], video source[src], video source[srcset]');
                          for(var v=0;v<vids.length;v++){
                            add(vids[v].getAttribute('src'));
                            add(vids[v].getAttribute('srcset'));
                          }
                          // 再扫 video/播放器元素的所有属性（data-src/data-video/data-url 等懒加载）
                          var players = document.querySelectorAll('video, [data-video], [data-src], [data-url], [data-file], [data-mp4]');
                          for(var p=0;p<players.length;p++){
                            var attrs = players[p].attributes;
                            for(var a=0;a<attrs.length;a++){
                              var av = attrs[a].value;
                              if(av && /\.(mp4|webm|mov|m4v)(\?|$)/i.test(av)) add(av);
                            }
                          }
                          // 暴力兜底：整个 HTML 正则扫所有图片+视频 URL（支持相对路径+JSON转义\/）
                          var html = document.documentElement.outerHTML;
                          html = html.replace(/\\\//g, '/');
                          var re = /[^\s"'<>\\()]+?\.(?:jpg|jpeg|png|webp|avif|mp4|webm|mov|m4v)(?:\?[^\s"'<>\\]*)?/gi;
                          var mm;
                          while((mm=re.exec(html))!==null){ add(mm[0]); }
                          return out;
                        })()
                        """
                        dr = send_cdp(200, 'Runtime.evaluate', {'expression': direct_js, 'returnByValue': True})
                        durls = dr.get('result', {}).get('result', {}).get('value', []) or []
                        self._cdp_direct_urls = [u for u in durls if isinstance(u, str)]
                        if self._cdp_direct_urls:
                            self._log('CDP直读原图: 从渲染页面提取到 %d 个图片地址（srcset/data-*）' % len(self._cdp_direct_urls))
                        # ===== 自动翻页抓全部：拼 N.html 逐页访问，合并去重 =====
                        try:
                            if getattr(self, 'auto_page_var', None) and self.auto_page_var.get():
                                import re as _re
                                if _re.search(r'/\d+\.html$', url):
                                    base = _re.sub(r'/\d+\.html$', '/', url)
                                else:
                                    base = url[:-5] + '/'
                                seen = set(self._cdp_direct_urls)
                                try:
                                    _maxp = int(self.auto_page_max_var.get())
                                except Exception:
                                    _maxp = 100
                                for n in range(2, _maxp + 1):
                                    if self.stop_flag.is_set():
                                        self._log('已停止')
                                        break
                                    nxt = '%s%d.html' % (base, n)
                                    self._log('自动翻页: 第 %d 页 %s' % (n, nxt))
                                    send_cdp(210 + n, 'Page.navigate', {'url': nxt})
                                    for _w in range(8):
                                        if self.stop_flag.is_set():
                                            break
                                        time.sleep(0.5)
                                    send_cdp(230 + n, 'Runtime.evaluate', {'expression': 'window.scrollTo(0,document.body.scrollHeight)', 'returnByValue': True})
                                    time.sleep(0.5)
                                    dr2 = send_cdp(250 + n, 'Runtime.evaluate', {'expression': direct_js, 'returnByValue': True})
                                    new2 = dr2.get('result', {}).get('result', {}).get('value', []) or []
                                    added = 0
                                    for u in new2:
                                        if isinstance(u, str) and u not in seen:
                                            seen.add(u)
                                            self._cdp_direct_urls.append(u)
                                            added += 1
                                    self._log('  第 %d 页新增 %d 张，累计 %d 张' % (n, added, len(self._cdp_direct_urls)))
                                    if added == 0:
                                        break
                        except Exception as _ape:
                            self._log('自动翻页出错（忽略）: %s' % _ape)
                        # ===== 视频轮播：点"下一个"收集同页多个视频（3/3 这种看图器）=====
                        try:
                            for _v in range(10):
                                # 点"下一个"按钮
                                send_cdp(300 + _v, 'Runtime.evaluate', {'expression': "(function(){var bs=document.querySelectorAll('a,button,div,span');for(var i=0;i<bs.length;i++){var t=(bs[i].textContent||'').trim();if(t.indexOf('下一个')>=0&&t.length<12){bs[i].click();return true;}}return false;})()"})
                                time.sleep(2)
                                dr_v = send_cdp(320 + _v, 'Runtime.evaluate', {'expression': "(function(){var v=document.querySelector('video');return (v&&(v.currentSrc||v.src))||'';})()", 'returnByValue': True})
                                vurl = dr_v.get('result', {}).get('result', {}).get('value', '') or ''
                                if vurl and vurl not in self._cdp_direct_urls:
                                    self._cdp_direct_urls.append(vurl)
                                    self._log('轮播视频: 新增 %s' % vurl[-60:])
                                else:
                                    break
                        except Exception as _ve:
                            self._log('视频轮播出错（忽略）: %s' % _ve)
                    except Exception as _e:
                        self._cdp_direct_urls = []
                        self._log('CDP直读原图: 提取失败（忽略，走HTML解析）: %s' % _e)
                    ws.close()

                    # 关闭独立标签页（复用用户标签页时不关闭）
                    if bws is not None:
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
            resp = http_get(url, headers=BROWSER_HEADERS, timeout=timeout)
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

    def _extract_post_links(self, page, base_url, html=None):
        """从列表页提取帖子链接

        优先用「卡片式条目」判据（v3.1.12 新增，对 /photo/id-xxx.html 这类
        非纯数字 ID 的相册/视频站有效），识别不到时回退下面的 URL 形态规则。
        """
        import re
        from urllib.parse import urljoin, urlparse

        # ===== 1) 卡片式条目：带图 + 同型反复出现 =====
        card_links = self._extract_card_links(page, base_url, html)

        # ===== 2) URL 形态规则（老逻辑，论坛类站点兜底）=====
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

        rule_links = sorted(list(links))
        if card_links:
            self._log('帖子识别: 卡片式条目 %d 个（形态规则另有 %d 个，按卡片结果取）'
                      % (len(card_links), len(rule_links)))
            return card_links
        return rule_links

    def _extract_card_links(self, page, base_url, html=None, min_repeat=3):
        """卡片式条目识别：列表页里「带图 + 同型反复出现」的链接才是帖子

        判据（须全部满足）：
          1. 同域名
          2. 链接自身或内部含图片（<img> 或 background-image）—— 纯文字导航/分页天然排除
          3. 不在 pager/pagination/menu/nav/footer/header/breadcrumb 容器内
          4. 归一化形态在页面上出现 >= min_repeat 次（列表条目必然同型重复）
          5. 形态与当前页不同（否则「相关分类 / 同类列表页」会被当成帖子，
             实测某相册站列表页有 88 条 /photos/series-xxx.html 侧栏导航，全靠这条挡掉）
        识别不到返回 []，由调用方回退老的 URL 形态规则。
        """
        import re
        from urllib.parse import urljoin, urlparse
        from collections import Counter
        if not html:
            html = getattr(page, 'html_content', '') or ''
        if not html:
            return []
        try:
            from lxml import html as _LH
            doc = _LH.fromstring(html)
        except Exception as e:
            self._log('卡片式识别: HTML 解析失败（忽略）: %s' % str(e)[:80])
            return []
        base_domain = urlparse(base_url).netloc.replace('www.', '')
        cur_shape = url_shape(urlparse(base_url).path)
        bad_box = re.compile(r'pager|pagination|page-?nav|breadcrumb|footer|header|menu|\bnav\b', re.I)

        rows = []
        for a in doc.iter('a'):
            href = (a.get('href') or '').strip()
            if not href or href.startswith('#') or href.lower().startswith('javascript:'):
                continue
            full = urljoin(base_url, href)
            sp = urlparse(full)
            if sp.scheme not in ('http', 'https'):
                continue
            if sp.netloc.replace('www.', '') != base_domain:
                continue
            # 卡片判据：自身或内部含图片
            card = bool(a.findall('.//img')) or 'background-image' in (a.get('style') or '')
            if not card:
                card = bool(a.xpath('.//*[contains(@style,"background-image")]'))
            if not card:
                continue
            # 容器判据：排除导航/分页/页脚等区域里的链接
            box = ''
            p = a.getparent()
            for _i in range(3):
                if p is None:
                    break
                box += ' %s %s' % (p.tag or '', p.get('class') or '')
                p = p.getparent()
            if bad_box.search(box):
                continue
            rows.append((full, url_shape(sp.path)))

        if not rows:
            return []
        counts = Counter(shape for _u, shape in rows)

        def pick(threshold):
            out = []
            for u, shape in rows:
                if shape == cur_shape or counts[shape] < threshold:
                    continue
                if u not in out:
                    out.append(u)
            return out

        out = pick(min_repeat)
        if not out:
            out = pick(2)   # 列表页只有 2 个条目时也认
        return out

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
        self._show_run_bar(True)  # 重试时同样要让运行控制行出现

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

    def _debug_profile_dir(self):
        """调试浏览器专用的 user-data-dir（与日常 Chrome 隔离，否则 Chrome 136+ 调试端口不生效）"""
        return os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'WebGrabber', 'debug_profile')

    def _prepare_debug_profile(self, user_data_dir):
        """清理上次异常退出留下的会话残留（避免下次启动弹「Chrome 未正确关闭/恢复页面」）"""
        import shutil
        try:
            for f in ('Last Session', 'Last Tabs', 'Current Session', 'Current Tabs'):
                p = os.path.join(user_data_dir, f)
                if os.path.exists(p):
                    os.remove(p)
            for sd in (os.path.join(user_data_dir, 'Default', 'Session'),
                       os.path.join(user_data_dir, 'Default', 'Snapshots')):
                if os.path.exists(sd):
                    shutil.rmtree(sd, ignore_errors=True)
        except Exception as e:
            self._log('清理会话残留失败: %s' % e)

    def _find_browser_exe(self, choice='Chrome'):
        """按用户选择返回 (可执行文件路径, 浏览器名)；两个都没装则返回 (None, None)"""
        chrome_paths = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]
        edge_paths = [
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        ]
        # 用户选的那个优先，没装则退回另一个
        order = ([('Edge', edge_paths), ('Chrome', chrome_paths)] if choice == 'Edge'
                 else [('Chrome', chrome_paths), ('Edge', edge_paths)])
        for name, paths in order:
            for p in paths:
                if os.path.exists(p):
                    return p, name
        return None, None

    def _debug_browser_root_pids(self):
        """本程序自己启动的调试浏览器「主进程」PID 集合。
        按 debug_profile 目录识别（与「独立窗口」「清理残留」用的是同一标记），排除 --type= 子进程。"""
        import re as _re
        import subprocess
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
                "Where-Object { $_.CommandLine -like '*WebGrabber*debug_profile*' -and $_.CommandLine -notlike '*--type=*' } | "
                "ForEach-Object { 'PID:' + $_.ProcessId }"
            )
            r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                               timeout=12, capture_output=True)
            # 直接按字节抽取，避免 PowerShell 输出编码（GBK/UTF-8）不一致
            return set(int(x) for x in _re.findall(rb'PID:(\d+)', r.stdout))
        except Exception:
            return set()

    def _top_level_window_pids(self):
        """桌面上所有「可见」顶层窗口所属的 PID 集合"""
        import ctypes
        from ctypes import wintypes
        pids = set()
        try:
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

            def cb(hwnd, lParam):
                if IsWindowVisible(hwnd):
                    pid = wintypes.DWORD()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    pids.add(pid.value)
                return True

            EnumWindows(EnumWindowsProc(cb), 0)
        except Exception:
            pass
        return pids

    def _debug_browser_visible_pid(self):
        """本程序的调试浏览器「确实有可见窗口」时返回其主进程 PID，否则 None。
        用来区分「真的可用」和「端口被残留进程占着、但窗口根本看不见」——后者会让
        「启动调试浏览器」误判成已在运行而静默返回（用户感觉点了没反应）。"""
        pids = self._debug_browser_root_pids()
        if not pids:
            return None
        hit = sorted(pids & self._top_level_window_pids())
        return hit[0] if hit else None

    def _embedded_browser_alive(self):
        """本程序当前嵌入的浏览器窗口是否仍然有效且可见。
        注意：嵌入后它是本程序的子窗口，不再是「顶层窗口」，所以不能用
        _debug_browser_visible_pid()（那只找桌面上的顶层窗口）来判断，否则
        会把「已经正常嵌入、用得好好的」误判成残留而反复重启。"""
        import ctypes
        hwnd = getattr(self, 'browser_hwnd', None)
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            if not user32.IsWindow(hwnd):
                return False
            return bool(user32.IsWindowVisible(hwnd))
        except Exception:
            return False

    def _wait_debug_port_free(self, timeout=8):
        """等待 9222 端口释放（刚杀完进程时 Chrome 还要一点时间才真正退出）"""
        import time
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not self._is_debug_browser_running():
                return True
            time.sleep(0.4)
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
        """启动调试浏览器（9222端口）并嵌入到软件里"""
        import subprocess
        import shutil
        import time

        # ===== 「已在运行」不能只看端口 =====
        # 端口通只能说明有东西在监听 9222。若上次运行（或另一个实例）留下的调试浏览器
        # 退出得不干净，会占着端口、窗口却看不见——这时直接 return，用户就是「点了没反应」。
        # 所以：必须「有可见窗口」才复用，否则清掉残留重新启动。这与用户手工先点一下
        # 「独立窗口」再点本按钮的效果一致，但不需要他手动做。
        if self._is_debug_browser_running():
            # a) 已经嵌进本程序、窗口也还在 → 名副其实的「无需重复启动」，什么都不做
            if self._embedded_browser_alive():
                self._log('调试浏览器已在运行（已嵌入本程序），无需重复启动')
                return
            # b) 桌面上有它的独立可见窗口（例如之前用「独立窗口」开的）→ 拉进本程序
            pid = self._debug_browser_visible_pid()
            if pid:
                self._debug_browser_pid = pid
                self._embed_retry = 0
                self._log('调试浏览器已在运行（PID=%d），正在把它嵌入到软件窗口...' % pid)
                self._embed_browser()
                return
            # c) 端口通、但窗口完全看不见（上次退出的残留）→ 清理重启
            self._log('9222 端口被占用但没有可见的调试浏览器窗口（多为上次退出后的残留），正在清理并重启...')

        # 清掉占用调试配置目录的残留进程，并等端口真正释放
        # （刚杀完进程时端口不会立刻空出来，直接启动新实例会因端口冲突起不来 → 又变成「没反应」）
        self._kill_stale_debug_browser()
        if not self._wait_debug_port_free():
            self._log('9222 端口仍被其他程序占用，调试浏览器可能无法正常工作')

        # 使用独立的调试配置目录（Chrome 136+使用默认User Data目录时调试端口不生效）
        user_data_dir = self._debug_profile_dir()
        os.makedirs(user_data_dir, exist_ok=True)
        self._prepare_debug_profile(user_data_dir)

        # 获取用户选择的浏览器
        browser_choice = getattr(self, 'browser_choice_var', None)
        choice = browser_choice.get() if browser_choice else 'Chrome'
        browser_path, browser_name = self._find_browser_exe(choice)

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
            '--disable-session-crashed-bubble',
            '--disable-features=InfiniteSessionRestore',
            '--disable-gpu',
            '--disable-gpu-compositing',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
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

        # 启动浏览器（不带 CREATE_NEW_CONSOLE：那是多余的黑色控制台窗口，且打包成
        # 无控制台的 exe 后标准句柄无效，容易让 Popen 直接失败；显式重定向到 DEVNULL 更稳）
        self._log('正在启动%s调试浏览器（9222端口）...' % browser_name)
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._debug_browser_pid = proc.pid
            self._embed_retry = 0
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
            target_pid = getattr(self, '_debug_browser_pid', None)
            # 没有 PID 时（复用已在运行的浏览器）先查出自家调试浏览器的进程号，
            # 否则下面的标题匹配可能把「用户日常浏览器的窗口」嵌进来
            own_pids = set()
            if not target_pid:
                own_pids = self._debug_browser_root_pids()

            def enum_callback(hwnd, lParam):
                nonlocal found_hwnd
                if not IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                hpid = pid.value
                # 优先按启动时的 PID 精确匹配（最可靠，不依赖窗口标题）
                if target_pid:
                    if hpid == target_pid:
                        found_hwnd = hwnd
                        return False
                    return True
                # 只能按标题匹配时，先把范围限定在自家调试浏览器的进程内
                if own_pids and hpid not in own_pids:
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
                # 加次数上限：原来会每 2 秒无限重试，用户点了没窗口出现就一直静默刷日志
                self._embed_retry = getattr(self, '_embed_retry', 0) + 1
                if self._embed_retry <= 6:
                    self._log('未找到调试浏览器窗口，稍后重试...（%d/6）' % self._embed_retry)
                    self.root.after(2000, self._embed_browser)
                else:
                    self._embed_retry = 0
                    self._log('始终没找到调试浏览器窗口。若浏览器没出现，请点「独立窗口」启动一次，'
                              '或确认 9222 端口未被其他程序占用')
                return

            self._embed_retry = 0
            self.browser_hwnd = found_hwnd

            # 获取宿主窗口句柄
            self.browser_frame.update_idletasks()
            host_hwnd = self.browser_frame.winfo_id()

            # 嵌入浏览器窗口
            SetParent = ctypes.windll.user32.SetParent
            SetParent(found_hwnd, host_hwnd)

            # 先切到浏览器页签并刷新布局，确保宿主窗口拿到真实尺寸
            self.content_notebook.select(2)
            self.browser_frame.update_idletasks()
            self.browser_frame.update()

            # 调整浏览器窗口大小（多次调整+尺寸抖动，强制 Chrome 重新布局渲染）
            MoveWindow = ctypes.windll.user32.MoveWindow
            width = self.browser_frame.winfo_width()
            height = self.browser_frame.winfo_height()
            MoveWindow(found_hwnd, 0, 0, width, height, True)
            # 延迟多次执行抖动调整，修复嵌入后图标/图层不绘制的问题
            self.root.after(150, lambda: self._resize_browser(jitter=True))
            self.root.after(600, lambda: self._resize_browser(jitter=True))
            self.root.after(1800, lambda: self._resize_browser(jitter=True))
            # 嵌入完成后隐藏-显示强制全量重绘（等效且强于手动拖动，favicon/图标必出）
            self.root.after(2500, self._force_browser_redraw)
            # 激进重排：极小尺寸强制重排+连续10次调整+枚举子窗口同步（v2.2.6 验证过的方案）
            self.root.after(3000, self._aggressive_resize)
            # 嵌入完成后自动刷新页面一次，强制完整重绘（图标/快捷方式必出）
            self.root.after(4000, self._browser_reload_once)

            self._log('浏览器已嵌入到「浏览器」页签')
            self.browser_hint.pack_forget()  # 隐藏提示标签

            # 绑定窗口大小变化事件
            self.browser_frame.bind('<Configure>', self._on_browser_resize)

        except Exception as e:
            self._log('嵌入浏览器失败: %s' % e)

    def _resize_browser(self, jitter=False):
        """调整浏览器窗口大小以适应宿主窗口；jitter=True 时做尺寸抖动强制 Chrome 重排渲染"""
        if self.browser_hwnd:
            try:
                import ctypes
                MoveWindow = ctypes.windll.user32.MoveWindow
                RedrawWindow = ctypes.windll.user32.RedrawWindow
                self.browser_frame.update_idletasks()
                self.browser_frame.update()
                width = self.browser_frame.winfo_width()
                height = self.browser_frame.winfo_height()
                if width > 0 and height > 0:
                    MoveWindow(self.browser_hwnd, 0, 0, width, height, True)
                    if jitter:
                        # 先明显缩小120px（真实尺寸变化，慢速间隔），延迟后再恢复——等效"拖动窗口"，强制Chrome重排渲染
                        MoveWindow(self.browser_hwnd, 0, 0, width, max(1, height - 120), True)
                        self.root.after(500, lambda: MoveWindow(self.browser_hwnd, 0, 0, width, height, True))
                    # 强制立即重绘
                    RedrawWindow(self.browser_hwnd, None, None, 0x0001 | 0x0100)  # RDW_INVALIDATE | RDW_UPDATENOW
            except Exception:
                pass

    def _aggressive_resize(self):
        """激进重排：极小尺寸强制重排 → 连续10次调整 → 第5次后枚举子窗口同步（v2.2.6 验证方案）"""
        try:
            import ctypes
            import time
            from ctypes import wintypes
            MoveWindow = ctypes.windll.user32.MoveWindow
            EnumChildWindows = ctypes.windll.user32.EnumChildWindows
            EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            hwnd = self.browser_hwnd
            if not hwnd:
                return
            w = self.browser_frame.winfo_width()
            h = self.browser_frame.winfo_height()
            if w <= 0 or h <= 0:
                w, h = 900, 600

            def cb(hwnd_child, lp):
                try:
                    MoveWindow(hwnd_child, 0, 0, w, h, True)
                except Exception:
                    pass
                return True

            for i in range(10):
                if i == 0:
                    # 极小尺寸强制 Chrome 完整重排
                    MoveWindow(hwnd, 0, 0, max(100, w // 3), max(100, h // 3), True)
                else:
                    MoveWindow(hwnd, 0, 0, w, h, True)
                if i >= 5:
                    # 第5次后枚举所有子窗口（Chrome 内层渲染窗口）同步调整
                    EnumChildWindows(hwnd, EnumProc(cb), 0)
                self.root.update_idletasks()
                time.sleep(0.05)
            self._log('激进重排完成（极小尺寸+10次调整+子窗口同步）')
        except Exception:
            pass

    def _force_browser_redraw(self):
        """隐藏再显示浏览器窗口，强制 Windows 全量重绘（修复嵌入后图标/favicon 不绘制）"""
        try:
            import ctypes
            ShowWindow = ctypes.windll.user32.ShowWindow
            if self.browser_hwnd:
                ShowWindow(self.browser_hwnd, 0)  # SW_HIDE
                self.root.after(400, lambda: self._show_browser_after_hide())
        except Exception:
            pass

    def _show_browser_after_hide(self):
        try:
            import ctypes
            ShowWindow = ctypes.windll.user32.ShowWindow
            if self.browser_hwnd:
                ShowWindow(self.browser_hwnd, 5)  # SW_SHOW
                self._resize_browser(jitter=True)
                self._log('已强制重绘嵌入的浏览器窗口')
        except Exception:
            pass

    def _browser_reload_once(self):
        """嵌入后自动刷新调试浏览器页面一次，强制完整重绘（修复图标/快捷方式不显示）"""
        try:
            import urllib.request as _ur
            import json as _json
            import websocket as _ws
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            page = next((t for t in tabs if t.get('type') == 'page'), None)
            if page:
                ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % page['id'], timeout=10)
                ws.send(_json.dumps({'id': 1, 'method': 'Page.reload', 'params': {'ignoreCache': True}}))
                try:
                    ws.recv()
                except Exception:
                    pass
                ws.close()
                self._log('已自动刷新嵌入的浏览器页面（强制完整重绘）')
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

    def _post_range_values(self):
        """读取「范围」两个框 → (range_start, range_end)

        range_start 是 0-based 索引（直接给列表切片用），range_end 是 1-based 的终止序号。
        留空/非法值都走 parse_range_pair 的默认（起始 1、终止 20），填反自动对调。
        """
        s, e = parse_range_pair(self.post_range_start_var.get(), self.post_range_end_var.get())
        return s - 1, e

    def _page_range_values(self):
        """读取「页码」两个框 → (起始页, 终止页)，都是 1-based；终止页 0 表示「不限」。

        留空/非法值走 parse_page_range 的默认（起始 1、终止不限），填反自动对调。
        """
        return parse_page_range(self.page_range_start_var.get(), self.page_range_end_var.get())

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
        # 范围：两个框（起始 / 终止 帖子序号，1-based 闭区间；留空按默认 1 / 20）
        range_start, range_end = self._post_range_values()
        if range_start > 0:
            self._log('范围: 第%d到第%d个帖子' % (range_start + 1, range_end))
        post_range = range_end  # 最大帖子数用range_end
        min_size = self.min_size_var.get()

        self._log('=' * 50)
        self._log('%s %s' % (APP_NAME, APP_VERSION))
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

    def _expand_post_pages(self, base_url, page, html, timeout, img_urls):
        """站内分页：把同一个帖子的后续页也抓全（如 /photo/id-xxx.html → /photo/id-xxx/2.html）

        不少站把「一个帖子」的图分在若干页里（实测某相册站一页只给 15 张，共 8 页 109 张），
        只抓第一页会误以为帖子就这么点内容。做法：
          1. 页面上找「自身分页」链接（路径 == 当前页去 .html + /<数字>.html），取最大页码
             （注意：分页条往往只渲染首尾几页，所以必须取最大值，不能数链接个数）
          2. 第 2..N 页逐页抓取、合并去重；各页图片照常走原图升级
          3. 连续 2 页拿不到新图就停（没新的就停止），另有「最多页」上限兜底
        受「自动翻页抓全部」(auto_page_var) 控制；CDP 浏览器模式在 _fetch_page 内已翻过，这里跳过。
        返回合并后的图片列表。
        """
        import re
        from urllib.parse import urlparse, urljoin
        try:
            if not img_urls:
                return img_urls
            # CDP 模式：_fetch_page 内部已按 auto_page_var 翻过页，避免翻两遍
            try:
                if self.render_mode_var.get() == '浏览器模式(CDP)':
                    return img_urls
            except Exception:
                pass
            sp0 = urlparse(base_url)
            path0 = sp0.path or ''
            if re.search(r'/\d+\.html$', path0):
                cur_dir = re.sub(r'/\d+\.html$', '/', path0)
            elif path0.endswith('.html'):
                cur_dir = path0[:-5] + '/'
            else:
                return img_urls
            # 找「自身分页」链接，取最大页码
            maxp = 0
            pat = re.compile(re.escape(cur_dir) + r'(\d+)\.html$')
            try:
                for a in page.css('a'):
                    href = a.attrib.get('href', '') or ''
                    if not href:
                        continue
                    sub = urlparse(urljoin(base_url, href))
                    if sub.netloc.replace('www.', '') != sp0.netloc.replace('www.', ''):
                        continue
                    m = pat.match(sub.path)
                    if m:
                        try:
                            maxp = max(maxp, int(m.group(1)))
                        except Exception:
                            pass
            except Exception:
                pass
            if maxp < 2:
                return img_urls
            # 确认本页还有后续页，此时才提示开关状态，免得用户以为抓全了
            if not (getattr(self, 'auto_page_var', None) and self.auto_page_var.get()):
                self._log('  本页还有 %d 页（共 %d 页），站内翻页未启用（高级选项 → 自动翻页抓全部）'
                          % (maxp - 1, maxp))
                return img_urls
            try:
                limit = int(self.auto_page_max_var.get())
            except Exception:
                limit = 100
            maxp = min(maxp, max(limit, 2))
            self._log('  站内翻页: 本帖共 %d 页，继续抓第 2-%d 页...' % (maxp, maxp))
            seen = set(img_urls)
            ordered = list(img_urls)      # 保留下载顺序（第 1 页在前，后续页按序追加）
            added_total = 0
            empty_rounds = 0
            for n in range(2, maxp + 1):
                if self.stop_flag.is_set():
                    self._log('  已停止')
                    break
                nxt = '%s://%s%s%d.html' % (sp0.scheme, sp0.netloc, cur_dir, n)
                try:
                    sub_html, sub_page = self._fetch_page(nxt, timeout)
                    sub_imgs = self._extract_images_from_page(sub_page, nxt, sub_html)
                except Exception as e:
                    self._log('  第 %d 页抓取失败: %s' % (n, str(e)[:100]))
                    sub_imgs = []
                new = [u for u in sub_imgs if u not in seen]
                for u in new:
                    seen.add(u)
                    ordered.append(u)
                added_total += len(new)
                self._log('  第 %d 页新增 %d 张（累计 %d 张）' % (n, len(new), len(ordered)))
                if new:
                    empty_rounds = 0
                else:
                    empty_rounds += 1
                    if empty_rounds >= 2:
                        self._log('  连续 %d 页没有新图，停止站内翻页' % empty_rounds)
                        break
            if added_total:
                self._log('  站内翻页完成: 新增 %d 张，合计 %d 张' % (added_total, len(ordered)))
            return ordered
        except Exception as e:
            self._log('  站内翻页出错（忽略）: %s' % e)
            return img_urls

    def _crawl_whole_site(self, url, save_dir, max_threads, timeout, post_range, min_size):
        """全站抓取：列表页翻页+进详情页抓取"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        # 范围：与 _crawl_worker 同一口径（两个框 → 起始/终止 帖子序号）
        range_start, range_end = self._post_range_values()

        # 分页翻页，收集所有帖子链接
        all_post_links = []
        current_url = url
        page_num = 1

        # 页码范围（v3.1.14：两个框 = 起始 / 终止 列表页码；终止留空 = 不限）
        page_start, page_end = self._page_range_values()
        max_pages = page_end if page_end > 0 else 50   # 不限时沿用旧的 50 页硬上限
        if page_start > max_pages:
            max_pages = page_start   # 起始页比上限还大时，至少得翻到起始页
        if page_end > 0:
            self._log('页码: 第%d-%d页（区间外的帖子不计入）' % (page_start, page_end))
        elif page_start > 1:
            self._log('页码: 从第%d页开始，翻到底（最多%d页）' % (page_start, max_pages))
        else:
            self._log('页码: 不限（自动翻到底，最多%d页）' % max_pages)

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

            post_links = self._extract_post_links(page, current_url, html)
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

            # 将当前页的帖子链接添加到总列表（只收页码区间内的页）
            if page_num < page_start:
                self._log('  第%d页在页码范围之前，只翻过不收集' % page_num)
            else:
                all_post_links.extend(post_links)

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
        skipped_count = 0
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
            if all_post_links and skipped_count > 0:
                # 识别正常、只是都被增量扫描跳过了：这里绝不能回退成单页抓取，
                # 否则会把列表页当帖子再抓一遍封面图（没新内容时的正确行为就是什么都不做）
                self._log('识别到 %d 个帖子，均已抓过（增量扫描跳过 %d 个）。要重抓请勾选「强制重扫」。'
                          % (len(all_post_links), skipped_count))
                return
            if page_start > 1 and not all_post_links:
                # 页码区间起点超过了列表实际页数：识别/翻页都正常，只是区间内一条帖子都没有，
                # 这时同样不能回退单页抓取（会把列表页当帖子抓封面图）
                self._log('页码范围第%d页起没有取到任何帖子（共翻了 %d 页），请确认起始页码是否超出列表实际页数。'
                          % (page_start, page_num))
                return
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
                # ===== 站内分页：同一帖子的后续页也抓全（受「自动翻页抓全部」控制）=====
                img_urls = self._expand_post_pages(post_url, post_page, post_html, timeout, img_urls)
                self._log('  提取到 %d 张图片' % len(img_urls))
                self._update_task(task_id, progress='0/%d' % len(img_urls))

                if img_urls:
                    success, fail, skipped = self._download_image_list(img_urls, post_save_dir, max_threads, min_size, task_id, referer=post_url)
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

    def _scroll_debug_browser(self, times=3):
        """CDP 滚动调试浏览器当前活跃标签 N 轮，触发懒加载"""
        try:
            import urllib.request as _ur
            import json as _json
            import time as _time
            import websocket as _ws
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            pages = [t for t in tabs if t.get('type') == 'page']
            if not pages:
                return False
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=10)
            n = 0
            for _round in range(times):
                n += 1
                ws.send(_json.dumps({'id': n, 'method': 'Runtime.evaluate',
                                     'params': {'expression': 'window.scrollTo(0, document.body.scrollHeight)', 'returnByValue': True}}))
                try:
                    _json.loads(ws.recv())
                except Exception:
                    pass
                _time.sleep(1.5)
                n += 1
                ws.send(_json.dumps({'id': n, 'method': 'Runtime.evaluate',
                                     'params': {'expression': 'window.scrollTo(0, document.body.scrollHeight/2)', 'returnByValue': True}}))
                try:
                    _json.loads(ws.recv())
                except Exception:
                    pass
                _time.sleep(1)
            ws.close()
            return True
        except Exception:
            return False

    def _fetch_current_tab_html(self):
        """CDP 取调试浏览器当前活跃标签的 HTML"""
        try:
            import urllib.request as _ur
            import json as _json
            import websocket as _ws
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            pages = [t for t in tabs if t.get('type') == 'page']
            if not pages:
                return ''
            active = next((t for t in pages if t.get('active')), pages[0])
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=10)
            ws.send(_json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                 'params': {'expression': 'document.documentElement.outerHTML', 'returnByValue': True}}))
            resp = _json.loads(ws.recv())
            ws.close()
            return resp.get('result', {}).get('result', {}).get('value', '')
        except Exception:
            return ''

    def _collect_image_clues(self, html):
        """收集页面图片相关线索（供AI分析）"""
        import re as _re
        if not html:
            return '无HTML'
        n_img = len(_re.findall(r'<img\b', html, _re.I))
        n_data_src = len(_re.findall(r'data-(?:src|original|lazy|real|url|image|pic|file|thumb|preview|large|big|full)\s*=', html, _re.I))
        n_bg = len(_re.findall(r'background(?:-image)?\s*:\s*url\(', html, _re.I))
        n_lazy = len(_re.findall(r'(?:loading="lazy"|lazyload|blur|placeholder)', html, _re.I))
        n_urls = len(_re.findall(r'(?:https?:)?//[^"\']+\.(?:jpg|jpeg|png|webp|gif|avif)', html, _re.I))
        return ('img标签%d个, data-*图片属性%d处, CSS背景图%d处, 懒加载/占位特征%d处, 页面内图片URL%d个'
                % (n_img, n_data_src, n_bg, n_lazy, n_urls))

    def _ai_analyze_page_strategy(self, html, img_count, url):
        """AI 看图 + DOM线索 → 返回调整策略 dict（截图→视觉模型→JSON解析）"""
        import urllib.request as _ur
        import json as _json
        import base64 as _b64
        import io as _io
        import re as _re
        if not (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)):
            return None
        # 1. 截图当前浏览器页面
        try:
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            pages = [t for t in tabs if t.get('type') == 'page']
            if not pages:
                return None
            active = next((t for t in pages if t.get('active')), pages[0])
            import websocket as _ws
            ws = _ws.create_connection('ws://127.0.0.1:9222/devtools/page/%s' % active['id'], timeout=15)
            ws.send(_json.dumps({'id': 1, 'method': 'Page.captureScreenshot', 'params': {'format': 'png'}}))
            resp = _json.loads(ws.recv())
            ws.close()
            png_b64 = resp.get('result', {}).get('data')
            if not png_b64:
                return None
            from PIL import Image
            img = Image.open(_io.BytesIO(_b64.b64decode(png_b64))).convert('RGB')
            img.thumbnail((1024, 1024))
            buf = _io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            jpg_b64 = _b64.b64encode(buf.getvalue()).decode()
        except Exception:
            return None
        # 2. DOM 线索
        clue = self._collect_image_clues(html)
        # 3. 调视觉模型，要求输出JSON策略
        question = ('这是爬虫软件要抓图的网站页面截图（目标: %s）。当前规则只提取到 %d 张图片。'
                    'DOM线索: %s。请判断该页面的图片获取方式，只输出JSON（不要多余文字）：'
                    '{"has_images": true或false, "strategy": "scroll"或"attr"或"click"或"none", '
                    '"scroll_times": 数字, "note": "一句话中文说明"}。'
                    'has_images=页面是否确实有值得下载的图片；strategy: scroll=图片懒加载需继续滚动出现, '
                    'attr=图片URL藏在data-*等属性或特殊位置, click=需要点击/展开才能看到, none=页面无图或无法获取。'
                    '若页面截图里能看到大量图片，strategy填scroll并给合理的scroll_times(2-8)。'
                    % (url[:60], img_count, clue))
        try:
            body = {'messages': [{'role': 'user', 'content': [
                        {'type': 'text', 'text': question},
                        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + jpg_b64}},
                    ]}],
                    'max_tokens': 300, 'temperature': 0.1}
            ok, out = self._ai_completion(body, timeout=240)
            if not ok:
                self._log('AI策略分析调用失败')
                return None
            text = out['choices'][0]['message']['content'].strip()
        except Exception as e:
            self._log('AI策略分析调用失败: %s' % e)
            return None
        # 4. 解析 JSON（容忍模型输出多余文字）
        try:
            m = _re.search(r'\{.*\}', text, _re.S)
            if m:
                d = _json.loads(m.group(0))
                if isinstance(d, dict) and 'strategy' in d:
                    return d
        except Exception:
            pass
        self._log('AI策略输出无法解析: %s' % text[:100])
        return None

    def _ai_adjust_extract(self, url, html, img_urls):
        """AI 看图分析加载方式 → 执行策略（滚动/重新提取）→ 返回调整后的图片列表"""
        self._log('提取图片过少(%d张)，启动AI看图分析抓取策略...' % len(img_urls))
        strategy = self._ai_analyze_page_strategy(html, len(img_urls), url)
        if not strategy:
            self._log('AI策略分析未返回有效结果，按当前结果继续')
            return img_urls
        note = strategy.get('note', '')
        if note:
            self._log('AI判断: %s' % note[:120])
        if strategy.get('has_images') is False:
            self._log('AI判断页面无可下载图片，停止提取')
            return []
        # 执行滚动策略
        if strategy.get('strategy') == 'scroll':
            times = int(strategy.get('scroll_times', 3))
            times = max(1, min(times, 8))
            self._log('AI策略: 继续滚动 %d 轮触发懒加载' % times)
            self._scroll_debug_browser(times)
            new_html = self._fetch_current_tab_html()
            if new_html and len(new_html) > len(html):
                html = new_html
        # 重新提取
        try:
            from scrapling import Selector
            page = Selector(html)
            new_imgs = self._extract_images_from_page(page, url, html)
        except Exception:
            new_imgs = img_urls
        if len(new_imgs) > len(img_urls):
            self._log('AI调整后提取到 %d 张图片（原 %d 张）' % (len(new_imgs), len(img_urls)))
            return new_imgs
        self._log('AI调整后图片数未增加（%d 张），按当前结果继续' % len(img_urls))
        return img_urls

    def _ai_browser_url(self):
        """取调试浏览器当前活跃标签 URL"""
        import urllib.request as _ur
        import json as _json
        try:
            with _ur.urlopen('http://127.0.0.1:9222/json/list', timeout=3) as r:
                tabs = _json.loads(r.read())
            pages = [t for t in tabs if t.get('type') == 'page']
            if not pages:
                return ''
            active = next((t for t in pages if t.get('active')), pages[0])
            return active.get('url', '')
        except Exception:
            return ''

    def _ai_adjust_crawl_tool(self, url=''):
        """ai_adjust_crawl 工具：AI 看图分析当前浏览器页加载方式 → 滚动触发 → 重新提取 → 汇报结果"""
        # 优先以浏览器当前页为目标（用户说"这个页面"即浏览器里打开的页，截图分析的就是它）
        browser_url = self._ai_browser_url()
        if browser_url:
            target = browser_url
        else:
            target = url.strip() or self.url_var.get().strip()
        html = self._fetch_current_tab_html()
        if not html:
            return '调试浏览器未运行或没有打开页面，请先在「浏览器模式」启动调试浏览器并打开目标页面'
        # 初始提取
        try:
            from scrapling import Selector
            init_imgs = self._extract_images_from_page(Selector(html), target or '当前页', html)
        except Exception:
            init_imgs = []
        # AI 看图分析
        strategy = self._ai_analyze_page_strategy(html, len(init_imgs), target or '当前页')
        if not strategy:
            return 'AI策略分析失败（截图或视觉模型不可用），当前已提取 %d 张图片' % len(init_imgs)
        lines = ['AI看图分析: %s' % (strategy.get('note', '') or '（无说明）')]
        if strategy.get('has_images') is False:
            lines.append('AI判断页面无可下载图片')
            return '\n'.join(lines)
        # 执行滚动策略
        if strategy.get('strategy') == 'scroll':
            try:
                times = max(1, min(int(strategy.get('scroll_times', 3)), 8))
            except Exception:
                times = 3
            self._log('AI工具: 按策略滚动 %d 轮触发懒加载' % times)
            self._scroll_debug_browser(times)
            new_html = self._fetch_current_tab_html()
            if new_html and len(new_html) > len(html):
                html = new_html
        # 重新提取
        try:
            from scrapling import Selector
            new_imgs = self._extract_images_from_page(Selector(html), target or '当前页', html)
        except Exception:
            new_imgs = init_imgs
        lines.append('调整前 %d 张 → 调整后 %d 张' % (len(init_imgs), len(new_imgs)))
        if len(new_imgs) > len(init_imgs):
            lines.append('已按AI策略调整并重新提取，图片数增加，可继续用 start_crawl 抓取下载')
        else:
            lines.append('图片数未增加，可能需要登录/点击展开，或该页无法用当前方式获取')
        return '\n'.join(lines)

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

        # 非正文图片：第三方统计/广告脚本、站点图标位、二维码等（实测相册站一页会混进十几张）
        JUNK_MEDIA = re.compile(
            r'googletagmanager\.com|google-analytics\.com|googlesyndication\.com|doubleclick\.net'
            r'|/gtag/|/images/sites/|/images/empty|favicon|/qrcode', re.IGNORECASE)

        def try_add(img_url):
            if not img_url or img_url.startswith('data:') or img_url.startswith('about:') or img_url == 'blank':
                return
            # 站点自身的资源/统计类 URL（不是正文图片），提取阶段就排掉，省得白跑下载
            if JUNK_MEDIA.search(img_url):
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
                # 带查询串/子路径的静态资源也要排掉（core-state.js?v=… / beacon.min.js/v31ed… 实测会被误当图片）
                _res_path = url_lower.split('?')[0].split('#')[0]
                if not re.search(r'\.(?:js|css|json|xml|map|woff2?|ttf|otf|eot)(?:/|$)', _res_path):
                    img_urls.add(full_url)

        # ===== CDP直读原图优先：浏览器模式下已从渲染页面拿到原图列表（srcset最大+去缩略图后缀）=====
        direct = getattr(self, '_cdp_direct_urls', None)
        if direct:
            for u in direct:
                try_add(u)
            self._cdp_direct_urls = []  # 用完即清，避免污染后续页
            self._log('图片提取: 使用CDP直读原图，共 %d 张（渲染页面直读，非HTML猜解）' % len(img_urls))
            return list(img_urls)

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

    def _download_image_list(self, img_urls, save_dir, max_threads, min_size, task_id=None, referer=None):
        """下载图片列表，返回 (成功数, 失败数, 跳过数)；referer 用作防盗链来源页"""
        # 统一过滤无效URL（about:blank、模板残留、非图片静态资源等）
        _NON_IMG_EXT = ('.js', '.css', '.html', '.htm', '.php', '.json', '.xml', '.woff', '.woff2', '.ttf', '.ico')
        def _looks_like_img(u):
            if not u or 'about:' in u or '{{' in u or '}}' in u:
                return False
            ul = u.lower().split('?')[0].split('#')[0]
            if ul.endswith(_NON_IMG_EXT):
                return False
            # 站点导航/标签图标等非正文资源
            for junk in ('/images/sites/', '/images/user-tags/', '/images/empty.png', '/static/image/'):
                if junk in ul:
                    return False
            # 暴力正则误抓的 JS 代码片段（含 %60、路径里有多个=）
            if '%60' in u or u.count('=') > 2:
                return False
            return True
        img_urls = [u for u in img_urls if _looks_like_img(u)]
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
        orig_ok = 0          # 换成原图的张数
        orig_fallback = 0    # 原图不可用、回退预览图的张数
        start_time = time.time()

        def _cdp_fallback(url, idx):
            """HTTP 通道彻底失败时的浏览器通道兜底（带代理/登录态）；成功返回文件路径，失败 None"""
            try:
                os.makedirs(save_dir, exist_ok=True)
                _u = url.lower()
                _ext = '.jpg'
                for e in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif']:
                    if e in _u:
                        _ext = e
                        break
                fp = os.path.join(save_dir, 'img_%03d%s' % (idx + 1, _ext))
                if self._cdp_download_image(url, fp) and os.path.exists(fp):
                    return fp
            except Exception:
                pass
            return None

        def download_one(idx, img_url):
            nonlocal success, fail, skipped, total_bytes, orig_ok, orig_fallback
            if self.stop_flag.is_set():
                return
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
            # xchina 站：视频/大图真实在 img.xchina.io CDN，页面里写的 xchina.co 路径是错的
            if img_url.startswith('https://xchina.co/') and ('/photos/' in img_url or '.mp4' in img_url):
                img_url = 'https://img.xchina.io/' + img_url[len('https://xchina.co/'):]
            # ===== v3.1.11：预览图地址 → 先试同目录原图（0001_600x0.webp → 0001.jpg），失败自动回退预览 =====
            try:
                want_orig = bool(self.orig_img_var.get())
            except Exception:
                want_orig = True
            preview_url = img_url
            candidates = orig_url_candidates(img_url) if want_orig else [img_url]
            had_origs = len(candidates) > 1
            cand_idx = 0
            img_url = candidates[0]        # 从原图候选开始试
            # 重试机制：每个候选最多重试3次；候选（原图 → 预览）逐个试，全试完才判这张图失败
            max_retries = 3
            retry = 0
            while retry < max_retries:
                try:
                    # 去掉stream=True，直接用resp.content
                    # 走统一通道：直连优先（忽略注册表里的失效代理）+ 图片专用请求头
                    resp = http_get(img_url, headers=IMAGE_HEADERS, timeout=30, referer=referer)
                    content = resp.content
                    # 状态码 / 文件头 / 尺寸 三道检查
                    # ⚠ 猜错原图地址时 CDN 会回 200 + 一段 HTML（实测 xchina 就是这样），只看状态码会把网页存成图片
                    if resp.status_code != 200:
                        code = resp.status_code
                        reason = 'HTTP %d' % code
                        # 404/403 这种"明确的否定"直接换候选；5xx/429 才值得重试
                        transient = (code >= 500 or code in (408, 425, 429))
                    elif not looks_like_media(content):
                        reason = '非图片内容(可能是HTML)'
                        transient = False
                    elif min_size > 0 and len(content) < min_size * 1024:
                        reason = '过小 %.1fKB' % (len(content) / 1024)
                        transient = True   # 可能只是没下完，值得重试
                    else:
                        reason = ''
                        transient = False
                    if reason:
                        # 同一个候选先重试（可能是下载不完整/服务端抖动）
                        if transient and retry < max_retries - 1:
                            retry += 1
                            time.sleep(1)
                            continue
                        # 原图都小于下限 → 换成更小的预览图没有意义，直接跳过这张
                        if reason.startswith('过小'):
                            skipped += 1
                            self._log('跳过[过小 %.1fKB < %dKB][%d/%d]: %s' % (len(content)/1024, min_size, success + fail + skipped, len(img_urls), img_url[:80]))
                            # 更新任务进度（跳过的也算处理过）
                            if task_id:
                                self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                            return
                        # 还有候选 → 换下一个（原图取不到就回退预览图）
                        nxt = cand_idx + 1
                        if nxt < len(candidates):
                            self._log('原图不可用(%s)，回退预览图: %s' % (reason, img_url[:90]))
                            cand_idx = nxt
                            img_url = candidates[nxt]
                            retry = 0
                            continue
                        # 候选全试完 → 浏览器通道兜底（原图地址常需登录态/防盗链，HTTP 通道会 403）
                        fp = _cdp_fallback(img_url, idx)
                        if fp:
                            success += 1
                            total_bytes += os.path.getsize(fp)
                            self._log('浏览器通道下载成功[%d/%d]: %s' % (success + fail + skipped, len(img_urls), img_url[:80]))
                            if task_id:
                                self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                            return
                        fail += 1
                        self._log('下载失败[%s][%d/%d]: %s' % (reason, success + fail + skipped, len(img_urls), img_url[:80]))
                        if task_id:
                            self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                        return
                    # 取到可用内容：统计原图替换情况（换到原图的张数 / 回退预览的张数）
                    if had_origs:
                        if img_url != preview_url:
                            orig_ok += 1
                        else:
                            orig_fallback += 1
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
                    # ===== 伪装嗅探：MP4 视频常被改名为 .jpg，读文件头 ftyp 自动改名 =====
                    try:
                        with open(filepath, 'rb') as f:
                            head = f.read(12)
                        if len(head) >= 12 and head[4:8] == b'ftyp':
                            mp4_path = filepath.rsplit('.', 1)[0] + '.mp4'
                            os.rename(filepath, mp4_path)
                            filepath = mp4_path
                            self._log('检测到伪装视频（ftyp），已重命名: %s' % os.path.basename(mp4_path))
                    except Exception:
                        pass
                    # ===== 格式转换：WEBP/AVIF -> JPG（可选，品质可调）=====
                    try:
                        cw = getattr(self, 'convert_webp_var', None) and self.convert_webp_var.get()
                        ca = getattr(self, 'convert_avif_var', None) and self.convert_avif_var.get()
                        if (cw and ext == '.webp') or (ca and ext == '.avif'):
                            from PIL import Image
                            import io as _io
                            im = Image.open(_io.BytesIO(content)).convert('RGB')
                            q = 90
                            try:
                                q = int(self.jpg_quality_var.get())
                            except Exception:
                                pass
                            q = max(1, min(100, q))
                            new_filepath = filepath.rsplit('.', 1)[0] + '.jpg'
                            im.save(new_filepath, 'JPEG', quality=q)
                            if new_filepath != filepath:
                                os.remove(filepath)
                                filepath = new_filepath
                    except Exception:
                        pass  # 转失败就保留原文件
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
                        retry += 1
                        time.sleep(1)
                        continue
                    # 网络层异常：先换下一个候选（原图 → 预览图），候选试完再走浏览器通道
                    nxt = cand_idx + 1
                    if nxt < len(candidates):
                        self._log('原图请求异常(%s)，回退预览图: %s' % (str(e)[:60], img_url[:90]))
                        cand_idx = nxt
                        img_url = candidates[nxt]
                        retry = 0
                        continue
                    # 最后一次重试还是失败：尝试走浏览器通道（带代理/登录态）
                    fp = _cdp_fallback(img_url, idx)
                    if fp:
                        success += 1
                        total_bytes += os.path.getsize(fp)
                        self._log('浏览器通道下载成功[%d/%d]: %s' % (success + fail + skipped, len(img_urls), img_url[:80]))
                        if task_id:
                            self._update_task(task_id, progress='%d/%d' % (success + fail + skipped, len(img_urls)))
                        return
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
                if self.stop_flag.is_set():
                    self._log('用户停止下载，取消剩余 %d 个任务' % sum(1 for f in futures if not f.done()))
                    for f in futures:
                        f.cancel()
                    break
                try:
                    future.result()
                except Exception as e:
                    fail += 1
                    self._log('任务异常: %s' % str(e)[:100])

        if orig_ok or orig_fallback:
            self._log('原图替换: %d 张取到原图%s' % (
                orig_ok,
                ('，%d 张原图地址不可用已回退预览图' % orig_fallback) if orig_fallback else ''))
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
        # 去掉 " - 第 N 页" 后缀，避免多页抓取建不同文件夹
        title = re.sub(r'\s*[-_—]\s*第\s*\d+\s*页\s*$', '', title)
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

        # AI 看图调整策略：提取过少且AI可用时，让AI看页面判断加载方式并重新提取
        if len(img_urls) < 3 and (self.ai_ok or (self.ai_proc and self.ai_proc.poll() is None)) \
                and self.render_mode_var.get() == '浏览器模式(CDP)':
            img_urls = self._ai_adjust_extract(url, html, img_urls)

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

        success, fail, skipped = self._download_image_list(img_urls, save_dir, max_threads, min_size, task_id, referer=url)

        # AI 智能过滤（可选，未启用或服务未启动则自动跳过）
        if self.ai_filter_var.get():
            removed = self._ai_filter_images(save_dir, task_id)
            if removed:
                self._log('AI过滤删除 %d 张无关图' % removed)

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
        # 任务结束：没有待重试的失败任务就收起运行控制行（稍等一拍，等失败统计落到按钮状态上）
        try:
            self.root.after(300, self._sync_run_bar)
        except Exception:
            pass
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
    # 启动时自动清理一次截图目录（保留最近200张），防历史累积
    try:
        app._clean_screenshots(200)
    except Exception:
        pass
    root.mainloop()


if __name__ == '__main__':
    main()








































