"""Module for wrapping benchmark/eval execution and persisting evaluation receipts."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

from pydantic import ValidationError

from shared.eval_receipt import ContaminationStatus, EvalReceiptV1, FreshnessStatus

log = logging.getLogger(__name__)


class ReceiptWriteError(Exception):
    """Raised when the EvalReceiptWriter fails to write or validate a receipt."""

    pass


class EvalReceiptWriter:
    """Writer that wraps benchmark/eval execution, measures resources, and persists validated receipts."""

    def __init__(self, ledger_dir: str = "eval_ledger") -> None:
        self.ledger_dir = ledger_dir
        self.wall_time_seconds: float | None = None
        self.peak_memory_mb: float | None = None
        self._start_time: float | None = None

    def __enter__(self) -> EvalReceiptWriter:
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._start_time is not None:
            self.wall_time_seconds = time.perf_counter() - self._start_time

        try:
            import resource

            max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            import sys
            if sys.platform == "darwin":
                self.peak_memory_mb = max_rss / (1024.0 * 1024.0)
            else:
                self.peak_memory_mb = max_rss / 1024.0
        except (ImportError, OSError):
            self.peak_memory_mb = 0.0

    def write(
        self,
        result: Any,
        artifacts: dict[str, str],
        metadata: dict[str, Any],
        output_path: str | None = None,
    ) -> EvalReceiptV1:
        """Computes hashes of all provided artifacts, records resources, validates, and persists receipt.

        Args:
            result: The scoring result (can be a float, dict, or object with a score attribute).
            artifacts: Dict mapping artifact keys (e.g. 'model_id', 'route') to local file paths.
            metadata: Additional metadata for the EvalReceiptV1 fields.
            output_path: Optional exact path to write the JSON receipt. If omitted, writes to a default
                location in the ledger directory using the run_id.

        Returns:
            A validated EvalReceiptV1 instance.

        Raises:
            ReceiptWriteError: If any hash cannot be computed, validation fails, or file writing fails.
        """
        # 1. Parse normalized_score from result
        normalized_score = None
        if isinstance(result, (int, float)):
            normalized_score = float(result)
        elif isinstance(result, str):
            try:
                normalized_score = float(result)
            except ValueError:
                raise ReceiptWriteError(f"Could not parse normalized_score from string: {result}")
        elif isinstance(result, dict):
            normalized_score = result.get("normalized_score") or result.get("score")
        else:
            normalized_score = getattr(result, "normalized_score", None) or getattr(
                result, "score", None
            )

        if normalized_score is None:
            raise ReceiptWriteError("Could not extract normalized_score from result")

        try:
            normalized_score = float(normalized_score)
        except (ValueError, TypeError) as e:
            raise ReceiptWriteError(
                f"normalized_score must be a float, got {normalized_score}"
            ) from e

        # 2. Compute hashes of provided artifact paths
        hash_fields: dict[str, str] = {}
        hash_field_map = {
            "model_id": "model_id_hash",
            "model_id_hash": "model_id_hash",
            "route": "route_hash",
            "route_hash": "route_hash",
            "config": "config_hash",
            "config_hash": "config_hash",
            "prompt": "prompt_hash",
            "prompt_hash": "prompt_hash",
            "scorer": "scorer_hash",
            "scorer_hash": "scorer_hash",
            "dataset": "dataset_hash",
            "dataset_hash": "dataset_hash",
        }

        for key, path in artifacts.items():
            if not isinstance(path, str):
                raise ReceiptWriteError(
                    f"Artifact path for key '{key}' must be a string, got {type(path)}"
                )

            # Compute SHA-256
            sha256 = hashlib.sha256()
            try:
                with open(path, "rb") as f:
                    while chunk := f.read(8192):
                        sha256.update(chunk)
            except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as e:
                raise ReceiptWriteError(
                    f"Failed to compute hash for artifact '{key}' at '{path}': {e}"
                ) from e

            hash_val = f"sha256:{sha256.hexdigest()}"
            field_name = hash_field_map.get(key)
            if field_name:
                hash_fields[field_name] = hash_val

        # 3. Construct raw artifact refs
        raw_refs = metadata.get("raw_artifact_refs")
        if raw_refs is None:
            raw_refs = list(artifacts.values())

        # 4. Handle resource observations
        res_obs = dict(metadata.get("resource_observations") or {})

        # If wall_time_seconds is not in res_obs, populate from writer's context or since init
        if "wall_time_seconds" not in res_obs:
            if self.wall_time_seconds is None and self._start_time is not None:
                self.wall_time_seconds = time.perf_counter() - self._start_time
            if self.wall_time_seconds is not None:
                res_obs["wall_time_seconds"] = self.wall_time_seconds

        # If peak_memory_mb is not in res_obs, populate from writer's context or current usage
        if "peak_memory_mb" not in res_obs:
            if self.peak_memory_mb is None:
                try:
                    import resource

                    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    import sys
                    if sys.platform == "darwin":
                        self.peak_memory_mb = max_rss / (1024.0 * 1024.0)
                    else:
                        self.peak_memory_mb = max_rss / 1024.0
                except (ImportError, OSError):
                    self.peak_memory_mb = 0.0
            res_obs["peak_memory_mb"] = self.peak_memory_mb

        # 5. Assemble and validate EvalReceiptV1
        kwargs = {}
        kwargs.update(metadata)
        kwargs.update(hash_fields)
        kwargs["normalized_score"] = normalized_score
        kwargs["raw_artifact_refs"] = raw_refs
        kwargs["resource_observations"] = res_obs

        try:
            receipt = EvalReceiptV1(**kwargs)
        except ValidationError as e:
            raise ReceiptWriteError(f"EvalReceiptV1 validation failed: {e}") from e

        # 6. Persist to ledger
        if output_path is None:
            run_id = kwargs.get("run_id")
            if not run_id:
                raise ReceiptWriteError(
                    "run_id must be provided in metadata to determine output path"
                )
            output_path = os.path.join(self.ledger_dir, "receipts", f"{run_id}.json")

        try:
            dirname = os.path.dirname(output_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(receipt.model_dump_json(indent=2))
        except OSError as e:
            raise ReceiptWriteError(f"Failed to write receipt to '{output_path}': {e}") from e

        return receipt


if __name__ == "__main__":
    # Create the sample receipt when run directly
    print("Generating sample eval receipt...")

    # 1. Create a samples directory inside the ledger
    ledger_dir = "eval_ledger"
    samples_dir = os.path.join(ledger_dir, "samples")
    os.makedirs(samples_dir, exist_ok=True)

    # 2. Write mock artifact files to calculate actual hashes
    # Prefixing with # to ensure they are valid python comment syntaxes if checked as python
    mock_files = {
        "model_id": "mock_model.bin",
        "route": "mock_route.json",
        "config": "mock_config.yaml",
        "prompt": "mock_prompt.txt",
        "scorer": "mock_scorer.py",
        "dataset": "mock_dataset.jsonl",
    }

    artifacts = {}
    for key, name in mock_files.items():
        path = os.path.join(samples_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# mock contents for {key}\n")
        artifacts[key] = path

    # 3. Define metadata
    metadata = {
        "run_id": "sample-run-001",
        "authority_case": "CASE-SAMPLE-001",
        "task_ref": "task-sample-001",
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["Sample model passes baseline constraints"],
        "what_this_does_not_prove": ["Generalisation to unseen environments"],
        "replayable": True,
    }

    # 4. Use context manager to run the mock evaluation
    with EvalReceiptWriter(ledger_dir=ledger_dir) as writer:
        # Mock scorer result
        result = {"normalized_score": 0.95}
        time.sleep(0.1)  # sleep a tiny bit to get non-zero wall time

    # 5. Write the receipt to eval_ledger/samples/sample_receipt_v1.json
    output_path = os.path.join(samples_dir, "sample_receipt_v1.json")
    receipt = writer.write(result, artifacts, metadata, output_path=output_path)

    # 6. Verify that it compiles and parses successfully
    with open(output_path, encoding="utf-8") as f:
        data = f.read()
    parsed = EvalReceiptV1.model_validate_json(data)
    print(f"Successfully generated and validated sample receipt at: {output_path}")
    print(f"Wall time: {parsed.resource_observations.get('wall_time_seconds')}s")
    print(f"Peak memory: {parsed.resource_observations.get('peak_memory_mb')}MB")
