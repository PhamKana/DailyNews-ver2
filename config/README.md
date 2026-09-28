# Cấu hình API — bắt đầu ở đây sau khi fork

## Mặc định chỉ Gemini — không tự chuyển sang DeepSeek

Chuỗi mặc định (engine `gemini`): **`gemini-3-flash-preview` → `gemini-2.5-flash` → `gemini-2.5-flash-lite`**. Đây là thứ tự ưu tiên cho bot, không phải bảng xếp hạng tuyệt đối cho mọi tác vụ. Chỉ thử model kế khi request lỗi/hết quota hoặc trả nội dung rỗng; dừng ngay khi thành công.
Google hiện liệt kê các model này có Free Tier cho đầu vào/đầu ra:
https://ai.google.dev/gemini-api/docs/pricing

**Phải dùng API key thuộc project Free Tier, chưa bật billing.** Tên model không bảo đảm miễn phí nếu project của key đã ở Paid Tier. Kiểm tra Plan của project trong Google AI Studio; quota thực tế xem tại đó. Code không thể xác định gói thanh toán chỉ từ chuỗi API key.

Khi tất cả model Gemini lỗi, bot không chuyển sang DeepSeek với cấu hình mặc định. Lần gọi AI sẽ thất bại và pipeline xử lý lỗi theo cơ chế hiện tại. GitHub workflows không truyền key DeepSeek nữa. Nếu Worker cũ còn `LLM_ENGINE=auto` hoặc `deepseek`, bỏ override đó; xóa secret DeepSeek khi muốn loại bỏ hoàn toàn khả năng gọi dịch vụ này. Cần deploy lại để áp dụng thay đổi local.

## 1. Chọn API/model

Sửa **[api.json](api.json)** — đây là cấu hình mặc định dùng chung cho pipeline Python và Worker hỏi đáp:

| Trường | Ý nghĩa |
|---|---|
| `engine` | `auto`: Gemini trước, DeepSeek dự phòng; hoặc `gemini` / `deepseek` để chỉ dùng một bên |
| `providers.gemini.model` | Tên model Gemini tài khoản của bạn được dùng |
| `providers.gemini.fallback_models` | Danh sách model dự phòng, thử theo thứ tự từ trái sang phải |
| `providers.gemini.endpoint` | Endpoint Gemini generateContent, giữ `{model}` trong URL |
| `providers.deepseek.model` | Tên model DeepSeek tài khoản của bạn được dùng |
| `providers.deepseek.endpoint` | Endpoint tương thích Anthropic Messages |
| `temperature` | Độ biến thiên câu trả lời |
| `timeout_seconds` | Thời gian chờ mỗi request |
| `max_tokens` | Giới hạn đầu ra cho nhánh Anthropic-compatible |

Chỉ khi chủ động chấp nhận dùng API trả phí: đặt `"engine": "deepseek"` rồi điền `DEEPSEEK_API_KEY`. Không dùng `auto` nếu muốn tránh fallback sang DeepSeek.
Hãy dùng tên model thực sự được cấp cho tài khoản của bạn; model DeepSeek được giữ để tương thích cấu hình cũ và không dùng mặc định.

**Hiện hỗ trợ hai giao thức trên.** Đổi endpoint chỉ áp dụng cho dịch vụ cùng giao thức; API khác định dạng như OpenAI Chat Completions cần thêm adapter, không thể chỉ thay URL.

## 2. Điền khóa truy cập

- **Python local:** copy [.env.example](.env.example) thành `config/.env`, điền key. Code tự đọc file, không phụ thuộc thư mục đang đứng.
- **GitHub Actions:** thêm các tên bên dưới vào repository **Secrets**. Không commit file chứa key.
- **Cloudflare Worker:** dùng `npx wrangler secret put TEN_BIEN` trong `worker/`; local Worker đọc `worker/.dev.vars`. Worker không đọc file `.env` của Python.

| Biến | Khi nào cần |
|---|---|
| `GEMINI_API_KEY` | Dùng Gemini cho bản tin hoặc hỏi đáp |
| `DEEPSEEK_API_KEY` | Dùng DeepSeek cho bản tin hoặc hỏi đáp |
| `TELEGRAM_BOT_TOKEN` | Gửi tin Telegram / vận hành Worker |
| `TELEGRAM_CHAT_ID` | Người nhận bản tin từ Python |
| `PRODUCTHUNT_TOKEN` | Tùy chọn, lấy nguồn Product Hunt |
| `CLOUDFLARE_API_TOKEN` | Tùy chọn, Python ghi dữ liệu KV |
| `CLOUDFLARE_ACCOUNT_ID` | Account Cloudflare chứa KV |
| `CLOUDFLARE_KV_NAMESPACE_ID` | Namespace KV, phải trùng binding Worker |
| `GITHUB_PAT` | Chỉ Worker, để `/refresh` kích hoạt repo |

Khóa Gemini lấy tại Google AI Studio; DeepSeek tại dashboard API của DeepSeek; token bot Telegram lấy qua BotFather. Các khóa dịch vụ còn lại lấy ở dashboard của dịch vụ tương ứng.

## 3. Thứ tự ưu tiên

Python: **biến môi trường đang có → `config/.env` → `.env` ở root (hỗ trợ cũ)**.
Cấu hình model: **biến môi trường không rỗng → `api.json`**.

Override tùy chọn: `LLM_ENGINE`, `LLM_TEMPERATURE`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `GEMINI_ENDPOINT`, `DEEPSEEK_MODEL`, `DEEPSEEK_ENDPOINT`.
Python và Worker đều hỗ trợ các override này. Trên GitHub, cách đơn giản là sửa `api.json`; workflow hiện chỉ truyền các secret cần thiết.

`api.json` chỉ chứa cấu hình công khai. Không đưa key vào endpoint hoặc file này. Sửa cấu hình chung xong cần deploy lại Worker để áp dụng cho hỏi đáp; Python đọc lại ở lần chạy kế tiếp.

## 4. Chủ đề quan tâm

Sửa [thesis.yaml](thesis.yaml): `tracking`, `deep_tech_tracking`, `keywords_boost`, `outside_lane_domains`.
`what_counts_as_matters` hiện chỉ mang tính mô tả; code chưa sử dụng trường này để chấm điểm.

`GEMINI_MODEL` override sẽ chỉ dùng một model, bỏ fallback mặc định. Muốn override cả chuỗi, thêm `GEMINI_FALLBACK_MODELS` (phân cách bằng dấu phẩy). Đặt chuỗi rỗng để tắt fallback. Log ghi model đã trả lời thành công.
