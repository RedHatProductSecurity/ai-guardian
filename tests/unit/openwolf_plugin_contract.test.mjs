import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import * as fs from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import test from "node:test"

import ignore from "../../.opencode/plugins/openwolf/ignore-runtime.ts"
import { createIgnoreMatcher } from "../../.opencode/plugins/openwolf/anatomy-scope.ts"
import { wolfDirExists } from "../../.opencode/plugins/openwolf/fs.ts"

function temporaryDirectory() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "openwolf-plugin-test-"))
}

test("gitignore wildcards match complete literal runs without losing valid positions", () => {
  const cases = [
    ["*test*.json", "target-test.json"],
    ["*foo*bar.txt", "xfooyfoo-bar.txt"],
    ["*test.json", "target-test.json"],
  ]

  for (const [pattern, file] of cases) {
    assert.equal(ignore().add(pattern).ignores(file), true, `${pattern} should ignore ${file}`)
  }
  assert.equal(ignore().add("*test*.json").ignores("target-test.txt"), false)
})

test("regular gitignore files continue to load", () => {
  const root = temporaryDirectory()
  try {
    fs.writeFileSync(path.join(root, ".gitignore"), "*test*.json\n")
    const ignored = createIgnoreMatcher(root)
    assert.equal(ignored("target-test.json", false), true)
    assert.equal(ignored("target-test.txt", false), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("symlinked gitignore files are ignored when O_NOFOLLOW is available", { skip: typeof fs.constants.O_NOFOLLOW !== "number" }, () => {
  const root = temporaryDirectory()
  try {
    const target = path.join(root, "rules")
    fs.writeFileSync(target, "*.log\n")
    fs.symlinkSync(target, path.join(root, ".gitignore"))
    assert.equal(createIgnoreMatcher(root)("ignored.log", false), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("FIFO gitignore files are rejected without blocking", { skip: process.platform === "win32" }, () => {
  const root = temporaryDirectory()
  try {
    const ignorePath = path.join(root, ".gitignore")
    execFileSync("mkfifo", [ignorePath])
    assert.equal(createIgnoreMatcher(root)("not-ignored.log", false), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test("OpenWolf enablement changes invalidate the config cache", () => {
  const root = temporaryDirectory()
  const wolfDir = path.join(root, ".wolf")
  const configPath = path.join(wolfDir, "config.json")
  try {
    fs.mkdirSync(wolfDir)
    fs.writeFileSync(configPath, '{"openwolf":{"enabled":false}}')
    fs.utimesSync(configPath, 1_000_000_000, 1_000_000_000)
    assert.equal(wolfDirExists(root), false)

    fs.writeFileSync(configPath, '{"openwolf":{"enabled": null}}')
    fs.utimesSync(configPath, 1_000_000_001, 1_000_000_001)
    assert.equal(fs.statSync(configPath).size, 30)
    assert.equal(wolfDirExists(root), true)

    fs.writeFileSync(configPath, '{"openwolf":{"enabled":false}}')
    fs.utimesSync(configPath, 1_000_000_002, 1_000_000_002)
    assert.equal(wolfDirExists(root), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
