'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const buildFactory = require('../utils/build-functions');

function makeService(files) {
  // files: { 'src/handlers/foo/function.yml': 'timeout: 10\n', ... }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-'));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

function ctx({ service = 'auth', stage = 'dev' } = {}) {
  return {
    options: { stage },
    resolveConfigurationProperty: async (p) => (p[0] === 'service' ? service : undefined),
  };
}

test('auto-derives name and handler from folder + service + stage', async () => {
  const dir = makeService({
    'src/handlers/refresh_token/function.yml': 'timeout: 30\n',
  });
  const build = buildFactory(dir);
  const fns = await build(ctx({ service: 'auth', stage: 'dev' }));
  assert.deepEqual(fns.refresh_token, {
    name: 'cdts-dev-auth-refresh-token',
    handler: 'src/handlers/refresh_token/handler.handler',
    timeout: 30,
  });
});

test('multi-word folder gets kebab-cased in AWS name', async () => {
  const dir = makeService({
    'src/handlers/create_signature/function.yml': 'memorySize: 256\n',
  });
  const fns = await buildFactory(dir)(ctx({ service: 'documents', stage: 'pro' }));
  assert.equal(fns.create_signature.name, 'cdts-pro-documents-create-signature');
  assert.equal(fns.create_signature.handler, 'src/handlers/create_signature/handler.handler');
});

test('scheduled and workers types are scanned too', async () => {
  const dir = makeService({
    'src/handlers/api_call/function.yml': 'timeout: 5\n',
    'src/scheduled/nightly_sync/function.yml': 'timeout: 900\n',
    'src/workers/queue_processor/function.yml': 'timeout: 60\n',
  });
  const fns = await buildFactory(dir)(ctx({ service: 'jobs', stage: 'dev' }));
  assert.equal(fns.api_call.handler, 'src/handlers/api_call/handler.handler');
  assert.equal(fns.nightly_sync.handler, 'src/scheduled/nightly_sync/handler.handler');
  assert.equal(fns.queue_processor.handler, 'src/workers/queue_processor/handler.handler');
});

test('function.yml can override name (escape hatch)', async () => {
  const dir = makeService({
    'src/handlers/legacy/function.yml': 'name: my-legacy-name\ntimeout: 5\n',
  });
  const fns = await buildFactory(dir)(ctx());
  assert.equal(fns.legacy.name, 'my-legacy-name');
});

test('function.yml can override handler (escape hatch)', async () => {
  const dir = makeService({
    'src/handlers/proxied/function.yml': 'handler: src/handlers/proxied/other.entry\n',
  });
  const fns = await buildFactory(dir)(ctx());
  assert.equal(fns.proxied.handler, 'src/handlers/proxied/other.entry');
});

test('preserves arbitrary function-level fields (events, memorySize, env, layers)', async () => {
  const dir = makeService({
    'src/handlers/refresh_token/function.yml':
      'timeout: 30\n' +
      'memorySize: 256\n' +
      'description: Renueva un access token\n' +
      'environment:\n  LOG_LEVEL: INFO\n' +
      'events:\n  - httpApi:\n      method: POST\n      path: /auth/refresh-token\n',
  });
  const fns = await buildFactory(dir)(ctx({ service: 'auth' }));
  assert.equal(fns.refresh_token.timeout, 30);
  assert.equal(fns.refresh_token.memorySize, 256);
  assert.equal(fns.refresh_token.description, 'Renueva un access token');
  assert.deepEqual(fns.refresh_token.environment, { LOG_LEVEL: 'INFO' });
  assert.equal(fns.refresh_token.events[0].httpApi.path, '/auth/refresh-token');
});

test('empty function.yml still produces valid name/handler', async () => {
  const dir = makeService({
    'src/handlers/ping/function.yml': '',
  });
  const fns = await buildFactory(dir)(ctx({ service: 'health' }));
  assert.equal(fns.ping.name, 'cdts-dev-health-ping');
  assert.equal(fns.ping.handler, 'src/handlers/ping/handler.handler');
});

test('missing function.yml raises a clear error', async () => {
  const dir = makeService({});
  fs.mkdirSync(path.join(dir, 'src/handlers/oops'), { recursive: true });
  await assert.rejects(
    buildFactory(dir)(ctx()),
    /Missing function\.yml in src[\\/]handlers[\\/]oops/
  );
});

test('kebab-case folder is rejected (python cannot import dashes)', async () => {
  const dir = makeService({
    'src/handlers/bad-folder/function.yml': '',
  });
  await assert.rejects(
    buildFactory(dir)(ctx()),
    /must be snake_case/
  );
});

test('uppercase folder is rejected', async () => {
  const dir = makeService({
    'src/handlers/BadFolder/function.yml': '',
  });
  await assert.rejects(
    buildFactory(dir)(ctx()),
    /must be snake_case/
  );
});

test('service with no src/ returns empty map', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-'));
  const fns = await buildFactory(dir)(ctx());
  assert.deepEqual(fns, {});
});

test('stage defaults to dev when not provided', async () => {
  const dir = makeService({
    'src/handlers/ping/function.yml': '',
  });
  const build = buildFactory(dir);
  const fns = await build({
    options: {},
    resolveConfigurationProperty: async () => 'auth',
  });
  assert.equal(fns.ping.name, 'cdts-dev-auth-ping');
});
