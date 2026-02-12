"""统计报告命令行工具"""
import argparse
import json
from .stats.opportunity_tracker import OpportunityTracker


def main():
    parser = argparse.ArgumentParser(description="套利机会统计报告")
    parser.add_argument(
        "--weekly", "-w",
        action="store_true",
        help="显示周报"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="JSON 格式输出"
    )

    args = parser.parse_args()
    tracker = OpportunityTracker()

    if args.weekly:
        report = tracker.get_weekly_report()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print_weekly_report(report)
    else:
        if args.json:
            print(json.dumps(tracker.get_summary(), indent=2))
        else:
            tracker.print_report()


def print_weekly_report(report: dict):
    """打印周报"""
    print("\n" + "=" * 50)
    print("           套利机会周报")
    print("=" * 50)
    print(f"统计周期: {report['period']}")
    print(f"总机会数: {report['total_opportunities']}")
    print(f"总扫描次数: {report['total_scans']}")
    print(f"日均机会: {report['avg_opportunities_per_day']:.2f}")
    print(f"平均利润率: {report['avg_profit']:.2f}%")

    print("\n【每日明细】")
    print("-" * 50)
    print(f"{'日期':<12} {'机会数':<8} {'扫描次数':<10} {'平均利润':<10} {'最高利润'}")
    print("-" * 50)

    for day in report['daily_breakdown']:
        print(
            f"{day['date']:<12} "
            f"{day['opportunities']:<8} "
            f"{day['scans']:<10} "
            f"{day['avg_profit']:.2f}%{'':<5} "
            f"{day['max_profit']:.2f}%"
        )

    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
