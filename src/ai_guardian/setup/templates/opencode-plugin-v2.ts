// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
// ai-guardian-opencode-generation: v2
import { createGuardianBridge } from '../ai-guardian/ai-guardian-bridge';
import { isAbsolute } from 'node:path';

const guardian = createGuardianBridge({ ideType: 'opencode' });
const SESSION_METADATA_TIMEOUT_MS = 500;
const MAX_SESSION_REQUESTS = 128;
const PROMPT_REFUSAL_NOTICE =
  'AI Guardian refused the previous prompt. The original prompt was not sent to the model. Do not answer or continue that request. Ask the user to provide a new prompt without the sensitive or blocked content.';
const PRE_TOOL_REFUSAL_NOTICE =
  'AI Guardian refused a tool call before execution. The tool did not run. Do not retry or continue that operation. Tell the user it was blocked and wait for a new instruction.';
const POST_TOOL_REFUSAL_NOTICE =
  'AI Guardian blocked a tool result after execution. The tool ran, but its result was withheld from the model. Do not infer or repeat the result. Tell the user it was blocked and wait for a new instruction.';

type JsonRecord = Record<string, unknown>;

function textValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  return String(value);
}

function contentText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return textValue(value);
  const record = value as JsonRecord;
  if (typeof record.output === 'string') return record.output;
  if (typeof record.text === 'string') return record.text;
  if (Array.isArray(record.content)) {
    return record.content
      .map((part) => {
        if (!part || typeof part !== 'object') return '';
        const item = part as JsonRecord;
        return typeof item.text === 'string' ? item.text : '';
      })
      .filter(Boolean)
      .join('\n');
  }
  return JSON.stringify(value) || '';
}

function hookData(
  hookEventName: string,
  cwd: string,
  extra: JsonRecord = {},
  opencodeVersion: string = 'unknown',
): JsonRecord {
  return {
    hook_event_name: hookEventName,
    opencode_version: opencodeVersion,
    integration_version: '__AI_GUARDIAN_VERSION__',
    hook_source: 'opencode',
    cwd,
    ...extra,
  };
}

function resultWithReplacement(original: unknown, replacement: unknown): unknown {
  if (original && typeof original === 'object' && !Array.isArray(original)) {
    const record = original as JsonRecord;
    if ('output' in record) {
      return { ...record, output: replacement };
    }
    if ('content' in record) {
      return {
        ...record,
        content: [{ type: 'text', text: textValue(replacement) }],
      };
    }
  }
  return { output: replacement };
}

