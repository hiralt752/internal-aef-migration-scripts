import sys

from services.pipeline.migration_pipeline import MigrationPipeline
from utils.bootstrap import (
    bootstrap_storage
)


def main():
    """
    Entry point for migration execution.

    Usage:
        python migration.py extraction
        python migration.py structure
        python migration.py transformation
        python migration.py upload
    """
    bootstrap_storage()
    
    if len(sys.argv) < 2:
        raise ValueError(
            "Migration stage required.\n"
            "Example: python migration.py extraction"
        )

    stage = sys.argv[1].lower()

    pipeline = MigrationPipeline()

    if stage == "extraction":
        pipeline.run_extraction()

    elif stage == "structure":
        raise NotImplementedError(
            "Structure stage not implemented yet."
        )

    elif stage == "transformation":
        raise NotImplementedError(
            "Transformation stage not implemented yet."
        )

    elif stage == "upload":
        raise NotImplementedError(
            "Upload stage not implemented yet."
        )

    else:
        raise ValueError(
            f"Unsupported stage: {stage}"
        )


if __name__ == "__main__":
    main()