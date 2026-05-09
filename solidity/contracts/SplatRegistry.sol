// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title SplatChain Registry
 * @notice Blockchain-verified Gaussian Splat provenance.
 *         Links raw capture input_hash to trained model_hash,
 *         creating an immutable provenance chain.
 *
 * Trust tiers:
 *   Tier 1 — Self-attested (any wallet)
 *   Tier 2 — Verified attester (approved by DAO/multisig)
 *   Tier 3 — Hardware-attested (TEE/SGX pipeline, future)
 */
contract SplatRegistry {

    // ── Structs ──────────────────────────────────────────────────

    struct Attestation {
        address creator;         // Wallet that attested
        bytes32 inputHash;       // SHA-256 of raw input data
        bytes32 modelHash;       // SHA-256 of trained splat file
        string  captureMethod;   // e.g., "iphone_lidar", "dslr_photogrammetry"
        string  modelFormat;     // e.g., "ply", "splat", "ksplat"
        uint256 timestamp;       // Block timestamp
        uint8   tier;           // Trust tier (1, 2, or 3)
        bool    revoked;         // Whether attestation has been revoked
    }

    // ── Storage ──────────────────────────────────────────────────

    /// @dev modelHash => Attestation
    mapping(bytes32 => Attestation) public splats;

    /// @dev inputHash => modelHash (one input can produce one registered model)
    mapping(bytes32 => bytes32) public inputToModel;

    /// @dev creator => number of attestations
    mapping(address => uint256) public attestationCount;

    /// @dev Approved attesters (can create Tier 2 attestations)
    mapping(address => bool) public attesters;

    /// @dev Total attestation count
    uint256 public totalAttestations;

    // ── Access ──────────────────────────────────────────────────

    address public owner;
    address public pendingOwner;

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyAttester() {
        require(attesters[msg.sender], "Not approved attester");
        _;
    }

    // ── Events ──────────────────────────────────────────────────

    event SplatAttested(
        bytes32 indexed modelHash,
        bytes32 indexed inputHash,
        address indexed creator,
        string  captureMethod,
        string  modelFormat,
        uint8   tier
    );

    event SplatRevoked(
        bytes32 indexed modelHash,
        address indexed revoker,
        string  reason
    );

    event AttesterApproved(address indexed attester);
    event AttesterRevoked(address indexed attester);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // ── Constructor ──────────────────────────────────────────────

    constructor() {
        owner = msg.sender;
        attesters[msg.sender] = true;
        emit AttesterApproved(msg.sender);
    }

    // ── Attestation ──────────────────────────────────────────────

    /**
     * @notice Attest a Gaussian Splat's provenance.
     * @param inputHash    SHA-256 hash of raw input data (photos, LiDAR, etc.)
     * @param modelHash    SHA-256 hash of the trained .ply/.splat file
     * @param captureMethod  How the capture was made
     * @param modelFormat    File format of the model
     */
    function attest(
        bytes32 inputHash,
        bytes32 modelHash,
        string calldata captureMethod,
        string calldata modelFormat
    ) external {
        require(modelHash != bytes32(0), "Model hash cannot be zero");
        require(splats[modelHash].timestamp == 0, "Already attested");
        require(inputToModel[inputHash] == bytes32(0), "Input already bound to a model");

        uint8 tier = attesters[msg.sender] ? uint8(2) : uint8(1);

        splats[modelHash] = Attestation({
            creator: msg.sender,
            inputHash: inputHash,
            modelHash: modelHash,
            captureMethod: captureMethod,
            modelFormat: modelFormat,
            timestamp: block.timestamp,
            tier: tier,
            revoked: false
        });

        if (inputHash != bytes32(0)) {
            inputToModel[inputHash] = modelHash;
        }

        attestationCount[msg.sender]++;
        totalAttestations++;

        emit SplatAttested(modelHash, inputHash, msg.sender, captureMethod, modelFormat, tier);
    }

    /**
     * @notice Revoke an attestation. Only the original creator or owner.
     * @param modelHash  Hash of the model to revoke
     * @param reason     Why it's being revoked
     */
    function revoke(bytes32 modelHash, string calldata reason) external {
        Attestation storage att = splats[modelHash];
        require(att.timestamp != 0, "Not found");
        require(!att.revoked, "Already revoked");
        require(msg.sender == att.creator || msg.sender == owner, "Not creator or owner");

        att.revoked = true;

        emit SplatRevoked(modelHash, msg.sender, reason);
    }

    // ── View functions ───────────────────────────────────────────

    /**
     * @notice Get full attestation details by model hash.
     */
    function getAttestation(bytes32 modelHash) external view returns (Attestation memory) {
        return splats[modelHash];
    }

    /**
     * @notice Quick check: is this model verified and not revoked?
     */
    function isVerified(bytes32 modelHash) external view returns (bool) {
        Attestation storage att = splats[modelHash];
        return att.timestamp != 0 && !att.revoked;
    }

    /**
     * @notice Get the trust tier for a model (0 = not found).
     */
    function getTier(bytes32 modelHash) external view returns (uint8) {
        Attestation storage att = splats[modelHash];
        if (att.timestamp == 0) return 0;
        if (att.revoked) return 0;
        return att.tier;
    }

    /**
     * @notice Find which model was produced from a given input hash.
     */
    function getModelByInput(bytes32 inputHash) external view returns (bytes32) {
        return inputToModel[inputHash];
    }

    // ── Admin ────────────────────────────────────────────────────

    function approveAttester(address attester) external onlyOwner {
        attesters[attester] = true;
        emit AttesterApproved(attester);
    }

    function revokeAttester(address attester) external onlyOwner {
        attesters[attester] = false;
        emit AttesterRevoked(attester);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        pendingOwner = newOwner;
    }

    function acceptOwnership() external {
        require(msg.sender == pendingOwner, "Not pending owner");
        emit OwnershipTransferred(owner, msg.sender);
        owner = msg.sender;
        pendingOwner = address(0);
    }
}