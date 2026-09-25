import {visibilityMode} from './visibility.js';
/** Session-pinned npm runtimes. This module performs local I/O only. */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {pathToFileURL, fileURLToPath} from 'node:url';

export const RUNTIME_PROTOCOL = 1;
export const CHECK_INTERVAL = 24 * 3600_000;
export interface UpdateState {
  checkedAt?: number; latest?: string; selected?: string; previous?: string;
  status?: 'current'|'ready'|'available'|'error'|'unsupported'; detail?: string;
}
export const stableVersion = (v: unknown): v is string => typeof v === 'string' && /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(v) && v.split('.').every(n=>Number.isSafeInteger(Number(n)));
export function newer(a: string,b: string): boolean {
  if (!stableVersion(a)||!stableVersion(b)) return false;
  const x=a.split('.').map(Number),y=b.split('.').map(Number);
  for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i];
  return false;
}
export function compatible(a:string,b:string):boolean {
  if(!stableVersion(a)||!stableVersion(b))return false;
  const x=a.split('.'),y=b.split('.');
  return x[0]===y[0] && (x[0]!=='0'||x[1]===y[1]);
}
export function readObject(file:string):any {try{const v=JSON.parse(fs.readFileSync(file,'utf8'));return v&&typeof v==='object'&&!Array.isArray(v)?v:{}}catch{return {}}}
export function updatesDir(root:string):string{return path.join(root,'.wolf','updates')}
export function updateState(root:string):UpdateState {return readObject(path.join(updatesDir(root),'state.json'))}
export function atomicObject(file:string,value:unknown):void {
  fs.mkdirSync(path.dirname(file),{recursive:true});const temp=file+'.'+crypto.randomUUID()+'.tmp';
  try{const fd=fs.openSync(temp,'wx',0o600);try{fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}fs.renameSync(temp,file)}finally{try{fs.unlinkSync(temp)}catch{}}
}
export function updatePolicy(root:string):'compatible'|'all'|'notify'|'off' {
  const file=path.join(root,'.wolf','config.json');
  let cfg:any;
  try {
    const parsed=JSON.parse(fs.readFileSync(file,'utf8'));
    if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return 'off';
    cfg=parsed.openwolf;
  } catch(error) { if((error as NodeJS.ErrnoException).code!=='ENOENT')return 'off'; }
  if(cfg?.enabled===false || process.env.OPENWOLF_NO_UPDATE==='1')return 'off';
  const mode=cfg?.updates?.mode ?? 'compatible';
  return ['compatible','all','notify','off'].includes(mode)?mode:'off';
}
export function installedVersion(root:string):string {
  const v=readObject(path.join(root,'.wolf','hooks','runtime.json')).version;
  return stableVersion(v)?v:'unknown';
}
export function releasePackage(root:string,version:string):string {
  if(!stableVersion(version))throw new Error('Invalid release version');
  return path.join(updatesDir(root),'releases',version,'node_modules','openwolf');
}
export function readyRelease(root:string,version:unknown):string|undefined {
  if(!stableVersion(version))return;
  const pkg=releasePackage(root,version),meta=readObject(path.join(pkg,'package.json'));
  const ready=readObject(path.join(updatesDir(root),'releases',version,'ready.json'));
  if(meta.name==='openwolf'&&meta.version===version&&meta.openwolfRuntime?.protocol===RUNTIME_PROTOCOL&&ready.version===version)return pkg;
}
// Windows reports uid=0 for ordinary files; it is not POSIX root ownership.
// Protected authority on Windows is unsupported and remains disabled by its verifier.
const protectedRuntime=()=>process.platform!=='win32'&&fs.statSync(fileURLToPath(import.meta.url)).uid===0;
/** Never select a new version for an existing session (including resume). */
export function pinRuntime(root:string,session:string):string|undefined {
  if(!session || !stableVersion(installedVersion(root)) || protectedRuntime())return; // protected runtime or no identity => installed
  const dir=path.join(updatesDir(root),'pins');
  const file=path.join(dir,crypto.createHash('sha256').update(session).digest('hex')+'.json');
  let pin=readObject(file);
  if(!fs.existsSync(file)) {
    const candidate=updateState(root).selected;
    const version=updatePolicy(root)!=='off'&&stableVersion(candidate)&&newer(candidate,installedVersion(root))&&readyRelease(root,candidate)?candidate:null;
    fs.mkdirSync(dir,{recursive:true});
    const tmp=file+'.'+crypto.randomUUID()+'.tmp';
    try{fs.writeFileSync(tmp,JSON.stringify({version}),{flag:'wx',mode:0o600});try{fs.linkSync(tmp,file)}catch(e){if((e as NodeJS.ErrnoException).code!=='EEXIST')throw e}}finally{try{fs.unlinkSync(tmp)}catch{}}
    pin=readObject(file);
  }
  return readyRelease(root,pin.version);
}
/** At most one detached, bounded worker per project/check interval. */
export function scheduleUpdate(root:string):void {
  try {
    if(updatePolicy(root)==='off'||protectedRuntime())return;
    const state=updateState(root);
    if(typeof state.checkedAt==='number'&&Date.now()-state.checkedAt<CHECK_INTERVAL)return;
    const worker=path.join(root,'.wolf','hooks','update-worker.js');
    if(!fs.existsSync(worker)||!stableVersion(installedVersion(root)))return;
    const dir=updatesDir(root);fs.mkdirSync(dir,{recursive:true});
    const request=path.join(dir,'requested');
    try {if(Date.now()-fs.statSync(request).mtimeMs<300_000)return;fs.unlinkSync(request)}catch{}
    try{fs.writeFileSync(request,'',{flag:'wx',mode:0o600})}catch{return}
    const child=spawn(/^bun(?:\.exe)?$/.test(path.basename(process.execPath))?'node':process.execPath,[worker,root],{cwd:dir,detached:true,stdio:'ignore',windowsHide:true});
    child.on('error',()=>{try{fs.unlinkSync(request)}catch{}});child.unref();
  } catch {} // unavailable npm/network must never interrupt a coding session
}
const bridgeKey=Symbol.for('openwolf.hook.runtime');
export function bridgedInput():string|undefined{return (globalThis as any)[bridgeKey]?.input}
export async function delegateRuntime(root:string,hook:string,input:string):Promise<boolean> {
  if((globalThis as any)[bridgeKey])return false;
  if(!stableVersion(installedVersion(root)))return false;
  // A protected runtime must not execute repository-selected code.
  if(protectedRuntime())return false;
  let payload:any;try{payload=JSON.parse(input)}catch{return false}
  const pkg=pinRuntime(root,payload.session_id ?? '');
  if(!pkg || !/^[a-z-]+$/.test(hook))return false;
  const entry=path.join(pkg,'dist','hooks',hook+'.js');
  if(!fs.existsSync(entry))return false;
  (globalThis as any)[bridgeKey]={input};
  try{await import(pathToFileURL(entry).href);return true}catch{delete (globalThis as any)[bridgeKey];return false}
}
export function updateNotice(root:string,session:string):string|undefined {
  if(!session||updatePolicy(root)==='off'||visibilityMode(root)==='off')return;
  const s=updateState(root);if(!stableVersion(s.latest)||!newer(s.latest,installedVersion(root)))return;
  if(s.status!=='ready'&&s.status!=='available'&&s.status!=='unsupported')return;
  const id=crypto.createHash('sha256').update(s.status+':'+s.latest).digest('hex');
  const file=path.join(updatesDir(root),'notices',id);
  try{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,'',{flag:'wx',mode:0o600})}catch{return}
  if(s.status==='unsupported')return `OpenWolf ${s.latest} is available; this installation needs a runtime migration.`;
  return s.status==='ready'?`OpenWolf ${s.latest} is ready for new sessions; this session keeps its pinned runtime.`:`OpenWolf ${s.latest} is available; automatic upgrade is outside this project's update policy.`;
}
