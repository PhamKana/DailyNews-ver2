# Morning Intel Agent

Bot tổng hợp tin công nghệ bằng AI, gửi bản tin tiếng Việt qua Telegram và lưu xu hướng theo thời gian. Chạy bằng Python + GitHub Actions; Cloudflare Worker bổ sung hỏi đáp trực tiếp.

## Bắt đầu từ đâu?

- **Thay API, model, key:** [config/README.md](config/README.md).
- **Cài bot hỏi đáp Telegram:** [docs/telegram-worker.md](docs/telegram-worker.md).
- **Hiểu kiến trúc và các điểm cần sửa:** [docs/architecture.md](docs/architecture.md).
- **Thiết kế gốc:** [docs/design/brief.md](docs/design/brief.md).

## Chạy local

Yêu cầu Python 3.11 trở lên. Trên PowerShell, chạy từ thư mục repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config/.env.example config/.env
# Điền key vào config/.env, chọn model trong config/api.json.
.\.venv\Scripts\python.exe src/main.py
```

Trên macOS/Linux, dùng `.venv/bin/python` thay cho `.\.venv\Scripts\python.exe` và `cp` thay cho `Copy-Item`.
Tổng hợp tuần: chạy `src/weekly.py` thay cho `src/main.py`.

**Lưu ý hiện tại:** `DRY_RUN=true` chỉ chặn gửi Telegram; vẫn gọi nguồn/AI, ghi dữ liệu local và có thể ghi Cloudflare KV nếu đã điền key. Không dùng nó như chế độ thử hoàn toàn không tác động dữ liệu.

## Cấu trúc

```text
config/        API, mẫu biến môi trường, chủ đề quan tâm
src/           Pipeline Python, bộ nhớ, gửi tin và các nguồn tin
worker/        Webhook Telegram và bộ gọi AI cho hỏi đáp
tests/         Kiểm thử Python
worker/tests/  Kiểm thử Worker bằng Node
.github/       Lịch tự động và kiểm thử
archive/       Bản tin ngày/tuần đã lưu
knowledge/     Kiến thức và xu hướng tích lũy
state/         ID tin đã xử lý
docs/          Hướng dẫn, kiến trúc và tài liệu thiết kế
```

## Chạy tự động trên GitHub

Sau khi fork, thêm key trong **Settings → Secrets and variables → Actions** theo [hướng dẫn cấu hình](config/README.md), rồi bật Actions và chạy workflow thủ công lần đầu.

- `daily.yml`: 06:00 giờ Việt Nam mỗi ngày; nhận cả lệnh `/refresh`.
- `weekly.yml`: lịch hiện tại là 06:00 thứ Hai giờ Việt Nam.
- Workflow lưu lại `archive/`, `knowledge/`, `state/` bằng commit vào repo.
- Model và endpoint đọc từ `config/api.json` trong repo; không cần sửa workflow khi đổi các giá trị này.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
node --test worker/tests/*.test.js
```

Kiểm thử dùng API giả lập, không gửi Telegram hoặc tiêu tốn API thật. Worker tests yêu cầu Node 22 trở lên.

Dữ liệu bài viết, chủ đề quan tâm và câu hỏi/lịch sử chat được gửi cho nhà cung cấp AI đã chọn. Không đưa thông tin nhạy cảm vào các nội dung này nếu chưa kiểm tra chính sách của nhà cung cấp.
