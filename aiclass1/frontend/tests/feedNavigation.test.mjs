import test from 'node:test';
import assert from 'node:assert/strict';
import {swipeDirection,stepVideo} from '../src/feedNavigation.mjs';
test('one finger gesture always changes at most one work',()=>{
 for(const pixels of [60,90,150,300,1200]){
  assert.equal(swipeDirection(3,-pixels),1);
  assert.equal(swipeDirection(3,pixels),-1);
  assert.equal(stepVideo(3,swipeDirection(3,-pixels),14),4);
  assert.equal(stepVideo(10,swipeDirection(3,pixels),14),9);
 }
});
test('horizontal gestures and tiny movements do not navigate',()=>{
 for(const [dx,dy] of [[1,10],[0,59],[150,80],[-200,-90],[0,0]]){
  assert.equal(swipeDirection(dx,dy),0);
  assert.equal(stepVideo(5,swipeDirection(dx,dy),14),5);
 }
});
test('last and first works wrap in both directions without skipping',()=>{
 assert.equal(stepVideo(1,-1,14),14);
 assert.equal(stepVideo(13,1,14),14);
 assert.equal(stepVideo(14,1,14),1);
 assert.equal(stepVideo(14,-1,14),13);
 assert.equal(stepVideo(12,1,14),13);
 assert.equal(stepVideo(2,-1,14),1);
 assert.equal(stepVideo(1,1,14),2);
 assert.equal(stepVideo(10,1000,14),11);
 assert.equal(stepVideo(10,-500,14),9);
 assert.equal(stepVideo(5,0,14),5);
});
test('every forward swipe advances one work cyclically',()=>{
 let id=1;
 for(let i=0;i<14;i++)id=stepVideo(id,1,14);
 assert.equal(id,1);
});
