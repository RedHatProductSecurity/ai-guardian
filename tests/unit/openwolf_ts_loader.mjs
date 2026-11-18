import { access } from "node:fs/promises"
import { fileURLToPath } from "node:url"

export async function resolve(specifier, context, nextResolve) {
  if (
    specifier.startsWith(".") &&
    specifier.endsWith(".js") &&
    context.parentURL?.includes("/.opencode/plugins/openwolf/")
  ) {
    const target = new URL(specifier.slice(0, -3) + ".ts", context.parentURL)
    try {
      await access(fileURLToPath(target))
      return { url: target.href, shortCircuit: true }
    } catch {
      // Leave non-TypeScript .js imports to Node's default resolver.
    }
  }

  return nextResolve(specifier, context)
}
