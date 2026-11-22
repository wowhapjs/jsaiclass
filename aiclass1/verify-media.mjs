import {createReadStream,readFileSync} from 'node:fs';
import {stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
const here=fileURLToPath(new URL('.',import.meta.url));
const manifest=JSON.parse(readFileSync(join(here,'media-manifest.json'),'utf8'));
const dir=process.argv[2]||manifest.mediaDir;
let errors=0;
for(const x of manifest.entries){
 const p=resolve(dir,x.file);
 try{
  const info=await stat(p);
  const h=createHash('sha256');
  for await(const chunk of createReadStream(p))h.update(chunk);
  const actual=h.digest('hex');
  const ok=info.size===x.bytes&&actual===x.sha256;
  console.log((ok?'OK':'FAIL')+' Product '+String(x.id).padStart(2,'0')+' bytes='+info.size);
  if(!ok)errors++;
 }catch(e){console.log('FAIL Product '+String(x.id).padStart(2,'0')+' '+e.code);errors++}
}
if(errors){console.error('MEDIA_INTEGRITY_FAILED '+errors);process.exit(1)}
console.log('MEDIA_INTEGRITY_OK '+manifest.entries.length);
