// Standalone production verification bundle; never deployed as an app route.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import console from 'node:console';
import { execFileSync } from 'node:child_process';
const req=createRequire(fs.realpathSync('node_modules/vitest/package.json'));
const esbuild=req('esbuild');
const dest=path.resolve('.local/compare-browser/dist');fs.mkdirSync(dest,{recursive:true});
// CLI 2.72.7 local Kong does not translate sb_publishable for the WebSocket URL.
// Auth is still an anonymous user's authenticated session, never service_role.
const local = process.env.PROOF_SUPABASE_URL ? null : JSON.parse(execFileSync('pnpm',['exec','supabase','status','-o','json'],{encoding:'utf8',stdio:['ignore','pipe','ignore']}));
const url=process.env.PROOF_SUPABASE_URL||local.API_URL, key=process.env.PROOF_PUBLIC_KEY||local.ANON_KEY;
(async()=>{
 await esbuild.build({entryPoints:['tests/compare/browser-entry.ts'],bundle:true,minify:true,format:'esm',target:'es2022',outfile:dest+'/app.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"','process.env.NEXT_PUBLIC_MAP_STYLE_URL':'""','process.env.NEXT_PUBLIC_SUPABASE_URL':JSON.stringify(url),'process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY':JSON.stringify(key)},plugins:[{name:'test-router-worker',setup(b){b.onResolve({filter:/^next\/link$/},()=>({path:path.resolve('tests/compare/link.ts')}));b.onLoad({filter:/lib\/visibility\/browser.ts$/},args=>({contents:fs.readFileSync(args.path,'utf8').replace("new URL('../../workers/visibility.worker.ts', import.meta.url)","new URL('./worker.js', import.meta.url)"),loader:'ts'}));}}]});
 await esbuild.build({entryPoints:['workers/visibility.worker.ts'],bundle:true,minify:true,format:'esm',target:'es2022',outfile:dest+'/worker.js'});
 fs.copyFileSync('app/globals.css',dest+'/style.css');fs.writeFileSync(dest+'/index.html','<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="style.css"><div id="root"></div><script type="module" src="app.js"></script></html>');
 console.log('Production validation bundle built.');
})();
