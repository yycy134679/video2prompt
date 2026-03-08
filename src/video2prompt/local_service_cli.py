"""本地服务 CLI。"""

from __future__ import annotations

import argparse
import json

from .managed_parser_service import ManagedParserService


def _build_parser_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser_cmd = subparsers.add_parser("parser", help="受管解析服务")
    parser_sub = parser_cmd.add_subparsers(dest="parser_action", required=True)

    parser_sub.add_parser("status", help="输出当前状态")

    prepare_parser = parser_sub.add_parser("prepare", help="写入受管默认配置")
    prepare_parser.add_argument("--clear-cookies", action="store_true", help="清空默认 Cookie")

    start_parser = parser_sub.add_parser("start", help="启动受管解析服务")
    start_parser.add_argument("--wait-timeout", type=float, default=20.0, help="等待健康检查秒数")

    parser_sub.add_parser("stop", help="停止受管解析服务")
    parser_sub.add_parser("health", help="检查受管解析服务健康状态")


def main() -> int:
    parser = argparse.ArgumentParser(description="video2prompt 本地服务 CLI")
    subparsers = parser.add_subparsers(dest="service", required=True)
    _build_parser_parser(subparsers)
    args = parser.parse_args()

    service = ManagedParserService()
    if args.service != "parser":
        parser.error(f"不支持的服务: {args.service}")

    if args.parser_action == "status":
        print(json.dumps(service.read_status().to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.parser_action == "prepare":
        service.prepare_managed_files(clear_cookies=bool(args.clear_cookies))
        print("受管解析服务配置已更新")
        return 0
    if args.parser_action == "start":
        pid = service.start(wait_timeout=float(args.wait_timeout))
        print(f"受管解析服务已启动，PID={pid}")
        return 0
    if args.parser_action == "stop":
        service.stop()
        print("受管解析服务已停止")
        return 0
    if args.parser_action == "health":
        ok, message = service.health_check()
        print(message)
        return 0 if ok else 1

    parser.error(f"不支持的操作: {args.parser_action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
