import test from 'node:test';
import assert from 'node:assert/strict';
import {createMediaPreloader} from '../src/mediaPreloader.mjs';

const make=()=>{
 const calls=[],prepared=[];
 const preloader=createMediaPreloader({
  urlFor:id=>'/aiclass1/media/'+id,
  fetcher:async(url,options)=>{
   calls.push({url,options});
   return new Response(new Uint8Array(128),{status:206,headers:{'content-type':'video/mp4','content-range':'bytes 0-127/6000000'}});
  },
  onPrepared:id=>prepared.push(id)
 });
 return {preloader,calls,prepared};
};
test('native streaming URL is used; warm-up requests only limited initial ranges',async()=>{
 const x=make();
 assert.equal(x.preloader.enter(1),'/aiclass1/media/1');
 assert.deepEqual(await x.preloader.prepare(1),[2,3]);
 assert.deepEqual(x.calls.map(c=>c.url),['/aiclass1/media/2','/aiclass1/media/3']);
 assert.deepEqual(x.calls.map(c=>c.options.headers.Range),['bytes=0-393215','bytes=0-196607']);
 assert.ok(x.calls.every(c=>c.options.credentials==='same-origin'&&c.options.cache==='default'));
 assert.equal(x.preloader.enter(2),'/aiclass1/media/2');
 assert.deepEqual(await x.preloader.prepare(2),[3,4]);
 assert.deepEqual(x.calls.map(c=>c.url),['/aiclass1/media/2','/aiclass1/media/3','/aiclass1/media/4']);
 assert.equal(x.preloader.enter(3),'/aiclass1/media/3');
 x.preloader.dispose();
});
test('cyclic prefetch from 13 warms 1 and 2, and from 12 warms 13 and 1',async()=>{
 const x=make();
 x.preloader.enter(12);
 assert.deepEqual(await x.preloader.prepare(12),[13,1]);
 x.preloader.enter(13);
 assert.deepEqual(await x.preloader.prepare(13),[1,2]);
 assert.equal(x.preloader.enter(1),'/aiclass1/media/1');
 assert.deepEqual(await x.preloader.prepare(1),[2,3]);
 assert.deepEqual(x.preloader.getPreparedIds(),[1,2,3,13]);
 x.preloader.dispose();
});
test('quick swipes cancel background range traffic immediately to favor playback',async()=>{
 let resolveFetch,signal;
 const events=[];
 const p=createMediaPreloader({
  urlFor:n=>'media-'+n,
  fetcher:(_url,opt)=>{signal=opt.signal;return new Promise(resolve=>resolveFetch=resolve)},
  onPrepared:id=>events.push(id)
 });
 p.enter(1);
 const running=p.prepare(1);
 await Promise.resolve();
 assert.equal(p.enter(2),'media-2');
 assert.equal(signal.aborted,true);
 resolveFetch(new Response(new Uint8Array(128),{status:206,headers:{'content-type':'video/mp4'}}));
 assert.deepEqual(await running,[]);
 assert.deepEqual(events,[]);
 p.dispose();
});
test('cache markers retain previous, current, and only two next works',async()=>{
 const x=make();
 x.preloader.enter(1);await x.preloader.prepare(1);
 x.preloader.enter(2);await x.preloader.prepare(2);
 x.preloader.enter(3);await x.preloader.prepare(3);
 assert.deepEqual(x.preloader.getPreparedIds(),[2,3,4,5]);
 x.preloader.enter(4);
 assert.deepEqual(x.preloader.getPreparedIds(),[3,4,5]);
 x.preloader.dispose();
});
test('a server ignoring Range is not allowed to trigger whole-MP4 buffering',async()=>{
 const onPrepared=[];
 let consumed=0,cancelled=0;
 const p=createMediaPreloader({
  urlFor:id=>'media-'+id,
  fetcher:async()=>({
   status:200,
   headers:new Headers({'content-type':'video/mp4'}),
   body:{cancel:async()=>{cancelled++}},
   arrayBuffer:async()=>{consumed++;return new ArrayBuffer(10000000)}
  }),
  onPrepared:id=>onPrepared.push(id)
 });
 p.enter(1);
 assert.deepEqual(await p.prepare(1),[]);
 assert.equal(consumed,0);
 assert.equal(cancelled,2);
 assert.deepEqual(onPrepared,[]);
 p.dispose();
});
test('prepared callbacks signal readiness without changing the direct video URL',async()=>{
 const x=make();
 x.preloader.enter(13);
 await x.preloader.prepare(13);
 assert.deepEqual(x.prepared,[1,2]);
 assert.equal(x.preloader.enter(1),'/aiclass1/media/1');
 x.preloader.dispose();
});
