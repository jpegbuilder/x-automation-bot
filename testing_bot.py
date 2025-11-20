"""
X Follow Bot - Test Mode

Testing the bot with scenarios defined in scenarios.yaml

Usage examples:
    python test_bot.py --ads_id=YOUR_ID --scenario=simple_follow --target=username
    python test_bot.py --ads_id=YOUR_ID --scenario=like_and_follow --target=username
    python test_bot.py --ads_id=YOUR_ID --scenario=careful_follow --target=username
"""

import sys
import argparse
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from x_bot.core.x_follow_bot import XFollowBot
from x_bot.scenario.scenario_engine import ScenarioEngine
from x_bot.test_bot.testbot_engine import TestBotEngine


def main() -> int:

    parser = argparse.ArgumentParser(
        description="X Follow Bot - Test Mode with Scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Examples:
              python test_bot.py --ads_id=12345 --scenario=simple_follow --target=elonmusk
              python test_bot.py --ads_id=re45ff --scenario=like_and_follow --target=username
              python test_bot.py --ads_id=test123 --scenario=careful_follow --target=username --verbose
        """,
    )

    # Required arguments
    parser.add_argument(
        "--ads_id",
        required=True,
        help="AdsPower profile ID",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name from scenarios.yaml",
    )
    parser.add_argument(
        "--target",
        required=False,
        help="Target username (without @). Some scenarios may require it.",
    )

    # Optional arguments
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output with stack traces",
    )

    args = parser.parse_args()

    # Print banner
    print("\n" + "=" * 60)
    print("  X FOLLOW BOT - TEST MODE")
    print("=" * 60)
    print(f"Profile ID: {args.ads_id}")
    print(f"Scenario:   {args.scenario}")
    target_display = f"@{args.target}" if args.target else "-"
    print(f"Target:     {target_display}")
    print("=" * 60 + "\n")

    test_bot: TestBotEngine | None = None

    try:
        # Create inner bot (real XFollowBot)
        print("⏳ Creating bot instance (XFollowBot)...")
        inner_bot = XFollowBot(
            profile_id=args.ads_id,
            airtable_manager=None,  # You can provide Airtable manager here if needed
        )

        # Wrap it in TestableBot for colored logs and step tracking
        print("⏳ Wrapping bot into TestableBot...")
        test_name = f"{args.scenario}_{args.ads_id}"
        test_bot = TestBotEngine(
            bot=inner_bot,
            test_name=test_name,
        )

        # Initialize ScenarioEngine on top of TestableBot
        print("⏳ Loading scenarios...")
        engine = ScenarioEngine(bot=test_bot)

        # Start test session (for logging/summary)
        test_bot.start_test()

        # Start AdsPower profile
        print("⏳ Starting AdsPower profile...")
        if not test_bot.start_profile():
            print("❌ Failed to start profile")
            return 1

        print("✅ Profile started\n")

        # Connect to browser
        print("⏳ Connecting to browser...")
        if not test_bot.connect_to_browser():
            print("❌ Failed to connect to browser")
            test_bot.stop_profile()
            return 1

        print("✅ Connected to browser\n")

        # Execute scenario
        print(f"⏳ Executing scenario '{args.scenario}'...")
        try:
            result = engine.execute_scenario(
                name=args.scenario,
                target_username=args.target,
            )
        except ValueError as ve:
            # Typically thrown when target is required but not provided
            print(f"❌ Scenario execution error: {ve}")
            return 1

        # Finish test (mark end time)
        test_bot.finish_test()

        # Check result
        if result.get("success"):
            print("\n✅ Scenario completed successfully!")
        else:
            print("\n⚠️ Scenario finished with errors.")
            if result.get("error"):
                print(f"   First error: {result['error']}")

        # Print summary and save structured log
        print()
        test_bot.print_summary()

        return 0 if result.get("success") else 1

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user (Ctrl+C)")
        return 130

    except Exception as e:
        print(f"\n❌ Error: {e}")

        if args.verbose:
            print("\n" + "=" * 60)
            print("STACK TRACE:")
            print("=" * 60)
            import traceback

            traceback.print_exc()

        return 1

    finally:
        # Stop profile in any case
        if test_bot is not None:
            try:
                print("\n⏳ Stopping AdsPower profile...")
                test_bot.stop_profile()
                print("✅ Profile stopped")
            except Exception as e:
                print(f"⚠️  Error stopping profile: {e}")


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
