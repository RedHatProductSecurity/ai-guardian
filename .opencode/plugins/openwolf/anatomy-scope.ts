import * as fs from 'node:fs';
import * as path from 'node:path';
import ignore from './ignore-runtime.js';
// Shared scanner/read eligibility. Reported by @Noboxer in #114.
export const DEFAULT_EXCLUDE_PATTERNS: readonly string[] = [
  // Node / JS
  // Note: ".netlify" only. A bare "netlify" would exclude netlify/functions/,
  // which is application source in every Netlify project.
  "node_modules", "dist", "build", ".next", ".nuxt", ".turbo", ".vercel",
  ".netlify", ".output", "coverage",
  // Python
  "__pycache__", ".venv", "venv", "site-packages", ".pytest_cache",
  ".mypy_cache", ".ruff_cache", ".tox", "*.pyc",
  // JVM / Android
  ".gradle", "target", ".m2",
  // Rust / Go / other build output
  ".cargo",
  // Tooling and editors
  ".git", ".wolf", ".cache", ".vscode", ".idea",
  // OS and editor droppings
  ".DS_Store", "Thumbs.db",
  // Generated assets
  "*.min.js", "*.min.css", "*.map",
];

export const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
  ".woff", ".woff2", ".ttf", ".eot", ".otf",
  ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
  ".exe", ".dll", ".so", ".dylib", ".bin",
  ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
  ".mp3", ".mp4", ".avi", ".mov", ".webm", ".ogg",
  ".sqlite", ".db",
  ".wasm",
  ".lock",
]);

const NOISE_BASENAMES = new Set([
  "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "composer.lock",
  "cargo.lock", "gemfile.lock", "poetry.lock", "uv.lock", "bun.lockb", "bun.lock",
  ".ds_store", "thumbs.db", ".phpunit.result.cache", ".eslintcache", ".tsbuildinfo",
]);
const NOISE_SUFFIXES = [".min.js", ".min.css", ".map", ".cache", ".tsbuildinfo", ".pyc", ".snap"];
const NOISE_DIRS = new Set([
  "coverage", ".nyc_output", "__snapshots__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
  // Agent config surfaces: steering the model toward its own harness config
  // via the index is noise (audit: .claude/*.md topped a project's importance
  // ranking), and the agent already knows these files natively.
  ".claude", ".codex", ".opencode", ".gemini", ".cursor", ".agents",
]);

function isNoiseFile(relPath: string): boolean {
  const parts = relPath.split("/");
  const basename = parts[parts.length - 1].toLowerCase();
  if (NOISE_BASENAMES.has(basename)) return true;
  if (NOISE_SUFFIXES.some((s) => basename.endsWith(s))) return true;
  if (parts.some((p) => NOISE_DIRS.has(p.toLowerCase()))) return true;
  return false;
}

const SENSITIVE_EXTENSIONS = new Set([
  ".pem", ".key", ".p8", ".p12", ".pfx", ".keystore", ".jks", ".ppk", ".kdbx", ".tfstate",
]);
const SENSITIVE_BASENAMES = new Set([".npmrc", ".netrc", ".htpasswd", ".pgpass"]);

function isSensitiveFile(basename: string): boolean {
  const lower = basename.toLowerCase();
  if (lower === ".env" || lower.startsWith(".env.")) return true;
  if (SENSITIVE_BASENAMES.has(lower)) return true;
  const dot = lower.lastIndexOf(".");
  if (dot >= 0 && SENSITIVE_EXTENSIONS.has(lower.slice(dot))) return true;
  if (/^id_(rsa|dsa|ecdsa|ed25519)/.test(lower)) return true;
  if (lower.includes("credential") || /^secrets\.(json|ya?ml|toml)$/.test(lower)) return true;
  return false;
}

export function shouldExclude(
  relPath: string,
  excludePatterns: string[]
): boolean {
  const parts = relPath.split("/");
  const basename = parts[parts.length - 1];

  // Always exclude sensitive files regardless of config
  if (isSensitiveFile(basename)) return true;

  // Always exclude generated/derived noise (lockfiles, caches, minified).
  if (isNoiseFile(relPath)) return true;

  for (const pattern of excludePatterns) {
    // Simple glob: check if any path segment matches
    if (pattern.startsWith("*.")) {
      const ext = pattern.slice(1);
      if (relPath.endsWith(ext)) return true;
    } else {
      if (parts.includes(pattern)) return true;
    }
  }
  return false;
}

export function isVirtualenvDir(dirPath: string): boolean {
  try {
    return fs.statSync(path.join(dirPath, "pyvenv.cfg")).isFile();
  } catch {
    return false;
  }
}

export function createIgnoreMatcher(root: string): (relative: string, directory: boolean) => boolean {
  const cache = new Map<string, ReturnType<typeof ignore>>();
  const rules = (dir: string) => {
    if (!cache.has(dir)) {
      let text = "";
      try { text = fs.readFileSync(path.join(root, dir, ".gitignore"), "utf8"); } catch {}
      cache.set(dir, ignore().add(text));
    }
    return cache.get(dir)!;
  };
  return (relative, directory) => {
    const parts = relative.replace(/\\/g, "/").split("/");
    let excluded = false;
    for (let depth = 0; depth < parts.length; depth++) {
      const base = parts.slice(0, depth).join("/");
      const target = parts.slice(depth).join("/") + (directory ? "/" : "");
      const result = rules(base).test(target);
      if (result.ignored) excluded = true;
      else if (result.unignored) excluded = false;
    }
    return excluded;
  };
}

export function anatomyReadEligible(root: string, relative: string): boolean {
  if (!relative || relative.startsWith('../') || path.isAbsolute(relative)) return false;
  let config: any = {};
  try { config = JSON.parse(fs.readFileSync(path.join(root,'.wolf/config.json'),'utf8')).openwolf?.anatomy ?? {}; } catch {}
  const patterns = Array.isArray(config.exclude_patterns) ? config.exclude_patterns.filter((p: unknown)=>typeof p==='string') : [...DEFAULT_EXCLUDE_PATTERNS];
  if (shouldExclude(relative, patterns) || BINARY_EXTENSIONS.has(path.extname(relative).toLowerCase())) return false;
  const parts = relative.split('/');
  const ignored = config.respect_gitignore === false ? undefined : createIgnoreMatcher(root);
  // Match the scanner's ancestor pruning, including nested ignore rules and virtualenvs.
  for (let i=1;i<=parts.length;i++) {
    const rel = parts.slice(0,i).join('/'), directory=i<parts.length;
    if (ignored?.(rel,directory) || directory && isVirtualenvDir(path.join(root,rel))) return false;
    try {
      const entry = fs.lstatSync(path.join(root, rel));
      if (directory ? !entry.isDirectory() : !entry.isFile()) return false;
    } catch { return false; }
  }
  try { return fs.statSync(path.join(root,relative)).size <= 1024*1024; } catch { return false; }
}
