// Granja La Estancia: public address relay.
// This branch is separate from DIGIT LABORAL's production branch.
// No page content, photographs, forms or original site files are modified.
const http = require('node:http');
const { Readable } = require('node:stream');

const ORIGIN = 'https://granja-la-estancia.bruno-alexander-cde.chatgpt.site';
const PORT = Number(process.env.PORT || 10000);

const excluded = new Set([
  'connection', 'transfer-encoding', 'keep-alive', 'proxy-authenticate',
  'proxy-authorization', 'te', 'trailer', 'upgrade', 'content-length',
  'content-encoding', 'set-cookie'
]);
const copiedRequestHeaders = [
  'accept', 'accept-language', 'user-agent', 'content-type', 'cookie',
  'range', 'if-none-match', 'if-modified-since', 'authorization',
  'x-requested-with'
];

function copyCookies(upstream, res, publicHost) {
  if (typeof upstream.headers.getSetCookie !== 'function') return;
  const cookieHeaders = upstream.headers.getSetCookie().map(cookie => (
    cookie.split('; Domain=')[0] 
  ));
  if (cookieHeaders.length) res.setHeader('set-cookie', cookieHeaders);
}

http.createServer(async (req, res) => {
  const requestPath = req.url && req.url.startsWith('/') ? req.url : '/';
  const upstreamUrl = ORIGIN + requestPath;
  const host = req.headers.host || 'granja-la-estancia.onrender.com';
  const publicOrigin = 'https://' + host;
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 45000);
  try {
    const headers = {};
    for (const k of copiedRequestHeaders) {
      if (req.headers[k]) headers[k] = req.headers[k];
    }
    const method = req.method || 'GET';
    const options = {
      method, headers, redirect: 'manual', signal: abort.signal
    };
    if (!['GET', 'HEAD'].includes(method)) {
      options.body = req;
      options.duplex = 'half';
    }

    const upstream = await fetch(upstreamUrl, options);
    res.statusCode = upstream.status;
    for (const [key, value] of upstream.headers.entries()) {
      const lower = key.toLowerCase();
      if (excluded.has(lower) || lower === 'access-control-allow-origin') continue;
      if (lower === 'location') {
        res.setHeader(key, value.startsWith(ORIGIN) ? publicOrigin + value.slice(ORIGIN.length) : value);
      } else if (lower === 'content-security-policy' || lower === 'content-security-policy-report-only') {
        res.setHeader(key, value.split(ORIGIN).join(publicOrigin));
      } else {
        res.setHeader(key, value);
      }
    }
    copyCookies(upstream, res, host);
    if (method === 'HEAD' || !upstream.body) {
      res.end();
      return;
    }
    const type = (upstream.headers.get('content-type') || '').toLowerCase();
    const needsUrlReplacement = type.includes('text/') || type.includes('javascript') || type.includes('json') || type.includes('xml') || type.includes('svg');
    if (needsUrlReplacement) {
      const text = await upstream.text();
      const modified = text.split(ORIGIN).join(publicOrigin);
      res.end(modified);
    } else {
      await new Promise((resolve, reject) => {
        const readable = Readable.fromWeb(upstream.body);
        readable.on('error', reject);
        res.on('error', reject);
        res.on('close', resolve);
        readable.pipe(res);
      });
    }
  } catch (error) {
    if (!res.headersSent) {
      res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('No se pudo conectar con la página original de Granja La Estancia.');
    } else {
      res.end();
    }
    console.error('Upstream request failed:', error.message);
  } finally {
    clearTimeout(timeout);
  }
}).listen(PORT, '0.0.0.0', () => {
  console.log('Granja La Estancia public relay listening on ' + PORT);
});

// One-time non-invasive check of the existing public website at start-up.
(async () => {
  try {
    const reply = await fetch(ORIGIN, { signal: AbortSignal.timeout(20000) });
    const page = await reply.text();
    const s = page.toLowerCase();
    const start = s.indexOf('<title>');
    const finish = s.indexOf('</title>');
    const title = start >= 0 && finish > start ? page.slice(start + 7, finish).slice(0, 150) : '(sin titulo)';
    console.log('Original website check: ' + JSON.stringify({
      status: reply.status,
      contentType: reply.headers.get('content-type'),
      length: page.length,
      title,
      html: s.includes('<html')
    }));
  } catch (error) {
    console.error('Original website check failed: ' + error.message);
  }
})();

// Confirm the public address can serve the unchanged source through this service.
setTimeout(async () => {
  try {
    const reply = await fetch('https://granja-la-estancia.onrender.com/', { signal: AbortSignal.timeout(30000) });
    const page = await reply.text();
    const s = page.toLowerCase();
    const start = s.indexOf('<title>');
    const finish = s.indexOf('</title>');
    console.log('New public address check: ' + JSON.stringify({
      status: reply.status,
      contentType: reply.headers.get('content-type'),
      length: page.length,
      title: start >= 0 && finish > start ? page.slice(start + 7, finish).slice(0, 150) : '(sin titulo)',
      html: s.includes('<html')
    }));
  } catch (error) {
    console.error('New public address check failed: ' + error.message);
  }
}, 5000).unref();
