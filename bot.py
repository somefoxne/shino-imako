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
def get_database_repo_url() -> str:
    """Trả về URL repo database, tự động nhúng GITHUB_TOKEN nếu có cấu hình trong .env"""
    url = DATABASE_REPO_URL
    github_token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GIT_TOKEN", "").strip()
    if github_token and url.startswith("https://") and "@" not in url:
        url = url.replace("https://", f"https://{github_token}@")
    return url


def configure_git_repo(repo_dir: str):
    """Cấu hình user.name, user.email và remote origin URL cho repository"""
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        return
    try:
        subprocess.run(["git", "-C", repo_dir, "config", "user.name", "Shino Imako Bot"], check=False)
        subprocess.run(["git", "-C", repo_dir, "config", "user.email", "bot@shino-imako.local"], check=False)
        target_url = get_database_repo_url()
        subprocess.run(["git", "-C", repo_dir, "remote", "set-url", "origin", target_url], check=False)
    except Exception:
        pass


def ensure_database_repo() -> str:
    """
    Đảm bảo repo database đã được clone và pull mới nhất.
    Trả về đường dẫn tới file database.txt
    """
    db_file_path = os.path.join(DATABASE_REPO_DIR, DATABASE_FILENAME)
    clone_url = get_database_repo_url()
    
    if not os.path.exists(DATABASE_REPO_DIR):
        print(f"[*] Thư mục repo database chưa tồn tại. Đang clone từ {DATABASE_REPO_URL}...")
        try:
            subprocess.run(["git", "clone", clone_url, DATABASE_REPO_DIR], check=True)
            print("[+] Clone database repo thành công!")
            configure_git_repo(DATABASE_REPO_DIR)
        except Exception as e:
            print(f"[!] Không thể clone database repo: {e}")
            print(f"[*] Sẽ sử dụng file cục bộ '{DATABASE_FILENAME}' nếu có.")
            return DATABASE_FILENAME
    else:
        if os.path.exists(os.path.join(DATABASE_REPO_DIR, ".git")):
            configure_git_repo(DATABASE_REPO_DIR)
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
        configure_git_repo(DATABASE_REPO_DIR)
        print(f"[*] Đang commit và push database: '{commit_message}'")
        subprocess.run(["git", "-C", DATABASE_REPO_DIR, "add", DATABASE_FILENAME], check=True)
        diff_status = subprocess.run(["git", "-C", DATABASE_REPO_DIR, "diff", "--cached", "--quiet"])
        if diff_status.returncode != 0:
            commit_res = subprocess.run(
                ["git", "-C", DATABASE_REPO_DIR, "commit", "-m", commit_message],
                capture_output=True, text=True
            )
            if commit_res.returncode != 0:
                print(f"[!] Lỗi khi git commit: {commit_res.stderr.strip()}")
                return

            push_res = subprocess.run(
                ["git", "-C", DATABASE_REPO_DIR, "push", "origin", "main"],
                capture_output=True, text=True
            )
            if push_res.returncode == 0:
                print("[+] Git push database thành công!")
            else:
                push_res2 = subprocess.run(
                    ["git", "-C", DATABASE_REPO_DIR, "push"],
                    capture_output=True, text=True
                )
                if push_res2.returncode == 0:
                    print("[+] Git push database thành công!")
                else:
                    err_msg = push_res.stderr.strip() or push_res2.stderr.strip()
                    print(f"[!] Lỗi khi git push database: {err_msg}")
                    print(f"    >> GỢI Ý: Nếu dùng HTTPS trên VPS, hãy thêm GITHUB_TOKEN=ghp_... vào file .env để tự động cấp quyền push.")
        else:
            print("[-] Không có thay đổi nào trong database để commit.")
    except Exception as e:
        print(f"[!] Lỗi khi commit/push database: {e}")


