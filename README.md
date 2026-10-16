# Video Công Thức (bản public)

Ứng dụng Windows tìm video viral trên các page Facebook, chép lời tiếng Việt ngay trên máy (faster-whisper `small`) và xuất Excel. Không cần API key; có thể thêm key AI để cải thiện lời thoại.
**Hướng dẫn có ảnh cho người mới:** [Tải bản PDF](docs/HUONG-DAN.pdf) · [Đọc trực tiếp](docs/HUONG-DAN.md).

## Cài đặt

Yêu cầu: Windows 10/11 64-bit, Internet. Không cần cài sẵn Python hay quyền quản trị.

1. Trên GitHub bấm **Code → Download ZIP**, bấm chuột phải file ZIP → **Extract All** (không chạy bên trong ZIP).
2. Bấm đúp **`CAI_DAT.bat`** (SmartScreen chặn thì **More info → Run anyway**). Lần đầu mất khoảng 5–15 phút, tải ~1 GB. Bộ cài tự:
   - cài Python 3.11 nếu máy chưa có (winget, không có thì tải từ python.org; chỉ cho tài khoản hiện tại);
   - cài Microsoft Edge WebView2 nếu thiếu;
   - tạo `.venv`, cài thư viện trong `requirements.txt`;
   - tải trước mô hình Whisper `small` (~490 MB, vào `data/models/`) và trình duyệt quét (dùng Edge nếu có, không thì Chromium ~150 MB);
   - tạo lối tắt **Video Công Thức** trên Desktop rồi mở ứng dụng.
3. Những lần sau mở bằng lối tắt trên Desktop hoặc **`CHAY_APP.bat`**.

Lỗi mạng giữa chừng: bấm lại `CAI_DAT.bat`, phần đã xong được giữ, chỉ làm tiếp phần thiếu. `.venv` hỏng (ví dụ chép thư mục từ máy khác) được tạo lại tự động.

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
- Nhiều video cùng kịch bản (lời thoại giống ≥ 50%, đổi ở `data/settings.json` → `scan.dedupe_threshold`) chỉ giữ bản view cao nhất; kịch bản đã lấy trước đó bị bỏ qua.
- Video lời nói dưới 30 ký tự bị bỏ qua.

### File Excel

`output/<ngày>.xlsx` (trùng tên sẽ thêm ` (lần N)`), gồm ba trang theo bố cục bản đầy đủ nhưng không có cột phân tích AI:

- **Chi tiết video**: hai hàng tiêu đề chia nhóm **Thông tin bài**, **Chỉ số**, **Nội dung**, **Theo dõi**. Có follower, ngày giờ đăng theo giờ Việt Nam, loại video, thời lượng, link mở bài, lượt xem/cảm xúc/bình luận/chia sẻ/tổng tương tác, các tỷ lệ, caption, lời thoại, hook gốc và ghi chú. **Chủ đề** và **Trạng thái** để trống cho người dùng tự điền. Hook lấy dòng caption đầu và tối đa 30 từ đầu lời thoại gốc, không dùng AI.
- **Tổng hợp kênh**: tổng quan lượt chạy, thống kê từng kênh (trung vị và ngưỡng viral thực dùng khi lọc), top 10 lượt xem.
- **Nhật ký**: thời gian, tham số quét, model chép lời, nhà cung cấp/model cải thiện lời thoại nếu bật, kết quả từng kênh, video bỏ qua (xám) và lỗi (đỏ).

Các số đếm được ghi dạng chữ Việt như `6,6 triệu`, `66 nghìn`, `850`; tỷ lệ và thời lượng vẫn là số, chỉ số chưa biết để trống. Tổng tương tác cộng những số cảm xúc/bình luận/chia sẻ đã biết; View/Follower = view/follower, hệ số trung vị = view/trung vị kênh, tỷ lệ tương tác = tổng tương tác/view, tỷ lệ share = share/view. Video mới xếp trước, mỗi nhóm giảm dần theo view; ô STT và tình trạng video mới có nền xanh nhạt. Video đã lấy giữ lời thoại lịch sử nhưng cập nhật chỉ số từ lần quét hiện tại. Lời thoại ưu tiên bản AI sửa nếu có và được ghi chú rõ. Tab **Kết quả** vẫn đọc được các file cũ có trang **Nội dung** và **Tình hình quét**.

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
- `frontend/`: giao diện JavaScript thuần; `config/`: cấu hình parser Facebook. Lựa chọn quét (`data/settings.json`) và danh sách kênh (`data/channels.txt`) của người dùng nằm trong `data/`, không đưa lên Git; mặc định nằm trong `backend/core/config.py`.
- `data/`, `output/`, `profile/`: dữ liệu khi chạy (gitignore).

