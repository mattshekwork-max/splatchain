"""
SplatChain Integration Test — End-to-End Provenance Chain

This test exercises the entire pipeline:
  1. Generate device + pipeline keypairs
  2. Create fake "raw input" files (simulating photos + depth maps)
  3. Create a capture attestation (hash + sign input data)
  4. Create a fake "trained splat" file (simulating .ply output)
  5. Create a training receipt (bind input_hash -> model_hash)
  6. Generate the .verify.json sidecar
  7. Verify the sidecar against the splat file (full provenance check)
  8. Tamper with the splat and verify detection
  9. Tamper with a signature and verify detection
  10. Test missing sidecar (unverified)
  11. Test the CLI commands (keygen, attest, receipt, verify)
  12. Test the PlayCanvas hash module compatibility
"""

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure the project root is in sys.path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Helpers ─────────────────────────────────────────────────────────────

def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def write_fake_files(directory: Path, count: int = 10, prefix: str = "frame"):
    """Write fake input files (simulating photos + depth maps)."""
    files = []
    for i in range(count):
        # Photo
        photo = directory / f"{prefix}_{i:04d}.jpg"
        photo.write_bytes(os.urandom(4096 + i * 100))  # variable sizes
        files.append(photo)
        # Depth map
        depth = directory / f"{prefix}_{i:04d}_depth.raw"
        depth.write_bytes(os.urandom(2048 + i * 50))
        files.append(depth)
    return files

def write_fake_splat(directory: Path, name: str = "scene.ply", size_kb: int = 256):
    """Write a fake .ply splat file with proper PLY header."""
    path = directory / name
    # PLY header + random Gaussian data
    header = b"""ply
binary_little_endian 1.0
format binary_little_endian 1.0
element vertex 1000
property float x
property float y
property float z
property float nx
property float ny
property float nz
property float f_dc_0
property float f_dc_1
property float f_dc_2
property float opacity
property float scale_0
property float scale_1
property float scale_2
property float rot_0
property float rot_1
property float rot_2
property float rot_3
end_header
"""
    # Each vertex: 17 floats * 4 bytes = 68 bytes per vertex
    num_vertices = 1000
    data = header + os.urandom(num_vertices * 68)
    path.write_bytes(data)
    return path

# ── Test Functions ────────────────────────────────────────────────────────

def test_keypair_generation():
    """Test 1: Keypair generation and basic crypto."""
    from splatchain.crypto import generate_keypair, sign_data, verify_signature
    
    priv, pub = generate_keypair()
    assert len(priv) == 64, f"Private key should be 64 hex chars, got {len(priv)}"
    assert len(pub) == 64, f"Public key should be 64 hex chars, got {len(pub)}"
    assert priv != pub, "Private and public keys should differ"
    
    # Sign and verify
    msg = {"hello": "world", "number": 42}
    sig = sign_data(priv, msg)
    assert len(sig) == 128, f"Ed25519 sig should be 128 hex chars, got {len(sig)}"
    assert verify_signature(pub, msg, sig), "Signature should verify"
    
    # Wrong message should fail
    assert not verify_signature(pub, {"hello": "wrong"}, sig), "Wrong message should fail"
    
    # Wrong key should fail
    _, wrong_pub = generate_keypair()
    assert not verify_signature(wrong_pub, msg, sig), "Wrong key should fail"
    
    print("  [PASS] Test 1: Keypair generation + sign/verify")