# ==========================================
# 2. XỬ LÝ ĐỌC/GHI FILE DATABASE
# ==========================================
def parse_database(filepath: str) -> Dict[str, str]:
    """
    Đọc file database.txt và trả về từ điển ánh xạ:
    chartag -> primary_copytag (tag bản quyền đầu tiên/chính xác nhất)
    Hỗ trợ cả dòng có hoặc không có dấu '?' ở đầu:
      - chartag -> copytag1 copytag2 ...
      - ?chartag -> copytag1 copytag2 ...
    """
    db = {}
    if not os.path.exists(filepath):
        return db

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Tự động bỏ qua dấu '?' nếu có ở đầu dòng
            if line.startswith("?"):
                line = line[1:].strip()

            if "->" in line:
                left, right = line.split("->", 1)
                chartag = left.strip()
                # Lọc sạch khoảng trắng và bỏ các token hỏng dạng dict nếu có
                raw_tags = right.strip().split()
                clean_tags = [t for t in raw_tags if not t.startswith("{") and not t.endswith("}") and "'" not in t]
                if chartag and clean_tags:
                    # Tag bản quyền đầu tiên là tag chính
                    db[chartag] = clean_tags[0]

    return db


def update_database_file(filepath: str, chartag: str, top_copytags: List[str]):
    """
    Cập nhật hoặc thêm quy tắc nhân vật -> bản quyền vào file database.txt:
    chartag -> copytag
    """
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

    clean_copytags = [t for t in top_copytags if not t.startswith("{") and not t.endswith("}") and "'" not in t]
    if not clean_copytags:
        return

    # Lấy tag bản quyền hàng đầu chính xác nhất
    primary_copytag = clean_copytags[0]
    new_entry = f"{chartag} -> {primary_copytag}\n"
    found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("?"):
            stripped = stripped[1:].strip()
        if stripped.startswith(f"{chartag} ->"):
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
                data2 = resp2.json()
                related_tags_raw = data2.get("related_tags", [])

        copytags = []
        for item in related_tags_raw:
            tag_name = ""
            is_dep = False
            cat = None

            if isinstance(item, dict):
                # Format Danbooru mới: {'tag': {'name': '...', 'category': 3, 'is_deprecated': False}, 'cosine_similarity': ...}
                if "tag" in item and isinstance(item["tag"], dict):
                    t_info = item["tag"]
                    tag_name = t_info.get("name", "")
                    is_dep = t_info.get("is_deprecated", False)
                    cat = t_info.get("category")
                elif "name" in item:
                    tag_name = item.get("name", "")
                    is_dep = item.get("is_deprecated", False)
                    cat = item.get("category")
            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                tag_name = str(item[0])
            elif isinstance(item, str):
                tag_name = item

            tag_name = str(tag_name).strip()

            # Bỏ qua nếu rỗng, hoặc là tag bị deprecated
            if not tag_name or is_dep:
                continue

            # Đảm bảo là category 3 (copyright) nếu API trả về trường category
            if cat is not None and cat not in (3, "3", "copyright"):
                continue

            # Bỏ qua nếu trùng với chính character tag hoặc đã tồn tại trong danh sách
            if tag_name != chartag and tag_name not in copytags:
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


