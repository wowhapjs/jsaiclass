import test from 'node:test';
import assert from 'node:assert/strict';
import {createMediaPreloader} from '../src/mediaPreloader.mjs';
const make=()=>{
 const calls=[],revoked=[],created=[];
 const preloader=createMediaPreloader({
  urlFor:id=>'/aiclass1/media/'+id,
  fetcher:async(url,options)=>{
   calls.push({url,options});
   return {ok:true,headers:new Headers({'content-type':'video/mp4'}),blob:async()=>new Blob([url],{type:'video/mp4'})};
  },
  createObjectURL:blob=>{const url='blob:reel/'+(created.length+1);created.push({url,blob});return url},
  revokeObjectURL:url=>revoked.push(url)
 });
 return {preloader,calls,created,revoked}
};
test('fully fetches N+1 then N+2 and uses prefetched bytes at navigation',async()=>{
 const x=make();assert.equal(x.preloader.enter(1),'/aiclass1/media/1');
 assert.deepEqual(await x.preloader.prepare(1),[2,3]);
 assert.deepEqual(x.calls.map(x=>x.url),['/aiclass1/media/2','/aiclass1/media/3']);
 assert.ok(x.calls.every(x=>x.options.credentials==='same-origin'&&x.options.cache==='no-store'));
 assert.equal(x.preloader.enter(2),'blob:reel/1');
 assert.deepEqual(await x.preloader.prepare(2),[3,4]);
 assert.deepEqual(x.calls.map(x=>x.url),['/aiclass1/media/2','/aiclass1/media/3','/aiclass1/media/4']);
 assert.equal(x.preloader.enter(3),'blob:reel/2');
 x.preloader.dispose();
 assert.equal(x.revoked.length,3);
});
test('last work preloads 1 and 2; previous work preloads 13 then 1',async()=>{
 const x=make();x.preloader.enter(12);
 assert.deepEqual(await x.preloader.prepare(12),[13,1]);
 assert.deepEqual(x.calls.map(c=>c.url),['/aiclass1/media/13','/aiclass1/media/1']);
 x.preloader.enter(13);
 assert.deepEqual(await x.preloader.prepare(13),[1,2]);
 assert.deepEqual(x.calls.map(c=>c.url),['/aiclass1/media/13','/aiclass1/media/1','/aiclass1/media/2']);
 assert.equal(x.preloader.enter(1),'blob:reel/2');
 assert.deepEqual(await x.preloader.prepare(1),[2,3]);
 assert.deepEqual(x.preloader.getPreparedIds(),[1,2,3,13]);
 x.preloader.dispose();
});
test('fast swipes abort obsolete downloads without storing stale media',async()=>{
 let resolveFetch,signal;
 const created=[];
 const preload=createMediaPreloader({
  urlFor:n=>'video-'+n,
  fetcher:(_url,opt)=>{signal=opt.signal;return new Promise(resolve=>{resolveFetch=resolve})},
  createObjectURL:()=>{created.push('blob');return 'blob:1'},
  revokeObjectURL:()=>{}
 });
 preload.enter(1);
 const inFlight=preload.prepare(1);
 await Promise.resolve();
 preload.enter(4);
 assert.equal(signal.aborted,true);
 resolveFetch({ok:true,headers:new Headers({'content-type':'video/mp4'}),blob:async()=>new Blob(['test'])});
 assert.deepEqual(await inFlight,[]);
 assert.deepEqual(created,[]);
 preload.dispose();
});
test('retains only previous, active and two next cached works',async()=>{
 const x=make();x.preloader.enter(1);await x.preloader.prepare(1);
 x.preloader.enter(2);await x.preloader.prepare(2);
 x.preloader.enter(3);await x.preloader.prepare(3);
 assert.deepEqual(x.preloader.getPreparedIds(),[2,3,4,5]);
 assert.equal(x.revoked.length,0);
 x.preloader.enter(4);
 assert.deepEqual(x.preloader.getPreparedIds(),[3,4,5]);
 assert.equal(x.revoked.length,1);
 x.preloader.dispose();
});

test('finishing an in-flight next work after swiping into it triggers autoplay handoff',async()=>{
 let resolveFetch,signal;
 const events=[];
 const preloader=createMediaPreloader({
  urlFor:id=>'media-'+id,
  fetcher:(_url,opt)=>{signal=opt.signal;return new Promise(resolve=>{resolveFetch=resolve})},
  createObjectURL:()=> 'blob:ready-2',
  revokeObjectURL:()=>{},
  onPrepared:(id,url)=>events.push({id,url})
 });
 preloader.enter(1);
 const preparing=preloader.prepare(1);
 await Promise.resolve();
 assert.equal(preloader.enter(2),'media-2');
 assert.equal(signal.aborted,false);
 resolveFetch({ok:true,headers:new Headers({'content-type':'video/mp4'}),blob:async()=>new Blob(['video'])});
 assert.deepEqual(await preparing,[]);
 assert.deepEqual(events,[{id:2,url:'blob:ready-2'}]);
 assert.equal(preloader.enter(2),'blob:ready-2');
 preloader.dispose();
});
test('cache pruning retains wrap-around previous and next works',async()=>{
 const x=make();x.preloader.enter(13);
 assert.deepEqual(await x.preloader.prepare(13),[1,2]);
 assert.deepEqual(x.preloader.getPreparedIds(),[1,2]);
 x.preloader.enter(1);
 assert.deepEqual(await x.preloader.prepare(1),[2,3]);
 assert.deepEqual(x.preloader.getPreparedIds(),[1,2,3]);
 x.preloader.dispose();
});
