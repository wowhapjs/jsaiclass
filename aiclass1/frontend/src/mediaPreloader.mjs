// Lightweight streaming warm-up: do NOT download whole MP4 files into Blob URLs.
// The visible <video> plays the authenticated /media/:id URL using native HTTP Range
// requests. These small, bounded next-video requests are only cache/network hints;
// browsers decide whether to reuse the ranges for the player.
export function createMediaPreloader({
 urlFor,
 maxId=13,
 fetcher=(url,init)=>fetch(url,init),
 onPrepared=()=>{},
 firstBytes=384*1024,
 secondBytes=192*1024
}){
 const ready=new Set(),pending=new Map();
 let current=0,generation=0,request=null,disposed=false;
 const valid=id=>Number.isInteger(id)&&id>=1&&id<=maxId;
 const wrap=n=>((n-1+maxId)%maxId)+1;
 const inWindow=id=>new Set([wrap(id-1),id,wrap(id+1),wrap(id+2)]);
 function prune(id){
  const keep=inWindow(id);
  for(const v of ready)if(!keep.has(v))ready.delete(v);
 }
 function stop(){
  generation++;
  for(const task of pending.values())task.controller.abort();
  pending.clear();request=null;
 }
 function enter(id){
  if(!valid(id))throw new RangeError('Unknown video ID');
  generation++;current=id;request=null;
  // The visible video now receives bandwidth priority over every warm-up.
  for(const task of pending.values())task.controller.abort();
  pending.clear();prune(id);
  return urlFor(id);
 }
 async function warm(id,bytes){
  if(ready.has(id))return true;
  const controller=new AbortController();
  pending.set(id,{controller});
  try{
   const response=await fetcher(urlFor(id),{
    method:'GET',credentials:'same-origin',cache:'default',
    headers:{Range:'bytes=0-'+(bytes-1)},signal:controller.signal
   });
   // Do not consume a 200 whole-file response from a server ignoring Range.
   if(response.status!==206||!response.headers.get('content-type')?.includes('video/mp4')){
    await response.body?.cancel?.().catch(()=>{});return false;
   }
   const data=await response.arrayBuffer();
   if(data.byteLength>bytes||controller.signal.aborted||disposed||!inWindow(current).has(id))return false;
   ready.add(id);prune(current);onPrepared(id);
   return true;
  }catch{return false}
  finally{if(pending.get(id)?.controller===controller)pending.delete(id)}
 }
 async function prepare(id){
  if(disposed||id!==current)return [];
  if(request?.id===id)return request.promise;
  const token=generation;
  const job=(async()=>{
   const completed=[];
   const targets=[wrap(id+1),wrap(id+2)].filter((target,i,arr)=>target!==id&&arr.indexOf(target)===i);
   for(const [index,target] of targets.entries()){
    if(disposed||token!==generation||id!==current)break;
    const ok=await warm(target,index===0?firstBytes:secondBytes);
    if(!disposed&&token===generation&&id===current&&ok)completed.push(target);
   }
   return completed;
  })();
  request={id,promise:job};
  try{return await job}
  finally{if(request?.promise===job)request=null}
 }
 function forget(id){ready.delete(id)}
 function clear(){stop();ready.clear();current=0}
 function dispose(){disposed=true;clear()}
 return {enter,prepare,stop,forget,clear,dispose,getPreparedIds:()=>[...ready].sort((a,b)=>a-b)};
}
