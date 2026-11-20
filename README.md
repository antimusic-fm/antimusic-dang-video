# Antimusic Dang Video

Công cụ nội bộ của AntiMusic Café & Radio: tự đăng video đã duyệt lên YouTube và Instagram theo lịch trong Google Sheet.

- `dang_video.py`: script đăng (chỉ dùng thư viện có sẵn của Python). Xem `python3 dang_video.py -h`.
- `.github/workflows/dang-video.yml`: GitHub Actions chạy script 4 lần/giờ.
- `lay_khoa_google.py`: lấy quyền Google một lần trên máy chủ sở hữu kênh.
- `docs/`: trang chủ và chính sách bảo mật (GitHub Pages).

Khoá truy cập nằm trong GitHub Secrets, không nằm trong repo.
