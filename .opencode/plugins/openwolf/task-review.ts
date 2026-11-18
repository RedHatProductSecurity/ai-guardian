/** Optional advisory review nudges, inspired by Casepod. No execution controls. */
import * as fs from 'node:fs';
import * as path from 'node:path';
import {createHash} from 'node:crypto';
import {mutateJSON} from './anatomy-lock.js';

interface ReviewState {
  task: string; last_at: number; active_ms: number; paused: boolean;
  failures: number; seen: string[]; last_nudge?: number; pending?: string; ended?: boolean;
}
const hash=(text:string)=>createHash('sha256').update(text).digest('hex');
function object(file:string):any {try {const value=JSON.parse(fs.readFileSync(file,'utf8'));return value && typeof value==='object' ? value : {}}catch{return {}}}
function policy(root:string) {
  const cfg=object(path.join(root,'.wolf/config.json')).openwolf;
  if(cfg?.enabled===false || cfg?.task_review?.enabled!==true)return null;
  const bounded=(v:unknown,fallback:number,min:number,max:number)=>typeof v==='number' && Number.isFinite(v) ? Math.min(max,Math.max(min,v)) : fallback;
  return {interval:bounded(cfg.task_review.interval_minutes,5,1,60)*60_000,
    threshold:Math.floor(bounded(cfg.task_review.failure_threshold,2,2,10)),
    cooldown:bounded(cfg.task_review.cooldown_minutes,5,1,60)*60_000};
}
function file(root:string,agent:string,session:string) {return path.join(root,'.wolf/hooks/task-review',hash(agent+':'+session)+'.json')}
function currentTask(root:string,agent:string,session:string):string {
  const active=object(path.join(root,'.wolf/handoff/active',hash(agent+':'+session)+'.json'));
  return typeof active.objective==='string' && active.objective ? hash(active.objective) : 'session-task';
}

export function observeTaskReview(root:string,agent:string,hook:string,input:any,now=Date.now()):void {
  const cfg=policy(root),session=input?.session_id;
  if(!cfg || typeof session!=='string' || !session || !['claude','codex'].includes(agent))return;
  if(!['user-prompt-submit','post-bash','post-read','post-write','stop','session-end'].includes(hook))return;
  const task=currentTask(root,agent,session);
  mutateJSON<ReviewState>(file(root,agent,session),{task,last_at:now,active_ms:0,paused:false,failures:0,seen:[]},25,state=>{
    if(state.task!==task || state.ended)Object.assign(state,{task,last_at:now,active_ms:0,paused:false,failures:0,seen:[],last_nudge:undefined,pending:undefined,ended:false});
    // Exclude time waiting for the next user turn. No timers or extra model turns.
    if(!state.paused)state.active_ms+=Math.max(0,now-state.last_at);
    state.last_at=now;
    state.paused=hook==='stop'||hook==='session-end';
    if(hook==='session-end'){state.ended=true;state.pending=undefined;return;}
    if(hook==='post-bash') {
      const exit=input.tool_response?.exit_code ?? input.tool_response?.exitCode;
      const id=typeof input.tool_use_id==='string' ? hash(input.tool_use_id) : undefined;
      // Unknown results and deliveries without stable IDs are not evidence of repeated failure.
      if(id && !state.seen.includes(id) && typeof exit==='number' && Number.isInteger(exit)) {
        state.seen=[...state.seen,id].slice(-128);
        state.failures=exit===0 ? 0 : state.failures+1;
      }
    }
    if(state.last_nudge!==undefined && now-state.last_nudge<cfg.cooldown)return;
    if(state.failures>=cfg.threshold)state.pending='repeated reported command failures';
    else if(state.active_ms>=cfg.interval)state.pending='time spent on the current task';
  });
}

function consumeTaskReview(root:string,agent:string,session:string,now:number):string | undefined {
  if(!policy(root) || !session || !['claude','codex'].includes(agent))return;
  const target=file(root,agent,session);
  if(!fs.existsSync(target))return;
  let reason:string|undefined;
  const written=mutateJSON<ReviewState>(target,{} as ReviewState,25,state=>{
    if(!state.pending || state.ended)return;
    reason=state.pending;state.pending=undefined;state.last_nudge=now;state.active_ms=0;state.failures=0;
  });
  if(!written || !reason)return;
  return `OpenWolf review suggestion (${reason}): briefly reassess the current task, evidence and strategy. Consider a smaller next check or a different approach if useful. Continue with the current plan if it remains justified. This is an advisory nudge; no approval or audit is required.`;
}

/** Advisory bookkeeping failure must not interfere with the normal hook response. */
export function takeTaskReview(root:string,agent:string,session:string,now=Date.now()):string | undefined {
  try {return consumeTaskReview(root,agent,session,now)} catch {return undefined}
}
