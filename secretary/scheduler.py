"""
定期実行スケジューラー
秘書エージェントを定期的に実行する
"""

import time
import logging
import signal
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class SecretaryScheduler:
    """秘書エージェントの定期実行スケジューラー"""

    def __init__(self, interval_minutes: int = 60):
        self.interval_seconds = interval_minutes * 60
        self.running = False
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.info("シャットダウン信号を受信しました。停止します...")
        self.running = False
        sys.exit(0)

    def run_once(self) -> str:
        """1回だけ実行する"""
        from secretary.main import SecretaryAgent
        agent = SecretaryAgent()
        return agent.run()

    def run_loop(self):
        """定期実行ループ"""
        self.running = True
        logger.info(f"秘書スケジューラーを開始します（{self.interval_seconds // 60}分ごとに実行）")

        while self.running:
            start_time = datetime.now()
            logger.info(f"実行開始: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

            try:
                report = self.run_once()
                print("\n" + "=" * 60)
                print(f"実行時刻: {start_time.strftime('%Y年%m月%d日 %H:%M')}")
                print(report)
                print("=" * 60 + "\n")
            except Exception as e:
                logger.error(f"実行エラー: {e}", exc_info=True)

            logger.info(f"次の実行まで {self.interval_seconds // 60} 分待機します")
            time.sleep(self.interval_seconds)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI秘書スケジューラー")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="実行間隔（分）デフォルト: 60",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回だけ実行して終了する",
    )
    args = parser.parse_args()

    scheduler = SecretaryScheduler(interval_minutes=args.interval)

    if args.once:
        report = scheduler.run_once()
        print(report)
    else:
        scheduler.run_loop()
