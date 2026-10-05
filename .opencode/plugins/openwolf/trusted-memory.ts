import {recordReceipt} from './visibility.js';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

export interface MemoryApproval {
  version: 1;
  roots: string[];
  approved_by: string;
  approved_at: string;
  deployment: 'managed-harness';
  revoked_by?:string;revoked_at?:string;supersedes?:string;
  documents: Record<string, {content: string; sha256: string; source: string}>;
}
export interface MemoryTrust {status: 'ready' | 'unavailable' | 'revoked'; reason: string; approval?: MemoryApproval}
const digest = (s: string) => crypto.createHash('sha256').update(s).digest('hex');
/** Owner and effective access both matter (ACLs may grant writes despite mode bits).
 * Symlinks are rejected, including writable ancestors. No repository setting can
 * grant approval. The authority is provisioned under a separate OS principal.
 */
export function protectedPath(target: string): boolean {
  if (process.platform === 'win32' || !process.getuid || process.getuid() === 0) return false;
  let p = path.resolve(target);
  try {
    for (;;) {
      const st = fs.lstatSync(p);
      if (st.isSymbolicLink() || st.uid !== 0 || (st.mode & 0o022)) return false;
      try { fs.accessSync(p, fs.constants.W_OK); return false; } catch {}
      const parent = path.dirname(p);
      if (parent === p) return true;
      p = parent;
    }
  } catch { return false; }
}
export function memoryTrust(projectRoot: string): MemoryTrust {
  const root = fs.realpathSync(projectRoot);
  const store = process.env.OPENWOLF_TRUST_STORE ?? (process.platform === 'darwin' ? '/Library/Application Support/OpenWolf/trust' : '/var/lib/openwolf/trust');
  // A protected store is insufficient if an agent can replace its verifier.
  if (!protectedPath(fileURLToPath(import.meta.url))) return {status:'unavailable',reason:'Protected runtime and managed harness required; durable instruction injection is disabled.'};
  const snapshot = path.join(store, digest(root) + '.json');
  if (!protectedPath(snapshot)) return {status:'unavailable',reason:'No protected approval snapshot for this project.'};
  try {
    const a = JSON.parse(fs.readFileSync(snapshot,'utf8')) as MemoryApproval;
    if (a.version !== 1 || a.deployment !== 'managed-harness' || !Array.isArray(a.roots) || !a.roots.includes(root) || !a.approved_by || !Number.isFinite(Date.parse(a.approved_at)) || !a.documents) throw new Error('Invalid approval');
    if(a.revoked_at){if(!a.revoked_by||!Number.isFinite(Date.parse(a.revoked_at)))throw new Error('Invalid revocation');return {status:'revoked',reason:`Approval revoked by ${a.revoked_by} at ${a.revoked_at}; durable injection is disabled.`};}
    for (const [name,d] of Object.entries(a.documents)) {
      if (!/^[\w.-]+\.md$/.test(name) || typeof d.content !== 'string' || digest(d.content) !== d.sha256 || !d.source) throw new Error('Invalid approved document');
    }
    return {status:'ready',reason:'Protected approval snapshot loaded; managed harness is an operator prerequisite.',approval:a};
  } catch { return {status:'unavailable',reason:'Approval snapshot failed verification.'}; }
}
export function approvedMemory(wolfDir: string, name: string): string {
  try { const document=memoryTrust(path.dirname(wolfDir)).approval?.documents[name];if(document?.content)recordReceipt(path.dirname(wolfDir),{operation:'rule-verified',evidence:document.sha256});return document?.content??''; }
  catch { return ''; }
}
