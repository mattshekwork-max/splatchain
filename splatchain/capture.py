"""Capture Attestation — provenance for raw input data.

This module creates a signed attestation that sensor data existed
before the model was trained. It hashes the input files, selects
coded frames for verification, and signs everything with a device key.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .crypto import (
    sha256_files,
    hash_frames_coded,
    sign_data,
    verify_signature,
    generate_keypair,
)


class CaptureAttestation:
    """
    Attest that raw capture data (photos, LiDAR, etc.) existed
    before a Gaussian Splat was trained from it.
    """

    VERSION = 1

    def __init__(
        self,
        device_key: str,
        device_id: str,
        capture_method: str,
        gps: Optional[dict] = None,
        frame_seed: int = 42,
        frame_step: int = 1,
        max_frames: int = 20,
    ):
        self.device_key = device_key  # Ed25519 private key hex
        self.device_id = device_id
        self.capture_method = capture_method
        self.gps = gps or {}
        self.frame_seed = frame_seed
        self.frame_step = frame_step
        self.max_frames = max_frames

    @classmethod
    def create_device(cls, capture_method: str = "unknown", gps: Optional[dict] = None):
        """Create a new device with a fresh keypair. Returns (attestation_instance, device_info)."""
        private_hex, public_hex = generate_keypair()
        device_id = public_hex  # Use public key as device ID
        instance = cls(
            device_key=private_hex,
            device_id=device_id,
            capture_method=capture_method,
            gps=gps,
        )
        device_info = {
            "device_id": device_id,
            "public_key": public_hex,
            "private_key": private_hex,  # Store securely in production!
            "capture_method": capture_method,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return instance, device_info

    def attest(
        self,
        input_dir: str | Path,
        sensor_types: Optional[list[str]] = None,
        duration_s: Optional[float] = None,
    ) -> dict:
        """
        Create a capture attestation for a directory of input files.
        
        Args:
            input_dir: Path to directory containing raw input files
            sensor_types: List of sensor types used (e.g., ["rgb", "lidar", "imu"])
            duration_s: Duration of capture in seconds
            
        Returns:
            Attestation dict with signatures and frame hashes
        """
        input_dir = Path(input_dir)
        if not input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")

        # Collect all files (images, depth maps, etc.)
        extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".bin", ".ply", ".las", ".xyz"}
        all_files = [f for f in sorted(input_dir.rglob("*")) if f.is_file() and f.suffix.lower() in extensions]
        
        if not all_files:
            # Include all files if no recognized extensions
            all_files = [f for f in sorted(input_dir.rglob("*")) if f.is_file()]

        # 1. Compute input_hash (whole directory)
        input_hash = sha256_files(all_files)

        # 2. Compute coded frame hashes (specific frames in deterministic order)
        image_files = [f for f in all_files if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr"}]
        frame_hashes = hash_frames_coded(
            image_files,
            seed=self.frame_seed,
            step=self.frame_step,
            max_frames=self.max_frames,
        )

        # 3. Build attestation document
        attestation = {
            "version": self.VERSION,
            "type": "capture_attestation",
            "device_id": self.device_id,
            "capture_method": self.capture_method,
            "input_hash": input_hash,
            "input_file_count": len(all_files),
            "frame_hashes": frame_hashes,
            "frame_seed": self.frame_seed,
            "gps": self.gps,
            "sensor_types": sensor_types or ["rgb"],
            "duration_s": duration_s,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 4. Sign
        # Sign the canonical form (sorted keys, compact JSON)
        canonical = json.dumps(attestation, sort_keys=True, separators=(",", ":"))
        signature = sign_data(self.device_key, attestation)
        attestation["signature"] = signature

        return attestation

    @staticmethod
    def verify(attestation: dict, public_key: Optional[str] = None) -> bool:
        """
        Verify a capture attestation signature.
        
        Args:
            attestation: The attestation dict with signature
            public_key: The device's public key. If None, uses device_id from attestation.
        
        Returns:
            True if signature is valid
        """
        if public_key is None:
            public_key = attestation.get("device_id", "")
        
        sig = attestation.pop("signature", None)
        if sig is None:
            return False
        
        valid = verify_signature(public_key, attestation, sig)
        attestation["signature"] = sig  # Restore
        return valid


def load_attestation(path: Path) -> dict:
    """Load an attestation from a JSON file."""
    with open(path) as f:
        return json.load(f)


def save_attestation(attestation: dict, path: Path) -> None:
    """Save an attestation to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(attestation, f, indent=2)