"""Verify splat provenance — the core verification logic.

Used by viewers (PlayCanvas, etc.) and the CLI to check whether
a splat has valid on-chain attestation with matching signatures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from enum import Enum

from .crypto import sha256_file, verify_signature
from .registry import SplatRegistryClient


class VerificationStatus(Enum):
    VERIFIED = "verified"           # Full chain valid
    ATTESTED_UNVERIFIED = "attested_unverified"  # On-chain but sigs can't be checked
    REVOKED = "revoked"             # On-chain but revoked
    UNVERIFIED = "unverified"      # Not on registry
    OFFLINE = "offline"            # Can't reach registry
    SIG_INVALID = "sig_invalid"    # On-chain but signature doesn't match


class VerificationResult:
    """Result of verifying a splat's provenance."""
    
    def __init__(
        self,
        status: VerificationStatus,
        model_hash: str,
        input_hash: Optional[str] = None,
        attestation: Optional[dict] = None,
        capture_attestation: Optional[dict] = None,
        training_receipt: Optional[dict] = None,
        on_chain: Optional[dict] = None,
        message: str = "",
        tier: int = 0,
    ):
        self.status = status
        self.model_hash = model_hash
        self.input_hash = input_hash
        self.attestation = attestation
        self.capture_attestation = capture_attestation
        self.training_receipt = training_receipt
        self.on_chain = on_chain
        self.message = message
        self.tier = tier
    
    @property
    def is_verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED
    
    @property
    def badge(self) -> str:
        """Emoji badge for viewer rendering."""
        return {
            VerificationStatus.VERIFIED: "✅",
            VerificationStatus.ATTESTED_UNVERIFIED: "⚠️",
            VerificationStatus.REVOKED: "🚫",
            VerificationStatus.UNVERIFIED: "⚠️",
            VerificationStatus.OFFLINE: "📡",
            VerificationStatus.SIG_INVALID: "⚠️",
        }.get(self.status, "❓")
    
    @property
    def label(self) -> str:
        """Human-readable status label."""
        return {
            VerificationStatus.VERIFIED: "Verified Capture",
            VerificationStatus.ATTESTED_UNVERIFIED: "Attested (unverified sigs)",
            VerificationStatus.REVOKED: "Revoked",
            VerificationStatus.UNVERIFIED: "Unverified",
            VerificationStatus.OFFLINE: "Offline — cached verification only",
            VerificationStatus.SIG_INVALID: "Signature invalid",
        }.get(self.status, "Unknown")
    
    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "badge": self.badge,
            "label": self.label,
            "model_hash": self.model_hash,
            "input_hash": self.input_hash,
            "tier": self.tier,
            "message": self.message,
            "on_chain": self.on_chain,
        }
    
    def __repr__(self):
        return f"VerificationResult({self.badge} {self.label}, tier={self.tier})"


