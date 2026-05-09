"""Cryptographic utilities — Ed25519 signing, SHA-256/BLAKE3 hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import RawEncoder


# ── Hashing ──────────────────────────────────────────────────────────────

def sha256_bytes(data: bytes) -> str:
    """SHA-256 hash of raw bytes. Returns hex string."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """SHA-256 hash of a file. Reads in chunks for large files."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 * 1024 * 1024):  # 8MB chunks
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths: list[Path]) -> str:
    """SHA-256 hash of multiple files concatenated. Deterministic order."""
    h = hashlib.sha256()
    sorted_paths = sorted(paths, key=lambda p: str(p))
    for path in sorted_paths:
        h.update(str(path.name).encode("utf-8"))
        h.update(":".encode())
        h.update(sha256_file(path).encode("utf-8"))
        h.update("|".encode("utf-8"))
    return h.hexdigest()


def blake3_file(path: Path) -> str:
    """BLAKE3 hash of a file. Falls back to SHA-256 if blake3 not installed."""
    try:
        import blake3 as _blake3
        h = _blake3.blake3()
        with open(path, "rb") as f:
            while chunk := f.read(8 * 1024 * 1024):
                h.update(chunk)
        return h.hexdigest()
    except ImportError:
        return sha256_file(path)


# ── Frame-level hashing ──────────────────────────────────────────────────

def hash_frames_coded(
    frame_paths: list[Path],
    seed: int = 42,
    step: int = 1,
    max_frames: int = 20,
) -> list[dict]:
    """
    Hash specific frames in a coded order.
    
    Instead of hashing ALL frames (expensive), we select frames
    deterministically using a seed-based pattern:
      1. Sort frames by name
      2. Use seed to compute start offset + step
      3. Hash up to max_frames frames
    
    This creates a unique fingerprint that's nearly impossible to fake
    without knowing the seed and having the actual frames.
    """
    if not frame_paths:
        return []
    
    sorted_paths = sorted(frame_paths, key=lambda p: str(p.name))
    total = len(sorted_paths)
    
    # Deterministic selection using seed
    # start: seed % total, step: (seed % 7) + 3 (3-9)
    rng = _simple_rng(seed)
    start = next(rng) % total
    step = (next(rng) % 7) + 3
    
    selected = []
    idx = start
    count = 0
    while count < max_frames and count < total:
        selected.append(sorted_paths[idx % total])
        idx += step
        count += 1
    
    # Hash each selected frame
    frame_hashes = []
    for path in selected:
        frame_hashes.append({
            "frame": path.name,
            "hash": sha256_file(path),
            "index": sorted_paths.index(path),
        })
    
    return frame_hashes


def _simple_rng(seed: int):
    """Simple deterministic RNG for frame selection. Not crypto-grade."""
    state = seed
    while True:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        yield state


# ── Ed25519 Signing ──────────────────────────────────────────────────────

def generate_keypair() -> tuple[str, str]:
    """Generate Ed25519 keypair. Returns (private_key_hex, public_key_hex)."""
    signing_key = SigningKey.generate()
    private_hex = bytes(signing_key).hex()
    public_hex = bytes(signing_key.verify_key).hex()
    return private_hex, public_hex


def sign_data(private_key_hex: str, data: dict) -> str:
    """Sign a JSON dict with Ed25519 private key. Returns signature hex."""
    signing_key = SigningKey(bytes.fromhex(private_key_hex), encoder=RawEncoder)
    msg = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signed = signing_key.sign(msg)
    return signed.signature.hex()


def verify_signature(public_key_hex: str, data: dict, signature_hex: str) -> bool:
    """Verify an Ed25519 signature over a JSON dict."""
    try:
        verify_key = VerifyKey(bytes.fromhex(public_key_hex), encoder=RawEncoder)
        msg = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        verify_key.verify(msg, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False


# ── Model hashing ────────────────────────────────────────────────────────

def hash_splat(path: Path) -> str:
    """Hash a splat file (.ply, .splat, .ksplat). Uses SHA-256."""
    return sha256_file(path)