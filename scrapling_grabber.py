# -*- coding: utf-8 -*-
"""Scrapling 图片爬虫 - 基于 Scrapling 的简单图片抓取工具"""
import os
import sys
import time
import urllib.parse
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用 SSL 验证（避免部分网站证书问题）
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 浏览器请求头
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 图片扩展名
IMG_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.avif')


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


def crawl_images(url, save_dir, max_threads=8):
    """用 Scrapling 抓取网页图片并下载"""
    try:
        from scrapling import Fetcher
    except ImportError:
        print('错误: Scrapling 未安装，请运行 pip install scrapling')
        return

    print('=' * 50)
    print('Scrapling 图片爬虫')
    print('=' * 50)
    print('目标网址:', url)
    print('保存目录:', save_dir)
    print('下载线程:', max_threads)
    print()

    # 创建保存目录
    os.makedirs(save_dir, exist_ok=True)

    # 用 Scrapling 抓取网页
    print('[1/3] 正在抓取网页...')
    start_time = time.time()
    try:
        fetcher = Fetcher()
        response = fetcher.get(url, headers=BROWSER_HEADERS, timeout=30)
        page = response.adaptor
    except Exception as e:
        print('抓取失败:', e)
        return

    crawl_time = time.time() - start_time
    print('抓取完成，耗时: %.2f 秒' % crawl_time)

    # 提取图片链接
    print('[2/3] 正在提取图片链接...')
    img_urls = set()

    # 从 img 标签提取
    try:
        imgs = page.css('img')
        for img in imgs:
            attrs = img.attributes
            for attr in ['src', 'data-src', 'data-original', 'data-lazy-src', 'data-echo', 'data-url']:
                val = attrs.get(attr, '')
                if val and not val.startswith('data:'):
                    full_url = urllib.parse.urljoin(url, val)
                    if any(full_url.lower().endswith(ext) for ext in IMG_EXTS) or '/image' in full_url.lower():
                        img_urls.add(full_url)
    except Exception as e:
        print('提取 img 标签失败:', e)

    # 从 CSS 背景图片提取
    try:
        elements = page.css('[style*="background"]')
        for elem in elements:
            style = elem.attributes.get('style', '')
            if 'url(' in style:
                import re
                matches = re.findall(r'url\(["\']?([^"\')]+)["\']?\)', style)
                for m in matches:
                    full_url = urllib.parse.urljoin(url, m)
                    if any(full_url.lower().endswith(ext) for ext in IMG_EXTS):
                        img_urls.add(full_url)
    except Exception as e:
        pass

    print('提取到 %d 张图片' % len(img_urls))

    if not img_urls:
        print('没有找到图片')
        return

    # 下载图片
    print('[3/3] 正在下载图片...')
    download_start = time.time()
    success_count = 0
    total_bytes = 0

    def download_one(idx, img_url):
        ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1]
        if not ext or ext not in IMG_EXTS:
            ext = '.jpg'
        filename = 'img_%03d%s' % (idx, ext)
        save_path = os.path.join(save_dir, filename)
        size = download_image(img_url, save_path)
        return idx, size, img_url

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {executor.submit(download_one, i + 1, url): i for i, url in enumerate(img_urls)}
        for future in as_completed(futures):
            try:
                idx, size, img_url = future.result()
                if size:
                    success_count += 1
                    total_bytes += size
                    print('  [%d/%d] 下载成功: %s (%.1f KB)' % (
                        idx, len(img_urls), os.path.basename(img_url)[:50], size / 1024))
                else:
                    print('  [%d/%d] 下载失败: %s' % (idx, len(img_urls), os.path.basename(img_url)[:50]))
            except Exception as e:
                print('  下载异常:', e)

    download_time = time.time() - download_start
    total_time = time.time() - start_time

    print()
    print('=' * 50)
    print('抓取完成!')
    print('  总图片数: %d' % len(img_urls))
    print('  下载成功: %d' % success_count)
    print('  下载失败: %d' % (len(img_urls) - success_count))
    print('  总大小: %.2f MB' % (total_bytes / 1024 / 1024))
    print('  抓取耗时: %.2f 秒' % crawl_time)
    print('  下载耗时: %.2f 秒' % download_time)
    print('  总耗时: %.2f 秒' % total_time)
    print('  平均速度: %.2f KB/s' % (total_bytes / 1024 / download_time if download_time > 0 else 0))
    print('=' * 50)


def main():
    """主函数"""
    if len(sys.argv) >= 3:
        url = sys.argv[1]
        save_dir = sys.argv[2]
        max_threads = int(sys.argv[3]) if len(sys.argv) >= 4 else 8
    else:
        print('Scrapling 图片爬虫')
        print('用法: scrapling_grabber.exe <网址> <保存目录> [线程数]')
        print()
        url = input('请输入网址: ').strip()
        if not url:
            print('网址不能为空')
            input('按回车键退出...')
            return
        save_dir = input('请输入保存目录 (默认: ./downloads): ').strip()
        if not save_dir:
            save_dir = './downloads'
        max_threads = input('请输入下载线程数 (默认: 8): ').strip()
        max_threads = int(max_threads) if max_threads else 8

    crawl_images(url, save_dir, max_threads)
    print()
    input('按回车键退出...')


if __name__ == '__main__':
    main()
