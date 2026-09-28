# Bot hỏi đáp Telegram qua Cloudflare Worker

Worker xử lý `/start`, `/refresh`, `/trends`, `/forget`, nút hỏi sâu và câu hỏi tự do. Pipeline Python ghi context vào KV; Worker đọc context và gọi AI theo [cấu hình API chung](../config/README.md).

## Cài đặt cho bản fork

Trong thư mục `worker/`, copy `wrangler.example.toml` đè lên `wrangler.toml`, rồi điền `GITHUB_OWNER`, `GITHUB_REPO` và KV namespace của bạn. `wrangler.toml` hiện tại được giữ nguyên thông tin triển khai của repo gốc để không làm gián đoạn bot đang dùng.

```powershell
cd worker
Copy-Item wrangler.example.toml wrangler.toml
npx wrangler login
npx wrangler kv namespace create DIGEST_KV
```

Copy ID namespace nhận được vào `[[kv_namespaces]].id` trong `wrangler.toml`.

Đặt secret, chỉ cần key của nhà cung cấp AI bạn dùng:

```powershell
npx wrangler secret put GEMINI_API_KEY
# Hoặc / thêm dự phòng:
npx wrangler secret put DEEPSEEK_API_KEY
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put GITHUB_PAT
npx wrangler deploy
```

GitHub PAT cần quyền Contents: Read and write trên repo đích để gọi repository_dispatch. Thêm `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_KV_NAMESPACE_ID` vào GitHub Secrets để Python ghi đúng KV; token cần quyền sửa KV.

Đăng ký URL Worker vừa deploy với Telegram bằng phương thức Bot API `setWebhook`, tham số `url` là URL Worker. Token bot trong thao tác này phải trùng `TELEGRAM_BOT_TOKEN` đã đặt. Không lưu URL có token vào repo hoặc tài liệu chia sẻ.

## Chạy Worker local

Tạo `worker/.dev.vars` (đã được bỏ qua bởi Git), điền các biến cần dùng:

```dotenv
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
TELEGRAM_BOT_TOKEN=
GITHUB_PAT=
```

Chạy `npx wrangler dev`. Local KV tách biệt KV thật; muốn thử hỏi đáp cần có dữ liệu mẫu trong KV local. Local Worker vẫn có thể gọi AI và Telegram thật nếu bạn điền key thật.

Worker dùng model/endpoint chung ở `config/api.json`; nếu có override trong `[vars]` hoặc secret Worker thì override được ưu tiên. Sau khi thay file cấu hình chung, deploy lại Worker.

## Giới hạn hiện tại

Webhook chưa có xác thực request và giới hạn chat. Đây là hạng mục cần sửa trước khi dùng endpoint công khai rộng rãi. `/forget` hiện xóa lịch sử hội thoại nhưng chưa xóa trạng thái câu hỏi đang chờ. Xem [danh sách công việc tiếp theo](architecture.md).
