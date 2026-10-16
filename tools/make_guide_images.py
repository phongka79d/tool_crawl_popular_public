"""Capture only synthetic public UI and a throwaway sample Excel workbook.
Run: .venv/Scripts/python tools/make_guide_images.py
Uses installed Microsoft Edge; starts a temporary local static server if needed.
Never logs in to Facebook, reads real reports, or enters real credentials.
"""
from contextlib import contextmanager
from datetime import datetime
import html
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core.models import Video
from backend.services.export_excel import export

OUT = ROOT / 'docs' / 'img'
URL = 'http://127.0.0.1:8765/index.html?mock=1'


@contextmanager
def static_server():
    process = None
    try:
        expected = (ROOT / 'frontend' / 'index.html').read_bytes()
        try:
            with urlopen(URL, timeout=2) as response:
                if response.read() != expected:
                    raise RuntimeError('Port 8765 does not serve this public frontend; stop that server first.')
        except OSError:
            process = subprocess.Popen([sys.executable, '-m', 'http.server', '8765', '--bind', '127.0.0.1', '-d', str(ROOT / 'frontend')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for attempt in range(50):
                try:
                    with urlopen(URL, timeout=1) as response:
                        if response.read() != expected:
                            raise RuntimeError('Port 8765 does not serve this public frontend.')
                    break
                except OSError:
                    if process.poll() is not None or attempt == 49:
                        raise RuntimeError('Could not start the local preview server on port 8765.')
                    time.sleep(0.1)
        yield
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)


def annotate(page, targets):
    page.locator('#guide-annotations').evaluate_all('(nodes)=>nodes.forEach(n=>n.remove())')
    boxes = [target.bounding_box() for target in targets]
    if any(box is None for box in boxes):
        raise RuntimeError('An annotation target is invisible.')
    page.evaluate('''boxes => {
      const layer=document.createElement('div'); layer.id='guide-annotations';
      layer.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:2147483647';
      boxes.forEach((b,i)=>{const r=document.createElement('div');
        r.style.cssText=`position:absolute;left:${b.x+scrollX-4}px;top:${b.y+scrollY-4}px;width:${b.width+8}px;height:${b.height+8}px;border:3px solid #e32636;border-radius:8px;box-sizing:border-box`;
        const n=document.createElement('span');n.textContent=i+1;
        n.style.cssText='position:absolute;left:-13px;top:-13px;min-width:25px;height:25px;border-radius:50%;background:#e32636;color:white;font:bold 17px/25px Segoe UI;text-align:center;box-shadow:0 0 0 2px white';
        r.append(n);layer.append(r);});document.body.append(layer);
    }''', boxes)


def screenshot(page, name, targets, region=None):
    page.locator('.toast').evaluate_all('(nodes)=>nodes.forEach(n=>n.close())')
    if region is not None:
        region.scroll_into_view_if_needed()
    else:
        page.evaluate('window.scrollTo(0,0)')
    annotate(page, targets)
    options = {'full_page': True}
    if region is not None:
        box = region.bounding_box()
        dims = page.evaluate('({x:scrollX,y:scrollY,w:document.documentElement.scrollWidth,h:document.documentElement.scrollHeight})')
        x, y = max(0, box['x'] + dims['x'] - 20), max(0, box['y'] + dims['y'] - 20)
        options['clip'] = {'x': x, 'y': y, 'width': min(box['width'] + 40, dims['w'] - x), 'height': min(box['height'] + 40, dims['h'] - y)}
    page.screenshot(path=str(OUT / f'{name}.png'), **options)
    page.locator('#guide-annotations').evaluate('(e)=>e.remove()')
    print(name)


def excel_image(browser):
    """Render actual exporter cells, arranged into four readable column groups."""
    videos = [Video(video_id=str(i), url=f'https://www.facebook.com/reel/{100000+i}', page_url='https://www.facebook.com/page-demo', page_name='Bếp Mẫu (minh hoạ)', page_followers=120000, posted_at=1792126800, format='reel', duration_s=45+i, views=600000-i*130000, reactions=12000, comments=430, shares=1800, interactions=14230, ratio_follow=5, ratio_median=4, engagement=0.0237, share_rate=0.003, caption='Mẹo giữ rau tươi lâu hơn\nDữ liệu giả để hướng dẫn.', transcript='Hôm nay chúng ta cùng thử một mẹo nhỏ trong căn bếp. Rửa sạch rau và để ráo trước khi cất vào hộp.', taken_on='2026-10-15' if i == 2 else '') for i in (1, 2)]
    with tempfile.TemporaryDirectory(prefix='public-guide-') as directory:
        path = export(videos, ['Kênh mẫu: quét 35 video, giữ 2 video.'], ['Bỏ qua: video mẫu không có lời nói.'], output_dir=Path(directory), channel_stats=[{'url': videos[0].page_url, 'name': videos[0].page_name, 'followers': 120000, 'scanned': 35, 'recent': 20, 'median': 100000, 'threshold': 300000, 'selected': 2, 'highest_views': 470000}])
        book = load_workbook(path)
        try:
            sheet = book['Chi tiết video']
            groups = []
            for start, end in ((1, 7), (8, 16), (17, 20), (21, 24)):
                title = sheet.cell(1, start).value
                headers = ''.join('<th>'+html.escape(str(sheet.cell(2, c).value))+'</th>' for c in range(start, end+1))
                rows = []
                for row in (3, 4):
                    cells = []
                    for col in range(start, end+1):
                        cell = sheet.cell(row, col)
                        value = cell.value
                        if cell.hyperlink:
                            value = 'Mở bài ↗'
                        elif isinstance(value, datetime):
                            value = value.strftime('%d/%m/%Y %H:%M')
                        elif isinstance(value, (int, float)) and '%' in cell.number_format:
                            value = f'{value:.2%}'
                        elif isinstance(value, float):
                            value = f'{value:.2f}'
                        bg = '#'+cell.fill.fgColor.rgb[-6:] if cell.fill.fgColor.type == 'rgb' and cell.fill.patternType == 'solid' else 'white'
                        cells.append(f'<td style="background:{bg}">{html.escape(str(value or ""))}</td>')
                    rows.append('<tr>'+''.join(cells)+'</tr>')
                groups.append('<section><h2>'+html.escape(title)+'</h2><table><thead><tr>'+headers+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></section>')
            tabs = ''.join('<span>'+html.escape(name)+'</span>' for name in book.sheetnames)
        finally:
            book.close()
        page = browser.new_page(viewport={'width': 1280, 'height': 1100}, device_scale_factor=1.5)
        page.set_content('''<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{font:16px/1.4 "Segoe UI",sans-serif;background:#eef3f5;margin:28px;color:#243746}h1{font-size:25px;margin:0}p{margin:8px 0 20px;color:#536573}section{margin:22px 0;background:white;padding:16px;border:1px solid #bac9ce;border-radius:6px}h2{font-size:19px;margin:0 0 10px}table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}th,td{border:1px solid #bfc7ce;padding:9px;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}th{background:#234e63;color:white}nav{display:flex;gap:14px;background:#217346;padding:16px;color:white}nav span{background:white;color:#217346;padding:8px 14px;border-radius:4px}</style><h1>Excel · Chi tiết video</h1><p>Dữ liệu giả • Các cột được chia thành 4 nhóm để dễ đọc trong hướng dẫn; không phải cửa sổ Microsoft Excel.</p>'''+''.join(groups)+'<nav>'+tabs+'</nav>')
        screenshot(page, '11-excel', [page.locator('section').nth(i) for i in range(4)]+[page.locator('nav')])
        page.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with static_server(), sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge')
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=1.5, color_scheme='light')
            page = context.new_page()
            page.add_init_script('localStorage.clear()')
            page.goto(URL, wait_until='networkidle')
            button = lambda name: page.get_by_role('button', name=name, exact=True)
            text = lambda name: page.get_by_text(name, exact=True).first
            card = lambda title: text(title).locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," card ")][1]')
            page.get_by_label('Danh sách link kênh').wait_for()
            screenshot(page, '01-tong-quan', [page.locator('[role=tablist]'), card('Kênh cần quét'), card('Đăng nhập Facebook')])
            screenshot(page, '02-nhap-kenh', [page.get_by_label('Danh sách link kênh'), button('Lưu danh sách kênh')], card('Kênh cần quét'))
            text('Không đăng nhập được? Nạp file cookie').click()
            login = page.get_by_role('button', name='Đăng nhập lại', exact=True)
            if not login.count():
                login = button('Đăng nhập Facebook')
            screenshot(page, '03-facebook', [login, text('Không đăng nhập được? Nạp file cookie'), button('Chọn file cookie…')], card('Đăng nhập Facebook'))
            ai = card('Cải thiện lời thoại bằng AI (không bắt buộc)')
            screenshot(page, '04-ai', [page.get_by_label('Nhà cung cấp'), page.get_by_label('API key'), button('Kết nối')], ai)
            page.get_by_label('API key').fill('DEMO-ONLY-NOT-A-REAL-KEY')
            button('Kết nối').click()
            button('Kiểm tra và lưu').wait_for()
            screenshot(page, '05-ai-model', [page.get_by_label('Model', exact=True), button('Kiểm tra và lưu'), button('Xoá key')], ai)
            page.get_by_role('tab', name='Chạy quét', exact=True).click()
            page.get_by_label('Tôi đã đọc và tự chịu trách nhiệm', exact=True).wait_for()
            page.wait_for_function("document.querySelector('.scan-summary')?.textContent.trim()")
            screenshot(page, '06-tuy-chon', [card('Video cần quét'), card('Ngưỡng viral theo kênh'), page.locator('.scan-terms'), button('Bắt đầu quét')])
            page.get_by_label('Tôi đã đọc và tự chịu trách nhiệm', exact=True).check()
            button('Bắt đầu quét').click()
            page.locator('.scan-lanes').wait_for()
            page.wait_for_timeout(3000)
            screenshot(page, '07-tien-do', [page.locator('.scan-lanes'), card('Tiến độ từng kênh'), button('Dừng quét')])
            button('Mở file Excel').wait_for(timeout=45000)
            screenshot(page, '08-hoan-tat', [button('Mở file Excel'), button('Lưu bản sao…'), button('Xem trong Kết quả')])
            button('Xem trong Kết quả').click()
            page.get_by_label('Xem thống kê file').wait_for()
            page.wait_for_timeout(700)
            screenshot(page, '09-ket-qua', [page.get_by_label('Xem thống kê file'), card('Tổng quan kết quả'), button('Mở thư mục')])
            files = page.locator('.results-files')
            screenshot(page, '10-mo-excel', [files.locator('.results-file').first.get_by_role('button', name='Mở bằng Excel', exact=True), files.locator('.results-file').first.get_by_role('button', name='Lưu bản sao…', exact=True)], files)
            excel_image(browser)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
