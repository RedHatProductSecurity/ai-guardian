// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
import { execFileSync } from 'child_process';

export interface GuardianResult {
  blocked: boolean;
  error?: string;
  output?: string;
  updatedOutput?: unknown;
}

interface GuardianBridgeOptions {
  ideType: string;
  binary?: string;
  args?: string[];
  timeoutMs?: number;
}

interface ProcessFailure {
  status?: number;
  stdout?: unknown;
  stderr?: unknown;
}

type JsonRecord = Record<string, unknown>;

const GUARDIAN_BINARY = "ai-guardian";
const GUARDIAN_BINARY_ARGS: string[] = [];
const DEFAULT_TIMEOUT_MS = 30000;

function asRecord(value: unknown): JsonRecord | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as JsonRecord;
}

function textValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  return String(value);
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null);
}

function parseRecord(value: string): JsonRecord | undefined {
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return undefined;
  }
}

export function parseGuardianOutput(raw: unknown): GuardianResult | undefined {
  if (typeof raw !== 'string') return undefined;
  const output = raw.trim();
  if (!output) return undefined;

  const outer = parseRecord(output);
  if (!outer) return undefined;
  const inner = typeof outer.output === 'string'
    ? parseRecord(outer.output) || outer
    : outer;
  const hookOutput = asRecord(inner.hookSpecificOutput)
    || asRecord(outer.hookSpecificOutput)
    || {};
  const nestedDecision = asRecord(hookOutput.decision);
  const updatedOutput = firstDefined(
    hookOutput.updatedToolOutput,
    hookOutput.updatedMCPToolOutput,
    hookOutput.updated_mcp_tool_output,
    inner.updatedToolOutput,
    inner.updatedMCPToolOutput,
    inner.updated_mcp_tool_output,
    outer.updatedToolOutput,
    outer.updatedMCPToolOutput,
    outer.updated_mcp_tool_output,
  );
  const blocked = outer._blocked === true
    || inner._blocked === true
    || outer.decision === 'block'
    || inner.decision === 'block'
    || hookOutput.permissionDecision === 'deny'
    || hookOutput.decision === 'deny'
    || nestedDecision?.behavior === 'deny';
  const error = textValue(firstDefined(
    outer.systemMessage,
    inner.systemMessage,
    inner.reason,
    outer.reason,
    hookOutput.reason,
    outer.error,
    inner.error,
  )).trim();
  return {
    blocked,
    error: error || undefined,
    output,
    updatedOutput,
  };
}

export function createGuardianBridge(options: GuardianBridgeOptions) {
  const binary = options.binary || GUARDIAN_BINARY;
  const binaryArgs = options.args || GUARDIAN_BINARY_ARGS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  return {
    run(hookData: Record<string, unknown>): GuardianResult {
      try {
        const stdout = execFileSync(binary, [...binaryArgs, '--ide', options.ideType], {
          input: JSON.stringify(hookData),
          encoding: 'utf-8',
          timeout: timeoutMs,
          env: { ...process.env, AI_GUARDIAN_IDE_TYPE: options.ideType },
          stdio: ['pipe', 'pipe', 'pipe'],
        });
        const output = textValue(stdout).trim();
        return parseGuardianOutput(output) || {
          blocked: false,
          output: output || undefined,
        };
      } catch (error) {
        const failure = error as ProcessFailure;
        const output = textValue(failure.stdout).trim();
        const parsed = parseGuardianOutput(output);
        if (parsed) return parsed;
        if (failure.status === 1 || failure.status === 2) {
          return {
            blocked: true,
            error: textValue(failure.stderr).trim() || 'Blocked by ai-guardian',
            output: output || undefined,
          };
        }
        return { blocked: false, output: output || undefined };
      }
    },
  };
}
