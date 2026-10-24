#!/usr/bin/env node
/**
 * DC02: verifies a generated functional copy (business/ plus
 * business/FUNCTIONAL_SOURCE.json). Dependency-free (Node 18+), so the
 * consuming repository (rt-rma-mvp) can run it in CI without installing
 * anything from the source repository.
 *
 * Usage:
 *   node verify-functional-copy.mjs <repo-root> [--source-repo <path>] [--expect-commit <sha>]
 *
 * Checks:
 *  - the manifest exists and is well formed;
 *  - every listed file exists and its SHA-256 matches (line endings are
 *    normalized to LF, so a Windows checkout does not count as an edit);
 *  - business/ has no file that the manifest does not list (no manual additions);
 *  - with --expect-commit, the manifest names that commit;
 *  - with --source-repo, the commit exists in that clone of the source
 *    repository and every file equals its content at that commit.
 * Exit code 0 when the copy is intact, 1 otherwise.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";

const MANIFEST = "FUNCTIONAL_SOURCE.json";
const SOURCE_DIR = "business";

const hash = (buffer) => createHash("sha256").update(buffer.toString("utf8").replace(/\r\n/g, "\n")).digest("hex");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

/** Returns the list of problems found (empty when the copy is intact). */
export function verifyFunctionalCopy(root, { sourceRepo, expectCommit } = {}) {
  const problems = [];
  const dir = join(root, SOURCE_DIR);
  const manifestPath = join(dir, MANIFEST);
  if (!existsSync(manifestPath)) return [`falta ${SOURCE_DIR}/${MANIFEST}: la carpeta no es una copia generada (DC02)`];
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    return [`${MANIFEST} no es JSON valido: ${error.message}`];
  }
  if (!/^[0-9a-f]{40}$/.test(manifest.source_commit ?? "")) problems.push(`${MANIFEST}: source_commit invalido "${manifest.source_commit}"`);
  if (!Array.isArray(manifest.files) || manifest.files.length === 0) return [...problems, `${MANIFEST}: lista de archivos vacia`];
  if (expectCommit && manifest.source_commit !== expectCommit) problems.push(`la copia es del commit ${manifest.source_commit}, se esperaba ${expectCommit}`);

  const listed = new Set();
  for (const file of manifest.files) {
    listed.add(file.path);
    const full = join(dir, file.path);
    if (!existsSync(full)) {
      problems.push(`falta ${SOURCE_DIR}/${file.path}`);
      continue;
    }
    if (hash(readFileSync(full)) !== file.sha256) problems.push(`${SOURCE_DIR}/${file.path} fue modificado a mano (el SHA-256 no coincide con el manifiesto)`);
  }
  for (const full of walk(dir)) {
    const rel = relative(dir, full).replace(/\\/g, "/");
    if (rel !== MANIFEST && !listed.has(rel)) problems.push(`${SOURCE_DIR}/${rel} no figura en el manifiesto (agregado a mano)`);
  }

  if (sourceRepo && /^[0-9a-f]{40}$/.test(manifest.source_commit ?? "")) {
    try {
      execFileSync("git", ["cat-file", "-e", `${manifest.source_commit}^{commit}`], { cwd: sourceRepo, stdio: "ignore" });
      for (const file of manifest.files) {
        const original = execFileSync("git", ["show", `${manifest.source_commit}:${SOURCE_DIR}/${file.path}`], { cwd: sourceRepo, maxBuffer: 256 * 1024 * 1024 });
        if (hash(original) !== file.sha256) problems.push(`${SOURCE_DIR}/${file.path} no coincide con el commit ${manifest.source_commit} del repositorio de origen`);
      }
      const atCommit = execFileSync("git", ["ls-tree", "-r", "--name-only", manifest.source_commit, "--", SOURCE_DIR], { cwd: sourceRepo })
        .toString()
        .split("\n")
        .filter(Boolean)
        .map((p) => p.slice(SOURCE_DIR.length + 1));
      for (const path of atCommit) if (!listed.has(path)) problems.push(`el commit de origen tiene ${SOURCE_DIR}/${path}, que la copia no incluye`);
    } catch {
      problems.push(`el commit ${manifest.source_commit} no existe en el repositorio de origen ${sourceRepo}`);
    }
  }
  return problems;
}

function arg(name) {
  const at = process.argv.indexOf(`--${name}`);
  return at >= 0 ? process.argv[at + 1] : undefined;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const root = process.argv[2];
  if (!root || root.startsWith("--")) {
    console.error("Uso: node verify-functional-copy.mjs <repo-root> [--source-repo <path>] [--expect-commit <sha>]");
    process.exit(2);
  }
  const problems = verifyFunctionalCopy(root, { sourceRepo: arg("source-repo"), expectCommit: arg("expect-commit") });
  if (problems.length > 0) {
    console.error("La copia funcional NO esta sincronizada:");
    for (const p of problems) console.error(`  - ${p}`);
    process.exit(1);
  }
  const manifest = JSON.parse(readFileSync(join(root, SOURCE_DIR, MANIFEST), "utf8"));
  console.log(`OK: ${SOURCE_DIR}/ es la copia intacta del commit ${manifest.source_commit} (${manifest.files.length} archivos).`);
}
