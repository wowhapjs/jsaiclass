import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=join(dirname(fileURLToPath(import.meta.url)),'..');
const ui=readFileSync(join(root,'src/main.tsx'),'utf8');
const css=readFileSync(join(root,'src/reference.css'),'utf8');
test('all six approved interface structures are represented by dynamic components',()=>{
 for(const marker of ['auth-hero-scene','auth-country-pill','home-welcome','card-rail','feed-chips','comment-teaser','sheet-wave-decor','hearts-hero-brand','hearts-items','modal-flower','picked-row'])
  assert.ok(ui.includes(marker),marker+' missing from UI');
});
test('standalone cultural SVGs have production sources, not flattened screenshot crops',()=>{
 for(const name of ['01_sejong_mark','05_rwanda_korea_ai_motif','06_heart_check','07_clapper','08_crown','09_wave_corner','10_textile_corner','20_sunburst','21_cherry_blossom_branch','22_hanok_eaves_lantern','23_agaseke_basket','24_rwanda_landscape','25_gorilla_foliage'])
  assert.ok(existsSync(join(root,'public/assets',name+'.svg')),name+' missing');
 assert.ok(!ui.includes('reference_interfaces/'));
});
test('comments reference excluded sorting chips, reactions and mock counts',()=>{
 assert.ok(ui.includes('teaser.map('));
 assert.ok(!ui.includes('Supportive</'));
 assert.ok(!ui.includes('Newest</'));
 assert.ok(!ui.includes('Top</'));
 assert.ok(ui.includes('c.author'));
});
test('feed retains swipe, sound, play, and accessible scroll controls',()=>{
 for(const marker of ['onFeedTouchEnd','onFeedWheel','pauseOrPlay','toggleSound','aria-pressed={!actuallyMuted}','role="region"','title-play-toggle'])
  assert.ok(ui.includes(marker),marker+' missing');
});
test('mobile design and reduced motion rules are present',()=>{
 for(const marker of ['.auth .auth-content','.home-hero-art','.comment-teaser','.hearts-items','.limit-modal','@media(max-width:390px)','@media(max-height:740px)','prefers-reduced-motion'])
  assert.ok(css.includes(marker),marker+' missing');
});
