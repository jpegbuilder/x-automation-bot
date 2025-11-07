#!/usr/bin/env python3
"""
Run Remaining Targets update for all Target records
"""
import logging
from managers.airtable_manager import AirtableManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Run the Remaining Targets update"""
    print("=" * 70)
    print("REMAINING TARGETS UPDATE")
    print("=" * 70)
    print()

    # Initialize manager
    manager = AirtableManager()

    # Run the update
    logger.info("Starting Remaining Targets update for all Target records...")
    print()

    success = manager.update_all_remaining_targets()

    print()
    print("=" * 70)
    if success:
        print("✅ UPDATE COMPLETE")
    else:
        print("❌ UPDATE FAILED")
    print("=" * 70)

if __name__ == "__main__":
    main()
