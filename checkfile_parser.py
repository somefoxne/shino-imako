from typing import List, Set, Dict, Any, Optional

class CheckScope:
    """
    Đại diện cho một phạm vi quét bài viết trong checkfile.txt.
    - Hỗ trợ toàn bộ cú pháp Danbooru Cheatsheet (id:..., pool:..., user:..., tag, -tag...)
    - Chỉ thị thông báo/duyệt:
        + Noti:discord  -> Gửi thông báo kết quả cập nhật vào Discord
        + Noti:ask      -> Hỏi người dùng trên Discord trước khi thêm
    - Chỉ thị Re-add / Chống edit-war:
        + readd:never   -> Không bao giờ add lại nếu từng bị xóa
        + readd:<số>    -> Chỉ add lại nếu đã qua ít nhất <số> lượt chỉnh sửa sau khi bị xóa
    """
    def __init__(self, raw_line: str):
        self.raw_line = raw_line.strip()
        self.notis: Set[str] = set()               # noti:discord, noti:ask
        self.readd_policy: Optional[str] = None    # never, 5, etc.
        self.danbooru_tags: List[str] = []
        self.is_all: bool = False

        self._parse(self.raw_line)

    def _parse(self, line: str):
        tokens = line.split()
        for token in tokens:
            token = token.strip()
            if not token:
                continue

            # Bỏ qua action: nếu có (vì bot chỉ chuyên làm 1 nhiệm vụ gán copytag)
            if token.lower().startswith("action:"):
                continue

            # Chỉ thị Noti: (Noti:discord, Noti:ask, ...)
            if token.lower().startswith("noti:"):
                noti_val = token[len("noti:"):].lower().strip()
                if noti_val:
                    self.notis.add(noti_val)
                continue

            # Chỉ thị readd: (readd:never, readd:5, ...)
            if token.lower().startswith("readd:"):
                self.readd_policy = token[len("readd:"):].lower().strip()
                continue

            # Cờ ALL (quét tổng thể bài viết mới)
            if token.upper() == "ALL":
                self.is_all = True
                continue

            # Tiền tố tag: (vd: tag:user:thefoxne -> user:thefoxne, hoặc tag:miku -> miku)
            if token.lower().startswith("tag:"):
                clean_tag = token[len("tag:"):].strip()
                if clean_tag:
                    self.danbooru_tags.append(clean_tag)
                continue

            # Các token còn lại là tag truy vấn Danbooru hợp lệ (id:..., pool:..., user:..., tag, -tag...)
            self.danbooru_tags.append(token)

    def build_danbooru_query(self) -> str:
        """Tạo chuỗi query gửi lên Danbooru API (?tags=...)"""
        return " ".join(self.danbooru_tags)

    def matches_post(self, post: Dict[str, Any]) -> bool:
        """
        Kiểm tra an toàn bổ sung ở phía client (đặc biệt các tag loại trừ có dấu trừ -).
        """
        post_tags = set(post.get("tag_string", "").split())
        uploader_name = str(post.get("uploader_name", "")).lower()

        for tag in self.danbooru_tags:
            # Kiểm tra tag loại trừ (bắt đầu bằng -)
            if tag.startswith("-"):
                neg = tag[1:]
                if neg.lower().startswith("user:"):
                    target_u = neg[len("user:"):].lower()
                    if uploader_name and uploader_name == target_u:
                        return False
                else:
                    if neg in post_tags:
                        return False

        return True

    def should_ask(self) -> bool:
        """Kiểm tra có yêu cầu duyệt trên Discord trước khi thêm không (Noti:ask)"""
        return "ask" in self.notis

    def should_notify_discord(self) -> bool:
        """Kiểm tra có yêu cầu gửi log lên Discord không (Noti:discord)"""
        return "discord" in self.notis

    def __repr__(self):
        return f"<CheckScope line='{self.raw_line}' query='{self.build_danbooru_query()}' notis={self.notis} readd={self.readd_policy}>"


def parse_checkfile(filepath: str) -> List[CheckScope]:
    """Đọc file checkfile.txt và trả về danh sách các CheckScope hợp lệ."""
    scopes = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            scopes.append(CheckScope(line))
    return scopes
