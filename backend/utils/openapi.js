'use strict';

// Generates an OpenAPI 3 document for one service from what build-functions
// already knows (each function.yml: events, description) plus a static read
// of each handler.py. Nothing here is maintained by hand: add an endpoint and
// the next deploy documents it.
//
// What is inferred, and from where:
//   - route, method, summary ......... function.yml (events.httpApi, description)
//   - who may call it ................ @require_auth(AuthsTypes.X) / @require_any_auth
//   - request fields ................. body.get("x"), query_params.get("x"),
//                                       params.get("x"), uuid_param(.., "x"),
//                                       pagination_params(..)
//   - error responses ................ HandledError("message", status)
// What cannot be inferred (types of fields, the success payload) is left open
// rather than guessed.

const fs = require('fs');
const path = require('path');

const BODY_METHODS = new Set(['post', 'put', 'patch', 'delete']);

// [regex, capture group holding the field name, where the field travels]
// 'any' = read through `request_params`, so it may come in the query string
// or in the JSON body; it is shown where that method naturally carries it.
const FIELD_PATTERNS = [
  [/\b(?:body|payload)\.get\(\s*["'](\w+)["']/g, 1, 'body'],
  [/\b(?:body|payload)\[\s*["'](\w+)["']\s*\]/g, 1, 'body'],
  [/\b(?:query_params|query)\.get\(\s*["'](\w+)["']/g, 1, 'query'],
  [/\bparams\.get\(\s*["'](\w+)["']/g, 1, 'any'],
  [/\buuid_param\(\s*[^,]+?,\s*["'](\w+)["']/g, 1, 'any'],
];

const KNOWN_TYPES = { page: { type: 'integer', minimum: 1 }, page_size: { type: 'integer', minimum: 1 } };

function readHandlerSource(serviceDir, handler) {
  // "src/handlers/get_process/handler.handler" -> src/handlers/get_process/handler.py
  const file = path.join(serviceDir, `${handler.replace(/\.[^./]+$/, '')}.py`);
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
}

function inferAuth(src) {
  if (/@require_any_auth\b/.test(src)) return ['USER', 'INTERNAL'];
  const found = [];
  for (const m of src.matchAll(/require_auth\(\s*AuthsTypes\.(\w+)/g)) found.push(m[1]);
  return found;
}

function inferFields(src) {
  const fields = { body: new Set(), query: new Set(), any: new Set() };
  for (const [re, group, where] of FIELD_PATTERNS) {
    for (const m of src.matchAll(re)) fields[where].add(m[group]);
  }
  if (/\bpagination_params\(/.test(src)) {
    fields.any.add('page');
    fields.any.add('page_size');
  }
  return fields;
}

function inferErrors(src) {
  // status -> messages. Dynamic messages (f-strings, variables) are skipped.
  const errors = {};
  for (const m of src.matchAll(/HandledError\(\s*(f?)(["'])(.*?)\2\s*(?:,\s*(\d{3}))?\s*\)/g)) {
    const [, isF, , message, status] = m;
    if (isF || message.includes('{')) continue;
    const code = status || '400';
    (errors[code] = errors[code] || new Set()).add(message);
  }
  // Raised by libs/utils/params.py on the handler's behalf.
  const add = (status, message) => (errors[status] = errors[status] || new Set()).add(message);
  for (const m of src.matchAll(/\buuid_param\(\s*[^,]+?,\s*["']\w+["']\s*,\s*["']([^"']+)["']/g)) add('400', m[1]);
  if (/\bpagination_params\(/.test(src)) {
    add('400', 'invalid_page');
    add('400', 'invalid_page_size');
  }
  if (/\brequest_params\(/.test(src)) add('400', 'invalid_json_body');

  return errors;
}

function httpEvents(fn) {
  const out = [];
  for (const ev of fn.events || []) {
    const http = ev && ev.httpApi;
    if (!http) continue;
    let method;
    let route;
    if (typeof http === 'string') [method, route] = http.trim().split(/\s+/);
    else ({ method, path: route } = http);
    if (!method || !route || String(method).toUpperCase() === 'ANY') continue;
    out.push({ method: String(method).toLowerCase(), route });
  }
  return out;
}

const SCHEMES = { USER: 'userBearer', INTERNAL: 'adminBearer' };

function operationFor({ key, fn, method, route, src, service }) {
  const auth = inferAuth(src);
  const fields = inferFields(src);
  const errors = inferErrors(src);

  const parameters = [];
  for (const [, name] of [...route.matchAll(/\{(\w+)\+?\}/g)]) {
    parameters.push({ name, in: 'path', required: true, schema: { type: 'string' } });
  }

  const hasBody = BODY_METHODS.has(method);
  const queryNames = new Set([...fields.query, ...(hasBody ? [] : fields.any)]);
  const bodyNames = new Set([...fields.body, ...(hasBody ? fields.any : [])]);

  for (const name of [...queryNames].sort()) {
    parameters.push({ name, in: 'query', required: false, schema: KNOWN_TYPES[name] || {} });
  }

  const operation = {
    operationId: key,
    summary: key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
    description: (fn.description || '').trim(),
    tags: [service],
    parameters,
    responses: { 200: { description: 'OK' } },
    'x-lambda': fn.name,
  };

  if (hasBody && bodyNames.size) {
    const properties = {};
    for (const name of [...bodyNames].sort()) properties[name] = KNOWN_TYPES[name] || {};
    operation.requestBody = {
      required: false,
      content: { 'application/json': { schema: { type: 'object', properties } } },
    };
  }

  if (auth.length) {
    // Several entries = alternatives (any one of them is enough).
    operation.security = auth.map((a) => ({ [SCHEMES[a]]: [] })).filter((s) => Object.keys(s)[0] !== 'undefined');
    errors['401'] = errors['401'] || new Set();
    errors['401'].add('missing_bearer_token');
    errors['401'].add('invalid_or_expired_token');
  }

  for (const [status, messages] of Object.entries(errors)) {
    operation.responses[status] = { description: [...messages].sort().map((m) => `\`${m}\``).join(', ') };
  }

  return operation;
}

function buildOpenApi({ service, stage, serviceDir, functions, version }) {
  const paths = {};

  for (const [key, fn] of Object.entries(functions)) {
    const src = fn.handler ? readHandlerSource(serviceDir, fn.handler) : '';
    for (const { method, route } of httpEvents(fn)) {
      const openApiPath = route.replace(/\{(\w+)\+\}/g, '{$1}');
      paths[openApiPath] = paths[openApiPath] || {};
      paths[openApiPath][method] = operationFor({ key, fn, method, route, src, service });
    }
  }

  return {
    openapi: '3.0.3',
    info: {
      title: `cdts-${stage}-${service}`,
      version: version || 'local',
      description:
        'Generated automatically at deploy time from each Lambda\'s function.yml and handler. ' +
        'Field types and success payloads are not inferred; see docs/*-api.md for those.',
    },
    servers: [{ url: '/' }],
    tags: [{ name: service }],
    paths: Object.fromEntries(Object.entries(paths).sort(([a], [b]) => a.localeCompare(b))),
    components: {
      securitySchemes: {
        userBearer: { type: 'http', scheme: 'bearer', description: 'Token of a platform user (POST /auth/login).' },
        adminBearer: { type: 'http', scheme: 'bearer', description: 'Token of an internal admin (POST /admin-auth/login).' },
      },
    },
  };
}

module.exports = { buildOpenApi, httpEvents, inferAuth, inferFields, inferErrors };
