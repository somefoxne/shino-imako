import os
import sys
import time
import re
import json
import subprocess
import requests
from typing import Dict, List, Tuple, Optional, Any


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from checkfile_parser import parse_checkfile, CheckScope

# ==========================================
# CẤU HÌNH & LOAD .ENV
# ==========================================
def load_dotenv(filepath: str = ".env"):
    """Tự động đọc cấu hình từ file .env nếu có"""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

load_dotenv()

# Discord & Re-add Policy
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DEFAULT_READD_POLICY = os.getenv("RE_ADD_POLICY", "never").strip().lower()

# 2 Kho Git riêng biệt:
DATABASE_REPO_URL = os.getenv(
    "DATABASE_REPO_URL", 
    "https://github.com/somefoxne/copyright_request_database.git"
)
DATABASE_REPO_DIR = os.getenv("DATABASE_REPO_DIR", "copyright_request_database")
DATABASE_FILENAME = "database.txt"

# File cấu hình phạm vi quét (checkfile.txt)
CHECKFILE_PATH = os.path.join("data", "checkfile.txt")
if not os.path.exists(CHECKFILE_PATH) and os.path.exists("checkfile.txt"):
    CHECKFILE_PATH = "checkfile.txt"

# Biến môi trường kết nối Danbooru / Testbooru
TEST_MODE = False
DANBOORU_HOST = "https://danbooru.donmai.us"
USERNAME = ""
API_KEY = ""

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ShinoImakoBot/2.0 (by somefoxne)"})

def configure_environment(test_mode_override: Optional[bool] = None):
    """
    Cấu hình chế độ hoạt động: Testbooru (TEST_MODE) hoặc Danbooru thật (PRODUCTION)
    """
    global TEST_MODE, DANBOORU_HOST, USERNAME, API_KEY, SESSION

    test_mode_env = os.getenv("TEST_MODE", "off").strip().lower() in ("true", "1", "yes", "on")
    if test_mode_override is not None:
        TEST_MODE = test_mode_override
    else:
        TEST_MODE = test_mode_env

    if TEST_MODE:
        DANBOORU_HOST = os.getenv("TESTBOORU_URL", "https://testbooru.donmai.us").rstrip("/")
        USERNAME = os.getenv("TESTBOORU_USERNAME", "") or os.getenv("DANBOORU_USERNAME", "")
        API_KEY = os.getenv("TESTBOORU_API_KEY", "") or os.getenv("DANBOORU_API_KEY", "")
        print(f"[!] CHẾ ĐỘ TEST_MODE: [BẬT/ON]")
        print(f"    -> Đang kết nối tới Testbooru: {DANBOORU_HOST}")
        print(f"    -> Username: {USERNAME or '(Chưa thiết lập)'}")
    else:
        DANBOORU_HOST = os.getenv("DANBOORU_URL", "https://danbooru.donmai.us").rstrip("/")
        USERNAME = os.getenv("DANBOORU_USERNAME", "")
        API_KEY = os.getenv("DANBOORU_API_KEY", "")
        print(f"[*] CHẾ ĐỘ PRODUCTION: [TẮT/OFF]")
        print(f"    -> Đang kết nối tới Danbooru: {DANBOORU_HOST}")
        print(f"    -> Username: {USERNAME or '(Chưa thiết lập)'}")

    SESSION.auth = None
    if USERNAME and API_KEY:
        SESSION.auth = (USERNAME, API_KEY)