export default {
  id: 'ai-guardian',
  async setup(ctx) {
    const pluginCwd = ctx.location.directory;
    const opencodeVersion = typeof ctx.app.version === 'string' ? ctx.app.version : 'unknown';
    type SessionMetadata = { title: string; directory: string };
    const unknownSession = (): SessionMetadata => ({ title: '', directory: '' });
    // Deduplicate concurrent lookups only. Caching a directory across events
    // can check a moved session against another workspace's policy.
    const sessionRequests = new Map<string, Promise<SessionMetadata>>();
    const readSessionMetadata = (sessionID: string): Promise<SessionMetadata> => {
      const pending = sessionRequests.get(sessionID);
      if (pending) return pending;
      if (sessionRequests.size >= MAX_SESSION_REQUESTS) return Promise.resolve(unknownSession());
      const request = (async () => {
        const controller = new AbortController();
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          const session = await Promise.race([
            ctx.session.get({ sessionID }, { signal: controller.signal }),
            new Promise<undefined>((resolve) => {
              timer = setTimeout(() => {
                controller.abort();
                resolve(undefined);
              }, SESSION_METADATA_TIMEOUT_MS);
            }),
          ]);
          const directory = session?.location?.directory;
          return {
            title: typeof session?.title === 'string' ? session.title.slice(0, 4096) : '',
            directory: typeof directory === 'string' && directory.length <= 4096
              && isAbsolute(directory) && !directory.includes('\0') ? directory : '',
          };
        } catch {
          console.error('[ai-guardian] Could not read OpenCode session metadata');
          return unknownSession();
        } finally {
          if (timer !== undefined) clearTimeout(timer);
        }
      })();
      sessionRequests.set(sessionID, request);
      void request.finally(() => {
        if (sessionRequests.get(sessionID) === request) sessionRequests.delete(sessionID);
      });
      return request;
    };
    const sessionHookData = async (
      hookEventName: string,
      sessionID: string,
      extra: JsonRecord = {},
    ): Promise<JsonRecord> => {
      const session = await readSessionMetadata(sessionID);
      return hookData(hookEventName, session.directory, {
        ...extra,
        session_id: sessionID,
        session_title: session.title,
        workspace_source: session.directory ? 'session' : 'unknown',
        plugin_cwd: pluginCwd,
      }, opencodeVersion);
    };

    const recordRefusalNotice = async (
      sessionID: string,
      sourceID: unknown,
      text: string,
      kind: string,
    ) => {
      try {
        await ctx.session.synthetic({
          sessionID,
          ...(typeof sourceID === 'string'
            ? { id: `msg_ai_guardian_${sourceID}` }
            : {}),
          text,
          description: `AI Guardian ${kind}`,
          metadata: { source: 'ai-guardian', kind },
          resume: false,
        });
      } catch {
        console.error(
          '[ai-guardian] Could not add a refusal notice to the OpenCode transcript',
        );
      }
    };

    await ctx.session.hook('prompt', async (event) => {
      const prompt = event.prompt?.text || '';
      if (!prompt) return;
      const result = guardian.run(await sessionHookData('message.submit', event.sessionID, {
        prompt,
        message_id: event.messageID,
      }));
      if (result.blocked) {
        // V2 prompt hooks transform admission and expose no typed denial result.
        // Replace the owned draft so the blocked payload is not admitted, while
        // allowing a safe turn to be recorded in the requested session.
        event.prompt = {
          text: PROMPT_REFUSAL_NOTICE,
          files: [],
          agents: [],
          skills: [],
        };
      }
    });

    await ctx.tool.hook('execute.before', async (event) => {
      if (event.tool?.startsWith('ai-guardian')) return;
      const input = event.input;
      const result = guardian.run(await sessionHookData('tool.execute.before', event.sessionID, {
        tool_name: event.tool,
        tool_use: { name: event.tool, input },
        tool_use_id: event.id,
        message_id: event.messageID,
      }));
      if (result.blocked) {
        await recordRefusalNotice(
          event.sessionID,
          event.id,
          PRE_TOOL_REFUSAL_NOTICE,
          'pre-tool-refusal',
        );
        throw new Error('AI Guardian blocked this tool call before execution');
      }
    });

    await ctx.tool.hook('execute.after', async (event) => {
      if (event.tool?.startsWith('ai-guardian')) return;
      const input = event.input;
      const error =
        event.status === 'completed' ? undefined : (event.error as unknown);
      const output =
        event.status === 'completed'
          ? contentText(event.result)
          : error && typeof error === 'object' && 'message' in error
            ? textValue((error as JsonRecord).message)
            : textValue(error);
      const result = guardian.run(await sessionHookData('tool.execute.after', event.sessionID, {
        tool_name: event.tool,
        tool_use: { name: event.tool, input },
        tool_response: { output },
        tool_use_id: event.id,
        message_id: event.messageID,
      }));
      if (result.blocked) {
        await recordRefusalNotice(
          event.sessionID,
          event.id,
          POST_TOOL_REFUSAL_NOTICE,
          'post-tool-refusal',
        );
        throw new Error(
          'AI Guardian blocked this tool result after execution; result withheld',
        );
      }
      if (event.status === 'completed' && result.updatedOutput !== undefined) {
        event.result = resultWithReplacement(
          event.result,
          result.updatedOutput,
        ) as typeof event.result;
      }
    });

    const controller = new AbortController();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          const record = event as unknown as JsonRecord;
          if (record.type !== 'session.idle' && record.type !== 'session.deleted') continue;
          const data = (record.data || {}) as JsonRecord;
          const sessionID = textValue(data.sessionID);
          if (sessionID) {
            // Idle ends a turn, not the session or its session-scoped pause.
            const hookEvent = record.type === 'session.deleted' ? 'SessionEnd' : 'Stop';
            guardian.run(
              hookEvent === 'SessionEnd'
                ? hookData(hookEvent, '', {
                    session_id: sessionID,
                    workspace_source: 'unknown',
                    plugin_cwd: pluginCwd,
                  }, opencodeVersion)
                : await sessionHookData(hookEvent, sessionID),
            );
          }
        }
      } catch {
        // The subscription is expected to end when the plugin is unloaded.
      }
    })();

    return () => controller.abort();
  },
};
