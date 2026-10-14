// ai-guardian-generated-version: __AI_GUARDIAN_VERSION__
// ai-guardian-opencode-generation: v2
import { createGuardianBridge } from '../ai-guardian/ai-guardian-bridge';

const guardian = createGuardianBridge({ ideType: 'opencode' });
const OPENCODE_VERSION = '2.0.0';
const SESSION_TITLE_TTL_MS = 30_000;
const SESSION_TITLE_TIMEOUT_MS = 500;
const MAX_SESSION_TITLES = 128;
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
  opencodeVersion: string = OPENCODE_VERSION,
): JsonRecord {
  return {
    hook_event_name: hookEventName,
    opencode_version: opencodeVersion,
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
    const cwd = ctx.location.directory || process.cwd();
    const opencodeVersion = ctx.app.version;
    // Cache only metadata for the exact session, including misses and concurrent
    // lookups. Never load messages/transcripts just to name a tray entry.
    const sessionTitles = new Map<string, { expires: number; title: Promise<string> }>();
    const readSessionTitle = (sessionID: string): Promise<string> => {
      const now = Date.now();
      const cached = sessionTitles.get(sessionID);
      if (cached && cached.expires > now) return cached.title;
      for (const [id, entry] of sessionTitles) {
        if (entry.expires <= now) sessionTitles.delete(id);
      }
      if (sessionTitles.size >= MAX_SESSION_TITLES) {
        const oldest = sessionTitles.keys().next().value;
        if (oldest !== undefined) sessionTitles.delete(oldest);
      }
      const title = (async () => {
        const controller = new AbortController();
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          const session = await Promise.race([
            ctx.session.get({ sessionID }, { signal: controller.signal }),
            new Promise<undefined>((resolve) => {
              timer = setTimeout(() => {
                controller.abort();
                resolve(undefined);
              }, SESSION_TITLE_TIMEOUT_MS);
            }),
          ]);
          return typeof session?.title === 'string' ? session.title.slice(0, 4096) : '';
        } catch {
          console.error('[ai-guardian] Could not read OpenCode session title');
          return '';
        } finally {
          if (timer !== undefined) clearTimeout(timer);
        }
      })();
      sessionTitles.set(sessionID, { expires: now + SESSION_TITLE_TTL_MS, title });
      return title;
    };
    const sessionHookData = async (
      hookEventName: string,
      sessionID: string,
      extra: JsonRecord = {},
    ): Promise<JsonRecord> => hookData(hookEventName, cwd, {
      ...extra,
      session_id: sessionID,
      session_title: await readSessionTitle(sessionID),
    }, opencodeVersion);

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
      }));
      if (result.blocked) {
        await recordRefusalNotice(
          event.sessionID,
          event.messageID,
          PROMPT_REFUSAL_NOTICE,
          'prompt-refusal',
        );
        throw new Error('Blocked by ai-guardian');
      }
    });

    await ctx.tool.hook('execute.before', async (event) => {
      if (event.tool?.startsWith('ai-guardian')) return;
      const input = (event.input || {}) as JsonRecord;
      const result = guardian.run(await sessionHookData('tool.execute.before', event.sessionID, {
        tool_name: event.tool,
        tool_use: { name: event.tool, input },
        tool_use_id: event.id,
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
      const input = (event.input || {}) as JsonRecord;
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
            if (hookEvent === 'SessionEnd') sessionTitles.delete(sessionID);
            guardian.run(
              hookEvent === 'SessionEnd'
                ? hookData(hookEvent, cwd, { session_id: sessionID }, opencodeVersion)
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