def crawl_and_update_database(max_tags: Optional[int] = None, max_pages: Optional[int] = None, batch_push_size: int = 50):
    """
    Thu thập character tags từ Danbooru KHÔNG GIỚI HẠN:
    Duyệt qua tất cả các trang -> lấy related copyright tags -> lưu vào database.txt -> tự động push Git theo từng batch.
    """
    db_file_path = ensure_database_repo()
    existing_db = parse_database(db_file_path)
    existing_chartags = set(existing_db.keys())
    print(f"[*] Database hiện có: {len(existing_chartags)} nhân vật đã nạp.")

    url = f"{DANBOORU_HOST}/tags.json"
    page = 1
    last_id = None
    total_new_added = 0
    batch_count = 0

    print(f"\n[*] Bắt đầu cào character tags từ Danbooru (category=4, hide_empty=yes, order=date)...")
    if max_pages or max_tags:
        print(f"    (Giới hạn: max_pages={max_pages}, max_tags={max_tags})")
    else:
        print(f"    (Chế độ: CÀO TOÀN BỘ KHÔNG GIỚI HẠN)")

    while True:
        if max_pages and page > max_pages:
            print(f"[*] Đã đạt giới hạn tối đa {max_pages} trang.")
            break

        params = {
            "search[category]": "4",
            "search[hide_empty]": "yes",
            "search[is_deprecated]": "false",
            "search[order]": "date",
            "limit": "100",
        }
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
                print(f"[*] Đã duyệt hết danh sách character tags của Danbooru.")
                break

            # Lọc các character tag hợp lệ và chưa có trong database
            page_new_tags = []
            for t in tags_data:
                name = t.get("name", "")
                is_dep = t.get("is_deprecated", False)
                post_cnt = t.get("post_count", 0)

                if is_dep or post_cnt <= 0 or not name:
                    continue
                if name not in existing_chartags:
                    page_new_tags.append(name)
                    existing_chartags.add(name)

            print(f"  + Trang {page}: Tìm thấy {len(page_new_tags)}/{len(tags_data)} nhân vật mới chưa có trong database.")

            # Lấy related copyright tags cho từng nhân vật mới
            for ch in page_new_tags:
                top_tags = fetch_top_copyright_tags(ch, limit=10)
                if top_tags:
                    print(f"    [{total_new_added + 1}] {ch} -> {' '.join(top_tags)}")
                    update_database_file(db_file_path, ch, top_tags)
                    total_new_added += 1
                    batch_count += 1
                else:
                    print(f"    [-] Không tìm thấy copytag cho '{ch}'.")

                time.sleep(0.2)

                # Push Git theo từng batch
                if batch_count >= batch_push_size:
                    git_push_database(f"Auto-crawl add {batch_count} copyright rules (Total: {len(existing_chartags)})")
                    batch_count = 0

                if max_tags and total_new_added >= max_tags:
                    print(f"[*] Đã đạt giới hạn tối đa {max_tags} tags mới.")
                    break

            if max_tags and total_new_added >= max_tags:
                break

            last_id = tags_data[-1].get("id")
            page += 1

            if len(tags_data) < 100:
                print("[*] Đã đến trang cuối cùng của Danbooru.")
                break

            time.sleep(0.3)

        except Exception as e:
            print(f"[!] Lỗi khi cào dữ liệu trang {page}: {e}")
            break

    # Push phần còn lại nếu có
    if batch_count > 0:
        git_push_database(f"Auto-crawl add final {batch_count} copyright rules (Total: {len(existing_chartags)})")

    print(f"\n[+] Hoàn tất! Đã thêm {total_new_added} nhân vật mới vào database và đẩy lên Git.")



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
# 5. CƠ CHẾ QUÉT THEO CHECKFILE (DANBOORU SCOPES / RULES)
# ==========================================
def scan_and_apply_copytags():
    """
    Quét bài đăng theo các rule trong data/checkfile.txt:
    - Rule (trong checkfile.txt): dùng để giới hạn bot không quét các post chưa cần quét.
    - Database (trong copyright_request_database): từ điển ánh xạ chartag -> copytag.
    Đối với mỗi post thỏa mãn rule:
    Kiểm tra xem post có nhân vật nào thiếu copytag không, nếu thiếu thì tự động thêm.
    """
    db_file_path = ensure_database_repo()
    db = parse_database(db_file_path)

    print(f"[*] Đã tải {len(db)} quy tắc nhân vật -> bản quyền từ database.")

    if not os.path.exists(CHECKFILE_PATH):
        print(f"[!] Không tìm thấy file {CHECKFILE_PATH}. Vui lòng tạo file này để chạy bot.")
        return

    scopes = parse_checkfile(CHECKFILE_PATH)
    if not scopes:
        print(f"[!] File {CHECKFILE_PATH} không có dòng rule nào.")
        print(f"    >> GỢI Ý: Thêm các query vào {CHECKFILE_PATH} để giới hạn các post cần quét (ví dụ: pool:any, ookami_mio -hololive, rating:g...)")
        return

    print(f"[*] Đã nạp {len(scopes)} phạm vi quét (rules) từ {CHECKFILE_PATH}\n")

    for idx, scope in enumerate(scopes, 1):
        danbooru_query = scope.build_danbooru_query()
        print(f"[=== Rule #{idx} ===] Query: '{danbooru_query or 'Mặc định (ALL)'}'")
        print(f"  > Thông báo: {list(scope.notis) if scope.notis else 'Mặc định'}")
        print(f"  > Re-add policy: {scope.readd_policy or DEFAULT_READD_POLICY}")

        url = f"{DANBOORU_HOST}/posts.json"
        params = {"limit": 50}
        if danbooru_query:
            params["tags"] = danbooru_query

        try:
            resp = danbooru_api_request("GET", url, params=params)
            if resp.status_code != 200:
                print(f"[-] Lỗi truy vấn Danbooru cho query '{danbooru_query}': HTTP {resp.status_code}")
                continue

            posts = resp.json()
            if not isinstance(posts, list):
                print(f"[-] Dữ liệu trả về không phải danh sách bài đăng.")
                continue

            print(f"  > Tìm thấy {len(posts)} bài đăng.")

            for post in posts:
                post_id = post.get("id")
                if not post_id:
                    continue

                # 1. Kiểm tra an toàn bộ lọc loại trừ client-side (-tag, -user:...)
                if not scope.matches_post(post):
                    continue

                current_tags = set(post.get("tag_string", "").split())
                char_tag_string = post.get("tag_string_character", "")
                character_tags = char_tag_string.split() if char_tag_string else []

                # Nếu tag_string_character rỗng, tìm các tag trong post mà có trong db
                if not character_tags:
                    character_tags = [t for t in current_tags if t in db]

                for ch in character_tags:
                    # 2. Nếu nhân vật này chưa có trong database -> Tự động tìm copytag và cập nhật database
                    if ch not in db:
                        print(f"  [*] Post #{post_id}: Phát hiện character tag '{ch}' chưa có trong database.")
                        top_tags = fetch_top_copyright_tags(ch, limit=10)
                        if top_tags:
                            copytag = top_tags[0]
                            db[ch] = copytag
                            update_database_file(db_file_path, ch, top_tags)
                            print(f"      -> Tự động lưu database: {ch} -> {copytag}")
                            git_push_database(f"Auto-add copyright mapping: {ch} -> {copytag}")
                        else:
                            continue

                    copytag = db.get(ch)
                    if not copytag:
                        continue

                    # 3. Kiểm tra bài đăng có thiếu copytag không
                    if copytag in current_tags:
                        continue

                    print(f"  [*] Post #{post_id} chứa nhân vật '{ch}' nhưng thiếu bản quyền '{copytag}'.")

                    # 4. Kiểm tra chính sách Re-add chống edit-war
                    allowed, reason = check_readd_permission(post_id, copytag, policy=scope.readd_policy)
                    if not allowed:
                        print(f"      [BỎ QUA] Post #{post_id} -> {reason}")
                        continue

                    # 5. Kiểm tra Noti:ask (nếu yêu cầu duyệt)
                    if scope.should_ask():
                        print(f"      [NOTI:ASK] Bỏ qua chờ duyệt trên Discord cho Post #{post_id}")
                        continue

                    # 6. Tiến hành thêm tag
                    print(f"      [THÊM TAG] Hợp lệ! Đang gắn '{copytag}' vào Post #{post_id}...")
                    success = add_copytag_to_post(post_id, copytag, ch)

                    # 7. Gửi thông báo Discord nếu có cờ Noti:discord
                    if success:
                        current_tags.add(copytag)
                        if scope.should_notify_discord():
                            send_discord_notification(post_id, ch, copytag, post)

        except Exception as e:
            print(f"[!] Lỗi khi xử lý Rule #{idx}: {e}")


# ==========================================
# CLI ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    import main
    main.main()


