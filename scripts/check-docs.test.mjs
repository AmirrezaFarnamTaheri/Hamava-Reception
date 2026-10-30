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
 const root=await fixture({"README.md":"[missing](docs/missing.md)\n~~~md\n[example](ignored.md)\n~~~\n[external](https://example.com)","README.fa.md":"# مستندات"});
 const errors=await check(root);
 assert.equal(errors.length,1);
 assert.ok(errors[0].includes("docs/missing.md"));
});
test("traversal rejected",async()=>{
 const root=await fixture({"README.md":"[escape](../private.md)","README.fa.md":"# ترجمه"});
 assert.ok((await check(root)).some(x=>x.includes("escaping")));
});