def danbooru_api_request(method: str, url: str, **kwargs) -> requests.Response:
    """
    Gửi request lên Danbooru với cơ chế xử lý lỗi 401 thông minh:
    - Nếu trả về 401 Unauthorized:
        + Báo lỗi chi tiết và hướng dẫn kiểm tra API Key
        + Với GET requests (đọc tags, posts): Tự động thử lại không kèm auth (Public Read) để không bị chặn đọc dữ liệu
    """
    timeout = kwargs.pop("timeout", 15)
    resp = SESSION.request(method, url, timeout=timeout, **kwargs)

    if resp.status_code == 401:
        print(f"\n[!] LỖI HTTP 401 UNAUTHORIZED TỪ DANBOORU!")
        print(f"    URL: {url}")
        print(f"    Tài khoản trong .env: '{USERNAME or '(Rỗng)'}'")
        error_msg = resp.text.strip().replace("\n", " ")[:200]
        print(f"    Phản hồi từ server: {error_msg}")
        print(f"    >> LƯU Ý QUAN TRỌNG:")
        print(f"       1. Phải dùng API KEY (lấy tại {DANBOORU_HOST}/profile), KHÔNG ĐƯỢC dùng mật khẩu đăng nhập!")
        print(f"       2. Nếu bật TEST_MODE=on, tài khoản Danbooru thật sẽ KHÔNG hoạt động trên Testbooru (phải tạo tài khoản trên testbooru.donmai.us).")
        print(f"       3. Kiểm tra xem file .env có chứa ký tự hoặc khoảng trắng thừa không.\n")

        # Với GET request (đọc dữ liệu công khai): Tự động thử lại không kèm auth
        if method.upper() == "GET" and SESSION.auth:
            print("[*] Đang tự động thử lại request ở chế độ Khách công khai (không kèm auth)...")
            headers = dict(SESSION.headers)
            resp_public = requests.get(url, headers=headers, timeout=timeout, **kwargs)
            if resp_public.status_code == 200:
                print("[+] Thành công tải dữ liệu ở chế độ Khách công khai!")
                return resp_public
            return resp_public

    return resp




# ==========================================
# 1. QUẢN LÝ GIT CHO DATABASE REPO
# ==========================================
def ensure_database_repo() -> str:
    """
    Đảm bảo repo database đã được clone và pull mới nhất.
    Trả về đường dẫn tới file database.txt
    """
    db_file_path = os.path.join(DATABASE_REPO_DIR, DATABASE_FILENAME)
    
    if not os.path.exists(DATABASE_REPO_DIR):
        print(f"[*] Thư mục repo database chưa tồn tại. Đang clone từ {DATABASE_REPO_URL}...")
        try:
            subprocess.run(["git", "clone", DATABASE_REPO_URL, DATABASE_REPO_DIR], check=True)
            print("[+] Clone database repo thành công!")
        except Exception as e:
            print(f"[!] Không thể clone database repo: {e}")
            print(f"[*] Sẽ sử dụng file cục bộ '{DATABASE_FILENAME}' nếu có.")
            return DATABASE_FILENAME
    else:
        if os.path.exists(os.path.join(DATABASE_REPO_DIR, ".git")):
            print(f"[*] Đang đồng bộ (git pull) database từ {DATABASE_REPO_URL}...")
            try:
                subprocess.run(["git", "-C", DATABASE_REPO_DIR, "pull"], check=True)
                print("[+] Git pull database thành công!")
            except Exception as e:
                print(f"[!] Lỗi khi git pull database repo: {e}")

    if not os.path.exists(db_file_path):
        os.makedirs(DATABASE_REPO_DIR, exist_ok=True)
        with open(db_file_path, "w", encoding="utf-8") as f:
            f.write("# Copyright Request Database\n")
            f.write("# - Dòng đã duyệt: chartag -> copytag\n")
            f.write("# - Dòng chưa duyệt (có dấu ? ở đầu): ?chartag -> copytag1 copytag2 ...\n\n")

    return db_file_path


def git_push_database(commit_message: str):
    """
    Commit và push các thay đổi trong file database.txt lên git database repo
    """
    if not os.path.exists(os.path.join(DATABASE_REPO_DIR, ".git")):
        print("[-] Thư mục database không phải git repository, bỏ qua git push.")
        return

    try:
        print(f"[*] Đang commit và push database: '{commit_message}'")
        subprocess.run(["git", "-C", DATABASE_REPO_DIR, "add", DATABASE_FILENAME], check=True)
        diff_status = subprocess.run(["git", "-C", DATABASE_REPO_DIR, "diff", "--cached", "--quiet"])
        if diff_status.returncode != 0:
            subprocess.run(["git", "-C", DATABASE_REPO_DIR, "commit", "-m", commit_message], check=True)
            subprocess.run(["git", "-C", DATABASE_REPO_DIR, "push"], check=True)
            print("[+] Git push database thành công!")
        else:
            print("[-] Không có thay đổi nào trong database để commit.")
    except Exception as e:
        print(f"[!] Lỗi khi commit/push database: {e}")


# ==========================================
# 2. XỬ LÝ ĐỌC/GHI FILE DATABASE GỘP CHUNG
# ==========================================
def parse_database(filepath: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Đọc file database.txt và phân loại:
    1. approved_db: Dòng không có dấu ? -> ĐÃ DUYỆT (chartag -> copytag)
    2. unapproved_db: Dòng có dấu ? -> CHƯA DUYỆT (?chartag -> copytag1 copytag2 ...)
    """
    approved_db = {}
    unapproved_db = {}

    if not os.path.exists(filepath):
        return approved_db, unapproved_db

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("?"):
                # Dòng chưa duyệt: ?chartag -> copytag1 copytag2 ...
                content = line[1:].strip()
                if "->" in content:
                    left, right = content.split("->", 1)
                    chartag = left.strip()
                    copytags = right.strip().split()
                    if chartag:
                        unapproved_db[chartag] = copytags
            else:
                # Dòng đã duyệt: chartag -> copytag
                if "->" in line:
                    left, right = line.split("->", 1)
                    chartag = left.strip()
                    copytag = right.strip()
                    if chartag and copytag:
                        approved_db[chartag] = copytag

    return approved_db, unapproved_db


def update_database_file(filepath: str, chartag: str, top_copytags: List[str]):
    """
    Cập nhật hoặc thêm dòng chưa duyệt (?chartag -> copytag1 copytag2 ...)
    vào file database.txt mà không làm xáo trộn các dòng đã duyệt.
    """
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_entry = f"?{chartag} -> {' '.join(top_copytags)}\n"
    found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("?") and stripped[1:].strip().startswith(f"{chartag} ->"):
            lines[i] = new_entry
            found = True
            break

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_entry)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ==========================================
# 3. LẤY RELATED TAGS (CHỈ COPYRIGHT TAGS)
# ==========================================
def fetch_top_copyright_tags(chartag: str, limit: int = 10) -> List[str]:
    """
    Lấy danh sách related tags với category=copyright (Category 3 trên Danbooru).
    Endpoint: https://danbooru.donmai.us/related_tag.json?query=<chartag>&category=copyright
    """
    url = f"{DANBOORU_HOST}/related_tag.json"
    params = {
        "query": chartag,
        "category": "copyright"
    }

    try:
        resp = danbooru_api_request("GET", url, params=params)
        if resp.status_code != 200:
            print(f"[-] Lỗi khi gọi related_tag cho '{chartag}': {resp.status_code}")
            return []

        data = resp.json()
        related_tags_raw = data.get("related_tags", [])
        
        # Fallback category=3 nếu cần
        if not related_tags_raw:
            params["category"] = "3"
            resp2 = danbooru_api_request("GET", url, params=params)
            if resp2.status_code == 200:
                data = resp2.json()
                related_tags_raw = data.get("related_tags", [])


        copytags = []
        for item in related_tags_raw:
            if isinstance(item, list) and len(item) >= 1:
                tag_name = item[0]
            elif isinstance(item, dict) and "name" in item:
                tag_name = item["name"]
            else:
                tag_name = str(item)

            if tag_name and tag_name != chartag and tag_name not in copytags:
                copytags.append(tag_name)

            if len(copytags) >= limit:
                break

        return copytags

    except Exception as e:
        print(f"[!] Lỗi kết nối khi lấy related tag cho '{chartag}': {e}")
        return []


def update_database_pipeline(chartags: List[str]):
    """
    Đưa các chartag vào related_tag (category copyright),
    ghi vào database.txt dạng '?chartag -> copytags...' và tự động push Git database.
    """
    db_file_path = ensure_database_repo()
    print(f"[*] Đang lấy related copyright tags cho {len(chartags)} nhân vật...")

    updated_count = 0
    for chartag in chartags:
        print(f"[*] Đang truy vấn related copyright tags cho: '{chartag}'")
        top_tags = fetch_top_copyright_tags(chartag, limit=10)
        
        if top_tags:
            print(f"    -> Tìm thấy {len(top_tags)} copytags: {' '.join(top_tags)}")
            update_database_file(db_file_path, chartag, top_tags)
            updated_count += 1
        else:
            print(f"    -> Không tìm thấy related copyright tag nào cho '{chartag}'.")

    if updated_count > 0:
        commit_msg = f"Update unapproved copyright tags for: {', '.join(chartags[:3])}{'...' if len(chartags) > 3 else ''}"
        git_push_database(commit_msg)
        print(f"[+] Hoàn tất cập nhật và đẩy lên Git database!")
    else:
        print("[-] Không có dữ liệu mới để cập nhật.")


def fetch_character_tags_from_danbooru(
    max_pages: Optional[int] = None,
    limit_per_page: int = 100,
    delay: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Thu thập toàn bộ character tags từ Danbooru theo link:
    https://danbooru.donmai.us/tags?commit=Search&search%5Bcategory%5D=4&search%5Bhide_empty%5D=yes&search%5Border%5D=date
    Loại bỏ hoàn toàn:
    - is_deprecated == True
    - post_count <= 0
    """
    url = f"{DANBOORU_HOST}/tags.json"
    tags_collected = []
    page = 1
    last_id = None

    print(f"\n[*] Bắt đầu lấy character tags từ Danbooru (category=4, hide_empty=yes, order=date)...")

    while True:
        if max_pages and page > max_pages:
            print(f"[*] Đã đạt giới hạn tối đa {max_pages} trang.")
            break

        params = {
            "search[category]": "4",
            "search[hide_empty]": "yes",
            "search[is_deprecated]": "false",
            "search[order]": "date",
            "limit": str(limit_per_page),
        }

        # Dùng page=b<id> (before id) khi duyệt sâu để không bị giới hạn trang
        if last_id:
            params["page"] = f"b{last_id}"
        else:
            params["page"] = str(page)

        try:
            resp = danbooru_api_request("GET", url, params=params)
            if resp.status_code != 200:
                print(f"[-] Lỗi HTTP {resp.status_code} khi tải tags trang {page}")
                break


            tags_data = resp.json()
            if not tags_data or not isinstance(tags_data, list):
                print(f"[*] Đã duyệt hết danh sách tags tại trang {page}.")
                break

            valid_page_tags = []
            for t in tags_data:
                # Kiểm tra chặt chẽ: không lấy deprecated và không lấy 0 post
                is_dep = t.get("is_deprecated", False)
                post_cnt = t.get("post_count", 0)
                name = t.get("name", "")

                if is_dep or post_cnt <= 0 or not name:
                    continue

                valid_page_tags.append(t)

            tags_collected.extend(valid_page_tags)
            print(f"  + Trang {page}: Thu thập được {len(valid_page_tags)}/{len(tags_data)} tags hợp lệ (Tổng: {len(tags_collected)})")

            last_id = tags_data[-1].get("id")
            page += 1

            if len(tags_data) < limit_per_page:
                print("[*] Đã đến trang cuối cùng của Danbooru.")
                break

            time.sleep(delay)

        except Exception as e:
            print(f"[!] Lỗi khi cào tags trang {page}: {e}")
            break

    print(f"[+] Hoàn tất thu thập! Tổng cộng {len(tags_collected)} character tags hợp lệ.")
    return tags_collected


def crawl_and_update_database(max_tags: Optional[int] = None, max_pages: Optional[int] = None, batch_push_size: int = 20):
    """
    Thu thập character tags từ Danbooru -> lấy top 10 copyright tags -> lưu vào database.txt -> tự động push Git
    """
    db_file_path = ensure_database_repo()
    approved_db, unapproved_db = parse_database(db_file_path)

    existing_chartags = set(approved_db.keys()).union(set(unapproved_db.keys()))
    print(f"[*] Database hiện có: {len(approved_db)} đã duyệt, {len(unapproved_db)} chưa duyệt.")

    char_tags_info = fetch_character_tags_from_danbooru(max_pages=max_pages)
    if not char_tags_info:
        print("[-] Không thu thập được character tag nào từ Danbooru.")
        return

    new_chartags = [t["name"] for t in char_tags_info if t["name"] not in existing_chartags]
    if max_tags:
        new_chartags = new_chartags[:max_tags]

    print(f"[*] Tìm thấy {len(new_chartags)} character tags mới chưa có trong database.")

    if not new_chartags:
        print("[+] Toàn bộ character tags đã có trong database. Không cần cập nhật thêm!")
        return

    updated_count = 0
    batch_count = 0

    for idx, chartag in enumerate(new_chartags, 1):
        print(f"[{idx}/{len(new_chartags)}] Đang lấy related copyright tags cho '{chartag}'...")
        top_tags = fetch_top_copyright_tags(chartag, limit=10)

        if top_tags:
            print(f"    -> Top {len(top_tags)} copytags: {' '.join(top_tags)}")
            update_database_file(db_file_path, chartag, top_tags)
            updated_count += 1
            batch_count += 1
        else:
            print(f"    -> Không có related copyright tag nào cho '{chartag}'.")

        time.sleep(0.3)

        # Định kỳ push lên Git sau mỗi batch_push_size tags
        if batch_count >= batch_push_size:
            git_push_database(f"Auto add {batch_count} unapproved copyright rules (Total: {updated_count})")
            batch_count = 0

    if batch_count > 0:
        git_push_database(f"Auto add final {batch_count} unapproved copyright rules (Total: {updated_count})")

    print(f"\n[+] Hoàn tất! Đã thêm {updated_count} công thức mới vào database và đẩy lên Git.")



# ==========================================
# 4. CHÍNH SÁCH RE-ADD & THÔNG BÁO DISCORD
# ==========================================
def check_readd_permission(post_id: int, copytag: str, policy: Optional[str] = None) -> Tuple[bool, str]:
    """
    Kiểm tra chính sách Re-add để chống chiến tranh tag (Edit-war):
    - policy: 'never' (mặc định) hoặc một số nguyên (ví dụ '5' -> cần ít nhất 5 version kể từ lúc bị xóa).
    - Trả về (allowed, reason)
    """
    effective_policy = (policy or DEFAULT_READD_POLICY).lower().strip()
    url = f"{DANBOORU_HOST}/post_versions.json"
    params = {"search[post_id]": post_id, "limit": 100}

    try:
        resp = danbooru_api_request("GET", url, params=params)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code} khi kiểm tra post_versions"


        versions = resp.json()
        if not versions:
            return True, "Chưa có lịch sử versions, cho phép add"

        # Sắp xếp version mới nhất lên đầu
        versions = sorted(versions, key=lambda x: x.get("version", 0), reverse=True)
        latest_version = versions[0].get("version", 1)

        ever_had_tag = False
        last_version_with_tag = None

        for v in versions:
            tags = v.get("tags", "").split()
            v_num = v.get("version", 0)
            if copytag in tags:
                ever_had_tag = True
                if last_version_with_tag is None or v_num > last_version_with_tag:
                    last_version_with_tag = v_num

        # Nếu chưa từng có trong lịch sử -> Thoải mái thêm
        if not ever_had_tag:
            return True, "Chưa từng có tag trong lịch sử"

        # Nếu từng có nhưng đã bị xóa khỏi post hiện tại:
        if effective_policy == "never":
            return False, "Tag từng có và bị xóa; chính sách là 'readd:never'"

        # Nếu chính sách là số nguyên (ví dụ: readd:5)
        if effective_policy.isdigit():
            min_versions = int(effective_policy)
            # Khoảng cách giữa version hiện tại và version cuối cùng còn giữ tag
            version_diff = latest_version - (last_version_with_tag or latest_version)
            if version_diff >= min_versions:
                return True, f"Cho phép re-add sau {version_diff} versions (yêu cầu >= {min_versions})"
            else:
                return False, f"Chặn re-add: Mới qua {version_diff}/{min_versions} versions kể từ khi bị xóa"

        return False, f"Chính sách không hợp lệ ({effective_policy}), mặc định từ chối"

    except Exception as e:
        return False, f"Lỗi ngoại lệ khi kiểm tra history: {e}"


