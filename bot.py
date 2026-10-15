import os
import re
import json
import subprocess
import requests
from typing import Dict, List, Tuple, Optional

# ==========================================
# CẤU HÌNH (CONFIGURATION)
# ==========================================
DANBOORU_HOST = "https://danbooru.donmai.us"
USERNAME = os.getenv("DANBOORU_USERNAME", "")
API_KEY = os.getenv("DANBOORU_API_KEY", "")

# 2 Kho Git riêng biệt:
# 1. Git bot: https://github.com/somefoxne/shino-imako.git
# 2. Git database: https://github.com/somefoxne/copyright_request_database.git
DATABASE_REPO_URL = os.getenv(
    "DATABASE_REPO_URL", 
    "https://github.com/somefoxne/copyright_request_database.git"
)
# Thư mục lưu repo database (được clone/pull về máy để bot đọc và cập nhật)
DATABASE_REPO_DIR = os.getenv("DATABASE_REPO_DIR", "copyright_request_database")
DATABASE_FILENAME = "database.txt"

# File rules nằm ở repo bot
RULES_FILE = "rules.txt"

SESSION = requests.Session()
if USERNAME and API_KEY:
    SESSION.auth = (USERNAME, API_KEY)
SESSION.headers.update({"User-Agent": "ShinoImakoBot/1.0 (by somefoxne)"})


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
        # Nếu đã tồn tại thư mục git, tự động git pull để cập nhật dữ liệu mới nhất
        if os.path.exists(os.path.join(DATABASE_REPO_DIR, ".git")):
            print(f"[*] Đang đồng bộ (git pull) database từ {DATABASE_REPO_URL}...")
            try:
                subprocess.run(["git", "-C", DATABASE_REPO_DIR, "pull"], check=True)
                print("[+] Git pull database thành công!")
            except Exception as e:
                print(f"[!] Lỗi khi git pull database repo: {e}")

    # Nếu file chưa tồn tại trong repo, tạo file mẫu
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

    target_pattern = f"?{chartag} ->"
    new_entry = f"?{chartag} -> {' '.join(top_copytags)}\n"
    found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Nếu đã có dòng chưa duyệt của chartag này -> ghi đè cập nhật
        if stripped.startswith("?") and stripped[1:].strip().startswith(f"{chartag} ->"):
            lines[i] = new_entry
            found = True
            break

    if not found:
        # Nếu chưa có -> thêm vào cuối file
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_entry)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


def load_rules(filepath: str = RULES_FILE) -> List[str]:
    """
    Đọc rule file chứa danh sách query cần quét
    """
    rules = []
    if not os.path.exists(filepath):
        return rules
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                rules.append(line)
    return rules


