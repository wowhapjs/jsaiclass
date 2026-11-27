import test from 'node:test';
import assert from 'node:assert/strict';
import {swipeDirection,stepVideo} from '../src/feedNavigation.mjs';
const TOTAL=18;
test('one finger gesture always changes at most one work',()=>{
 for(const pixels of [60,90,150,300,1200]){
  assert.equal(swipeDirection(3,-pixels),1);
  assert.equal(swipeDirection(3,pixels),-1);
  assert.equal(stepVideo(3,swipeDirection(3,-pixels),TOTAL),4);
  assert.equal(stepVideo(10,swipeDirection(3,pixels),TOTAL),9);
 }
});
test('horizontal gestures and tiny movements do not navigate',()=>{
 for(const [dx,dy] of [[1,10],[0,59],[150,80],[-200,-90],[0,0]]){
  assert.equal(swipeDirection(dx,dy),0);
  assert.equal(stepVideo(5,swipeDirection(dx,dy),TOTAL),5);
 }
});
test('last and first works wrap in both directions without skipping',()=>{
 assert.equal(stepVideo(1,-1,TOTAL),18);
 assert.equal(stepVideo(13,1,TOTAL),14);
 assert.equal(stepVideo(14,1,TOTAL),15);
 assert.equal(stepVideo(17,1,TOTAL),18);
 assert.equal(stepVideo(18,1,TOTAL),1);
 assert.equal(stepVideo(18,-1,TOTAL),17);
 assert.equal(stepVideo(12,1,TOTAL),13);
 assert.equal(stepVideo(2,-1,TOTAL),1);
 assert.equal(stepVideo(1,1,TOTAL),2);
 assert.equal(stepVideo(10,1000,TOTAL),11);
 assert.equal(stepVideo(10,-500,TOTAL),9);
 assert.equal(stepVideo(5,0,TOTAL),5);
});
test('all 18 forward and backward swipes form a cycle',()=>{
 let id=1;
 for(let i=0;i<TOTAL;i++)id=stepVideo(id,1,TOTAL);
 assert.equal(id,1);
 for(let i=0;i<TOTAL;i++)id=stepVideo(id,-1,TOTAL);
 assert.equal(id,1);
});
