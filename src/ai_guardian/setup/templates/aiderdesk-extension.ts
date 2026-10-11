// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
import type { Extension, ExtensionContext } from '@aiderdesk/extensions';
import { createGuardianBridge } from './ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'aiderdesk' });

export default class AiGuardianExtension implements Extension {
  static metadata = {
    name: 'AI Guardian',
    version: '1.0.0',
    description: 'Security scanning for tool calls, prompts, and file access',
    author: 'ai-guardian',
  };

  async onToolApproval(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: event.toolName,
      tool_input: event.input || {},
    };
    const result = guardian.run(hookData);
    if (result.blocked) {
      context.log(`Blocked tool: ${event.toolName} - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }

  async onToolCalled(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: event.toolName,
      tool_input: event.input || {},
    };
    const result = guardian.run(hookData);
    if (result.blocked) {
      context.log(`Blocked tool: ${event.toolName} - ${result.error}`, 'warn');
      return { blocked: true, output: { error: result.error } };
    }
  }

  async onToolFinished(event: any, context: ExtensionContext) {
    const output =
      typeof event.output === 'string'
        ? event.output
        : JSON.stringify(event.output || '');
    const hookData = {
      hook_event_name: 'post_tool_use',
      tool_name: event.toolName,
      tool_response: { output },
    };
    const result = guardian.run(hookData);
    if (result.updatedOutput !== undefined) {
      return {
        output: typeof result.updatedOutput === 'string'
          ? result.updatedOutput
          : JSON.stringify(result.updatedOutput),
      };
    }
    if (result.output) {
      return { output: result.output };
    }
  }

  async onPromptStarted(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'prompt_submit',
      prompt: event.prompt || '',
    };
    const result = guardian.run(hookData);
    if (result.blocked) {
      context.log(`Blocked prompt - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }

  async onFilesAdded(event: any, context: ExtensionContext) {
    const files = event.files || [];
    for (const file of files) {
      const hookData = {
        hook_event_name: 'pre_tool_use',
        tool_name: 'Read',
        tool_input: { file_path: file.path || file },
      };
      const result = guardian.run(hookData);
      if (result.blocked) {
        context.log(`Blocked file: ${file.path || file} - ${result.error}`, 'warn');
        return { files: [] };
      }
    }
  }

  async onBeforeCommit(event: any, context: ExtensionContext) {
    const hookData = {
      hook_event_name: 'pre_tool_use',
      tool_name: 'Bash',
      tool_input: { command: 'git commit -m ' + JSON.stringify(event.message || '') },
    };
    const result = guardian.run(hookData);
    if (result.blocked) {
      context.log(`Blocked commit - ${result.error}`, 'warn');
      return { blocked: true };
    }
  }
}
