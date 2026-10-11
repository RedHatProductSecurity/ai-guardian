// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFileSync } from "node:child_process";

const GUARDIAN_BINARY = "ai-guardian";
const GUARDIAN_BINARY_ARGS: string[] = [];
const PI_MCP_ENABLED = __AI_GUARDIAN_PI_MCP_ENABLED__;
const MCP_TOOL_PREFIX = "mcp__ai-guardian__";
const MCP_FAILURE_TEXT = "AI Guardian MCP tools are unavailable.";

interface GuardianResult {
  blocked: boolean;
  error?: string;
  raw?: string;
  updatedOutput?: unknown;
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "toString" in value) {
    return String(value);
  }
  return "";
}

function parseGuardian(raw: string): GuardianResult | undefined {
  if (!raw.trim()) return undefined;
  try {
    const outer = JSON.parse(raw) as Record<string, any>;
    const inner = typeof outer.output === "string"
      ? JSON.parse(outer.output) as Record<string, any>
      : outer;
    const hookOutput = inner.hookSpecificOutput || outer.hookSpecificOutput || {};
    const updatedOutput = hookOutput.updatedToolOutput ?? hookOutput.updatedMCPToolOutput;
    const blocked = outer._blocked === true
      || inner._blocked === true
      || inner.decision === "block"
      || hookOutput.permissionDecision === "deny"
      || hookOutput.decision === "deny";
    const error = textValue(
      outer.systemMessage
        || inner.systemMessage
        || inner.reason
        || outer.reason,
    );
    return { blocked, error: error || undefined, raw, updatedOutput };
  } catch {
    return undefined;
  }
}

function runGuardian(hookData: Record<string, unknown>): GuardianResult {
  try {
    const stdout = execFileSync(GUARDIAN_BINARY, GUARDIAN_BINARY_ARGS, {
      input: JSON.stringify(hookData),
      encoding: "utf-8",
      timeout: 30000,
      env: { ...process.env, AI_GUARDIAN_IDE_TYPE: "pi" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    return parseGuardian(String(stdout)) || { blocked: false };
  } catch (error) {
    const failure = error as {
      status?: number;
      stdout?: unknown;
      stderr?: unknown;
    };
    const parsed = parseGuardian(textValue(failure.stdout));
    if (parsed) return parsed;
    if (failure.status === 1 || failure.status === 2) {
      return {
        blocked: true,
        error: textValue(failure.stderr) || "Blocked by ai-guardian",
      };
    }
    return { blocked: false };
  }
}

function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part): part is { type: string; text?: string } =>
      Boolean(part && typeof part === "object" && "type" in part),
    )
    .map((part) => part.type === "text" ? part.text || "" : "")
    .filter(Boolean)
    .join("\n");
}

function hookData(
  ctx: { cwd: string; sessionManager: { getSessionId(): string; getSessionFile(): string | undefined } },
  hookEventName: string,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    hook_event_name: hookEventName,
    pi_version: "1.0.0",
    hook_source: "pi",
    cwd: ctx.cwd,
    session_id: ctx.sessionManager.getSessionId(),
    transcript_path: ctx.sessionManager.getSessionFile(),
    ...extra,
  };
}

function updatedText(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "stdout" in value) {
    return textValue((value as { stdout?: unknown }).stdout);
  }
  if (value === undefined || value === null) return undefined;
  return JSON.stringify(value);
}

function replaceMessageText(message: any, replacement: string): any {
  if (typeof message.content === "string") {
    return { ...message, content: [{ type: "text", text: replacement }] };
  }
  if (!Array.isArray(message.content)) {
    return message;
  }
  let replaced = false;
  const content = message.content.map((part: any) => {
    if (!replaced && part && part.type === "text") {
      replaced = true;
      return { ...part, text: replacement };
    }
    return part;
  });
  return replaced ? { ...message, content } : message;
}

type McpClient = {
  connect(transport: unknown): Promise<void>;
  listTools(): Promise<{ tools?: Array<Record<string, any>> }>;
  callTool(request: Record<string, unknown>): Promise<Record<string, any>>;
  getServerVersion?(): { name?: string; version?: string } | undefined;
  close?(): Promise<void>;
};

type McpTransport = { close(): Promise<void> };

let mcpClient: McpClient | undefined;
let mcpTransport: McpTransport | undefined;
let mcpInitAttempted = false;

function mcpToolResult(result: Record<string, any>): Record<string, unknown> {
  const content = Array.isArray(result.content)
    ? result.content
    : [{ type: "text", text: MCP_FAILURE_TEXT }];
  return {
    content,
    details: {},
    isError: result.isError === true,
  };
}

async function closeMcp(): Promise<void> {
  const client = mcpClient;
  const transport = mcpTransport;
  mcpClient = undefined;
  mcpTransport = undefined;
  try {
    await client?.close?.();
  } catch {
    // The Pi process is already shutting down or the child has exited.
  }
  try {
    await transport?.close?.();
  } catch {
    // The Pi process is already shutting down or the child has exited.
  }
}