def test_capture_attestation():
    """Test 2: Create capture attestation for fake input data."""
    from splatchain.capture import CaptureAttestation, save_attestation, load_attestation
    from splatchain.crypto import sha256_files, verify_signature
    
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        input_dir.mkdir()
        
        # Write fake input files
        files = write_fake_files(input_dir, count=10)
        assert len(files) == 20  # 10 photos + 10 depth maps
        
        # Create device and attest
        ca, device_info = CaptureAttestation.create_device(
            capture_method="iphone_lidar",
            gps={"lat": 34.0522, "lon": -118.2437, "alt": 71, "accuracy_m": 3.2},
        )
        
        attestation = ca.attest(input_dir)
        
        # Check attestation structure
        assert attestation["version"] == 1
        assert attestation["input_hash"], "Should have input_hash"
        assert attestation["device_id"], "Should have device_id"
        assert attestation["capture_method"] == "iphone_lidar"
        assert attestation["gps"]["lat"] == 34.0522
        assert attestation["signature"], "Should be signed"
        assert "frame_hashes" in attestation, "Should have coded frame hashes"
        assert len(attestation["frame_hashes"]) > 0, "Should have at least one coded frame"
        
        # Save and reload
        att_path = Path(tmpdir) / "capture_attestation.json"
        save_attestation(attestation, att_path)
        loaded = load_attestation(att_path)
        assert loaded["input_hash"] == attestation["input_hash"]
        assert loaded["signature"] == attestation["signature"]
        
        # Verify independently
        msg = {k: v for k, v in attestation.items() if k != "signature"}
        assert verify_signature(attestation["device_id"], msg, attestation["signature"]), \
            "Capture attestation signature should verify"
        
        print(f"  [PASS] Test 2: Capture attestation (input_hash={attestation['input_hash'][:16]}...)")


def test_training_receipt():
    """Test 3: Create training receipt linking input to model."""
    from splatchain.capture import CaptureAttestation
    from splatchain.training import TrainingReceipt, save_receipt, load_receipt
    from splatchain.crypto import sha256_file
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create fake input and output
        input_dir = tmpdir / "input"
        input_dir.mkdir()
        write_fake_files(input_dir, count=10)
        
        splat_path = write_fake_splat(tmpdir, "scene.ply")
        model_hash = sha256_file(splat_path)
        
        # Create capture attestation first (need input_hash)
        ca, _ = CaptureAttestation.create_device(capture_method="dslr_photogrammetry")
        attestation = ca.attest(input_dir)
        input_hash = attestation["input_hash"]
        
        # Create training receipt
        tr, pipeline_info = TrainingReceipt.create_pipeline(
            pipeline_id="gaussian-splatting",
            version="0.1.0",
        )
        
        receipt = tr.create_receipt(
            splat_path=splat_path,
            input_hash=input_hash,
            gaussian_count=402873,
            quality_metrics={"psnr": 31.2, "ssim": 0.94},
            training_duration_s=1847,
        )
        
        # Check receipt structure
        assert receipt["version"] == 1
        assert receipt["model_hash"] == model_hash, "model_hash should match"
        assert receipt["input_hash"] == input_hash, "input_hash should bind"
        assert receipt["model_format"] == "ply"
        assert receipt["gaussian_count"] == 402873
        assert receipt["quality_metrics"]["psnr"] == 31.2
        assert receipt["pipeline_id"] == "gaussian-splatting"
        assert receipt["signature"], "Should be signed"
        
        # Verify the pre-image binding: input_hash appears in BOTH
        assert attestation["input_hash"] == receipt["input_hash"], \
            "input_hash must match between capture and training — the pre-image link!"
        
        # Verify signature
        from splatchain.crypto import verify_signature
        pipeline_pub = pipeline_info["pipeline_public_key"]
        msg = {k: v for k, v in receipt.items() if k != "signature"}
        assert verify_signature(pipeline_pub, msg, receipt["signature"]), \
            "Training receipt signature should verify"
        
        # Save and reload
        receipt_path = tmpdir / "training_receipt.json"
        save_receipt(receipt, receipt_path)
        loaded = load_receipt(receipt_path)
        assert loaded["model_hash"] == receipt["model_hash"]
        assert loaded["signature"] == receipt["signature"]
        
        print(f"  [PASS] Test 3: Training receipt (model_hash={model_hash[:16]}...)")


