import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';
import {withFileLock,HOOK_LOCK_BUDGET_MS} from './anatomy-lock.js';
import {nextBugId} from './bug-id.js';
import {sharedWolfDir} from './knowledge-root.js';
export interface BugObservation {error_message:string;file:string;root_cause:string;fix:string;tags:string[];line?:number;status?:string;observed_worktree?:string;}
export function recordBug(wolfDir:string,bug:BugObservation):void {
  const dir=path.join(wolfDir,'bug-pending');fs.mkdirSync(dir,{recursive:true});
  const id=crypto.randomUUID();const file=path.join(dir,id+'.json');
  const fd=fs.openSync(file,'wx',0o600);
  try {fs.writeFileSync(fd,JSON.stringify({id,at:new Date().toISOString(),bug}));fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
  reconcileBugs(wolfDir);
}
export function reconcileBugs(wolfDir:string):boolean {
  const pending=path.join(wolfDir,'bug-pending');let names:string[];
  try {names=fs.readdirSync(pending).filter(n=>n.endsWith('.json'));} catch {return true;}
  if (!names.length) return true;
  const file=path.join(sharedWolfDir(wolfDir),'buglog.json');
  const ok=withFileLock(file+'.lock',HOOK_LOCK_BUDGET_MS,()=>{
    let log:any={version:1,bugs:[]};
    try {log=JSON.parse(fs.readFileSync(file,'utf8'));} catch(e) {if ((e as NodeJS.ErrnoException).code!=='ENOENT') throw e;}
    if (Array.isArray(log)) log={version:1,bugs:log};
    if (!log || !Array.isArray(log.bugs)) throw new Error('Invalid buglog; observations retained without overwriting it');
    log.applied_observations ??= {};
    for (const name of names) {
      let event:any;
      try {event=JSON.parse(fs.readFileSync(path.join(pending,name),'utf8'));} catch(e) {if ((e as NodeJS.ErrnoException).code==='ENOENT') continue;throw e;}
      if (!event.id || !event.bug || typeof event.bug.file!=='string') throw new Error('Invalid bug observation retained');
      if (log.applied_observations[event.id]) continue;
      const b=event.bug as BugObservation;
      const existing=log.bugs.find((old:any)=>old?.file===b.file && old.error_message===b.error_message && old.fix===b.fix);
      if (existing) {existing.occurrences=(Number.isSafeInteger(existing.occurrences)?existing.occurrences:0)+1;existing.last_seen=event.at;}
      else log.bugs.push({...b,id:nextBugId(log),timestamp:event.at,last_seen:event.at,occurrences:1,related_bugs:[]});
      log.applied_observations[event.id]=true;
    }
    const tmp=file+'.'+crypto.randomUUID()+'.tmp';
    try {const fd=fs.openSync(tmp,'wx',0o600);try {fs.writeFileSync(fd,JSON.stringify(log,null,2));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}fs.renameSync(tmp,file);}finally{try{fs.unlinkSync(tmp);}catch{}}
    for(const name of names){try{fs.unlinkSync(path.join(pending,name));}catch{}}
    return true;
  });
  return ok===true;
}
