// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
// ai-guardian-opencode-generation: v1
import type { Plugin } from '@opencode-ai/plugin';
import { createGuardianBridge } from '../ai-guardian/ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'opencode' });

export const AiGuardian: Plugin = async (ctx) => {
  const cwd = ctx.directory || process.cwd();

  return {
    async 'tool.execute.before'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
      const hookData = {
        hook_event_name: 'tool.execute.before',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        tool_name: input.tool,
        tool_use: { name: input.tool, input: output.args || {} },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        throw new Error(result.error || 'Blocked by ai-guardian');
      }
    },

    async 'chat.message'(input, output) {
      const text = (output.parts || [])
        .filter((p) => p.type === 'text' && !p.synthetic)
        .map((p) => p.text || p.content || '')
        .join('\\n');
      if (!text) return;
      const hookData = {
        hook_event_name: 'message.submit',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        prompt: text,
        session_id: input.sessionID,
        cwd,
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        output.parts.length = 0;
        try {
          await ctx.client.tui.showToast({
            query: { directory: cwd },
            body: {
              title: 'AI Guardian',
              message: '🛡️ ai-guardian blocked your message because it contained content identified as a secret. Original content was removed and cannot be recovered. Resend without credentials, tokens, or other sensitive values.',
              variant: 'error',
              duration: 8000,
            },
          });
          return;
        } catch {
          return;
        }
      }
    },

    async 'tool.execute.after'(input, output) {
      if (input.tool?.startsWith('ai-guardian')) return;
      const hookData = {
        hook_event_name: 'tool.execute.after',
        opencode_version: '1.0.0',
        hook_source: 'opencode',
        tool_name: input.tool,
        tool_response: { output: output.output || '' },
        tool_use: { name: input.tool, input: input.args || {} },
        session_id: input.sessionID,
        tool_use_id: input.callID,
        cwd,
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        throw new Error(result.error || 'Blocked by ai-guardian');
      }
      if (result.updatedOutput !== undefined) {
        output.output = result.updatedOutput;
      }
    },

    async 'session.end'(input) {
      guardian.run({ hook_event_name: 'SessionEnd', opencode_version: '1.0.0', hook_source: 'opencode', session_id: input?.sessionID, cwd });
    },
  };
};
