from __future__ import annotations

import argparse
import json

from monitoring_service import MonitoringOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline monitoring analysis runner")
    parser.add_argument("--duration", type=int, default=None, help="Clip duration in seconds")
    parser.add_argument("--cameras", nargs="*", default=None, help="Camera IDs to analyze")
    parser.add_argument("--summary", action="store_true", help="Generate the daily summary instead of a task run")
    parser.add_argument("--date", default=None, help="Summary date in YYYY-MM-DD format")
    parser.add_argument("--no-feishu", action="store_true", help="Do not send the summary to Feishu")
    args = parser.parse_args()

    orchestrator = MonitoringOrchestrator(start_preview=False)
    try:
        if args.summary:
            result = orchestrator.generate_daily_summary(
                summary_date=args.date,
                send_to_feishu=not args.no_feishu,
            )
        else:
            result = orchestrator.run_task_sync(
                camera_ids=args.cameras,
                duration_seconds=args.duration,
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        orchestrator.shutdown()


if __name__ == "__main__":
    main()
