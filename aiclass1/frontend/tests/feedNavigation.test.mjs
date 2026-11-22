import test from 'node:test';
import assert from 'node:assert/strict';
import {swipeDirection,stepVideo} from '../src/feedNavigation.mjs';
test('one finger gesture always changes at most one work',()=>{
 for(const pixels of [60,90,150,300,1200]){
  assert.equal(swipeDirection(3,-pixels),1);
  assert.equal(swipeDirection(3,pixels),-1);
  assert.equal(stepVideo(3,swipeDirection(3,-pixels),13),4);
  assert.equal(stepVideo(10,swipeDirection(3,pixels),13),9);
 }
});
test('horizontal gestures and tiny movements do not navigate',()=>{
 for(const [dx,dy] of [[1,10],[0,59],[150,80],[-200,-90],[0,0]]){
  assert.equal(swipeDirection(dx,dy),0);
  assert.equal(stepVideo(5,swipeDirection(dx,dy),13),5);
 }
});
test('last and first works wrap in both directions without skipping',()=>{
 assert.equal(stepVideo(1,-1,13),13);
 assert.equal(stepVideo(13,1,13),1);
 assert.equal(stepVideo(12,1,13),13);
 assert.equal(stepVideo(2,-1,13),1);
 assert.equal(stepVideo(1,1,13),2);
 assert.equal(stepVideo(10,1000,13),11);
 assert.equal(stepVideo(10,-500,13),9);
 assert.equal(stepVideo(5,0,13),5);
});
test('every forward swipe advances one work cyclically',()=>{
 let id=1;
 for(let i=0;i<13;i++)id=stepVideo(id,1,13);
 assert.equal(id,1);
});
