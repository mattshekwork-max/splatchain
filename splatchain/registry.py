"""On-chain registry client — interact with SplatRegistry smart contract."""

from __future__ import annotations

import json
from typing import Optional

# Eth imports are optional — the SDK works offline without web3
try:
    from web3 import Web3
    from web3.contract import Contract
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False


# SplatRegistry ABI — minimal, just what we need
REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "inputHash", "type": "bytes32"},
            {"name": "modelHash", "type": "bytes32"},
            {"name": "captureMethod", "type": "string"},
            {"name": "modelFormat", "type": "string"},
        ],
        "name": "attest",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "modelHash", "type": "bytes32"},
        ],
        "name": "getAttestation",
        "outputs": [
            {
                "components": [
                    {"name": "creator", "type": "address"},
                    {"name": "inputHash", "type": "bytes32"},
                    {"name": "modelHash", "type": "bytes32"},
                    {"name": "captureMethod", "type": "string"},
                    {"name": "modelFormat", "type": "string"},
                    {"name": "timestamp", "type": "uint256"},
                    {"name": "revoked", "type": "bool"},
                ],
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "modelHash", "type": "bytes32"},
            {"name": "reason", "type": "string"},
        ],
        "name": "revoke",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "modelHash", "type": "bytes32"},
            {"indexed": True, "name": "inputHash", "type": "bytes32"},
            {"indexed": False, "name": "creator", "type": "address"},
        ],
        "name": "SplatAttested",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "modelHash", "type": "bytes32"},
            {"indexed": False, "name": "reason", "type": "string"},
        ],
        "name": "SplatRevoked",
        "type": "event",
    },
]


class SplatRegistryClient:
    """
    Client for the SplatRegistry smart contract on Base L2.
    
    Usage:
        client = SplatRegistryClient(
            rpc_url="https://mainnet.base.org",
            contract_address="0x...",
            private_key="0x...",  # Optional, needed for attestation
        )
        
        # Attest a splat
        tx_hash = client.attest(
            input_hash="0xabc...",
            model_hash="0xdef...",
            capture_method="iphone_lidar",
            model_format="ply",
        )
        
        # Check attestation
        result = client.get_attestation(model_hash="0xdef...")
    """

    # Base L2 chain ID
    BASE_CHAIN_ID = 8453
    BASE_TESTNET_CHAIN_ID = 84532  # Base Sepolia

    def __init__(
        self,
        contract_address: str,
        rpc_url: str = "https://mainnet.base.org",
        private_key: Optional[str] = None,
    ):
        if not HAS_WEB3:
            raise ImportError(
                "web3 is required for on-chain operations. "
                "Install with: pip install web3"
            )
        
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.contract_address = contract_address
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=REGISTRY_ABI,
        )
        self.private_key = private_key
    
    @classmethod
    def base_testnet(cls, contract_address: str, private_key: Optional[str] = None):
        """Connect to Base Sepolia testnet."""
        return cls(
            contract_address=contract_address,
            rpc_url="https://sepolia.base.org",
            private_key=private_key,
        )
    
    def _hash_to_bytes32(self, hex_hash: str) -> bytes:
        """Convert a hex hash string to bytes32."""
        h = hex_hash.removeprefix("0x")
        if len(h) == 64:  # SHA-256 hex
            return bytes.fromhex(h)
        raise ValueError(f"Invalid hash: {hex_hash}")
    
    def attest(
        self,
        input_hash: str,
        model_hash: str,
        capture_method: str = "unknown",
        model_format: str = "ply",
    ) -> str:
        """
        Register a splat attestation on-chain.
        
        Args:
            input_hash: SHA-256 hash of input data (hex, no 0x prefix)
            model_hash: SHA-256 hash of the trained model (hex, no 0x prefix)
            capture_method: How the capture was made
            model_format: File format (ply, splat, ksplat)
        
        Returns:
            Transaction hash
        """
        if not self.private_key:
            raise ValueError("Private key required for attestation")
        
        account = self.w3.eth.account.from_key(self.private_key)
        
        tx = self.contract.functions.attest(
            self._hash_to_bytes32(input_hash),
            self._hash_to_bytes32(model_hash),
            capture_method,
            model_format,
        ).build_transaction({
            "from": account.address,
            "nonce": self.w3.eth.get_transaction_count(account.address),
            "chainId": self.w3.eth.chain_id,
            "gas": 200_000,
            "maxFeePerGas": self.w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": self.w3.to_wei(0.001, "gwei"),
        })
        
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()
    
    def get_attestation(self, model_hash: str) -> Optional[dict]:
        """
        Look up an attestation by model hash.
        
        Returns:
            Attestation dict or None if not found
        """
        result = self.contract.functions.getAttestation(
            self._hash_to_bytes32(model_hash)
        ).call()
        
        creator, input_hash, m_hash, capture_method, model_format, timestamp, revoked = result
        
        if creator == "0x" + "0" * 40:  # Empty address = not found
            return None
        
        return {
            "creator": creator,
            "input_hash": input_hash.hex() if isinstance(input_hash, bytes) else input_hash,
            "model_hash": m_hash.hex() if isinstance(m_hash, bytes) else m_hash,
            "capture_method": capture_method,
            "model_format": model_format,
            "timestamp": timestamp,
            "revoked": revoked,
        }
    
    def revoke(self, model_hash: str, reason: str = "revoked by attester") -> str:
        """Revoke a splat attestation. Requires attester role."""
        if not self.private_key:
            raise ValueError("Private key required for revocation")
        
        account = self.w3.eth.account.from_key(self.private_key)
        
        tx = self.contract.functions.revoke(
            self._hash_to_bytes32(model_hash),
            reason,
        ).build_transaction({
            "from": account.address,
            "nonce": self.w3.eth.get_transaction_count(account.address),
            "chainId": self.w3.eth.chain_id,
            "gas": 150_000,
            "maxFeePerGas": self.w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": self.w3.to_wei(0.001, "gwei"),
        })
        
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()
    
    def is_verified(self, model_hash: str) -> tuple[bool, str]:
        """
        Quick check if a model hash has a valid on-chain attestation.
        
        Returns:
            (is_valid, status_message)
        """
        att = self.get_attestation(model_hash)
        if att is None:
            return False, "Not found on registry"
        if att["revoked"]:
            return False, "Revoked"
        return True, f"Verified (Tier 1, attester: {att['creator'][:10]}...)"

    def get_tier(self, model_hash: str) -> int:
        """Get the trust tier for an attestation. 0 = not found."""
        att = self.get_attestation(model_hash)
        if att is None:
            return 0
        if att["revoked"]:
            return 0
        # Tier determination would check attester registry
        # For now, all valid attestations are Tier 1
        return 1