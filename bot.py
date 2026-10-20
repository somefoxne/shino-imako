import os
import sys
import time
import re
import json
import subprocess
import requests
from typing import Dict, List, Tuple, Optional, Any, Set



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
    url = DATABASE_REPO_URL.strip()
    github_token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GIT_TOKEN", "").strip()
    if github_token and url.startswith("https://") and "@" not in url:
        # Sử dụng tiền tố x-access-token chuẩn cho GitHub Personal Access Token
        url = url.replace("https://", f"https://x-access-token:{github_token}@")
    return url


def run_git_command(args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Chạy lệnh Git an toàn trong môi trường headless/VPS, không bị treo prompt terminal"""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env
    )


def configure_git_repo(repo_dir: str):
    """Cấu hình user.name, user.email, safe.directory và remote origin URL cho repository"""
    try:
        # Tránh lỗi 'dubious ownership' phổ biến trên Docker / Pterodactyl container (Vibe Host)
        run_git_command(["git", "config", "--global", "--add", "safe.directory", "*"])
        if os.path.exists(repo_dir):
            abs_repo_dir = os.path.abspath(repo_dir).replace("\\", "/")
            run_git_command(["git", "config", "--global", "--add", "safe.directory", abs_repo_dir])

        if os.path.exists(os.path.join(repo_dir, ".git")):
            run_git_command(["git", "-C", repo_dir, "config", "user.name", "Shino Imako Bot"])
            run_git_command(["git", "-C", repo_dir, "config", "user.email", "bot@shino-imako.local"])
            target_url = get_database_repo_url()
            run_git_command(["git", "-C", repo_dir, "remote", "set-url", "origin", target_url])
    except Exception as e:
        print(f"[!] Lỗi khi cấu hình Git repository: {e}")


def ensure_database_repo() -> str:
    """
    Đảm bảo repo database đã được clone và pull mới nhất.
    Trả về đường dẫn tới file database.txt
    """
    db_file_path = os.path.join(DATABASE_REPO_DIR, DATABASE_FILENAME)
    clone_url = get_database_repo_url()
    
    # Cấu hình safe.directory toàn cục
    run_git_command(["git", "config", "--global", "--add", "safe.directory", "*"])

    if not os.path.exists(DATABASE_REPO_DIR):
        print(f"[*] Thư mục repo database chưa tồn tại. Đang clone từ {DATABASE_REPO_URL}...")
        try:
            res = run_git_command(["git", "clone", clone_url, DATABASE_REPO_DIR])
            if res.returncode == 0:
                print("[+] Clone database repo thành công!")
                configure_git_repo(DATABASE_REPO_DIR)
            else:
                err = res.stderr.strip() or res.stdout.strip()
                print(f"[!] Không thể clone database repo: {err}")
                print(f"[*] Sẽ sử dụng file cục bộ '{DATABASE_FILENAME}' nếu có.")
                return DATABASE_FILENAME
        except Exception as e:
            print(f"[!] Không thể clone database repo: {e}")
            return DATABASE_FILENAME
    else:
        if os.path.exists(os.path.join(DATABASE_REPO_DIR, ".git")):
            configure_git_repo(DATABASE_REPO_DIR)
            print(f"[*] Đang đồng bộ (git pull) database từ {DATABASE_REPO_URL}...")
            try:
                # Sử dụng autostash và rebase để không mất các cập nhật cục bộ
                pull_res = run_git_command(["git", "-C", DATABASE_REPO_DIR, "pull", "--autostash", "--rebase", "origin", "main"])
                if pull_res.returncode == 0:
                    print("[+] Git pull database thành công!")
                else:
                    pull_res2 = run_git_command(["git", "-C", DATABASE_REPO_DIR, "pull"])
                    if pull_res2.returncode == 0:
                        print("[+] Git pull database thành công!")
                    else:
                        print(f"[!] Lỗi khi git pull database: {pull_res.stderr.strip() or pull_res2.stderr.strip()}")
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

    github_token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GIT_TOKEN", "").strip()
    if not github_token and DATABASE_REPO_URL.startswith("https://") and "@" not in DATABASE_REPO_URL:
        print("[!] CẢNH BÁO GIT PUSH: Bạn chưa cấu hình GITHUB_TOKEN trong file .env!")
        print("    -> GitHub yêu cầu xác thực để push code. Bot không thể push ẩn danh.")
        print("    -> Vui lòng tạo Personal Access Token tại https://github.com/settings/tokens (quyền 'repo')")
        print("    -> Sau đó thêm vào file .env: GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx")

    try:
        configure_git_repo(DATABASE_REPO_DIR)
        print(f"[*] Đang commit và push database: '{commit_message}'")
        run_git_command(["git", "-C", DATABASE_REPO_DIR, "add", DATABASE_FILENAME])

        diff_status = run_git_command(["git", "-C", DATABASE_REPO_DIR, "diff", "--cached", "--quiet"])
        if diff_status.returncode != 0:
            commit_res = run_git_command(
                ["git", "-C", DATABASE_REPO_DIR, "commit", "-m", commit_message]
            )
            if commit_res.returncode != 0:
                print(f"[!] Lỗi khi git commit: {commit_res.stderr.strip() or commit_res.stdout.strip()}")
                return

            # Tự động rebase từ remote trước khi push để tránh xung đột 'Updates were rejected'
            run_git_command(["git", "-C", DATABASE_REPO_DIR, "pull", "--rebase", "origin", "main"])

            push_res = run_git_command(
                ["git", "-C", DATABASE_REPO_DIR, "push", "origin", "main"]
            )
            if push_res.returncode == 0:
                print("[+] Git push database thành công!")
            else:
                push_res2 = run_git_command(
                    ["git", "-C", DATABASE_REPO_DIR, "push"]
                )
                if push_res2.returncode == 0:
                    print("[+] Git push database thành công!")
                else:
                    err_msg = push_res.stderr.strip() or push_res2.stderr.strip() or push_res.stdout.strip()
                    print(f"[!] Lỗi khi git push database: {err_msg}")
                    if "could not read Username" in err_msg or "Authentication failed" in err_msg or "Permission to" in err_msg:
                        print("    >> NGUYÊN NHÂN: Thiếu hoặc sai GITHUB_TOKEN. Hãy điền GITHUB_TOKEN=ghp_... vào .env.")
                    elif "rejected" in err_msg:
                        print("    >> NGUYÊN NHÂN: Remote có commit mới hơn. Bot đã thử rebase.")
        else:
            print("[-] Không có thay đổi nào trong database để commit.")
    except Exception as e:
        print(f"[!] Lỗi khi commit/push database: {e}")


# ==========================================
# ==========================================
# 2. XỬ LÝ ĐỌC/GHI FILE DATABASE & CƠ CHẾ DUYỆT
# ==========================================
def parse_database(filepath: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Đọc file database.txt và phân loại rõ ràng:
    1. approved_db: Dòng KHÔNG có dấu ? -> ĐÃ DUYỆT (chartag -> copytag)
       -> Chỉ các quy tắc này mới được bot dùng để tự động gán vào bài đăng.
    2. unapproved_db: Dòng CÓ dấu ? -> CHỜ DUYỆT (?chartag -> copytag1 copytag2 ...)
       -> Chứa các gợi ý do crawler cào về, chờ xem xét duyệt trước khi áp dụng.
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
                # Dòng chờ duyệt: ?chartag -> copytag1 copytag2 ...
                content = line[1:].strip()
                if "->" in content:
                    left, right = content.split("->", 1)
                    chartag = left.strip()
                    raw_tags = right.strip().split()
                    clean_tags = [t for t in raw_tags if not t.startswith("{") and not t.endswith("}") and "'" not in t]
                    if chartag and clean_tags:
                        unapproved_db[chartag] = clean_tags
            else:
                # Dòng đã duyệt: chartag -> copytag
                if "->" in line:
                    left, right = line.split("->", 1)
                    chartag = left.strip()
                    raw_tags = right.strip().split()
                    clean_tags = [t for t in raw_tags if not t.startswith("{") and not t.endswith("}") and "'" not in t]
                    if chartag and clean_tags:
                        approved_db[chartag] = clean_tags[0]

    return approved_db, unapproved_db


def parse_all_databases(repo_dir: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Đọc TẤT CẢ các file .txt trong thư mục repo database và gộp kết quả lại:
    - database.txt        : Bot tự ghi tag chờ duyệt (?chartag -> ...) vào đây.
    - Các file .txt khác  : File do người dùng tự đặt tên (ví dụ: hololive.txt, arknights.txt),
                            chứa các tag ĐÃ DUYỆT mà người dùng tự soạn sẵn.
    - Bot CHỈ ĐỌC từ các file tên khác (không bao giờ ghi đè/xóa nội dung chúng).
    - Nếu một chartag có trong nhiều file: dòng ĐÃ DUYỆT luôn được ưu tiên hơn CHƯA DUYỆT.
    """
    merged_approved: Dict[str, str] = {}
    merged_unapproved: Dict[str, List[str]] = {}

    if not os.path.isdir(repo_dir):
        db_file = os.path.join(repo_dir, DATABASE_FILENAME)
        return parse_database(db_file)

    txt_files = sorted([
        f for f in os.listdir(repo_dir)
        if f.endswith(".txt") and not f.startswith(".")
    ])

    if not txt_files:
        return merged_approved, merged_unapproved

    loaded_summary = []
    for filename in txt_files:
        filepath = os.path.join(repo_dir, filename)
        approved, unapproved = parse_database(filepath)
        # Gộp approved: ưu tiên file tên riêng (hololive.txt...) hơn database.txt
        for chartag, copytag in approved.items():
            if chartag not in merged_approved:
                merged_approved[chartag] = copytag
        # Gộp unapproved: chỉ thêm nếu chưa có trong approved của bất kỳ file nào
        for chartag, copytags in unapproved.items():
            if chartag not in merged_approved and chartag not in merged_unapproved:
                merged_unapproved[chartag] = copytags
        if approved or unapproved:
            loaded_summary.append(f"{filename}({len(approved)}\u2713 {len(unapproved)}?)")

    if loaded_summary:
        print(f"[*] Nạp database từ {len(txt_files)} file: {', '.join(loaded_summary)}")

    return merged_approved, merged_unapproved


def update_database_file(filepath: str, chartag: str, top_copytags: List[str], approved: bool = False):
    """
    Cập nhật hoặc thêm quy tắc nhân vật -> bản quyền vào file database.txt:
    - approved=False: ghi dạng chờ duyệt '?chartag -> copytag1 copytag2 ...'
    - approved=True : ghi dạng đã duyệt 'chartag -> copytag'
    """
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

    clean_copytags = [t for t in top_copytags if not t.startswith("{") and not t.endswith("}") and "'" not in t]
    if not clean_copytags:
        return

    if approved:
        new_entry = f"{chartag} -> {clean_copytags[0]}\n"
    else:
        new_entry = f"?{chartag} -> {' '.join(clean_copytags)}\n"

    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        core = stripped[1:].strip() if stripped.startswith("?") else stripped
        if core.startswith(f"{chartag} ->"):
            # Nếu dòng hiện tại đã duyệt và dòng mới là chưa duyệt -> Không ghi đè lùi
            if not stripped.startswith("?") and not approved:
                found = True
                break
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
    Mọi quy tắc cào tự động đều lưu dưới dạng CHỜ DUYỆT (?chartag -> copytags...) để người quản trị kiểm duyệt.
    """
    db_file_path = ensure_database_repo()
    approved_db, unapproved_db = parse_all_databases(DATABASE_REPO_DIR)
    existing_chartags = set(approved_db.keys()) | set(unapproved_db.keys())
    print(f"[*] Database hiện có: {len(approved_db)} đã duyệt, {len(unapproved_db)} chưa duyệt.")


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
                    print(f"    [{total_new_added + 1}] ?{ch} -> {' '.join(top_tags)}")
                    update_database_file(db_file_path, ch, top_tags, approved=False)
                    unapproved_db[ch] = top_tags
                    total_new_added += 1
                    batch_count += 1
                else:
                    print(f"    [-] Không tìm thấy copytag cho '{ch}'.")

                time.sleep(0.2)

                # Push Git theo từng batch
                if batch_count >= batch_push_size:
                    git_push_database(f"Auto-crawl add {batch_count} copyright candidates (Total: {len(existing_chartags)})")
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
        git_push_database(f"Auto-crawl add final {batch_count} copyright candidates (Total: {len(existing_chartags)})")

    print(f"\n[+] Hoàn tất! Đã thêm {total_new_added} nhân vật mới vào database và đẩy lên Git.")



# ==========================================
# 4. CHÍNH SÁCH RE-ADD & THÔNG BÁO DISCORD
# ==========================================
def check_readd_permission(post_id: int, copytag: str, policy: Optional[str] = None) -> Tuple[bool, str]:
    """
    Kiểm tra chính sách Re-add để chống chiến tranh tag (Edit-war):
    - policy: 'never' (mặc định), 'off'/'none' (tắt kiểm tra), hoặc một số nguyên (ví dụ '5' -> cần ít nhất 5 version kể từ lúc bị xóa).
    - Trả về (allowed, reason)
    """
    effective_policy = (policy or DEFAULT_READD_POLICY).lower().strip()
    if effective_policy in ("off", "none", "disable", "disabled", "false", "0"):
        return True, "Chính sách re-add đã tắt"

    url = f"{DANBOORU_HOST}/post_versions.json"
    params = {"search[post_id]": post_id, "limit": 100}

    try:
        resp = danbooru_api_request("GET", url, params=params)
        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                # Endpoint post_versions trên Danbooru bị giới hạn quyền đối với tài khoản thành viên thông thường.
                # Bỏ qua kiểm tra re-add để không làm tắc nghẽn quá trình gán tag của bot.
                return True, f"Bỏ qua kiểm tra re-add (HTTP {resp.status_code}: tài khoản không có quyền xem post_versions)"
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


def add_copytag_to_post(post_id: int, copytag: str, chartag: str, current_tags: Optional[Set[str]] = None) -> bool:
    """Thực hiện gọi API Danbooru thêm copytag vào post"""
    url = f"{DANBOORU_HOST}/posts/{post_id}.json"

    # Nếu chưa có current_tags, tự động lấy tags hiện tại của post từ Danbooru
    if current_tags is None:
        try:
            resp_post = danbooru_api_request("GET", url)
            if resp_post.status_code == 200:
                current_tags = set(resp_post.json().get("tag_string", "").split())
            else:
                current_tags = set()
        except Exception:
            current_tags = set()

    new_tags = sorted(list(current_tags | {copytag}))
    old_tags_str = " ".join(sorted(list(current_tags)))
    new_tags_str = " ".join(new_tags)

    # Danbooru Rails Strong Parameters chỉ cho phép: tag_string, old_tag_string
    # KHÔNG gửi tag_string_diff hay edit_reason vì sẽ bị lỗi UnpermittedParameters 403
    data = {
        "post[tag_string]": new_tags_str,
        "post[old_tag_string]": old_tags_str
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
MIN_POST_COUNT_FOR_AUTO_TAG = int(os.getenv("MIN_POST_COUNT_AUTO", "1000"))


def get_tag_post_count(chartag: str) -> int:
    """Tra cứu số lượng post của một tag trên Danbooru."""
    url = f"{DANBOORU_HOST}/tags.json"
    params = {"search[name]": chartag, "search[hide_empty]": "no"}
    try:
        resp = danbooru_api_request("GET", url, params=params)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get('post_count', 0)
    except Exception as e:
        print(f"[!] Lỗi khi lấy post_count cho '{chartag}': {e}")
    return 0


def scan_and_apply_copytags():
    """
    Quét bài đăng theo các rule trong data/checkfile.txt.

    LUỒNG XỬ LÝ KHI GẶP NHÂN VẬT:
    A) CÓ trong database (các file .txt trong repo copyright_request_database):
       - Gán copytag tương ứng vào post bình thường.
    B) CHƯA có trong database:
       - Kiểm tra post_count của character tag đó trên Danbooru.
       - Nếu post_count > MIN_POST_COUNT_AUTO (mặc định 1000):
           lấy top 1 related copyright tag rồi gán thẳng vào post.
       - Nếu post_count <= 1000: bỏ qua.
    """
    ensure_database_repo()
    approved_db, _ = parse_all_databases(DATABASE_REPO_DIR)

    print(f"[*] Đã tải {len(approved_db)} công thức ĐÃ DUYỆT từ database.")
    print(f"[*] Ngưỡng tự động: nhân vật chưa trong database xử lý nếu post_count > {MIN_POST_COUNT_FOR_AUTO_TAG}.")

    # Cache trong chu kỳ: chartag -> top1_copytag (hoặc None)
    _auto_cache: Dict[str, Optional[str]] = {}

    if not approved_db:
        print("[!] Database trống - Bot sẽ dùng chế độ tự động cho toàn bộ nhân vật.")

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

                # Nếu tag_string_character rỗng, tìm các tag trong post mà có trong approved_db
                if not character_tags:
                    character_tags = [t for t in current_tags if t in approved_db]

                for ch in character_tags:
                    # A. Nhân vật CÓ trong database đã duyệt
                    if ch in approved_db:
                        copytag = approved_db.get(ch)
                        if not copytag or copytag in current_tags:
                            continue
                        print(f"  [*] Post #{post_id}: '{ch}' thiếu bản quyền '{copytag}' (database).")

                    # B. Nhân vật CHƯA có trong database -> kiểm tra post_count rồi tự động gán
                    else:
                        if ch in _auto_cache:
                            copytag = _auto_cache[ch]
                            if not copytag or copytag in current_tags:
                                continue
                        else:
                            post_count = get_tag_post_count(ch)
                            if post_count <= MIN_POST_COUNT_FOR_AUTO_TAG:
                                _auto_cache[ch] = None
                                continue
                            top_tags = fetch_top_copyright_tags(ch, limit=1)
                            copytag = top_tags[0] if top_tags else None
                            _auto_cache[ch] = copytag
                            if not copytag:
                                print(f"  [-] Post #{post_id}: '{ch}' có {post_count} bài nhưng không tìm được copyright tag.")
                                continue
                            if copytag in current_tags:
                                continue
                            print(f"  [*] Post #{post_id}: '{ch}' ({post_count} bài) -> tự động gán '{copytag}'.")


                    # 5. Kiểm tra chính sách Re-add chống edit-war
                    allowed, reason = check_readd_permission(post_id, copytag, policy=scope.readd_policy)
                    if not allowed:
                        print(f"      [BỎ QUA] Post #{post_id} -> {reason}")
                        continue

                    # 6. Kiểm tra Noti:ask (nếu yêu cầu duyệt)
                    if scope.should_ask():
                        print(f"      [NOTI:ASK] Bỏ qua chờ duyệt trên Discord cho Post #{post_id}")
                        continue

                    # 7. Tiến hành thêm tag
                    print(f"      [THÊM TAG] Hợp lệ! Đang gắn '{copytag}' vào Post #{post_id}...")
                    success = add_copytag_to_post(post_id, copytag, ch, current_tags=current_tags)


                    # 8. Gửi thông báo Discord nếu có cờ Noti:discord
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


