'use strict';

// Auto-discovers Lambdas under src/{handlers,scheduled,workers}/* and builds
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

const TYPES = ['handlers', 'scheduled', 'workers'];
const SNAKE_CASE = /^[a-z][a-z0-9_]*$/;

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

  return functions;
};
