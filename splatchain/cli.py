"""SplatChain CLI — attest and verify Gaussian Splat provenance.

Usage:
    splatchain attest <input_dir> [--device-key KEY] [--method METHOD] [--gps LAT,LON,ALT]
    splatchain receipt <splat_file> <input_hash> [--pipeline-key KEY]
    splatchain verify <splat_file> [--verify-json PATH] [--rpc-url URL] [--contract ADDRESS]
    splatchain keygen [--device | --pipeline]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .capture import CaptureAttestation, save_attestation, load_attestation
from .training import TrainingReceipt, save_receipt, load_receipt
from .verify import verify_splat, VerificationStatus
from .crypto import generate_keypair, sha256_file


@click.group()
@click.version_option("0.1.0")
def main():
    """SplatChain — Blockchain-verified Gaussian Splat provenance."""
    pass


@main.command()
@click.argument("input_dir", type=click.Path(exists=True))
@click.option("--device-key", help="Ed25519 private key hex (generates new one if omitted)")
@click.option("--method", default="unknown", help="Capture method (iphone_lidar, dslr_photogrammetry, drone, etc.)")
@click.option("--gps", help="GPS coordinates as lat,lon,alt (e.g., 34.05,-118.24,71)")
@click.option("--seed", default=42, type=int, help="Seed for coded frame selection")
@click.option("--output", "-o", help="Output .verify.json path")
def attest(input_dir, device_key, method, gps, seed, output):
    """Create a capture attestation for raw input data."""
    
    # Parse GPS
    gps_dict = {}
    if gps:
        parts = gps.split(",")
        if len(parts) >= 2:
            gps_dict = {
                "lat": float(parts[0]),
                "lon": float(parts[1]),
                "alt": float(parts[2]) if len(parts) > 2 else 0,
            }
    
    # Create attestation
    if device_key:
        # Use provided key
        _, public_key = generate_keypair()  # We need to derive public key
        from .crypto import SigningKey as _SK, RawEncoder as _RE
        sk = _SK(bytes.fromhex(device_key), encoder=_RE)
        device_id = bytes(sk.verify_key).hex()
        ca = CaptureAttestation(
            device_key=device_key,
            device_id=device_id,
            capture_method=method,
            gps=gps_dict,
            frame_seed=seed,
        )
    else:
        # Generate new device
        ca, device_info = CaptureAttestation.create_device(
            capture_method=method,
            gps=gps_dict,
        )
        click.echo(f"Generated new device key:")
        click.echo(f"  Device ID: {device_info['device_id'][:16]}...")
        click.echo(f"  Public key: {device_info['public_key'][:16]}...")
        click.echo(f"  Private key: {device_info['private_key'][:16]}...")
        click.echo(f"  ⚠️  Save the private key securely!")
        
        # Also save device info
        device_path = Path(input_dir) / ".splat-device.json"
        with open(device_path, "w") as f:
            json.dump(device_info, f, indent=2)
        click.echo(f"  Device info saved to: {device_path}")
    
    result = ca.attest(input_dir)
    
    # Save
    if output:
        out_path = Path(output)
    else:
        out_path = Path(input_dir) / "capture_attestation.json"
    
    save_attestation(result, out_path)
    click.echo(f"\n✅ Capture attestation saved to: {out_path}")
    click.echo(f"  Input hash:  {result['input_hash'][:32]}...")
    click.echo(f"  Frame hashes: {len(result['frame_hashes'])} coded frames")
    click.echo(f"  Signature:   {result['signature'][:32]}...")


@main.command()
@click.argument("splat_file", type=click.Path(exists=True))
@click.argument("input_hash")
@click.option("--pipeline-key", help="Ed25519 pipeline private key hex")
@click.option("--pipeline-id", default="gaussian-splatting", help="Pipeline identifier")
@click.option("--pipeline-version", default="0.1.0", help="Pipeline version")
@click.option("--input-attestation", type=click.Path(exists=True), help="Path to capture_attestation.json for binding verification")
@click.option("--output", "-o", help="Output .verify.json path")
def receipt(splat_file, input_hash, pipeline_key, pipeline_id, pipeline_version, input_attestation, output):
    """Create a training receipt for a trained splat model."""
    
    # Load input attestation if provided
    att_dict = None
    if input_attestation:
        att_dict = load_attestation(Path(input_attestation))
        # Verify input_hash matches
        att_input = att_dict.get("input_hash")
        if att_input and att_input != input_hash:
            click.echo(f"⚠️  Warning: input_hash doesn't match attestation!")
            click.echo(f"  Provided:  {input_hash[:16]}...")
            click.echo(f"  Attestation: {att_input[:16]}...")
            if not click.confirm("Continue anyway?"):
                sys.exit(1)
    
    # Create receipt
    if pipeline_key:
        tr = TrainingReceipt(
            pipeline_key=pipeline_key,
            pipeline_id=pipeline_id,
            pipeline_version=pipeline_version,
        )
    else:
        tr, pipeline_info = TrainingReceipt.create_pipeline(
            pipeline_id=pipeline_id,
            version=pipeline_version,
        )
        click.echo(f"Generated new pipeline key:")
        click.echo(f"  Pipeline: {pipeline_info['pipeline_name']}")
        click.echo(f"  Public key: {pipeline_info['pipeline_public_key'][:16]}...")
        
        pipeline_path = Path(splat_file).parent / ".splat-pipeline.json"
        with open(pipeline_path, "w") as f:
            json.dump(pipeline_info, f, indent=2)
        click.echo(f"  Pipeline info saved to: {pipeline_path}")
    
    result = tr.create_receipt(
        splat_path=splat_file,
        input_hash=input_hash,
        input_attestation=att_dict,
    )
    
    # Save
    if output:
        out_path = Path(output)
    else:
        out_path = Path(splat_file).with_suffix(Path(splat_file).suffix + ".receipt.json")
    
    save_receipt(result, out_path)
    click.echo(f"\n✅ Training receipt saved to: {out_path}")
    click.echo(f"  Model hash:  {result['model_hash'][:32]}...")
    click.echo(f"  Input hash:  {result['input_hash'][:32]}...")
    click.echo(f"  Format:       {result['model_format']}")
    click.echo(f"  Gaussians:    {result.get('gaussian_count', 'unknown')}")


@main.command()
@click.argument("splat_file", type=click.Path(exists=True))
@click.option("--verify-json", type=click.Path(exists=True), help="Path to .verify.json sidecar")
@click.option("--rpc-url", default="https://mainnet.base.org", help="RPC URL for Base L2")
@click.option("--contract", help="SplatRegistry contract address")
@click.option("--skip-chain", is_flag=True, help="Skip on-chain verification (offline mode)")
def verify(splat_file, verify_json, rpc_url, contract, skip_chain):
    """Verify a splat's provenance (on-chain + signatures)."""
    
    # Build registry client if contract provided
    registry = None
    if not skip_chain and contract:
        try:
            from .registry import SplatRegistryClient
            registry = SplatRegistryClient(
                contract_address=contract,
                rpc_url=rpc_url,
            )
        except ImportError:
            click.echo("⚠️  web3 not installed, skipping on-chain check")
            skip_chain = True
    
    result = verify_splat(
        splat_path=splat_file,
        verify_json_path=verify_json,
        registry=registry,
        skip_chain=skip_chain,
    )
    
    click.echo(f"\n{result.badge} {result.label}")
    click.echo(f"  Model hash:  {result.model_hash[:32]}...")
    if result.input_hash:
        click.echo(f"  Input hash:  {result.input_hash[:32]}...")
    click.echo(f"  Tier:        {result.tier}")
    click.echo(f"  Status:      {result.status.value}")
    if result.message:
        click.echo(f"  Details:     {result.message}")
    
    # Output JSON for programmatic use
    click.echo(f"\n--- JSON ---")
    click.echo(json.dumps(result.to_dict(), indent=2))


@main.command()
@click.option("--device", "key_type", flag_value="device", help="Generate device key")
@click.option("--pipeline", "key_type", flag_value="pipeline", help="Generate pipeline key")
def keygen(key_type):
    """Generate a new Ed25519 keypair."""
    private_hex, public_hex = generate_keypair()
    
    prefix = key_type or "generic"
    click.echo(f"Generated {prefix} Ed25519 keypair:")
    click.echo(f"  Private key: {private_hex}")
    click.echo(f"  Public key:  {public_hex}")
    click.echo(f"\n⚠️  Store the private key securely. Never commit it to git.")
    click.echo(f"The public key is used as the identity (device_id or pipeline_id).")


if __name__ == "__main__":
    main()