def send_discord_notification(post_id: int, chartag: str, copytag: str, post_data: Dict[str, Any]):
    """
    Gửi thông báo kết quả cập nhật lên Discord qua Webhook hoặc Bot Token
    """
    if not DISCORD_WEBHOOK_URL:
        return

    post_url = f"{DANBOORU_HOST}/posts/{post_id}"
    preview_url = post_data.get("preview_file_url") or post_data.get("large_file_url") or ""

    embed = {
        "title": f"🏷️ Đã gán Copytag vào Post #{post_id}",
        "url": post_url,
        "color": 3066993, # Xanh ngọc
        "fields": [
            {"name": "Nhân vật (Character)", "value": f"`{chartag}`", "inline": True},
            {"name": "Bản quyền (Copyright)", "value": f"`{copytag}`", "inline": True},
        ],
        "footer": {"text": "Shino Imako Copytag Bot"}
    }
    if preview_url:
        embed["thumbnail"] = {"url": preview_url}

    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        print(f"[!] Không thể gửi Discord Webhook: {e}")


def add_copytag_to_post(post_id: int, copytag: str, chartag: str) -> bool:
    """Thực hiện gọi API Danbooru thêm copytag vào post"""
    url = f"{DANBOORU_HOST}/posts/{post_id}.json"
    data = {
        "post[tag_string_diff]": f"+{copytag}",
        "post[edit_reason]": f"[Bot] Auto add copyright: {chartag} -> {copytag}"
    }

    try:
        resp = danbooru_api_request("PUT", url, data=data)
        if resp.status_code == 200:
            print(f"[+] Thành công thêm '{copytag}' vào post #{post_id}")
            return True
        else:
            print(f"[-] Thất bại khi thêm vào post #{post_id}. Mã lỗi: {resp.status_code}, Phản hồi: {resp.text[:200]}")
            return False

    except Exception as e:
        print(f"[!] Lỗi khi update post #{post_id}: {e}")
        return False


