// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
// ai-guardian-kilo-generation: v1
import type { Plugin } from '@kilocode/plugin';
import { createGuardianBridge } from '../ai-guardian/ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'kilo' });
const PRE_TOOL_REFUSAL_NOTICE =
  'AI Guardian blocked this tool call before execution. The tool did not run. Do not retry or continue that operation. Tell the user it was blocked and wait for a new instruction.';
const PROMPT_REFUSAL_NOTICE =
  'AI Guardian blocked the previous prompt. Do not answer or continue that request. Ask the user to provide a new prompt without sensitive or blocked content.';
const POST_TOOL_REFUSAL_NOTICE =
  'AI Guardian blocked this tool result after execution. The tool ran, and its result was replaced with a fixed refusal. Do not infer that the tool’s side effects were undone. Tell the user it was flagged and wait for a new instruction.';
const TRUSTED_GUARDIAN_TOOLS = new Set([
  'ai-guardian__check_path',
  'ai-guardian__check_command',
  'ai-guardian__check_mcp_trust',
  'ai-guardian__sanitize_text',
  'ai-guardian__sanitize_directory',
  'ai-guardian__check_annotations',
  'ai-guardian__get_violations',
  'ai-guardian__get_version',
  'ai-guardian__get_config',
  'ai-guardian__get_scanner_status',
  'ai-guardian__get_scanner_supported',
  'ai-guardian__get_patterns_list',
  'ai-guardian__get_metrics',
  'ai-guardian__doctor',
  'ai-guardian__prepare_support_bundle',
  'ai-guardian__send_support_bundle',
  'ai-guardian__scan_directory',
  'ai-guardian__scan_directory_report',
]);

function isTrustedGuardianTool(toolName: unknown): boolean {
  return typeof toolName === 'string' && TRUSTED_GUARDIAN_TOOLS.has(toolName);
}

const AiGuardian: Plugin = async (ctx) => {
  const cwd = ctx.directory || ctx.worktree;

  return {
    async 'tool.execute.before'(input, output) {
      if (isTrustedGuardianTool(input.tool)) return;
      const result = guardian.run({
        hook_event_name: 'tool.execute.before',
        kilo_plugin_api: 'v1',
        hook_source: 'kilo',
        tool_name: input.tool,
        tool_use: { name: input.tool, input: output.args || {} },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
        plugin_cwd: cwd,
        workspace_source: cwd ? 'session' : 'unknown',
      });
      if (result.blocked) throw new Error(PRE_TOOL_REFUSAL_NOTICE);
      if (result.error) console.warn(`[ai-guardian] ${result.error}`);
    },

    async 'chat.message'(input, output) {
      const textParts = (output.parts || []).filter(
        (part) =>
          part.type === 'text' &&
          !('synthetic' in part && part.synthetic === true),
      );
      const prompt = textParts.map((part) => part.text || '').join('\n');
      if (!prompt) return;

      const result = guardian.run({
        hook_event_name: 'UserPromptSubmit',
        kilo_plugin_api: 'v1',
        hook_source: 'kilo',
        prompt,
        session_id: input.sessionID,
        cwd,
        plugin_cwd: cwd,
        workspace_source: cwd ? 'session' : 'unknown',
      });

      const firstPart = textParts[0];
      if (result.updatedPrompt !== undefined) {
        if (
          typeof result.updatedPrompt === 'string' &&
          result.updatedPrompt &&
          firstPart
        ) {
          // Rebuild the prompt parts from the verified, redacted text so other
          // parts cannot retain an unscanned copy of the original message.
          output.parts.splice(0, output.parts.length, {
            ...firstPart,
            text: result.updatedPrompt,
          });
          console.warn(
            '[ai-guardian] Sensitive content was redacted from the Kilo prompt before submission.',
          );
          return;
        }
        result.blocked = true;
      }

      if (result.blocked) {
        // Kilo's chat hook exposes mutable message parts but no typed prompt
        // cancellation result. Replace every part before returning so the
        // original prompt is not forwarded by the plugin callback.
        if (firstPart) {
          output.parts.splice(0, output.parts.length, {
            ...firstPart,
            text: PROMPT_REFUSAL_NOTICE,
          });
        }
        console.warn(
          '[ai-guardian] A Kilo prompt was blocked and replaced with a fixed refusal notice.',
        );
        return;
      }

      if (result.error) {
        console.warn('[ai-guardian] Kilo prompt scan returned a warning.');
      }
    },

    async 'tool.execute.after'(input, output) {
      if (isTrustedGuardianTool(input.tool)) return;
      const result = guardian.run({
        hook_event_name: 'tool.execute.after',
        kilo_plugin_api: 'v1',
        hook_source: 'kilo',
        tool_name: input.tool,
        tool_use: { name: input.tool, input: input.args || {} },
        tool_response: { output: output.output || '' },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
        plugin_cwd: cwd,
        workspace_source: cwd ? 'session' : 'unknown',
      });
      // Native Kilo 7.8.27 Bash result rewriting was manually confirmed; keep
      // broader result paths qualified separately. Never leave a known-sensitive
      // original alongside the rewrite.
      if (result.blocked) {
        output.output = POST_TOOL_REFUSAL_NOTICE;
        output.title = 'AI Guardian blocked tool result';
        output.metadata = {};
        console.warn(
          '[ai-guardian] Kilo tool output was replaced with a fixed refusal.',
        );
        return;
      }

      if (result.updatedOutput !== undefined) {
        if (typeof result.updatedOutput === 'string') {
          output.output = result.updatedOutput;
          output.title = 'AI Guardian sanitized tool result';
          output.metadata = {};
          console.warn('[ai-guardian] Kilo tool output was sanitized.');
        } else {
          output.output = POST_TOOL_REFUSAL_NOTICE;
          output.title = 'AI Guardian blocked tool result';
          output.metadata = {};
          console.warn(
            '[ai-guardian] Kilo output replacement was invalid; a fixed refusal was applied.',
          );
        }
        return;
      }

      if (result.error) {
        console.warn('[ai-guardian] Kilo post-tool scan returned a warning.');
      }
    },
  };
};

export default { id: 'ai-guardian-kilo', server: AiGuardian };
