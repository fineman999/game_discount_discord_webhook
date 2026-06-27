"""CLI 엔트리포인트: `python -m dealbot [--dry-run] [-v]`."""

from __future__ import annotations

import argparse
import logging
import sys

from dealbot.config import ConfigError
from dealbot.run import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dealbot", description="Steam/Epic 할인 Discord 알림 봇")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discord 로 전송하지 않고 콘솔에만 출력 (상태도 변경 안 함)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 로그 출력")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return run(dry_run=args.dry_run)
    except ConfigError as exc:
        logging.error("설정 오류: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
