import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,mkdir,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,dirname} from "node:path";
import {check} from "./check-docs.mjs";
async function fixture(files){
 const root=await mkdtemp(join(tmpdir(),"hamava-docs-"));
 for(const [p,contents] of Object.entries(files)){
  await mkdir(dirname(join(root,p)),{recursive:true});
  await writeFile(join(root,p),contents);
 }
 return root;
}
test("complete translated pairs and local links pass",async()=>{
 const root=await fixture({"README.md":"[guide](docs/guide.md)","README.fa.md":"[راهنما](docs/guide.fa.md)","docs/guide.md":"# Guide","docs/guide.fa.md":"# راهنما"});
 assert.deepEqual(await check(root),[]);
});
test("missing translation is detected",async()=>{
 const root=await fixture({"README.md":"# Guide"});
 assert.ok((await check(root)).some(x=>x.includes("README.fa.md")));
});
test("broken link detected but fenced examples and absolute URLs ignored",async()=>{
 const root=await fixture({"README.md":"[missing](docs/missing.md)\n~~~md\n[example](ignored.md)\n~~~\n[external](https://example.com)","README.fa.md":"# مستندات\n~~~md\n[مثال](ignored.md)\n~~~"});
 const errors=await check(root);
 assert.equal(errors.length,1);
 assert.ok(errors[0].includes("docs/missing.md"));
});
test("traversal rejected",async()=>{
 const root=await fixture({"README.md":"[escape](../private.md)","README.fa.md":"# ترجمه"});
 assert.ok((await check(root)).some(x=>x.includes("escaping")));
});
test("mismatched translated shell commands are detected", async()=>{
 const root=await fixture({"README.md":"# Guide\n~~~sh\ncurl /api/v1/ready\n~~~", "README.fa.md":"# Translation\n~~~sh\ncurl /api/v1/delete\n~~~"});
 assert.ok((await check(root)).some(x=>x.includes("executable") && x.includes("README.fa.md")));
});
test("an unclosed code fence fails validation", async()=>{
 const root=await fixture({"README.md":"# Guide\n~~~sh\ncurl /health", "README.fa.md":"# Translation\n~~~sh\ncurl /health\n~~~"});
 assert.ok((await check(root)).some(x=>x.includes("unclosed")));
});
test("a different marker cannot close a code fence", async()=>{
 const root=await fixture({"README.md":"# Guide\n~~~sh\ncurl /health\n```\n[ignored](missing.md)", "README.fa.md":"# Translation"});
 assert.ok((await check(root)).some(x=>x.includes("unclosed")));
});
test("different descriptions may share identical executable blocks", async()=>{
 const root=await fixture({"README.md":"# Guide\nEnglish prose\n~~~http\nGET /health\n~~~", "README.fa.md":"# Translation\nPersian prose\n~~~http\nGET /health\n~~~"});
 assert.deepEqual(await check(root),[]);
});
test("missing translated example is detected", async()=>{
 const root=await fixture({"README.md":"# Guide\n~~~http\nGET /health\n~~~", "README.fa.md":"# Translation"});
 assert.ok((await check(root)).some(x=>x.includes("code fence count")));
});
