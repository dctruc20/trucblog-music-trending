# TrucBlog Music – tự cập nhật YouTube Music Trending

Hệ thống này tạo dữ liệu **Music mostPopular theo quốc gia** qua YouTube Data API v3. Nó không tự ý nhận dạng âm thanh và không đảm bảo mọi video đều cho phép nhúng.

1. Tạo repository GitHub công khai (ví dụ `trucblog-music-trending`) và upload TOÀN BỘ cấu trúc file của thư mục này, bao gồm `.github/workflows/update-trending.yml`, `scripts/update_trending.py`, `trending.json`.
2. Tạo YouTube Data API v3 key bằng Google Cloud Console. Cấu hình giới hạn API cho key phù hợp với môi trường CI; **không dán key vào Blogger, GitHub code hoặc công khai**.
3. Vào repository GitHub → Settings → Secrets and variables → Actions → New repository secret → Name `YOUTUBE_API_KEY`, Value là API key.
4. Vào Settings → Actions → General → Workflow permissions, chọn `Read and write permissions` nếu môi trường của bạn yêu cầu để bot commit file JSON. Workflow sử dụng `permissions: contents: write`.
5. Vào Actions → `TrucBlog daily YouTube Music Trending` → Run workflow để chạy lần đầu; sau đó tự chạy khoảng **00:20 UTC mỗi ngày** (GitHub có thể trì hoãn lịch).
6. Vào Settings → Pages → Build and deployment → Deploy from a branch → `main / (root)`.
7. Khi Actions hoàn tất và Pages xuất bản, dữ liệu ở `https://<USERNAME>.github.io/<REPOSITORY>/trending.json`. Hãy mở URL, kiểm tra `regions.VN` hoặc `regions.AU` đã có dữ liệu.
8. Mở file **TrucBlog_Music_Pro_v4_ADMIN_PRIVATE.html** trên máy riêng. Điền URL `trending.json` ở phần **YouTube Trending**, chọn quốc gia và số video, lưu cấu hình rồi **Xuất Blogger Widget** để cập nhật trang âm nhạc.

## Ghi chú

- Chi phí API/quota phụ thuộc Google Cloud. Mỗi ngày thực hiện hai yêu cầu `videos.list` (VN, AU). Nên theo dõi quota nếu mở rộng.
- Nếu API lỗi, chương trình giữ dữ liệu công khai cũ (trường hợp không truy xuất được cả hai vùng, không ghi đè dữ liệu).
- Dữ liệu được tạo từ API nên không có dữ liệu thật cho tới khi bạn **tạo secret và chạy workflow**.
- Trình duyệt tải JSON (không có API key) và xem video bằng YouTube IFrame API ngay trong Blogspot. Một số video từ chối nhúng hoặc bị giới hạn theo vùng/bản quyền; dùng liên kết “Xem trên YouTube”.
- Đừng đặt công cụ admin lên website công khai; việc lưu nháp bằng localStorage không tạo tài khoản admin có xác thực. Đăng bài thực tế vẫn cần người có quyền sửa Blogger.
- Lịch của GitHub Actions chạy ở nhánh mặc định; các repo công khai không hoạt động lâu ngày có thể bị tạm ngưng workflow theo chính sách GitHub.
