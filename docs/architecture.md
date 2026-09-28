# Kiến trúc và phạm vi bảo trì

## Luồng dữ liệu

`src/main.py`: lấy tin → lọc trùng/chấm điểm → AI chọn tin → đánh giá nguồn → bổ sung nội dung → AI phân tích → lưu dữ liệu → gửi Telegram.

- `sources/`: mỗi nguồn trả về `Item` chung trong `pipeline.py`.
- `pipeline.py`: lọc, chọn, xây prompt và đọc kết quả phân tích.
- `verify.py`: đánh giá độ tin cậy bằng quy tắc.
- `enrich.py`: lấy thêm nội dung bài viết.
- `llm_client.py`: adapter HTTP cho AI; `settings.py` đọc cấu hình chung.
- `memory.py`: quản lý `archive/`, `knowledge/`, `state/`.
- `deliver.py`: định dạng Telegram và ghi Cloudflare KV.
- `weekly.py`: tổng hợp bảy bản tin gần nhất (không nhất thiết bảy ngày lịch).
- `worker/src/index.js`: lệnh Telegram và context hội thoại.
- `worker/src/llm.js`: adapter hỏi đáp, cùng dùng `config/api.json` với Python.

Giữ các lệnh `python src/main.py` và `python src/weekly.py` để tương thích workflow cũ. Dữ liệu chạy thực tế vẫn ở các thư mục hiện tại để không phá lịch sử hoặc bước commit của Actions.

## Điểm cần sửa ở đợt tiếp theo

1. Xác thực webhook, giới hạn chat và tần suất gọi.
2. Chỉ đánh dấu tin đã gửi sau khi phân tích/gửi thành công; báo lỗi vận hành rõ ràng.
3. Dùng ID bền vững cho nút hỏi sâu, tránh ghi đè context bản tin cũ.
4. Nâng chất lượng phân loại và xác nhận chéo; nhãn xanh hiện chưa tương đương kiểm chứng thực tế.
5. Tách chế độ thử khỏi việc ghi dữ liệu/KV.
6. Thống nhất múi giờ Việt Nam và tránh workflow cùng ghi/push dữ liệu.
7. Giữ thứ tự ID khi giới hạn seen history; hiện chuyển qua set nên không bảo toàn thời gian.

## Tài liệu lịch sử

[Brief gốc](design/brief.md) và [quyết định cũ](history/decisions.md) được giữ để tra cứu bối cảnh, không thay thế hướng dẫn vận hành hiện tại. Hai báo cáo hoàn thành `result.md` và `result-webhook.md` đã bỏ vì trùng hướng dẫn/code; có thể tra lại qua Git.