# ==========================================
# 5. CƠ CHẾ QUÉT THEO CHECKFILE (DANBOORU SCOPES)
# ==========================================
def scan_and_apply_copytags():
    """
    Quét theo checkfile.txt:
    1. Git pull database mới nhất
    2. Đọc các công thức ĐÃ DUYỆT (dòng không có '?')
    3. Phân tích các Scope từ checkfile.txt (hỗ trợ đầy đủ cú pháp Danbooru Cheatsheet, Noti, readd)
    4. Tìm bài đăng -> Kiểm tra loại trừ (-tag, -user) -> Kiểm tra Re-add policy -> Thêm tag
    """
    db_file_path = ensure_database_repo()
    approved_db, unapproved_db = parse_database(db_file_path)

    print(f"[*] Đã tải {len(approved_db)} công thức ĐÃ DUYỆT từ database.")
    print(f"[*] (Có {len(unapproved_db)} công thức CHƯA DUYỆT đang chờ kiểm tra).")

    if not approved_db:
        print("[!] Chú ý: Chưa có công thức nào được DUYỆT trong database (chỉ có công thức chờ duyệt hoặc database trống).")
        print("[*] Bot sẽ quét các bài đăng để phát hiện nhân vật mới và tự động cập nhật công thức chờ duyệt '?chartag' lên Git...")

    if not os.path.exists(CHECKFILE_PATH):
        print(f"[!] Không tìm thấy file {CHECKFILE_PATH}. Vui lòng tạo file này để chạy bot.")
        return

    scopes = parse_checkfile(CHECKFILE_PATH)
    if not scopes:
        print(f"[!] File {CHECKFILE_PATH} không có dòng scope hợp lệ nào.")
        return

    print(f"[*] Đã nạp {len(scopes)} phạm vi quét (scopes) từ {CHECKFILE_PATH}\n")

    for idx, scope in enumerate(scopes, 1):
        danbooru_query = scope.build_danbooru_query()
        print(f"[=== Scope #{idx} ===] Query: '{danbooru_query}'")
        print(f"  > Thông báo: {list(scope.notis) if scope.notis else 'Mặc định'}")
        print(f"  > Re-add policy: {scope.readd_policy or DEFAULT_READD_POLICY}")

        url = f"{DANBOORU_HOST}/posts.json"
        params = {"tags": danbooru_query, "limit": 50}

        try:
            resp = danbooru_api_request("GET", url, params=params)
            if resp.status_code != 200:
                print(f"[-] Lỗi truy vấn Danbooru cho query '{danbooru_query}': HTTP {resp.status_code}")
                continue


            posts = resp.json()
            print(f"  > Tìm thấy {len(posts)} bài đăng.")

            for post in posts:
                post_id = post.get("id")
                
                # 1. Kiểm tra an toàn bộ lọc loại trừ client-side (-tag, -user:...)
                if not scope.matches_post(post):
                    continue

                current_tags = post.get("tag_string", "").split()
                character_tags = post.get("tag_string_character", "").split()

                # 2. Tự động phát hiện character tags mới chưa có trong database
                for ch in character_tags:
                    if ch and ch not in approved_db and ch not in unapproved_db:
                        print(f"  [*] Post #{post_id}: Phát hiện character tag mới '{ch}' chưa có trong database.")
                        top_tags = fetch_top_copyright_tags(ch, limit=10)
                        if top_tags:
                            print(f"      -> Thêm gợi ý: ?{ch} -> {' '.join(top_tags)}")
                            update_database_file(db_file_path, ch, top_tags)
                            unapproved_db[ch] = top_tags
                            git_push_database(f"Auto-discover unapproved rule: ?{ch}")

                # 3. Đối chiếu với các công thức đã duyệt trong database
                for chartag, copytag in approved_db.items():
                    if chartag in current_tags:
                        # Đã có sẵn tag này trên bài đăng -> Bỏ qua
                        if copytag in current_tags:
                            continue

                        print(f"  [*] Post #{post_id} chứa '{chartag}' nhưng thiếu '{copytag}'.")


                        # 3. Kiểm tra chính sách Re-add chống edit-war
                        allowed, reason = check_readd_permission(post_id, copytag, policy=scope.readd_policy)
                        if not allowed:
                            print(f"      [BỎ QUA] Post #{post_id} -> {reason}")
                            continue

                        # 4. Kiểm tra Noti:ask (nếu yêu cầu duyệt)
                        if scope.should_ask():
                            print(f"      [NOTI:ASK] Bỏ qua chờ duyệt tự động cho Post #{post_id}")
                            continue

                        # 5. Tiến hành thêm tag
                        print(f"      [THÊM TAG] Hợp lệ! Đang gắn '{copytag}' vào Post #{post_id}...")
                        success = add_copytag_to_post(post_id, copytag, chartag)

                        # 6. Gửi thông báo Discord nếu có cờ Noti:discord
                        if success and scope.should_notify_discord():
                            send_discord_notification(post_id, chartag, copytag, post)

        except Exception as e:
            print(f"[!] Lỗi khi xử lý scope #{idx}: {e}")


# ==========================================
# CLI ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    import main
    main.main()


