"use strict";

const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

process.loadEnvFile(path.join(__dirname, "..", ".env"));

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required in .env`);
  return value;
}

function port(name) {
  const value = Number(required(name));
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${name} must be a TCP port`);
  }
  return value;
}

const interfaceName = required("LAN_BIND_INTERFACE");
const lanIp = (os.networkInterfaces()[interfaceName] || []).find(
  (entry) => entry.family === "IPv4" && !entry.internal,
)?.address;
if (!lanIp) throw new Error(`No active IPv4 address on ${interfaceName}`);

const httpsPort = port("LAN_HTTPS_PORT");
const certPort = port("LAN_CERT_PORT");
const upstreamPort = port("LAN_UPSTREAM_PORT");
const upstreamHost = required("LAN_UPSTREAM_HOST");
const certDir = required("LAN_CERT_DIR");
const serverCert = fs.readFileSync(path.join(certDir, "server.crt"));
const serverKey = fs.readFileSync(path.join(certDir, "server.key"));
const caCert = fs.readFileSync(path.join(certDir, "lan-ca.cer"));

function upstreamHeaders(headers) {
  const copy = { ...headers };
  copy.host = `${upstreamHost}:${upstreamPort}`;
  if (copy.origin) copy.origin = `http://${upstreamHost}:${upstreamPort}`;
  delete copy["proxy-connection"];
  return copy;
}

const secureServer = https.createServer({ key: serverKey, cert: serverCert }, (req, res) => {
  const upstream = http.request(
    {
      host: upstreamHost,
      port: upstreamPort,
      path: req.url,
      method: req.method,
      headers: upstreamHeaders(req.headers),
    },
    (reply) => {
      res.writeHead(reply.statusCode || 502, reply.headers);
      reply.pipe(res);
    },
  );
  upstream.on("error", () => {
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end("Local web server unavailable");
  });
  req.on("aborted", () => upstream.destroy());
  req.pipe(upstream);
});

secureServer.on("upgrade", (req, socket, head) => {
  const upstream = net.connect(upstreamPort, upstreamHost);
  upstream.on("connect", () => {
    const headers = upstreamHeaders(req.headers);
    const requestLine = `${req.method} ${req.url} HTTP/1.1\r\n`;
    const headerLines = Object.entries(headers)
      .map(([name, value]) => `${name}: ${value}\r\n`)
      .join("");
    upstream.write(`${requestLine}${headerLines}\r\n`);
    if (head.length) upstream.write(head);
    socket.pipe(upstream);
    upstream.pipe(socket);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
});

const certServer = http.createServer((req, res) => {
  if (req.method !== "GET" || req.url !== "/lan-ca.cer") {
    res.writeHead(404).end();
    return;
  }
  res.writeHead(200, {
    "content-type": "application/x-x509-ca-cert",
    "content-disposition": 'attachment; filename="lan-ca.cer"',
    "content-length": caCert.length,
    "cache-control": "no-store",
  });
  res.end(caCert);
});

secureServer.listen(httpsPort, lanIp, () => {
  certServer.listen(certPort, lanIp, () => {
    process.stdout.write(`Website: https://${lanIp}:${httpsPort}/\n`);
    process.stdout.write(`Certificate: http://${lanIp}:${certPort}/lan-ca.cer\n`);
  });
});
