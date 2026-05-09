"""Training Receipt — provenance for the trained Gaussian Splat model.

Links the trained output model back to its attested input data,
creating the pre-image binding that makes the provenance chain work.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .crypto import sha256_file, sign_data, verify_signature, generate_keypair


class TrainingReceipt:
    """
    Create a receipt proving a trained splat was derived from attested input data.
    """

    VERSION = 1

    KNOWN_PIPELINES = {
        "gaussian-splatting": "INRIA Gaussian Splatting",
        "nerfstudio": "Nerfstudio SplatFacto",
        "postshot": "Postshot by JangaFX",
        "polycam": "Polycam",
        "luma": "Luma AI",
        "custom": "Custom pipeline",
    }

    def __init__(
        self,
        pipeline_key: str,
        pipeline_id: str = "gaussian-splatting",
        pipeline_version: str = "0.1.0",
    ):
        self.pipeline_key = pipeline_key  # Ed25519 private key hex
        self.pipeline_id = pipeline_id
        self.pipeline_version = pipeline_version

    @classmethod
    def create_pipeline(cls, pipeline_id: str = "gaussian-splatting", version: str = "0.1.0"):
        """Create a new pipeline identity with fresh keypair."""
        private_hex, public_hex = generate_keypair()
        instance = cls(
            pipeline_key=private_hex,
            pipeline_id=pipeline_id,
            pipeline_version=version,
        )
        pipeline_info = {
            "pipeline_id": pipeline_id,
            "pipeline_public_key": public_hex,
            "pipeline_private_key": private_hex,
            "pipeline_version": version,
            "pipeline_name": cls.KNOWN_PIPELINES.get(pipeline_id, pipeline_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return instance, pipeline_info

    def create_receipt(
        self,
        splat_path: str | Path,
        input_hash: str,
        input_attestation: Optional[dict] = None,
        gaussian_count: Optional[int] = None,
        training_config_path: Optional[str | Path] = None,
        quality_metrics: Optional[dict] = None,
        training_duration_s: Optional[float] = None,
    ) -> dict:
        """
        Create a training receipt for a trained splat.
        
        Args:
            splat_path: Path to the .ply/.splat file
            input_hash: Hash of the input data (from capture attestation)
            input_attestation: Full capture attestation dict (optional, for binding)
            gaussian_count: Number of Gaussians in the output
            training_config_path: Path to training config YAML (hashed for reproducibility)
            quality_metrics: Dict with PSNR, SSIM, etc.
            training_duration_s: How long training took in seconds
            
        Returns:
            Training receipt dict with signature
        """
        splat_path = Path(splat_path)
        if not splat_path.is_file():
            raise ValueError(f"Splat file does not exist: {splat_path}")

        # 1. Hash the output model
        model_hash = sha256_file(splat_path)

        # 2. Detect format from extension
        model_format = splat_path.suffix.lstrip(".")
        model_size_bytes = splat_path.stat().st_size

        # 3. Hash training config if provided
        config_hash = None
        if training_config_path:
            config_hash = sha256_file(Path(training_config_path))

        # 4. Extract Gaussian count from PLY header if not provided
        if gaussian_count is None and model_format == "ply":
            gaussian_count = _count_ply_gaussians(splat_path)

        # 5. Build receipt
        receipt = {
            "version": self.VERSION,
            "type": "training_receipt",
            "input_hash": input_hash,
            "model_hash": model_hash,
            "model_format": model_format,
            "model_size_bytes": model_size_bytes,
            "gaussian_count": gaussian_count,
            "pipeline_id": self.pipeline_id,
            "pipeline_version": self.pipeline_version,
            "pipeline_name": self.KNOWN_PIPELINES.get(self.pipeline_id, self.pipeline_id),
            "config_hash": config_hash,
            "quality_metrics": quality_metrics or {},
            "training_duration_s": training_duration_s,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 6. Verify input_hash binding if attestation provided
        if input_attestation:
            att_input_hash = input_attestation.get("input_hash")
            if att_input_hash and att_input_hash != input_hash:
                raise ValueError(
                    f"input_hash mismatch! Receipt says {input_hash[:16]}... "
                    f"but attestation says {att_input_hash[:16]}..."
                )

        # 7. Sign
        signature = sign_data(self.pipeline_key, receipt)
        receipt["signature"] = signature

        return receipt

    @staticmethod
    def verify(receipt: dict, pipeline_public_key: str) -> bool:
        """Verify a training receipt signature."""
        sig = receipt.pop("signature", None)
        if sig is None:
            return False
        valid = verify_signature(pipeline_public_key, receipt, sig)
        receipt["signature"] = sig
        return valid


def _count_ply_gaussians(path: Path) -> Optional[int]:
    """Try to extract Gaussian count from PLY header."""
    try:
        with open(path, "rb") as f:
            for line in f:
                if b"element vertex" in line:
                    return int(line.split()[-1])
                if b"end_header" in line:
                    break
    except Exception:
        pass
    return None


def load_receipt(path: Path) -> dict:
    """Load a training receipt from a JSON file."""
    with open(path) as f:
        return json.load(f)


def save_receipt(receipt: dict, path: Path) -> None:
    """Save a training receipt to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)