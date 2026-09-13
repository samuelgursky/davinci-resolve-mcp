const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/analysis_dashboard.py'), 'utf8');
const section = source.slice(source.indexOf("    let sourceSelectionFilter = 'all';"), source.indexOf('    function renderReviewBin()'));
const context = vm.createContext({console, encodeURIComponent});
vm.runInContext(`
const nodes = new Map();
function element() {return {dataset:{}, style:{}, textContent:'', listeners:{},
 setAttribute(){}, querySelector(selector){if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);},
 querySelectorAll(){return [];}, addEventListener(name,fn){this.listeners[name]=fn;},
 showModal(){this.open=true;}, close(){this.open=false;this.listeners.close();}};}
const document={createElement:element,body:{append(){}}};
const $=()=>element();
const state={review:{clipList:{clips:[
 {clip_id:'a',clip_name:'A',representative_frame_index:1},
 {clip_id:'b',clip_name:'B',representative_frame_index:1},
 {clip_id:'c',clip_name:'C',representative_frame_index:1}]}}};
let fail=false, mismatch=false, block=null;
const persisted=new Map();
async function api(path,options) {
 const id=decodeURIComponent(path.split('/')[3]);
 if(options?.method==='POST') {
  if(block)await block;
  if(fail)return {success:false,error:'disk full'};
  const body=JSON.parse(options.body);
  if(!mismatch)persisted.set(id+':'+body.field_path,body.new_value);
  return {success:true};
 }
 return {success:true,corrections:{id}};
}
const readCorrectionValue=(c,type,id,field)=>persisted.get(id+':'+field);
const renderReviewBin=()=>{};
${section}
`, context);
const run = code => vm.runInContext(code, context);
async function show(index) {
 const pending=run(`showSourcePreview(${index})`);
 run('previewImage.onload()');
 await pending;
}
(async () => {
 run('previewQueue=filteredClips().slice();sourcePreview.showModal()');
 await show(0);
 assert.equal(run('previewReady'),true);
 run('fail=true');
 await run("saveSourceReview('user.selection','Exclude')");
 assert.equal(run('previewIndex'),0);
 assert.match(run('previewStatus.textContent'),/Save failed/);
 run('fail=false;mismatch=true');
 await run("saveSourceReview('user.selection','Include')");
 assert.equal(run('previewIndex'),0);
 run('mismatch=false');
 await run("saveSourceReview('user.rating',5)");
 assert.equal(run('previewIndex'),0);
 assert.equal(run("persisted.get('a:user.rating')"),5);
 run('block=new Promise(resolve=>globalThis.release=resolve)');
 const saving=run("saveSourceReview('user.selection','Include')");
 await run("saveSourceReview('user.selection','Exclude')");
 await run('showSourcePreview(2)');
 assert.equal(run('previewIndex'),0);
 run('release()');
 await new Promise(resolve=>setImmediate(resolve));
 run('previewImage.onload()');
 await saving;
 assert.equal(run('previewIndex'),1);
 assert.equal(run("persisted.get('a:user.selection')"),'Include');
 run("block=null;sourceSelectionFilter='non-excluded'");
 await show(0);
 const exclude=run("saveSourceReview('user.selection','Exclude')");
 await new Promise(resolve=>setImmediate(resolve));
 run('previewImage.onload()');
 await exclude;
 assert.equal(run('previewQueue[previewIndex].clip_id'),'b');
 assert.equal(run('filteredClips().length'),2);
 assert.equal(run("persisted.get('a:user.rating')"),5);
 await run("saveSourceReview('user.selection','Unreviewed')");
 assert.equal(run('previewQueue[previewIndex].clip_id'),'b');
 for (const id of ['b','c']) {
  const pending=run("saveSourceReview('user.selection','Exclude')");
  await new Promise(resolve=>setImmediate(resolve));
  if(id==='b')run('previewImage.onload()');
  await pending;
 }
 assert.equal(run('sourcePreview.open'),false);
 assert.equal(run('filteredClips().length'),0);
 run("sourceSelectionFilter='excluded';previewQueue=filteredClips().slice();sourcePreview.showModal()");
 const loading=run('showSourcePreview(0)');
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(run('previewReady'),false);
 run('previewImage.onerror()');
 await loading;
 assert.equal(run('previewReady'),false);
 assert.equal(run('previewBusy'),false);
 await run("saveSourceReview('user.selection','Include')");
 assert.equal(run("persisted.get('a:user.selection')"),'Exclude');
 await show(1);
 await show(0);
 assert.match(run('previewStatus.textContent'),/Exclude.*5 stars/);
 // Closing a pending load cannot re-enable review controls with stale data.
 const pending=run('showSourcePreview(1)');
 run('sourcePreview.close();previewImage.onload()');
 await pending;
 assert.equal(run('previewReady'),false);
 // A save completed after Close still updates the bin/filter state.
 run("sourceSelectionFilter='all';previewQueue=filteredClips().slice();sourcePreview.showModal()");
 await show(0);
 run('block=new Promise(resolve=>globalThis.release=resolve)');
 const closingSave=run("saveSourceReview('user.selection','Include')");
 run('sourcePreview.close();release()');
 await closingSave;
 assert.equal(run('sourcePreview.open'),false);
 assert.equal(run("state.review.clipList.clips[0].user_selection"),'Include');
 run("sourceSelectionFilter='excluded'");
 assert.equal(run('filteredClips().length'),2);
 console.log('PASS: persisted readback, save failures, filters, serial navigation, rating independence, loading guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