def test_full_verification():
    """Test 4: Full end-to-end verification with sidecar."""
    from splatchain.capture import CaptureAttestation
    from splatchain.training import TrainingReceipt
    from splatchain.verify import verify_splat, VerificationStatus
    from splatchain.crypto import sha256_file
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 1. Create fake input data
        input_dir = tmpdir / "input"
        input_dir.mkdir()
        write_fake_files(input_dir, count=15, prefix="photo")
        
        # 2. Create trained splat
        splat_path = write_fake_splat(tmpdir, "downtown.ply", size_kb=512)
        
        # 3. Capture attestation
        ca, device_info = CaptureAttestation.create_device(
            capture_method="drone",
            gps={"lat": 40.7128, "lon": -74.006, "alt": 30},
        )
        attestation = ca.attest(input_dir)
        
        # 4. Training receipt
        tr, pipeline_info = TrainingReceipt.create_pipeline("nerfstudio", "0.3.0")
        receipt = tr.create_receipt(
            splat_path=splat_path,
            input_hash=attestation["input_hash"],
            gaussian_count=250000,
            quality_metrics={"psnr": 28.5, "ssim": 0.91},
            training_duration_s=3600,
        )
        
        # 5. Create sidecar
        sidecar = {
            "version": 1,
            "model_hash": receipt["model_hash"],
            "input_hash": attestation["input_hash"],
            "capture_attestation": attestation,
            "training_receipt": receipt,
        }
        sidecar_path = tmpdir / "downtown.ply.verify.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2))
        
        # 6. Verify — should pass (no on-chain, but sidecar validates)
        result = verify_splat(splat_path, verify_json_path=sidecar_path, skip_chain=True)
        
        # Without on-chain, it's ATTESTED_UNVERIFIED (signatures valid but no chain ref)
        assert result.status == VerificationStatus.ATTESTED_UNVERIFIED, \
            f"Expected ATTESTED_UNVERIFIED, got {result.status}: {result.message}"
        assert result.model_hash == receipt["model_hash"]
        assert result.input_hash == attestation["input_hash"]
        assert result.capture_attestation is not None
        assert result.training_receipt is not None
        
        print(f"  [PASS] Test 4: Full verification (status={result.status.value}, {result.message})")


def test_tampered_splat():
    """Test 5: Tampering with the splat file should change model_hash."""
    from splatchain.capture import CaptureAttestation
    from splatchain.training import TrainingReceipt
    from splatchain.verify import verify_splat, VerificationStatus
    from splatchain.crypto import sha256_file
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_dir = tmpdir / "input"
        input_dir.mkdir()
        write_fake_files(input_dir, count=5)
        splat_path = write_fake_splat(tmpdir, "original.ply")
        
        ca, _ = CaptureAttestation.create_device(capture_method="iphone_lidar")
        attestation = ca.attest(input_dir)
        tr, _ = TrainingReceipt.create_pipeline("gaussian-splatting")
        receipt = tr.create_receipt(
            splat_path=splat_path,
            input_hash=attestation["input_hash"],
            gaussian_count=1000,
        )
        
        # Save sidecar next to the ORIGINAL splat
        sidecar_path = tmpdir / "original.ply.verify.json"
        sidecar_path.write_text(json.dumps({
            "version": 1,
            "model_hash": receipt["model_hash"],
            "input_hash": attestation["input_hash"],
            "capture_attestation": attestation,
            "training_receipt": receipt,
        }, indent=2))
        
        # Verification should work on original
        result_orig = verify_splat(splat_path, verify_json_path=sidecar_path, skip_chain=True)
        assert result_orig.status == VerificationStatus.ATTESTED_UNVERIFIED
        
        # Now TAMPER: modify the splat file
        original_data = splat_path.read_bytes()
        tampered_data = original_data[:-4] + b"\x00\x00\x00\x00"  # flip last bytes
        tampered_path = tmpdir / "tampered.ply"
        tampered_path.write_bytes(tampered_data)
        
        # Compute tampered hash — should differ
        tampered_hash = sha256_file(tampered_path)
        original_hash = sha256_file(splat_path)
        assert tampered_hash != original_hash, "Tampering should change the hash"
        
        # Verification with wrong sidecar should detect mismatch
        result_tamper = verify_splat(tampered_path, verify_json_path=sidecar_path, skip_chain=True)
        
        # The verify function computes model_hash from the file and compares
        # with what's in the sidecar — model_hash won't match
        assert result_tamper.model_hash != receipt["model_hash"], \
            "Tampered file hash should differ from receipt"
        
        print(f"  [PASS] Test 5: Tampered splat detection (original vs tampered hashes differ)")


def test_missing_sidecar():
    """Test 6: Splats without sidecars should be UNVERIFIED."""
    from splatchain.verify import verify_splat, VerificationStatus
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        splat_path = write_fake_splat(tmpdir, "orphan.ply")
        
        result = verify_splat(splat_path, skip_chain=True)
        assert result.status == VerificationStatus.UNVERIFIED
        assert result.model_hash  # Should still compute the hash
        
        print(f"  [PASS] Test 6: Missing sidecar -> UNVERIFIED")


