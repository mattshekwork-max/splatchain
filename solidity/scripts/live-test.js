const hre = require("hardhat");

async function main() {
  const address = "0x80ef17276a998Dd5b0C784b7AFa08520703846e5";
  const [deployer] = await hre.ethers.getSigners();
  
  const SplatRegistry = await hre.ethers.getContractFactory("SplatRegistry");
  const registry = SplatRegistry.attach(address);

  console.log("=== SplatRegistry Live Test ===\n");
  console.log(`Contract: ${address}`);
  console.log(`Deployer: ${deployer.address}\n`);

  // ── Test 1: Attest a splat ──
  console.log("1. Attesting a splat...");
  
  // Simulate hashes (these would be SHA-256 of real files in production)
  const inputHash = "0x" + "ab".repeat(32);  // SHA-256 of raw input data
  const modelHash = "0x" + "cd".repeat(32);  // SHA-256 of trained splat file
  
  const tx1 = await registry.attest(
    inputHash,
    modelHash,
    "iphone_lidar",
    "ply"
  );
  const receipt1 = await tx1.wait();
  console.log(`   TX: ${receipt1.hash}`);
  console.log(`   Gas used: ${receipt1.gasUsed.toString()}`);
  console.log(`   Status: ${receipt1.status === 1 ? "✅ Success" : "❌ Failed"}\n`);

  // ── Test 2: Read the attestation back ──
  console.log("2. Reading attestation...");
  const att = await registry.getAttestation(modelHash);
  console.log(`   Creator: ${att.creator}`);
  console.log(`   Input hash: ${att.inputHash}`);
  console.log(`   Model hash: ${att.modelHash}`);
  console.log(`   Capture method: ${att.captureMethod}`);
  console.log(`   Model format: ${att.modelFormat}`);
  console.log(`   Timestamp: ${att.timestamp}`);
  console.log(`   Tier: ${att.tier}`);
  console.log(`   Revoked: ${att.revoked}\n`);

  // ── Test 3: Verify it ──
  console.log("3. Checking isVerified...");
  const verified = await registry.isVerified(modelHash);
  console.log(`   Verified: ${verified ? "✅ Yes" : "❌ No"}\n`);

  // ── Test 4: Get tier ──
  console.log("4. Getting trust tier...");
  const tier = await registry.getTier(modelHash);
  console.log(`   Tier: ${tier} (1=self-attested, 2=verified attester)\n`);

  // ── Test 5: Look up by input hash ──
  console.log("5. Looking up model by input hash...");
  const foundModel = await registry.getModelByInput(inputHash);
  console.log(`   Model hash: ${foundModel}\n`);

  // ── Test 6: Second attestation (Tier 2 — we're the approved attester) ──
  console.log("6. Attesting as approved attester (should be Tier 2)...");
  const inputHash2 = "0x" + "11".repeat(32);
  const modelHash2 = "0x" + "22".repeat(32);
  
  const tx2 = await registry.attest(
    inputHash2,
    modelHash2,
    "dslr_photogrammetry",
    "splat"
  );
  const receipt2 = await tx2.wait();
  console.log(`   TX: ${receipt2.hash}`);
  console.log(`   Status: ${receipt2.status === 1 ? "✅ Success" : "❌ Failed"}`);
  
  const att2 = await registry.getAttestation(modelHash2);
  console.log(`   Tier: ${att2.tier} (deployer is approved attester)\n`);

  // ── Test 7: Try to re-attest same model (should fail) ──
  console.log("7. Attempting duplicate attestation (should fail)...");
  try {
    const tx3 = await registry.attest(
      "0x" + "33".repeat(32),
      modelHash,  // same model hash
      "lidar",
      "ply"
    );
    await tx3.wait();
    console.log("   ❌ Should have reverted!");
  } catch (e) {
    console.log(`   ✅ Reverted as expected: ${e.message.substring(0, 80)}...\n`);
  }

  // ── Test 8: Revoke an attestation ──
  console.log("8. Revoking first attestation...");
  const tx4 = await registry.revoke(modelHash, "Test revocation");
  const receipt4 = await tx4.wait();
  console.log(`   TX: ${receipt4.hash}`);
  console.log(`   Status: ${receipt4.status === 1 ? "✅ Success" : "❌ Failed"}`);
  
  const isStillVerified = await registry.isVerified(modelHash);
  const tierAfterRevoke = await registry.getTier(modelHash);
  console.log(`   isVerified after revoke: ${isStillVerified ? "❌ Still verified" : "✅ No longer verified"}`);
  console.log(`   Tier after revoke: ${tierAfterRevoke} (0=revoked/not found)\n`);

  // ── Test 9: Total counts ──
  console.log("9. Counting attestations...");
  const total = await registry.totalAttestations();
  const ownerCount = await registry.attestationCount(deployer.address);
  console.log(`   Total: ${total}`);
  console.log(`   By deployer: ${ownerCount}`);

  console.log("\n=== All live tests complete ===");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });