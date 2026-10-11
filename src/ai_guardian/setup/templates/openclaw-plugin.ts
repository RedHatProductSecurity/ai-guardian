// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
import { definePluginEntry } from 'openclaw/plugin-sdk/plugin-entry';
import { createGuardianBridge } from './ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'openclaw' });

export default definePluginEntry({
  id: 'ai-guardian',
  name: 'AI Guardian',
  register(api) {
    api.on('before_tool_call', async (event) => {
      const hookData = {
        hook_event_name: 'pre_tool_use',
        tool_name: event.toolName,
        tool_input: event.params || {},
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        return { block: true, blockReason: result.error };
      }
    });

    api.on('after_tool_call', async (event) => {
      const output =
        typeof event.result === 'string'
          ? event.result
          : JSON.stringify(event.result || '');
      const hookData = {
        hook_event_name: 'post_tool_use',
        tool_name: event.toolName,
        tool_response: { output },
      };
      guardian.run(hookData);
    });

    api.on('message_received', async (event) => {
      const hookData = {
        hook_event_name: 'prompt_submit',
        prompt: event.content || '',
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        return { cancel: true, cancelReason: result.error };
      }
    });

    api.on('session_start', async () => {
      guardian.run({ hook_event_name: 'prompt_submit', prompt: '' });
    });

    api.on('session_end', async () => {
      guardian.run({ hook_event_name: 'session.end', hook_source: 'openclaw' });
    });
  },
});
