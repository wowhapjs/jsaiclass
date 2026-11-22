// Keep only the active work, the preceding work and the next two works in memory.
// A completed preload becomes a local Blob URL, so the next player can use real media bytes
// rather than relying on browsers to reuse speculative HTTP cache entries.
export function createMediaPreloader({
 urlFor,
 maxId=13,
 fetcher=(url,init)=>fetch(url,init),
 createObjectURL=blob=>URL.createObjectURL(blob),
 revokeObjectURL=url=>URL.revokeObjectURL(url)
}){
 const ready=new Map();
 let current=0,sequence=0,pending=null,request=null,disposed=false;
 const valid=id=>Number.isInteger(id)&&id>=1&&id<=maxId;
 function prune(id){
  for(const [videoId,url] of ready)
   if(videoId<id-1||videoId>id+2){ready.delete(videoId);revokeObjectURL(url)}
 }
 function stop(){
  sequence++;
  if(pending)pending.abort();
  pending=null;request=null;
 }
 function enter(id){
  if(!valid(id))throw new RangeError('Unknown video ID');
  stop();current=id;prune(id);
  return ready.get(id)||urlFor(id);
 }
 async function prepare(id){
  if(disposed||id!==current)return [];
  if(request)return request;
  const token=sequence;
  const run=(async()=>{
   const completed=[];
   for(const next of [id+1,id+2]){
    if(!valid(next)||disposed||token!==sequence)break;
    if(ready.has(next)){completed.push(next);continue}
    const abort=new AbortController();
    pending=abort;
    try{
     // Whole, small MP4 files are loaded in sequence: N+1 first, then N+2.
     // The current player has already started, so background traffic doesn't block first play.
     const response=await fetcher(urlFor(next),{
      method:'GET',credentials:'same-origin',cache:'no-store',signal:abort.signal
     });
     if(!response.ok||!response.headers.get('content-type')?.includes('video/mp4'))continue;
     const blob=await response.blob();
     if(disposed||abort.signal.aborted||token!==sequence)break;
     const url=createObjectURL(blob);
     ready.set(next,url);
     prune(id);
     completed.push(next);
    }catch(e){if(abort.signal.aborted||token!==sequence)break}
    finally{if(pending===abort)pending=null}
   }
   return completed;
  })();
  request=run;
  try{return await run}
  finally{if(request===run)request=null}
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
 function dispose(){
  disposed=true;clear();
 }
 return {enter,prepare,stop,forget,clear,dispose,getPreparedIds:()=>[...ready.keys()].sort((a,b)=>a-b)};
}
