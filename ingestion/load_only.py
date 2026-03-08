import logging
import sys
from pathlib import Path
import argparse

from ingestion.config import settings
from ingestion.load.qdrant import run_qdrant_loader
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    root_dir = Path(__file__).parents[1]
    load_dotenv(root_dir / ".env")

    input_file_stem = Path(settings.input_file).stem
    default_input_path = str(
        root_dir / settings.artifacts_dir / input_file_stem / "synthesis_results.jsonl"
    )

    parser = argparse.ArgumentParser(
        description="Load a synthesis JSONL file into Qdrant."
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=default_input_path,
        help="Path to synthesis_results.jsonl",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=settings.load.collection_name,
        help="Collection name to upset",
    )

    args = parser.parse_args()
    input_path = Path(args.input_file)

    if not input_path.exists():
        logger.error(f"File not found: {input_path}")
        sys.exit(1)

    logger.info("── Loading to Qdrant based on specific file ──")
    logger.info(f"Target collection: {args.collection}")
    logger.info(f"Input file: {input_path}")

    run_qdrant_loader(
        input_files=[input_path],
        collection_name=args.collection,
        dense_batch_size=settings.load.dense_batch_size,
        qdrant_upsert_batch=settings.load.qdrant_upsert_batch,
        overwrite_collection=settings.load.overwrite_collection,
        save_concat_jsonl=None,
    )

    logger.info("── Loading Complete ────────────────────")


if __name__ == "__main__":
    main()
