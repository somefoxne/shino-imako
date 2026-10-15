# Danbooru Copytag Bot - Shino Imako

Hệ thống bot tự động gắn `copytag` (thẻ bản quyền/nhóm) cho các bài đăng Danbooru theo database đã duyệt, và tự động thu thập đề xuất bản quyền từ `related_tag` để chờ người kiểm duyệt.

---

## 1. Kiến trúc 2 Git Repositories

Dự án được chia tách thành 2 kho Git độc lập:

1. **Git Bot (Mã nguồn thực thi)**:
   - URL: `https://github.com/somefoxne/shino-imako.git`
   - Chứa: Mã nguồn bot (`bot.py`), bộ phân tích phạm vi quét (`checkfile_parser.py`), file phạm vi quét (`data/checkfile.txt`), tài liệu và cấu hình.

2. **Git Database (Lưu trữ dữ liệu & Kiểm duyệt)**:
   - URL: `https://github.com/somefoxne/copyright_request_database.git`
   - Chứa duy nhất file `database.txt` lưu toàn bộ công thức tag đã duyệt và chờ duyệt.

---

## 2. Cấu trúc File `database.txt` (Tại git database)

```text
# --- CÁC DÒNG ĐÃ ĐƯỢC DUYỆT (Không có dấu '?' ở đầu) ---
# Format: chartag -> copytag
ookami_mio -> hololive
shirakami_fubuki -> hololive
rem_(re:zero) -> re:zero_kara_hajimeru_isekai_seikatsu

# --- CÁC DÒNG CHƯA ĐƯỢC DUYỆT (Bắt đầu bằng dấu '?') ---
# Format: ?chartag -> copytag1 copytag2 copytag3 ...
?ookami_mio -> hololive hololive_gamers cover_corp
?tokino_sora -> hololive cover_corp
```

---

## 3. Cấu trúc `data/checkfile.txt` (Phạm vi quét)

Mỗi dòng trong `data/checkfile.txt` đại diện cho một kịch bản quét độc lập:

```text
# Hỗ trợ toàn bộ cú pháp Danbooru Cheatsheet:
# id:<số>, pool:<số>, pool:any, user:<tên>, rating:s/g/q/e, tag_name
# Loại trừ bằng dấu trừ (-): -user:<tên>, -tag_name, -pool:<số>

# 1. Quét theo tag và gửi thông báo Discord:
ookami_mio -hololive Noti:discord

# 2. Quét tất cả bài trong pool trừ spammer, yêu cầu duyệt qua Discord, cho phép add lại sau 5 lượt sửa:
pool:any -user:spammer Noti:ask Noti:discord readd:5

# 3. Quét post của artist cụ thể, không bao giờ add lại nếu tag bị xóa:
user:artist_name Noti:discord readd:never
```

### Các chỉ thị hỗ trợ trong dòng quét:
- **`Noti:discord`**: Tự động gửi thông báo kết quả cập nhật kèm thumbnail vào Discord.
- **`Noti:ask`**: Gửi yêu cầu hỏi duyệt trên Discord trước khi thêm.
- **`readd:never`** *(Mặc định)*: Nếu tag từng có trong lịch sử mà bị xóa $\rightarrow$ Không bao giờ gắn lại.
- **`readd:<số>`** (vd `readd:5`): Chỉ cho phép gắn lại nếu đã trải qua ít nhất `<số>` lượt sửa (versions) sau khi bị xóa.
*(Lưu ý: Không cần chỉ thị `action:` vì bot chỉ chuyên xử lý duy nhất 1 nhiệm vụ gắn copytag).*

---

## 4. Hướng dẫn sử dụng

### Cài đặt:
```bash
pip install requests
```

### Cấu hình file `.env`:
Tạo file `.env` (hoặc sao chép từ `.env.example`):
```env
# ==========================================
# CHẾ ĐỘ TESTBOORU (TEST_MODE: on / off)
# ==========================================
TEST_MODE=off
TESTBOORU_URL=https://testbooru.donmai.us
TESTBOORU_USERNAME=your_testbooru_username
TESTBOORU_API_KEY=your_testbooru_api_key

# ==========================================
# DANBOORU CHÍNH THỨC (PRODUCTION)
# ==========================================
DANBOORU_URL=https://danbooru.donmai.us
DANBOORU_USERNAME=your_danbooru_username
DANBOORU_API_KEY=your_danbooru_api_key

# ==========================================
# DISCORD & CẤU HÌNH KHÁC
# ==========================================
DISCORD_TOKEN=your_discord_token_here
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DATABASE_REPO_URL=https://github.com/somefoxne/copyright_request_database.git
RE_ADD_POLICY=never
```

### Lệnh chạy:

1. **Quét bài đăng theo `data/checkfile.txt`**:
   ```bash
   # Chạy theo cấu hình TEST_MODE trong .env:
   python bot.py --scan

   # Ép buộc chạy trên Testbooru (kết nối testbooru.donmai.us):
   python bot.py --scan --test

   # Ép buộc chạy trên Danbooru thật:
   python bot.py --scan --live
   ```

2. **Lấy gợi ý copytags mới (category=copyright) và đẩy lên Git database**:
   ```bash
   python bot.py --update-db ookami_mio shirakami_fubuki tokino_sora
   ```