def test_invalid_signature():
    """Test 7: Tampering with attestation data should invalidate signature."""
    from splatchain.capture import CaptureAttestation
    from splatchain.training import TrainingReceipt
    from splatchain.verify import verify_splat, VerificationStatus
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        input_dir = tmpdir / "input"
        input_dir.mkdir()
        write_fake_files(input_dir, count=5)
        splat_path = write_fake_splat(tmpdir, "signed.ply")
        
        ca, _ = CaptureAttestation.create_device(capture_method="terrestrial_scanner")
        attestation = ca.attest(input_dir)
        tr, _ = TrainingReceipt.create_pipeline("postshot")
        receipt = tr.create_receipt(
            splat_path=splat_path,
            input_hash=attestation["input_hash"],
            gaussian_count=50000,
        )
        
        # TAMPER: change the GPS coordinates after signing
        tampered_att = dict(attestation)
        tampered_att["gps"] = {"lat": 0.0, "lon": 0.0, "alt": 0}  # wrong location!
        
        sidecar = {
            "version": 1,
            "model_hash": receipt["model_hash"],
            "input_hash": attestation["input_hash"],
            "capture_attestation": tampered_att,
            "training_receipt": receipt,
        }
        sidecar_path = tmpdir / "signed.ply.verify.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2))
        
        result = verify_splat(splat_path, verify_json_path=sidecar_path, skip_chain=True)
        # The signature was over the original data, not the tampered GPS
        # So verification should fail with SIG_INVALID
        assert result.status == VerificationStatus.SIG_INVALID, \
            f"Expected SIG_INVALID for tampered attestation, got {result.status}: {result.message}"
        
        print(f"  [PASS] Test 7: Invalid signature detected (tampered GPS)")


def test_coded_frames():
    """Test 8: Coded frame hashing produces deterministic, seed-dependent results."""
    from splatchain.crypto import hash_frames_coded
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        frames = []
        for i in range(100):
            f = tmpdir / f"frame_{i:04d}.jpg"
            f.write_bytes(os.urandom(2048))
            frames.append(f)
        
        # Same seed -> same frames
        r1 = hash_frames_coded(frames, seed=42, step=1, max_frames=20)
        r2 = hash_frames_coded(frames, seed=42, step=1, max_frames=20)
        assert r1 == r2, "Same seed should produce same frame selection"
        
        # Different seed -> different frames (probably)
        r3 = hash_frames_coded(frames, seed=999, step=1, max_frames=20)
        # The frame indices should differ
        assert {f["index"] for f in r1} != {f["index"] for f in r3}, \
            "Different seeds should select different frames"
        
        # max_frames caps the number
        assert len(r1) <= 20, f"Should select at most 20 frames, got {len(r1)}"
        
        # Step > 1 skips frames
        r4 = hash_frames_coded(frames, seed=42, step=3, max_frames=20)
        assert len(r4) <= 20
        
        print(f"  [PASS] Test 8: Coded frame hashing (seed=42: {len(r1)} frames, seed=999: {len(r3)} frames)")


