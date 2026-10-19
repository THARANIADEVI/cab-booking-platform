const http = require('node:http');
const next = require('next');
const app = next({ dev: true, dir: process.cwd(), hostname: '127.0.0.1', port: 3000 });
const handle = app.getRequestHandler();
app.prepare().then(() => {
  http.createServer((req, res) => handle(req, res)).listen(3000, '127.0.0.1', () => console.log('Next.js ready at http://localhost:3000'));
}).catch(error => { console.error(error); process.exit(1); });
