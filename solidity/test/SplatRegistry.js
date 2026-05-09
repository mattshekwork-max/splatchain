const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("SplatRegistry", function () {
  let registry;
  let owner;
  let addr1;
  let addr2;

  // Helper: compute bytes32 from hex string
  function hexToBytes32(hex) {
    return ethers.zeroPadValue(hex, 32);
  }

  // Helper: random bytes32
  function randomBytes32() {
    return ethers.hexlify(ethers.randomBytes(32));
  }

  beforeEach(async function () {
    [owner, addr1, addr2] = await ethers.getSigners();
    const SplatRegistry = await ethers.getContractFactory("SplatRegistry");
    registry = await SplatRegistry.deploy();
    await registry.waitForDeployment();
  });

  describe("Deployment", function () {
    it("should set owner as attester", async function () {
      expect(await registry.attesters(owner.address)).to.be.true;
    });

    it("should have zero attestations", async function () {
      expect(await registry.totalAttestations()).to.equal(0n);
    });
  });

  describe("Attestation", function () {
    it("should attest a splat", async function () {
      const inputHash = randomBytes32();
      const modelHash = randomBytes32();
      
      await registry.attest(inputHash, modelHash, "iphone_lidar", "ply");
      
      const att = await registry.getAttestation(modelHash);
      expect(att.creator).to.equal(owner.address);
      expect(att.inputHash).to.equal(inputHash);
      expect(att.modelHash).to.equal(modelHash);
      expect(att.captureMethod).to.equal("iphone_lidar");
      expect(att.modelFormat).to.equal("ply");
      expect(att.tier).to.equal(2n);  // Owner is approved attester → Tier 2
      expect(att.revoked).to.be.false;
    });

    it("should emit SplatAttested event", async function () {
      const inputHash = randomBytes32();
      const modelHash = randomBytes32();
      
      await expect(registry.attest(inputHash, modelHash, "drone", "splat"))
        .to.emit(registry, "SplatAttested")
        .withArgs(modelHash, inputHash, owner.address, "drone", "splat", 2);
    });

    it("should increment totalAttestations", async function () {
      await registry.attest(randomBytes32(), randomBytes32(), "dslr_photogrammetry", "ply");
      expect(await registry.totalAttestations()).to.equal(1n);
    });

    it("should assign Tier 1 to non-attesters", async function () {
      const inputHash = randomBytes32();
      const modelHash = randomBytes32();
      
      await registry.connect(addr1).attest(inputHash, modelHash, "unknown", "ply");
      
      const att = await registry.getAttestation(modelHash);
      expect(att.tier).to.equal(1n);  // Non-attester → Tier 1
    });

    it("should revert on duplicate modelHash", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      
      await expect(
        registry.attest(randomBytes32(), modelHash, "test2", "ply")
      ).to.be.revertedWith("Already attested");
    });

    it("should revert on zero modelHash", async function () {
      await expect(
        registry.attest(randomBytes32(), ethers.ZeroHash, "test", "ply")
      ).to.be.revertedWith("Model hash cannot be zero");
    });

    it("should revert on duplicate inputHash", async function () {
      const inputHash = randomBytes32();
      await registry.attest(inputHash, randomBytes32(), "test", "ply");
      
      await expect(
        registry.attest(inputHash, randomBytes32(), "test2", "ply")
      ).to.be.revertedWith("Input already bound to a model");
    });
  });

  describe("isVerified", function () {
    it("should return true for valid attestation", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      expect(await registry.isVerified(modelHash)).to.be.true;
    });

    it("should return false for non-existent hash", async function () {
      expect(await registry.isVerified(randomBytes32())).to.be.false;
    });

    it("should return false for revoked attestation", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      await registry.revoke(modelHash, "fraud");
      expect(await registry.isVerified(modelHash)).to.be.false;
    });
  });

  describe("getTier", function () {
    it("should return tier for attested model", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      expect(await registry.getTier(modelHash)).to.equal(2n);  // Owner is Tier 2
    });

    it("should return 0 for non-existent model", async function () {
      expect(await registry.getTier(randomBytes32())).to.equal(0n);
    });
  });

  describe("Revocation", function () {
    it("should allow creator to revoke", async function () {
      const modelHash = randomBytes32();
      await registry.connect(addr1).attest(randomBytes32(), modelHash, "test", "ply");
      
      await registry.connect(addr1).revoke(modelHash, "compromised");
      
      const att = await registry.getAttestation(modelHash);
      expect(att.revoked).to.be.true;
    });

    it("should allow owner to revoke", async function () {
      const modelHash = randomBytes32();
      await registry.connect(addr1).attest(randomBytes32(), modelHash, "test", "ply");
      
      await registry.revoke(modelHash, "dmca");
      
      const att = await registry.getAttestation(modelHash);
      expect(att.revoked).to.be.true;
    });

    it("should revert on double revoke", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      await registry.revoke(modelHash, "test");
      
      await expect(registry.revoke(modelHash, "test2"))
        .to.be.revertedWith("Already revoked");
    });

    it("should revert if not creator or owner", async function () {
      const modelHash = randomBytes32();
      await registry.connect(addr1).attest(randomBytes32(), modelHash, "test", "ply");
      
      await expect(
        registry.connect(addr2).revoke(modelHash, "unauthorized")
      ).to.be.revertedWith("Not creator or owner");
    });

    it("should emit SplatRevoked event", async function () {
      const modelHash = randomBytes32();
      await registry.attest(randomBytes32(), modelHash, "test", "ply");
      
      await expect(registry.revoke(modelHash, "fraud"))
        .to.emit(registry, "SplatRevoked")
        .withArgs(modelHash, owner.address, "fraud");
    });
  });

  describe("Admin", function () {
    it("should allow owner to approve attester", async function () {
      await registry.approveAttester(addr1.address);
      expect(await registry.attesters(addr1.address)).to.be.true;
    });

    it("should not allow non-owner to approve attester", async function () {
      await expect(
        registry.connect(addr1).approveAttester(addr2.address)
      ).to.be.revertedWith("Not owner");
    });

    it("should allow approved attester to create Tier 2", async function () {
      await registry.approveAttester(addr1.address);
      
      const modelHash = randomBytes32();
      await registry.connect(addr1).attest(randomBytes32(), modelHash, "test", "ply");
      
      const att = await registry.getAttestation(modelHash);
      expect(att.tier).to.equal(2n);
    });

    it("should allow owner to transfer ownership", async function () {
      await registry.transferOwnership(addr1.address);
      await registry.connect(addr1).acceptOwnership();
      expect(await registry.owner()).to.equal(addr1.address);
    });
  });

  describe("getModelByInput", function () {
    it("should return modelHash for known inputHash", async function () {
      const inputHash = randomBytes32();
      const modelHash = randomBytes32();
      await registry.attest(inputHash, modelHash, "test", "ply");
      
      expect(await registry.getModelByInput(inputHash)).to.equal(modelHash);
    });

    it("should return bytes32(0) for unknown inputHash", async function () {
      expect(await registry.getModelByInput(randomBytes32())).to.equal(ethers.ZeroHash);
    });
  });
});