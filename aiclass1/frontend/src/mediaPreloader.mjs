// Keep only previous, active and next two works in memory, wrapping across the end.
// Real MP4s are fetched with authentication and stored as short-lived Blob URLs.
// An in-flight next video is preserved if the user swipes into that work mid-download.
export function createMediaPreloader({
 urlFor,
 maxId=14,
 fetcher=(url,init)=>fetch(url,init),
 createObjectURL=blob=>URL.createObjectURL(blob),
 revokeObjectURL=url=>URL.revokeObjectURL(url),
 onPrepared=()=>{}
}){
 const ready=new Map(),pending=new Map();
 let current=0,generation=0,request=null,disposed=false;
 const valid=id=>Number.isInteger(id)&&id>=1&&id<=maxId;
 const wrap=n=>((n-1+maxId)%maxId)+1;
 const inWindow=id=>new Set([wrap(id-1),id,wrap(id+1),wrap(id+2)]);
 function prune(id){
  const keep=inWindow(id);
  for(const [videoId,url] of ready)
   if(!keep.has(videoId)){ready.delete(videoId);revokeObjectURL(url)}
 }
 function stop(){
  generation++;
  for(const task of pending.values())task.controller.abort();
  pending.clear();request=null;
 }
 function enter(id){
  if(!valid(id))throw new RangeError('Unknown video ID');
  generation++;current=id;request=null;
  // Keep the almost-complete download of the work being entered; abort other obsolete work.
  for(const [other,task] of pending)if(other!==id){task.controller.abort();pending.delete(other)}
  prune(id);
  return ready.get(id)||urlFor(id);
 }
 function download(id){
  if(ready.has(id))return Promise.resolve(true);
  const existing=pending.get(id);
  if(existing)return existing.promise;
  const controller=new AbortController();
  const promise=(async()=>{
   try{
    const response=await fetcher(urlFor(id),{
     method:'GET',credentials:'same-origin',cache:'no-store',signal:controller.signal
    });
    if(!response.ok||!response.headers.get('content-type')?.includes('video/mp4'))return false;
    const blob=await response.blob();
    if(disposed||controller.signal.aborted||!inWindow(current).has(id))return false;
    const url=createObjectURL(blob);
    ready.set(id,url);
    prune(current);
    onPrepared(id,url);
    return true;
   }catch{return false}
   finally{if(pending.get(id)?.promise===promise)pending.delete(id)}
  })();
  pending.set(id,{controller,promise});
  return promise;
 }
 async function prepare(id){
  if(disposed||id!==current)return [];
  if(request?.id===id)return request.promise;
  const token=generation;
  const job=(async()=>{
   const completed=[];
   const targets=[wrap(id+1),wrap(id+2)].filter((target,i,arr)=>target!==id&&arr.indexOf(target)===i);
   for(const target of targets){
    if(disposed||token!==generation||id!==current)break;
    const ok=await download(target);
    if(!disposed&&token===generation&&id===current&&ok)completed.push(target);
   }
   return completed;
  })();
  request={id,promise:job};
  try{return await job}
  finally{if(request?.promise===job)request=null}
 }
 function forget(id){
  const url=ready.get(id);
  if(url){ready.delete(id);revokeObjectURL(url)}
 }
 function clear(){
  stop();
  for(const url of ready.values())revokeObjectURL(url);
  ready.clear();current=0;
 }
 function dispose(){disposed=true;clear()}
 return {enter,prepare,stop,forget,clear,dispose,getPreparedIds:()=>[...ready.keys()].sort((a,b)=>a-b)};
}