### Hiệu năng chép lời

Sau mỗi kênh, ứng dụng chuyển video đã lọc sang một luồng chép lời/cải thiện AI; trình duyệt tiếp tục quét kênh kế hoặc nghỉ theo cấu hình. Mỗi lượt chạy chỉ dùng một mô hình Whisper và tải một audio tại một thời điểm. Lọc trùng kịch bản chạy **sau khi tất cả luồng chép lời hoàn tất**, giữ bản nhiều view nhất toàn lượt. Dừng quét vẫn xuất phần đã xong và các video lịch sử đã gặp.

Whisper `small/int8/CPU` dùng `beam_size=1`, `condition_on_previous_text=False`, nửa số CPU logic và `num_workers=1`. Đo trên reel Facebook `2303049847203173` (39,1 giây, máy 16 CPU logic): cấu hình cũ `beam_size=5` mất **42,532 giây**; cấu hình mới khi model đã nạp mất **19,799 giây** (gồm nạp model: 23,641 giây). Đây là đánh đổi giải mã greedy; lời thoại vẫn cần kiểm tra, không cam kết giống từng chữ.

Đo riêng 6 cấu hình greedy (giây, đã nạp model): `cpu_threads=0`: 20,605 / 20,605; `8`: 19,471 / 19,497; `16`: 23,161 / 21,623; mỗi cặp lần lượt `num_workers=1/2`. Tải public anonymous không còn nghỉ ngẫu nhiên 2–6 giây: không gắn phiên tài khoản, tải vẫn tuần tự. Nếu cần cookie, giữ nguyên nghỉ tải 2–6 giây và nghỉ request 1 giây, dùng bản cookie tạm riêng để không ghi đè cookie trình duyệt. Thời gian tải reel đo trước/sau: 6,637 / 2,442 giây (phụ thuộc mạng). Không thay đổi thời gian nghỉ giữa kênh.

Không bỏ tra ngày đăng của video ít view: ngày đăng quyết định video có thuộc mẫu tính trung vị hay không. Chỉ bỏ backfill metadata nếu **đã biết chắc video cũ hơn cửa sổ quét**; vẫn tra view/ngày còn thiếu của các video khác.

### Tạo lại hướng dẫn có ảnh

Sau khi cài thư viện của dự án, chạy hai lệnh sau từ thư mục gốc (Windows PowerShell):

```powershell
.\.venv\Scripts\python.exe tools/make_guide_images.py
.\.venv\Scripts\python.exe tools/make_guide_pdf.py
```

Cần Microsoft Edge đã cài; cả hai script dùng Playwright `channel='msedge'`, không tải trình duyệt hay cài thêm thư viện. Script ảnh tự mở một máy chủ tĩnh tạm ở cổng `8765`, phục vụ `frontend/` tại `/index.html?mock=1`, rồi tự đóng máy chủ do nó tạo. Có thể tự chạy trước `python -m http.server 8765 -d frontend`; nếu cổng đang phục vụ ứng dụng khác, hãy đóng máy chủ đó trước.

Logo: sửa `frontend/img/logo.svg` (logo trên giao diện), rồi chạy `.\.venv\Scripts\python.exe tools/make_icon.py` để dựng lại `frontend/img/logo.ico` dùng cho khung cửa sổ và lối tắt Desktop (cũng dùng Edge, không cài thêm gì).

Ảnh `docs/img/*.png` dùng dữ liệu mô phỏng và số chú thích đỏ, không đăng nhập Facebook hoặc nhập key thật. Ảnh Excel dựng từ workbook dữ liệu giả qua `backend.services.export_excel`; workbook tạm được xoá tự động, không đọc báo cáo cá nhân. Script PDF đọc `docs/HUONG-DAN.md`, kiểm tra các ảnh đã tải, xuất A4 với mục lục có liên kết và số trang, rồi in số trang/dung lượng. Không cần Word hay Microsoft Excel để tạo tài liệu.
