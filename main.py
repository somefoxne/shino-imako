import os
import sys
import time
import argparse
from typing import Optional

# Import toàn bộ logic từ bot.py
import bot

# ==========================================
# CẤU HÌNH VÒNG LẶP 24/7 CHO VIBE HOST / VPS
# ==========================================
RUN_LOOP_ENV = os.getenv("RUN_LOOP", "true").strip().lower() in ("true", "1", "yes", "on")
try:
    LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL_SECONDS", "300"))
except ValueError:
    LOOP_INTERVAL = 300


def run_loop_service(test_mode_override: Optional[bool] = None, run_once: bool = False):
    """
    Chạy chu kỳ quét tự động 24/7 cho VPS / Vibe Host.
    Tự động lặp lại sau mỗi khoảng thời gian LOOP_INTERVAL_SECONDS.
    """
    bot.configure_environment(test_mode_override=test_mode_override)
    
    print("\n" + "=" * 65)
    print(" DANBOORU COPYTAG BOT - SHINO IMAKO (24/7 SERVICE)")
    print("=" * 65)
    print(f"[*] Máy chủ API      : {bot.DANBOORU_HOST}")
    print(f"[*] Tài khoản        : {bot.USERNAME or '(Chưa thiết lập)'}")
    print(f"[*] Chế độ TEST_MODE : {'BẬT (Testbooru)' if bot.TEST_MODE else 'TẮT (Danbooru thật)'}")
    print(f"[*] Git Database     : {bot.DATABASE_REPO_URL}")
    print(f"[*] File phạm vi     : {bot.CHECKFILE_PATH}")
    print(f"[*] Vòng lặp 24/7    : {'BẬT (Mỗi ' + str(LOOP_INTERVAL) + 's)' if not run_once else 'TẮT (Chạy 1 lần)'}")
    print("=" * 65 + "\n")

    # Đảm bảo repo database đã được clone/pull mới nhất
    db_file = bot.ensure_database_repo()
    approved_db, unapproved_db = bot.parse_database(db_file)
    print(f"[*] Database: {len(approved_db)} quy tắc ĐÃ DUYỆT, {len(unapproved_db)} quy tắc CHƯA DUYỆT.")

    cycle_num = 1
    try:
        while True:
            print(f"\n>>> [CHU KỲ #{cycle_num}] Bắt đầu lúc {time.strftime('%Y-%m-%d %H:%M:%S')} <<<")
            
            # Thực thi quét bài và gắn copytag
            bot.scan_and_apply_copytags()


            if run_once or not RUN_LOOP_ENV:
                print("\n[*] Hoàn tất chu kỳ quét đơn (chế độ chạy 1 lần).")
                break

            print(f"\n[*] Nghỉ {LOOP_INTERVAL} giây ({LOOP_INTERVAL // 60} phút) trước khi quét chu kỳ tiếp theo...")
            time.sleep(LOOP_INTERVAL)
            cycle_num += 1

    except KeyboardInterrupt:
        print("\n[*] Đã nhận lệnh dừng từ người dùng / hệ thống. Đang thoát an toàn...")
    except Exception as e:
        print(f"\n[!] Lỗi không mong muốn trong vòng lặp dịch vụ: {e}")


def main():
    parser = argparse.ArgumentParser(description="Danbooru Copytag Bot - Shino Imako")
    parser.add_argument("--scan", action="store_true", help="Chạy quét bài đăng theo checkfile.txt")
    parser.add_argument("--update-db", nargs="+", help="Lấy related copyright tags cho chartag cụ thể, ghi '?chartag -> ...' và push Git database")
    parser.add_argument("--crawl-chartags", action="store_true", help="Cào danh sách character tags từ Danbooru (category=4, hide_empty=yes, order=date) để cập nhật database")
    parser.add_argument("--max-pages", type=int, default=None, help="Giới hạn số trang cào từ Danbooru (mỗi trang 100 tags)")
    parser.add_argument("--max-tags", type=int, default=None, help="Giới hạn số lượng character tags mới cần xử lý")
    parser.add_argument("--test", action="store_true", help="Bật chế độ TEST_MODE (Testbooru: https://testbooru.donmai.us)")
    parser.add_argument("--live", action="store_true", help="Chạy chế độ PRODUCTION (Danbooru thật)")
    parser.add_argument("--once", action="store_true", help="Chỉ quét 1 lần rồi thoát (tắt vòng lặp 24/7)")
    
    args = parser.parse_args()

    test_override = None
    if args.test:
        test_override = True
    elif args.live:
        test_override = False

    # 1. Nếu chạy cào danh sách character tags từ Danbooru
    if args.crawl_chartags:
        bot.configure_environment(test_mode_override=test_override)
        bot.crawl_and_update_database(max_tags=args.max_tags, max_pages=args.max_pages)
    # 2. Nếu người dùng chỉ định cụ thể các chartag cần update
    elif args.update_db:
        bot.configure_environment(test_mode_override=test_override)
        bot.update_database_pipeline(args.update_db)
    else:
        # Mặc định: Chạy quét bài đăng liên tục 24/7
        run_loop_service(test_mode_override=test_override, run_once=args.once)



if __name__ == "__main__":
    main()