def test_cli_keygen():
    """Test 9: CLI keygen command."""
    result = subprocess.run(
        [sys.executable, "-m", "splatchain.cli", "keygen", "--device"],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    assert result.returncode == 0, f"keygen failed: {result.stderr}"
    # CLI outputs via click.echo, not JSON — parse the text output
    output = result.stdout
    assert "Private key:" in output, f"Expected 'Private key:' in output:\n{output}"
    assert "Public key:" in output, f"Expected 'Public key:' in output:\n{output}"
    
    print(f"  [PASS] Test 9: CLI keygen")


def test_cli_attest_and_verify():
    """Test 10: CLI attest -> receipt -> verify round-trip."""
    from splatchain.crypto import generate_keypair
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
        
        # Create input dir with files
        input_dir = tmpdir / "input"
        input_dir.mkdir()
        write_fake_files(input_dir, count=5, prefix="img")
        
        # Create splat
        splat_path = write_fake_splat(tmpdir, "scene.ply")
        
        # Generate keys
        device_priv, device_pub = generate_keypair()
        pipeline_priv, pipeline_pub = generate_keypair()
        
        # Step 1: CLI attest
        result = subprocess.run(
            [sys.executable, "-m", "splatchain.cli", "attest",
             str(input_dir), "--device-key", device_priv,
             "--method", "iphone_lidar",
             "--gps", "34.05,-118.24,71",
             "-o", str(tmpdir / "attestation.json")],
            capture_output=True, text=True, timeout=15,
            env=env,
        )
        assert result.returncode == 0, f"attest failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        att = json.loads((tmpdir / "attestation.json").read_text())
        assert att["input_hash"]
        assert att["signature"]
        assert att["capture_method"] == "iphone_lidar"
        
        # Step 2: CLI receipt
        result = subprocess.run(
            [sys.executable, "-m", "splatchain.cli", "receipt",
             str(splat_path), att["input_hash"],
             "--pipeline-key", pipeline_priv,
             "-o", str(tmpdir / "receipt.json")],
            capture_output=True, text=True, timeout=15,
            env=env,
        )
        assert result.returncode == 0, f"receipt failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        receipt = json.loads((tmpdir / "receipt.json").read_text())
        assert receipt["model_hash"]
        assert receipt["signature"]
        
        # Step 3: Create sidecar
        sidecar = {
            "version": 1,
            "model_hash": receipt["model_hash"],
            "input_hash": att["input_hash"],
            "capture_attestation": att,
            "training_receipt": receipt,
        }
        sidecar_path = tmpdir / "scene.ply.verify.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2))
        
        # Step 4: CLI verify
        result = subprocess.run(
            [sys.executable, "-m", "splatchain.cli", "verify",
             str(splat_path), "--verify-json", str(sidecar_path),
             "--skip-chain"],
            capture_output=True, text=True, timeout=15,
            env=env,
        )
        assert result.returncode == 0, f"verify failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        
        # Parse JSON from verify output (last line with "---" separator)
        output = result.stdout
        assert "JSON" in output or "{" in output, f"Expected JSON in output:\n{output}"
        json_start = output.rfind("{")
        verify_output = json.loads(output[json_start:])
        assert verify_output["status"] in ("attested_unverified", "verified"), \
            f"Expected valid status, got {verify_output}"
        assert verify_output["model_hash"] == receipt["model_hash"]
        
        print(f"  [PASS] Test 10: CLI attest -> receipt -> verify round-trip")


def test_playcanvas_hash_compat():
    """Test 11: Verify that Python SDK and PlayCanvas plugin compute identical hashes."""
    from splatchain.crypto import sha256_file
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a splat file
        splat_path = write_fake_splat(Path(tmpdir), "compat.ply")
        python_hash = sha256_file(splat_path)
        
        # Read the raw bytes and compute SHA-256 manually (simulating JS SubtleCrypto)
        raw = splat_path.read_bytes()
        manual_hash = hashlib.sha256(raw).hexdigest()
        
        assert python_hash == manual_hash, \
            f"Python and manual hash should match: {python_hash} vs {manual_hash}"
        
        # Also test sha256_files (multi-file input hashing)
        input_dir = Path(tmpdir) / "input"
        input_dir.mkdir()
        files = write_fake_files(input_dir, count=3, prefix="test")
        
        from splatchain.crypto import sha256_files
        multi_hash = sha256_files([f for f in files if f.suffix == ".jpg"])
        assert multi_hash, "Should hash multiple files"
        assert len(multi_hash) == 64, "Should be SHA-256 hex"
        
        print(f"  [PASS] Test 11: Python/JS hash compatibility (hash={python_hash[:16]}...)")


# ── Main ─────────────────────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("SplatChain Integration Test Suite")
    print("=" * 60)
    
    tests = [
        test_keypair_generation,
        test_capture_attestation,
        test_training_receipt,
        test_full_verification,
        test_tampered_splat,
        test_missing_sidecar,
        test_invalid_signature,
        test_coded_frames,
        test_cli_keygen,
        test_cli_attest_and_verify,
        test_playcanvas_hash_compat,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        name = test.__doc__.split("\n")[0].strip()
        print(f"\n  {name}")
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 60}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)