def verify_splat(
    splat_path: str | Path,
    verify_json_path: Optional[str | Path] = None,
    registry: Optional[SplatRegistryClient] = None,
    skip_chain: bool = False,
) -> VerificationResult:
    """
    Full verification of a splat's provenance.
    
    Args:
        splat_path: Path to the .ply/.splat file
        verify_json_path: Path to the .verify.json sidecar. If None, auto-detected.
        registry: On-chain registry client. If None, chain verification is skipped.
        skip_chain: Skip on-chain verification entirely
    
    Returns:
        VerificationResult with status, tier, and details
    """
    splat_path = Path(splat_path)
    
    if not splat_path.is_file():
        return VerificationResult(
            status=VerificationStatus.UNVERIFIED,
            model_hash="",
            message=f"File not found: {splat_path}",
        )
    
    # 1. Compute model hash
    model_hash = sha256_file(splat_path)
    
    # 2. Load sidecar if available
    if verify_json_path is None:
        verify_json_path = splat_path.with_suffix(splat_path.suffix + ".verify.json")
        if not Path(verify_json_path).exists():
            verify_json_path = splat_path.parent / (splat_path.name + ".verify.json")
    
    sidecar = None
    verify_path = Path(verify_json_path) if verify_json_path else None
    
    if verify_path and verify_path.exists():
        with open(verify_path) as f:
            sidecar = json.load(f)
    
    # 3. On-chain verification
    on_chain = None
    if not skip_chain and registry:
        try:
            on_chain = registry.get_attestation(model_hash)
        except Exception as e:
            # Can't reach chain — offline mode
            if sidecar and sidecar.get("chain", {}).get("tx_hash"):
                return VerificationResult(
                    status=VerificationStatus.OFFLINE,
                    model_hash=model_hash,
                    message=f"Registry unreachable: {e}",
                )
            return VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                model_hash=model_hash,
                message="Not on registry and no sidecar found",
            )
    
    # 4. Check on-chain status
    if on_chain:
        if on_chain.get("revoked"):
            return VerificationResult(
                status=VerificationStatus.REVOKED,
                model_hash=model_hash,
                input_hash=on_chain.get("input_hash"),
                on_chain=on_chain,
                message="Attestation has been revoked",
            )
    
    # 5. Verify signatures if sidecar available
    capture_att = None
    training_receipt = None
    input_hash = None
    
    if sidecar:
        input_hash = sidecar.get("input_hash")
        capture_att = sidecar.get("capture_attestation")
        training_receipt = sidecar.get("training_receipt")
        
        # Verify capture attestation signature
        if capture_att:
            device_public_key = capture_att.get("device_id", "")
            sig = capture_att.get("signature")
            if sig:
                capture_att_copy = dict(capture_att)
                capture_att_copy.pop("signature", None)
                if not verify_signature(device_public_key, capture_att_copy, sig):
                    return VerificationResult(
                        status=VerificationStatus.SIG_INVALID,
                        model_hash=model_hash,
                        input_hash=input_hash,
                        capture_attestation=capture_att,
                        training_receipt=training_receipt,
                        on_chain=on_chain,
                        message="Capture attestation signature is invalid",
                    )
        
        # Verify training receipt signature  
        if training_receipt:
            # We'd need the pipeline's public key — look it up from registry or sidecar
            pipeline_public_key = training_receipt.get("pipeline_public_key", "")
            if pipeline_public_key:
                sig = training_receipt.get("signature")
                if sig:
                    receipt_copy = dict(training_receipt)
                    receipt_copy.pop("signature", None)
                    if not verify_signature(pipeline_public_key, receipt_copy, sig):
                        return VerificationResult(
                            status=VerificationStatus.SIG_INVALID,
                            model_hash=model_hash,
                            input_hash=input_hash,
                            capture_attestation=capture_att,
                            training_receipt=training_receipt,
                            on_chain=on_chain,
                            message="Training receipt signature is invalid",
                        )
        
        # Check input_hash binding between capture and training receipt
        if capture_att and training_receipt:
            att_input = capture_att.get("input_hash")
            receipt_input = training_receipt.get("input_hash")
            if att_input and receipt_input and att_input != receipt_input:
                return VerificationResult(
                    status=VerificationStatus.SIG_INVALID,
                    model_hash=model_hash,
                    input_hash=input_hash,
                    capture_attestation=capture_att,
                    training_receipt=training_receipt,
                    on_chain=on_chain,
                    message=f"Input hash mismatch: capture={att_input[:16]}... receipt={receipt_input[:16]}...",
                )
    
    # 6. Final determination
    if on_chain and sidecar:
        # Both on-chain and sidecar — full verification
        tier = 1  # Self-attested
        # TODO: Check attester tier from registry
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            model_hash=model_hash,
            input_hash=input_hash,
            capture_attestation=capture_att,
            training_receipt=training_receipt,
            on_chain=on_chain,
            tier=tier,
            message="Full provenance verified: on-chain attestation + valid signatures",
        )
    elif on_chain:
        # On-chain but no sidecar for sig verification
        return VerificationResult(
            status=VerificationStatus.ATTESTED_UNVERIFIED,
            model_hash=model_hash,
            input_hash=on_chain.get("input_hash"),
            on_chain=on_chain,
            tier=1,
            message="On-chain attestation found but no sidecar for signature verification",
        )
    elif sidecar:
        # Sidecar but no on-chain — offline / not yet registered
        return VerificationResult(
            status=VerificationStatus.ATTESTED_UNVERIFIED,
            model_hash=model_hash,
            input_hash=input_hash,
            capture_attestation=capture_att,
            training_receipt=training_receipt,
            message="Sidecar provenance found but no on-chain attestation",
        )
    else:
        # Nothing found
        return VerificationResult(
            status=VerificationStatus.UNVERIFIED,
            model_hash=model_hash,
            message="No provenance data found — unverified",
        )