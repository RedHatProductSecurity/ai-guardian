// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
// ai-guardian-kilo-generation: v1
import type { Plugin } from '@kilocode/plugin';
import { createGuardianBridge } from '../ai-guardian/ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'kilo' });
const PRE_TOOL_REFUSAL_NOTICE =
  'AI Guardian blocked this tool call before execution. The tool did not run. Do not retry or continue that operation. Tell the user it was blocked and wait for a new instruction.';
const POST_TOOL_REFUSAL_NOTICE =
  'AI Guardian flagged a tool result after execution. The tool ran. Native Kilo result handling is unverified; do not infer that the result was safely replaced or repeat it. Tell the user it was flagged and wait for a new instruction.';

const AiGuardian: Plugin = async (ctx) => {
  const cwd = ctx.directory || ctx.worktree;

  return {
    async 'tool.execute.before'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
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

    async 'tool.execute.after'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
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
      // The v7.8.27 callback runs before the tool result is finalized, but native
      // result-delivery behavior is unqualified. Do not install a transformed
      // result as though safe replacement had been established.
      if (result.blocked || result.updatedOutput !== undefined) {
        throw new Error(POST_TOOL_REFUSAL_NOTICE);
      }
      if (result.error) console.warn(`[ai-guardian] ${result.error}`);
    },
  };
};

export default { id: 'ai-guardian-kilo', server: AiGuardian };
