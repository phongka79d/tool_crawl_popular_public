# Video Công Thức (bản public)

Ứng dụng Windows tìm video viral trên các page Facebook, chép lời tiếng Việt ngay trên máy (faster-whisper `small`) và xuất Excel. Không cần API key; có thể thêm key AI để cải thiện lời thoại.

## Cài đặt

Yêu cầu: Windows 10/11, [Python 3.11](https://www.python.org/downloads/release/python-3119/), Internet, [Microsoft Edge WebView2 Runtime](https://go.microsoft.com/fwlink/p/?LinkId=2124703) (thường đã có).

1. Bấm đúp **`CAI_DAT.bat`**: tạo `.venv` và cài thư viện trong `requirements.txt`.
2. Bấm đúp **`CHAY_APP.bat`** để mở ứng dụng. Lần đầu ứng dụng chuẩn bị trình duyệt quét (dùng Edge nếu có, không thì tải Chromium ~150 MB) và lần chép lời đầu tiên tải mô hình Whisper `small` (~486 MB) vào `data/models/`.

Không cần đăng ký dịch vụ AI để chạy app. Thư viện kết nối AI được cài sẵn nhưng chỉ gọi khi bạn tự bật bằng key và model.

## Sử dụng

1. Tab **Cài đặt**: nhập mỗi dòng một link page Facebook → **Lưu danh sách kênh** → **Đăng nhập Facebook** (nên dùng tài khoản phụ). Không đăng nhập được thì nạp file cookie.
2. Tab **Chạy quét**: chọn số ngày, loại video (video thường/Reel), ngưỡng viral, xác nhận lưu ý rồi **Bắt đầu quét**. Nghỉ 30–60 giây giữa các kênh là có chủ ý.
3. Tab **Kết quả**: xem thống kê, mở Excel trong `output/`.

### Cải thiện lời thoại bằng AI (không bắt buộc)

Trong **Cài đặt**, chọn OpenAI, Anthropic (Claude), OpenRouter hoặc endpoint HTTPS tương thích OpenAI tự nhập; nhập key → **Kết nối** → chọn model (app gợi ý sẵn) → **Kiểm tra và lưu**. Nhà cung cấp có thể tính phí. Lời thoại được gửi tới nhà cung cấp để sửa từ nghe nhầm và thêm dấu câu, không viết lại hay thêm ý; vẫn cần đọc lại kết quả.

Không thêm key vẫn quét, chép lời và xuất Excel đầy đủ. Nếu AI lỗi, app giữ bản Whisper gốc và ghi chú lỗi trong Excel; nhạc/bài hát được AI nhận diện sẽ bị bỏ qua. **Xoá key** tắt tính năng. Lọc trùng luôn dùng lời thoại gốc, không dùng bản AI sửa; video đã lấy tái sử dụng bản sửa lưu trong lịch sử.

### Luật lấy video

Với mỗi kênh, xét các video đăng trong N ngày gần nhất: video được lấy khi lượt xem **≥ hệ số × trung vị lượt xem của kênh** và **≥ lượt xem tối thiểu**; mỗi kênh tối đa số video đã chọn, ưu tiên lượt xem cao. Mặc định: 14 ngày, ×3, 50.000 view, 10 video/kênh.

- Video đã lấy ở lần quét trước vẫn có trong file, ghi **Đã lấy ngày dd/mm**, không chép lời lại.
- Nhiều video cùng kịch bản (lời thoại giống ≥ 50%, đổi ở `config/settings.json` → `scan.dedupe_threshold`) chỉ giữ bản view cao nhất; kịch bản đã lấy trước đó bị bỏ qua.
- Video lời nói dưới 30 ký tự bị bỏ qua.

### File Excel

`output/<ngày>.xlsx`, trang **Nội dung**: STT, Chủ đề, Nội dung thoại, Trạng thái, Link video mẫu, Kênh, Lượt xem, Ngày đăng, Số kênh cùng đăng, Tình trạng. Cột **Chủ đề** và **Trạng thái** để trống cho người dùng tự điền. Trang **Tình hình quét** ghi kết quả từng kênh, video bị bỏ qua và lỗi.

Bản chép lời là bản máy nghe, có thể sai chữ (ví dụ "trồng" thay "chồng"); cần đọc lại trước khi dùng.

**Bảo mật:** key chỉ lưu trong **Windows Credential Manager**, dịch vụ `VideoCongThucPublic` (tách riêng bản đầy đủ), không có bản dự phòng chữ thường trong settings.json; kho không an toàn thì app từ chối lưu. Đặt lại cấu hình cũng xoá key. Không chia sẻ `profile/`, `data/` (chứa phiên đăng nhập Facebook, cookie) hay `output/`. Chỉ thu thập nội dung được phép và tuân thủ điều khoản Facebook.

## Dành cho người phát triển

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.main                      # mở ứng dụng
python -m backend.services.pipeline --days 14 --min-views 50000 --viral-factor 3 --max-per-channel 10
pytest
python -m http.server -d frontend           # xem giao diện mô phỏng: /index.html?mock=1
python tools/capture_feed.py                # thu fixture Facebook (cần đăng nhập)
```

Giao diện chạy ở cổng `47241` (bản đầy đủ dùng `47231`), nên hai bản chạy song song không bị trùng; nếu cổng bận, ứng dụng tự chuyển sang cổng trống.

- `backend/main.py`: cửa sổ pywebview; `backend/api/`: cầu nối `Bridge` cho giao diện.
- `backend/collectors/`: quét Facebook (Playwright, GraphQL), cookie, yt-dlp, chép lời faster-whisper.
- `backend/services/`: `pipeline.py` (quét → lọc viral → chép lời → lọc trùng kịch bản → xuất), `filters.py`, `export_excel.py`.
- `backend/core/`: cấu hình, SQLite (`data/cache.db`, gồm lịch sử video đã lấy), log.
- `frontend/`: giao diện JavaScript thuần; `config/`: `settings.json`, `channels.txt`, cấu hình parser Facebook.
- `data/`, `output/`, `profile/`: dữ liệu khi chạy (gitignore).
