"""Dựng frontend/img/logo.ico từ frontend/img/logo.svg (cửa sổ ứng dụng và lối tắt Desktop).
Chạy: .venv/Scripts/python tools/make_icon.py  — dùng Edge có sẵn, không cài thêm thư viện.
"""
import base64
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'frontend' / 'img' / 'logo.svg'
ICO = ROOT / 'frontend' / 'img' / 'logo.ico'
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# Vẽ SVG lên canvas để lấy điểm ảnh RGBA thô (không cần thư viện xử lý ảnh).
RASTER_JS = '''async ([source, size]) => {
  const image = new Image();
  image.src = source;
  await image.decode();
  const canvas = Object.assign(document.createElement('canvas'), {width: size, height: size});
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0, size, size);
  const rgba = context.getImageData(0, 0, size, size).data;
  let text = '';
  for (let i = 0; i < rgba.length; i += 8192) text += String.fromCharCode(...rgba.subarray(i, i + 8192));
  return {rgba: btoa(text), png: canvas.toDataURL('image/png').split(',')[1]};
}'''


def dib(size: int, rgba: bytes) -> bytes:
    """Ảnh BMP 32-bit trong ICO. System.Drawing (khung cửa sổ WinForms) không đọc được PNG cỡ nhỏ."""
    header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = [rgba[y * size * 4:(y + 1) * size * 4] for y in range(size)]
    pixels = b''.join(bytes(row[i + c] for i in range(0, len(row), 4) for c in (2, 1, 0, 3))
                      for row in reversed(rows))
    mask = b'\0' * (((size + 31) // 32) * 4 * size)   # alpha quyết định độ trong suốt
    return header + pixels + mask


def ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b'', b''
    for size, payload in images:
        side = 0 if size >= 256 else size   # 0 nghĩa là 256 trong định dạng ICO
        entries += struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32, len(payload), offset + len(data))
        data += payload
    return header + entries + data


def main():
    source = 'data:image/svg+xml;base64,' + base64.b64encode(SVG.read_bytes()).decode()
    images = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge')
        page = browser.new_page()
        for size in SIZES:
            result = page.evaluate(RASTER_JS, [source, size])
            # Cỡ lớn dùng PNG cho nhẹ (Windows đọc được); cỡ nhỏ dùng BMP cho mọi nơi hiển thị.
            payload = (base64.b64decode(result['png']) if size >= 128
                       else dib(size, base64.b64decode(result['rgba'])))
            images.append((size, payload))
        browser.close()
    ICO.write_bytes(ico(images))
    print(f'{ICO.relative_to(ROOT)}: {len(images)} cỡ, {ICO.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
