import * as fs from 'node:fs';
import * as path from 'node:path';
import {execFileSync} from 'node:child_process';
/** Only durable bug knowledge is shared. Anatomy, usage, sessions and STATUS
 * always remain in the worktree's own .wolf directory.
 */
export function sharedWolfDir(wolfDir: string): string {
  const root=path.dirname(wolfDir);
  try {
    if (!fs.statSync(path.join(root,'.git')).isFile()) return wolfDir;
    const common=execFileSync('git',['rev-parse','--path-format=absolute','--git-common-dir'],{cwd:root,encoding:'utf8',stdio:['ignore','pipe','ignore'],timeout:1000}).trim();
    if (path.basename(common) !== '.git') return wolfDir;
    const shared=path.join(path.dirname(common),'.wolf');
    return fs.statSync(shared).isDirectory() ? shared : wolfDir;
  } catch {return wolfDir;}
}