# ==========================================
# 3. LẤY RELATED TAGS (CHỈ COPYRIGHT TAGS)
# ==========================================
def fetch_top_copyright_tags(chartag: str, limit: int = 10) -> List[str]:
    """
    Lấy danh sách related tags với category=copyright (Category 3 trên Danbooru).
    Đảm bảo kết quả trả về 100% là copytag (không lẫn artist, general, character tags).
    Endpoint: https://danbooru.donmai.us/related_tag.json?query=<chartag>&category=copyright
    """
    url = f"{DANBOORU_HOST}/related_tag.json"
    
    # Danbooru API hỗ trợ category='copyright' (hoặc category=3)
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
        
        # Nếu Danbooru trả về rỗng theo param 'copyright', thử fallback param category=3
        if not related_tags_raw:
            params["category"] = "3"
            resp2 = SESSION.get(url, params=params, timeout=15)
            if resp2.status_code == 200:
                data = resp2.json()
                related_tags_raw = data.get("related_tags", [])

        copytags = []
        for item in related_tags_raw:
            # Item có thể là [tag_name, score] hoặc dict
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
    Đưa các chartag vào related_tag (chỉ lấy category copyright, tối đa top 10)
    Ghi vào file database.txt dạng '?chartag -> copytag1 copytag2 ...'
    Sau đó tự động commit & push lên Git repository database.
    """
    db_file_path = ensure_database_repo()
    print(f"[*] Đang thực hiện lấy related copyright tags cho {len(chartags)} nhân vật...")

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
# 4. QUÉT POSTS & TỰ ĐỘNG GẮN COPYTAG
# ==========================================
def has_copytag_ever_been_added(post_id: int, copytag: str) -> bool:
    """
    Kiểm tra lịch sử post_versions xem copytag đã từng được thêm lần nào chưa.
    Nếu đã từng có trong lịch sử (kể cả sau đó bị xóa) -> Trả về True (không add lại).
    Endpoint: https://danbooru.donmai.us/post_versions.json?search[post_id]=<ID>
    """
    url = f"{DANBOORU_HOST}/post_versions.json"
    params = {"search[post_id]": post_id, "limit": 100}

    try:
        resp = SESSION.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[-] Lỗi check post_versions cho post #{post_id}: HTTP {resp.status_code}")
            return True  # An toàn: nếu không check được thì coi như đã add để tránh duplicate edit

        versions = resp.json()
        for v in versions:
            added_tags = v.get("added_tags", [])
            if copytag in added_tags:
                return True
            tags_str = v.get("tags", "")
            if copytag in tags_str.split():
                return True

        return False
    except Exception as e:
        print(f"[!] Lỗi khi gọi post_versions cho post #{post_id}: {e}")
        return True


def add_copytag_to_post(post_id: int, copytag: str, chartag: str) -> bool:
    """
    Thực hiện thêm copytag vào post qua Danbooru API:
    PUT /posts/<post_id>.json
    post[tag_string_diff]=+<copytag>
    """
    url = f"{DANBOORU_HOST}/posts/{post_id}.json"
    data = {
        "post[tag_string_diff]": f"+{copytag}",
        "post[edit_reason]": f"Auto add copytag: {chartag} -> {copytag}"
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


def scan_and_apply_copytags():
    """
    Cơ chế quét:
    1. Pull git database mới nhất
    2. Đọc các công thức ĐÃ DUYỆT (dòng không có '?') từ database.txt
    3. Đọc rule file (rules.txt)
    4. Tìm bài đăng -> kiểm tra lịch sử -> thêm nếu chưa từng add lần nào
    """
    db_file_path = ensure_database_repo()
    approved_db, unapproved_db = parse_database(db_file_path)
    rules = load_rules()

    print(f"[*] Đã tải {len(approved_db)} công thức ĐÃ DUYỆT từ database.")
    print(f"[*] (Có {len(unapproved_db)} công thức CHƯA DUYỆT đang chờ kiểm tra).")

    if not approved_db:
        print("[!] Không có công thức đã duyệt nào trong database. Vui lòng duyệt các dòng có '?' trước!")
        return

    if not rules:
        print("[!] File rules.txt trống. Vui lòng thêm các tag/query cần quét vào rules.txt!")
        return

    print(f"[*] Bắt đầu quét {len(rules)} rule(s)...")

    for rule in rules:
        print(f"\n[===] Đang quét rule: '{rule}'")
        url = f"{DANBOORU_HOST}/posts.json"
        params = {"tags": rule, "limit": 50}

        try:
            resp = SESSION.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"[-] Lỗi query Danbooru cho rule '{rule}': {resp.status_code}")
                continue

            posts = resp.json()
            print(f"[*] Tìm thấy {len(posts)} bài đăng.")

            for post in posts:
                post_id = post.get("id")
                current_tags = post.get("tag_string", "").split()

                # Đối chiếu với danh sách đã duyệt (chartag -> copytag)
                for chartag, copytag in approved_db.items():
                    if chartag in current_tags:
                        # Nếu post hiện tại đã có copytag này rồi -> bỏ qua
                        if copytag in current_tags:
                            continue

                        print(f"[*] Post #{post_id} có '{chartag}' nhưng thiếu '{copytag}'. Đang kiểm tra lịch sử...")
                        if has_copytag_ever_been_added(post_id, copytag):
                            print(f"    -> [Bỏ qua] Post #{post_id} đã từng có/từng được add '{copytag}' trước đây.")
                        else:
                            print(f"    -> [Thêm] Chưa từng add lần nào. Tiến hành thêm '{copytag}'...")
                            add_copytag_to_post(post_id, copytag, chartag)

        except Exception as e:
            print(f"[!] Lỗi khi quét rule '{rule}': {e}")


# ==========================================
# CLI ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Danbooru Copytag Bot - Shino Imako")
    parser.add_argument("--scan", action="store_true", help="Quét bài đăng theo rules và đối chiếu database đã duyệt")
    parser.add_argument("--update-db", nargs="+", help="Lấy related copyright tags cho chartag, ghi '?chartag -> ...' và push Git database")
    
    args = parser.parse_args()

    if args.update_db:
        update_database_pipeline(args.update_db)
    elif args.scan:
        scan_and_apply_copytags()
    else:
        parser.print_help()
