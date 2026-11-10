'use strict';

// Auto-registers Lambdas under src/{handlers,scheduled,workers}/*.
// Also mirrors backend/libs/ into ./libs/ so serverless packages it with
// this service. The ./libs/ folder is gitignored.
const fs = require('fs');
const path = require('path');

const srcLibs = path.resolve(__dirname, '../../libs');
const dstLibs = path.resolve(__dirname, 'libs');
if (fs.existsSync(srcLibs)) {
  fs.rmSync(dstLibs, { recursive: true, force: true });
  fs.cpSync(srcLibs, dstLibs, { recursive: true });
}

module.exports.build = require('../../utils/build-functions')(__dirname);
