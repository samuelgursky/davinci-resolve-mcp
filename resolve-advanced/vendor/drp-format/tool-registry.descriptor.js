/**
 * Tool Registry Descriptor — drp-generator
 *
 * Registers encoder modules as api-method entries.
 */

const encoderModules = [
  {
    id: 'drpGenerator.gradeEncoder',
    name: 'Grade Encoder',
    description: 'Encode color grade parameters into DRP XML format (color wheels, adjustments)',
    tags: ['drp', 'grade', 'encode', 'xml'],
  },
  {
    id: 'drpGenerator.curvesEncoder',
    name: 'Curves Encoder',
    description: 'Encode custom curves (RGB, Hue vs Sat/Lum) for DRP files',
    tags: ['drp', 'curves', 'encode'],
  },
  {
    id: 'drpGenerator.powerWindowEncoder',
    name: 'Power Window Encoder',
    description: 'Encode power windows (circle, linear, polygon, curve) for DRP',
    tags: ['drp', 'power-window', 'encode'],
  },
  {
    id: 'drpGenerator.qualifierEncoder',
    name: 'Qualifier Encoder',
    description: 'Encode qualifiers (HSL, luminance, 3D) for DRP files',
    tags: ['drp', 'qualifier', 'encode'],
  },
  {
    id: 'drpGenerator.markerEncoder',
    name: 'Marker Encoder',
    description: 'Encode timeline and clip markers for DRP files',
    tags: ['drp', 'marker', 'encode'],
  },
  {
    id: 'drpGenerator.nodeTreeEncoder',
    name: 'Node Tree Encoder',
    description: 'Encode node tree structures (serial, parallel, layer mixers) for DRP',
    tags: ['drp', 'node', 'encode'],
  },
  {
    id: 'drpGenerator.effectEncoder',
    name: 'Effect Encoder',
    description: 'Encode OFX and built-in effects for DRP files',
    tags: ['drp', 'effect', 'encode'],
  },
  {
    id: 'drpGenerator.xmlBuilder',
    name: 'XML Builder',
    description: 'DRP XML generation utilities for building Resolve project files',
    tags: ['drp', 'xml', 'builder'],
  },
  {
    id: 'drpGenerator.drpPackager',
    name: 'DRP Packager',
    description: 'Package encoded components into complete DaVinci Resolve Project (.drp) files',
    tags: ['drp', 'package', 'resolve'],
  },
  {
    id: 'drpGenerator.gradeParameterDecoder',
    name: 'Grade Parameter Decoder',
    description: 'Decode grade parameters from existing DRP files for analysis',
    tags: ['drp', 'grade', 'decode', 'analysis'],
  },
];

module.exports = {
  source: 'drp-generator',
  version: '0.1.0',
  capabilities: encoderModules.map((m) => ({
    ...m,
    type: 'api-method',
    category: 'drp.encoder',
    source: 'drp-generator',
    availability: 'static',
  })),
};
