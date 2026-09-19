'use strict';

// Auto-registers every Lambda under src/{handlers,scheduled,workers}/*.
// See backend/utils/build-functions.js for the convention.
module.exports.build = require('../../utils/build-functions')(__dirname);
