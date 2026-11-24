from ai_agent_3_engage import run_agent_3_engagement_guides
from ai_agent_4_lifecycle import run_agent_4_lifecycle_tracker


def main() -> None:
    print("=== Running AU Updates 3 & 4 ===")
    run_agent_3_engagement_guides()
    run_agent_4_lifecycle_tracker()
    print("AU Updates 3 & 4 complete.")


if __name__ == "__main__":
    main()
