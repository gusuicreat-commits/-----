import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const port = Number(args[args.indexOf('--port') + 1] || 8766);
const mounts = {'/vendor/three/':'node_modules/three','/player/':'player','/fixtures/':'tests/fixtures'};
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.glb':'model/gltf-binary','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.mp4':'video/mp4','.wav':'audio/wav','.mp3':'audio/mpeg'};
http.createServer(async (req,res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const prefix = Object.keys(mounts).find(p => pathname.startsWith(p));
    if (!prefix) {res.writeHead(404);res.end('未找到资源');return;}
    const base = path.resolve(root,mounts[prefix]);
    let file = path.resolve(base,pathname.slice(prefix.length) || 'index.html');
    if (!file.startsWith(base + path.sep)) {res.writeHead(403);res.end('禁止访问');return;}
    if ((await stat(file)).isDirectory()) file = path.join(file,'index.html');
    const data = await readFile(file);
    const range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
    res.setHeader('Content-Type',mime[path.extname(file)] || 'application/octet-stream');
    res.setHeader('Accept-Ranges','bytes');
    if (range) {
      const start = Number(range[1]), end = Math.min(Number(range[2] || data.length-1),data.length-1);
      if(start > end) {res.writeHead(416);res.end();return;}
      res.writeHead(206,{'Content-Range':`bytes ${start}-${end}/${data.length}`,'Content-Length':end-start+1});res.end(data.subarray(start,end+1));
    } else {res.writeHead(200,{'Content-Length':data.length});res.end(data);}
  } catch {res.writeHead(404);res.end('未找到资源');}
}).listen(port,'127.0.0.1',() => console.log(`本地预览：http://127.0.0.1:${port}/player/`));
