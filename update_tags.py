#!/usr/bin/env python3
"""
Lệnh cập nhật tag nhân vật cụ thể vào Git database (Cách 2).
Khi cần sử dụng, bạn có thể:
  1. Điền danh sách nhân vật vào biến UPDATE_DB_TAGS trong .env rồi chạy:
     python update_tags.py

  2. Hoặc truyền trực tiếp tên nhân vật qua dòng lệnh:
     python update_tags.py shirakami_fubuki usada_pekora
"""
import os
import sys
import bot


def main():
    bot.configure_environment()

    tags = sys.argv[1:]
    if not tags:
        env_tags = os.getenv("UPDATE_DB_TAGS", "").strip()
        if env_tags:
            tags = env_tags.split()

    if not tags:
        print("\n" + "=" * 65)
        print(" DANBOORU COPYTAG BOT - CẬP NHẬT TAG THỦ CÔNG (CÁCH 2)")
        print("=" * 65)
        print("[!] Không tìm thấy tag nhân vật nào để cập nhật.")
        print("[*] Hướng dẫn sử dụng khi cần dùng:")
        print("    1. Điền vào file .env:")
        print("       UPDATE_DB_TAGS=ten_nhan_vat_1 ten_nhan_vat_2")
        print("       Sau đó chạy: python update_tags.py")
        print("    2. Hoặc truyền trực tiếp qua dòng lệnh:")
        print("       python update_tags.py ten_nhan_vat_1 ten_nhan_vat_2")
        print("=" * 65 + "\n")
        return

    print(f"\n[*] Đang cập nhật {len(tags)} tag nhân vật: {', '.join(tags)}")
    bot.update_database_pipeline(tags)


if __name__ == "__main__":
    main()
