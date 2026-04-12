"""Advisor CLI entrypoint."""

from __future__ import annotations

import argparse

from src.core.advisor_sidecar import AdvisorSidecarService
from src.schwab_client._advisor.store import AdvisorStore
from src.schwab_client.cli.output import handle_cli_error, print_json_response

FEEDBACK_STATUSES = ("followed", "partially_followed", "ignored", "unknown")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schwab-advisor",
        description="Recommendation journal and evaluator",
    )
    sub = parser.add_subparsers(dest="command")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")

    recommend = sub.add_parser(
        "recommend",
        parents=[common],
        help="Capture one recommendation",
    )
    recommend.add_argument(
        "--model-command",
        help="Override the model command used to generate the recommendation",
    )
    sub.add_parser("evaluate", parents=[common], help="Evaluate open recommendations")
    sub.add_parser("status", parents=[common], help="Show journal status")

    review = sub.add_parser("review", parents=[common], help="Review one recommendation")
    review.add_argument("run_id", type=int)

    feedback = sub.add_parser(
        "feedback",
        parents=[common],
        help="Record whether you acted on it",
    )
    feedback.add_argument("run_id", type=int)
    feedback.add_argument("--status", required=True, choices=FEEDBACK_STATUSES)
    feedback.add_argument("--notes")

    note = sub.add_parser(
        "note",
        parents=[common],
        help="Add lesson/note to a recommendation",
    )
    note.add_argument("run_id", type=int)
    note.add_argument("body")
    note.add_argument("--type", default="lesson")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "status"
    output_mode = "json" if getattr(args, "json", False) else "text"

    try:
        store = AdvisorStore()
        store.initialize()

        if command == "status":
            data = store.status()
            if output_mode == "json":
                print_json_response("advisor-status", data=data)
            else:
                print(f"Advisor DB: {data['db_path']}")
                print(
                    f"Runs: {data['run_count']} "
                    f"(open: {data['open_count']}, evaluations: {data['evaluation_count']})"
                )
                for run in data["recent_runs"]:
                    print(
                        f"- #{run['id']} [{run['status']}] "
                        f"{run['recommendation_type']} {run['direction']} "
                        f"{run['target_id']} ({run['horizon_days']}d)"
                    )
            return 0

        if command == "recommend":
            result = AdvisorSidecarService(store=store).recommend(
                model_command=getattr(args, "model_command", None)
            )
            if output_mode == "json":
                print_json_response("advisor-recommend", data=result.to_dict())
            else:
                print(result.recommendation.thesis)
                print(f"Run ID: {result.run_id}")
            return 0

        if command == "evaluate":
            data = AdvisorSidecarService(store=store).evaluate_open_runs()
            if output_mode == "json":
                print_json_response("advisor-evaluate", data=data)
            else:
                print(f"Evaluated {len(data['evaluated'])} run(s)")
                for row in data["evaluated"]:
                    print(f"- #{row['run_id']} {row['outcome']}: {row['notes']}")
                for row in data["skipped"]:
                    print(f"- #{row['run_id']} skipped: {row['reason']}")
            return 0

        if command == "review":
            data = store.get_run(args.run_id) or {"run_id": args.run_id, "found": False}
            if output_mode == "json":
                print_json_response("advisor-review", data=data)
            else:
                if not data.get("id"):
                    print(f"Run {args.run_id} not found.")
                else:
                    print(f"#{data['id']} {data['thesis']}")
                    print(data.get("rationale") or "")
                    print(
                        f"Target: {data.get('target_type')} {data.get('target_id')} | "
                        f"Direction: {data.get('direction')} | "
                        f"Horizon: {data.get('horizon_days')}d"
                    )
                    print(
                        f"Feedback: {len(data.get('feedback', []))} | "
                        f"Evaluations: {len(data.get('evaluations', []))} | "
                        f"Notes: {len(data.get('notes', []))}"
                    )
            return 0

        if command == "feedback":
            store.record_feedback(args.run_id, status=args.status, notes=args.notes)
            data = {"run_id": args.run_id, "status": args.status, "notes": args.notes}
            if output_mode == "json":
                print_json_response("advisor-feedback", data=data)
            else:
                print(f"Recorded feedback for run {args.run_id}: {args.status}")
            return 0

        if command == "note":
            store.record_note(args.run_id, body=args.body, note_type=args.type)
            data = {"run_id": args.run_id, "type": args.type, "body": args.body}
            if output_mode == "json":
                print_json_response("advisor-note", data=data)
            else:
                print(f"Added {args.type} note to run {args.run_id}")
            return 0

        return 0
    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=f"advisor-{command}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
