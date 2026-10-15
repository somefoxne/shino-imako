# Danbooru Copytag Bot - Shino Imako

Hệ thống bot tự động gắn `copytag` (thẻ bản quyền/nhóm) cho các bài đăng Danbooru theo rule đã duyệt, và tự động thu thập đề xuất bản quyền từ `related_tag` để chờ người kiểm duyệt.

---

## 1. Kiến trúc 2 Git Repositories

Dự án được chia tách thành 2 kho Git độc lập:

1. **Git Bot (Mã nguồn thực thi)**:
   - URL: `https://github.com/somefoxne/shino-imako.git`
   - Chứa: Mã nguồn bot (`bot.py`), danh sách rules quét (`rules.txt`), cấu hình, tài liệu.

2. **Git Database (Lưu trữ dữ liệu & Kiểm duyệt)**:
   - URL: `https://github.com/somefoxne/copyright_request_database.git`
   - Chứa: File `database.txt` lưu toàn bộ công thức tag đã duyệt và chờ duyệt.
   - Khi bot chạy, bot tự động `git pull` để lấy dữ liệu mới nhất, hoặc `git push` khi có tag mới được tạo.

---

## 2. Cấu trúc File `database.txt`

Cả 2 loại công thức (đã duyệt & chưa duyệt) được gộp chung trong 1 file duy nhất:

```text
# --- CÁC DÒNG ĐÃ ĐƯỢC DUYỆT (Không có dấu '?' ở đầu) ---
# Format: chartag -> copytag (chỉ 1 copytag chuẩn duy nhất)
ookami_mio -> hololive
shirakami_fubuki -> hololive
rem_(re:zero) -> re:zero_kara_hajimeru_isekai_seikatsu

# --- CÁC DÒNG CHƯA ĐƯỢC DUYỆT (Bắt đầu bằng dấu '?') ---
# Format: ?chartag -> copytag1 copytag2 copytag3 ... (top copyright tags)
?ookami_mio -> hololive hololive_gamers cover_corp
?tokino_sora -> hololive cover_corp
```

### Cách người kiểm duyệt duyệt tag:
- Tìm các dòng bắt đầu bằng `?` (dễ dàng tìm kiếm/grep trong editor hoặc Git).
- Xóa dấu `?` ở đầu dòng.
- Chọn lại 1 `copytag` chuẩn xác nhất và xóa các tag còn lại.
- Lưu lại và commit lên git repo database.

---

## 3. Cơ chế hoạt động của Bot

### Cơ chế 1: Cập nhật Database (`--update-db <chartags...>`)
1. Tự động đồng bộ git repo database (`git pull`).
2. Gửi request đến Danbooru API:
   `https://danbooru.donmai.us/related_tag.json?query=chartag&category=copyright`
   *(Chỉ lấy thẻ thuộc category **copyright**, đảm bảo 100% trả về là copytag).*
3. Lấy tối đa **top 10** copyright tags liên quan.
4. Ghi hoặc cập nhật dòng `?chartag -> copytag1 copytag2 ...` vào `database.txt`.
5. Tự động `git commit` và `git push` lên repository `copyright_request_database`.

### Cơ chế 2: Quét bài đăng & Tự động gắn Copytag (`--scan`)
1. Tự động đồng bộ git repo database (`git pull`).
2. Đọc các công thức **đã duyệt** (các dòng **không có dấu `?`**).
3. Đọc query cần quét từ `rules.txt` (ví dụ: `ookami_mio -hololive`).
4. Gọi API `/posts.json` để tìm danh sách bài đăng.
5. Với mỗi bài đăng có chứa `chartag`:
   - Gọi `/post_versions.json?search[post_id]=<ID>` để kiểm tra toàn bộ lịch sử chỉnh sửa.
   - **Nếu copytag đã từng xuất hiện hoặc từng được add trong lịch sử**: Bỏ qua (không add lại để tránh lặp hoặc vi phạm chỉnh sửa).
   - **Nếu chưa từng add lần nào**: Gọi `PUT /posts/<ID>.json` với `+copytag` để tự động thêm tag bản quyền vào bài viết.

---

## 4. Hướng dẫn sử dụng

### Cài đặt:
```bash
pip install requests
```

### Thiết lập biến môi trường (Khuyên dùng):
```powershell
$env:DANBOORU_USERNAME="tên_tài_khoản"
$env:DANBOORU_API_KEY="api_key_danbooru"

# Cấu hình URL git database (nếu cần thay đổi)
$env:DATABASE_REPO_URL="https://github.com/somefoxne/copyright_request_database.git"
```

### Lệnh chạy:

1. **Lấy gợi ý copytags mới và đẩy lên Git database**:
   ```bash
   python bot.py --update-db ookami_mio shirakami_fubuki tokino_sora
   ```

2. **Chạy quét bài và tự động gắn copytag đã duyệt**:
   ```bash
   python bot.py --scan
   ```
