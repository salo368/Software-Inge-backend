'use strict';

// Auto-discovers Lambdas under src/{handlers,scheduled,workers,webhooks}/* and builds
// the Serverless "functions" map. Each subfolder must be snake_case and
// contain a function.yml with the function-specific config (events, memory,
// timeout, layers, environment overrides, etc.). name and handler are
// derived from the convention:
//
//   folder:  snake_case               (python module compatible)
//   name:    cdts-<stage>-<service>-<folder-with-dashes>
//   handler: src/<type>/<folder>/handler.handler
//
// function.yml MAY override name or handler as a last-resort escape hatch;
// if present those explicit values win.
//
// Usage from a block's serverless.yml:
//
//   # backend/<services|platform>/<block>/functions.js
//   'use strict';
//   module.exports.build = require('../../utils/build-functions')(__dirname);
//
//   # backend/<services|platform>/<block>/serverless.yml
//   functions: ${file(./functions.js):build}

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { buildOpenApi, httpEvents } = require('./openapi');

const TYPES = ['handlers', 'scheduled', 'workers', 'webhooks'];
const SNAKE_CASE = /^[a-z][a-z0-9_]*$/;

// API docs (Swagger UI + openapi.json) are served by every service that has
// HTTP routes, except in these stages.
const DOCS_DISABLED_STAGES = ['pro'];
const DOCS_DIR = path.join('src', '_docs');

function loadYaml(file) {
  return yaml.load(fs.readFileSync(file, 'utf8')) || {};
}

function assertSnakeCase(folder, fnDir) {
  if (!SNAKE_CASE.test(folder)) {
    throw new Error(
      `[build-functions] Folder "${folder}" (${fnDir}) must be snake_case ` +
      `(lowercase letters, digits, underscores; must start with a letter). ` +
      `Python cannot import folders with dashes.`
    );
  }
}

// Route prefix shared by the service's endpoints ("/processes"); falls back to
// the service name when they do not share one.
function docsPrefix(service, functions) {
  const first = new Set();
  for (const fn of Object.values(functions)) {
    for (const { route } of httpEvents(fn)) first.add(route.split('/')[1]);
  }
  return first.size === 1 ? `/${[...first][0]}` : `/${service.replace(/_/g, '-')}`;
}

// Writes <service>/src/_docs/openapi.json (packaged with `src/**`) and adds the
// Lambda that serves it. Docs must never block a deploy: on any failure it
// warns and the service deploys without them.
function addApiDocs({ service, stage, serviceDir, functions }) {
  if (DOCS_DISABLED_STAGES.includes(stage)) return;

  const hasHttp = Object.values(functions).some((fn) => httpEvents(fn).length > 0);
  if (!hasHttp) return;

  try {
    const spec = buildOpenApi({
      service,
      stage,
      serviceDir,
      functions,
      version: (process.env.GITHUB_SHA || '').slice(0, 7) || undefined,
    });

    const docsDir = path.join(serviceDir, DOCS_DIR);
    fs.mkdirSync(docsDir, { recursive: true });
    fs.writeFileSync(path.join(docsDir, 'openapi.json'), JSON.stringify(spec, null, 2));

    const prefix = docsPrefix(service, functions);
    functions.api_docs = {
      name: `cdts-${stage}-${service}-api-docs`,
      // libs/ is mirrored into every service by functions.js; this module has no DB imports.
      handler: 'libs/utils/openapi_docs.handler',
      description: `Swagger UI (${prefix}/docs) and the generated OpenAPI document (${prefix}/openapi.json) of this service.`,
      memorySize: 256,
      timeout: 10,
      events: [
        { httpApi: { method: 'GET', path: `${prefix}/docs` } },
        { httpApi: { method: 'GET', path: `${prefix}/openapi.json` } },
      ],
    };
  } catch (e) {
    console.warn(`[build-functions] API docs skipped for "${service}": ${e.message}`);
  }
}

module.exports = (serviceDir) => async ({ options, resolveConfigurationProperty }) => {
  const service = await resolveConfigurationProperty(['service']);
  const stage = options.stage || options.s || 'dev';

  const functions = {};

  for (const type of TYPES) {
    const typeDir = path.join(serviceDir, 'src', type);
    if (!fs.existsSync(typeDir)) continue;

    const folders = fs.readdirSync(typeDir).sort();
    for (const folder of folders) {
      const fnDir = path.join(typeDir, folder);
      if (!fs.statSync(fnDir).isDirectory()) continue;

      const fnYml = path.join(fnDir, 'function.yml');
      if (!fs.existsSync(fnYml)) {
        throw new Error(
          `[build-functions] Missing function.yml in ${path.relative(serviceDir, fnDir)}`
        );
      }
      assertSnakeCase(folder, fnDir);

      const custom = loadYaml(fnYml);
      const folderKebab = folder.replace(/_/g, '-');

      functions[folder] = {
        name: `cdts-${stage}-${service}-${folderKebab}`,
        handler: `src/${type}/${folder}/handler.handler`,
        ...custom, // explicit name/handler in function.yml override the auto ones
      };
    }
  }

  addApiDocs({ service, stage, serviceDir, functions });

  return functions;
};