async function registerMcpTools(pi: ExtensionAPI, ctx: any): Promise<void> {
  if (!PI_MCP_ENABLED || mcpInitAttempted) return;
  mcpInitAttempted = true;

  let client: McpClient | undefined;
  let transport: McpTransport | undefined;
  try {
    const { Client } = await import("@modelcontextprotocol/sdk/client/index.js");
    const { StdioClientTransport } = await import(
      "@modelcontextprotocol/sdk/client/stdio.js"
    );
    const env = {
      ...Object.fromEntries(
        Object.entries(process.env).filter((entry): entry is [string, string] =>
          typeof entry[1] === "string",
        ),
      ),
      AI_GUARDIAN_PROJECT_DIR: ctx.cwd || process.cwd(),
    };
    transport = new StdioClientTransport({
      command: GUARDIAN_BINARY,
      args: [...GUARDIAN_BINARY_ARGS, "mcp-server"],
      env,
    }) as McpTransport;
    client = new Client({ name: "ai-guardian-pi", version: "1.0.0" }) as McpClient;
    await client.connect(transport);
    const server = client.getServerVersion?.();
    if (!server || server.name !== "ai-guardian") {
      throw new Error("unexpected MCP server identity");
    }

    const listed = await client.listTools();
    for (const tool of listed.tools || []) {
      if (!tool || typeof tool.name !== "string" || !tool.name) continue;
      const name = `${MCP_TOOL_PREFIX}${tool.name}`;
      const activeClient = client;
      pi.registerTool({
        name,
        label: `AI Guardian: ${tool.name}`,
        description: typeof tool.description === "string"
          ? tool.description
          : "AI Guardian security advisor",
        parameters: (tool.inputSchema || {
          type: "object",
          properties: {},
        }) as any,
        async execute(_toolCallId: string, params: Record<string, unknown>) {
          try {
            return mcpToolResult(await activeClient.callTool({
              name: tool.name,
              arguments: params || {},
            }));
          } catch {
            return {
              content: [{ type: "text", text: MCP_FAILURE_TEXT }],
              details: {},
              isError: true,
            };
          }
        },
      });
    }
    mcpClient = client;
    mcpTransport = transport;
  } catch {
    try {
      await client?.close?.();
    } catch {
      // The child may have failed closed before the client connected.
    }
    try {
      await transport?.close?.();
    } catch {
      // The child may have failed closed before the client connected.
    }
    ctx?.ui?.notify?.(MCP_FAILURE_TEXT, "error");
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("input", async (event, ctx) => {
    const result = runGuardian(hookData(ctx, "UserPromptSubmit", {
      prompt: event.text,
    }));
    if (result.blocked) {
      ctx.ui.notify(result.error || "Blocked by ai-guardian", "error");
      return { action: "handled" };
    }
    return { action: "continue" };
  });

  pi.on("before_provider_request", async (event, ctx) => {
    // User prompts and tool results are scanned by dedicated hooks. Scanning
    // this aggregate payload causes PII/secret false positives.
    return event.payload;
  });

  pi.on("tool_call", async (event, ctx) => {
    const result = runGuardian(hookData(ctx, "PreToolUse", {
      tool_name: event.toolName,
      tool_use: { name: event.toolName, input: event.input },
      tool_use_id: event.toolCallId,
    }));
    if (result.blocked) {
      return {
        block: true,
        terminate: true,
        reason: result.error || "Blocked by ai-guardian",
      };
    }
  });

  pi.on("tool_result", async (event, ctx) => {
    const result = runGuardian(hookData(ctx, "PostToolUse", {
      tool_name: event.toolName,
      tool_use: { name: event.toolName, input: event.input },
      tool_use_id: event.toolCallId,
      tool_response: { output: contentText(event.content) },
    }));
    if (result.blocked) {
      return {
        content: [{ type: "text", text: result.error || "Output blocked by ai-guardian" }],
        isError: true,
      };
    }
    const replacement = updatedText(result.updatedOutput);
    if (replacement !== undefined) {
      return { content: [{ type: "text", text: replacement }] };
    }
  });

  pi.on("message_end", async (event, ctx) => {
    if (event.message.role !== "assistant") return;
    const output = contentText(event.message.content);
    if (!output) return;
    const result = runGuardian(hookData(ctx, "PostToolUse", {
      tool_name: "AssistantResponse",
      tool_response: { output },
    }));
    if (result.blocked) {
      return {
        message: replaceMessageText(
          event.message,
          result.error || "Assistant output blocked by ai-guardian",
        ),
      };
    }
    const replacement = updatedText(result.updatedOutput);
    if (replacement !== undefined) {
      return { message: replaceMessageText(event.message, replacement) };
    }
  });

  pi.on("user_bash", async (event, ctx) => {
    const result = runGuardian(hookData(ctx, "PreToolUse", {
      tool_name: "Bash",
      tool_use: { name: "Bash", input: { command: event.command } },
    }));
    if (result.blocked) {
      return {
        result: {
          output: result.error || "Blocked by ai-guardian",
          exitCode: 1,
          cancelled: false,
          truncated: false,
        },
      };
    }
  });

  pi.on("session_start", async (_event, ctx) => {
    await registerMcpTools(pi, ctx);
    const result = runGuardian(hookData(ctx, "SessionStart"));
    if (result.blocked) {
      ctx.ui.notify(result.error || "Session blocked by ai-guardian", "error");
    }
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    await closeMcp();
    runGuardian(hookData(ctx, "SessionEnd"));
  });
}
