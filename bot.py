import os
import sys
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

DANBOORU_HOST = os.getenv("DANBOORU_URL", "https://danbooru.donmai.us").rstrip("/")
USERNAME = os.getenv("DANBOORU_USERNAME", "")
API_KEY = os.getenv("DANBOORU_API_KEY", "")

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Chính sách mặc định khi tag bị xóa (never / số lượt edit)
DEFAULT_READD_POLICY = os.getenv("RE_ADD_POLICY", "never").strip().lower()

# 2 Kho Git riêng biệt:
# 1. Git bot: https://github.com/somefoxne/shino-imako.git
# 2. Git database: https://github.com/somefoxne/copyright_request_database.git
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

SESSION = requests.Session()
if USERNAME and API_KEY:
    SESSION.auth = (USERNAME, API_KEY)
SESSION.headers.update({"User-Agent": "ShinoImakoBot/2.0 (by somefoxne)"})


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
        resp = SESSION.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[-] Lỗi khi gọi related_tag cho '{chartag}': {resp.status_code}")
            return []

        data = resp.json()
        related_tags_raw = data.get("related_tags", [])
        
        # Fallback category=3 nếu cần
        if not related_tags_raw:
            params["category"] = "3"
            resp2 = SESSION.get(url, params=params, timeout=15)
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
        resp = SESSION.get(url, params=params, timeout=15)
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
        resp = SESSION.put(url, data=data, timeout=15)
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
        print("[!] Database chưa có công thức nào được duyệt! Hãy duyệt các dòng có dấu '?' trước.")
        return

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
            resp = SESSION.get(url, params=params, timeout=15)
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

                # 2. Đối chiếu với các công thức đã duyệt trong database
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
    import argparse
    parser = argparse.ArgumentParser(description="Danbooru Copytag Bot - Shino Imako")
    parser.add_argument("--scan", action="store_true", help="Quét bài đăng theo checkfile.txt và đối chiếu database đã duyệt")
    parser.add_argument("--update-db", nargs="+", help="Lấy related copyright tags cho chartag, ghi '?chartag -> ...' và push Git database")
    
    args = parser.parse_args()

    if args.update_db:
        update_database_pipeline(args.update_db)
    elif args.scan:
        scan_and_apply_copytags()
    else:
        parser.print_help()
