/**
 * schema.js — JSON schema fetching and AJV-based validation.
 */

import {state} from './state.js';

// -- Schema loader -------------------------------------------------------------

export async function loadSchema() {
  try {
    const r    = await fetch('/api/schema');
    state.schema = await r.json();
  } catch {
    // Schema-less editing is still functional
  }
}

// -- AJV ----------------------------------------------------------------------

/**
 * Validate a parsed YAML object against the loaded schema.
 * Returns an array of human-readable error strings (empty = valid).
 */
export async function validateAgainstSchema(parsed) {
  try {
    const ajv      = new Ajv({ allErrors: true, jsonPointers: true });
    const validate = ajv.compile(state.schema);
    if (validate(parsed)) return [];
    return (validate.errors || []).map(err => {
      const path = err.dataPath || err.instancePath || '(root)';
      return `${path}: ${err.message}`;
    });
  } catch { return []; }
}

// -- Schema-aware YAML completions (used by Ace editor completer) --------------

export function getSchemaOptions(schema, path, existingProps = null) {
  let node = schema;
  for (const key of path) {
    node = resolveRef(node, schema);
    node = unwrapArray(node, schema);
    node = resolveRef(node, schema);
    const props = getProps(node, schema, existingProps);
    if (!props) return [];
    node = props[key] || resolveAnyOfFor(node, key, schema);
    if (!node) return [];
  }
  node = resolveRef(node, schema);
  node = unwrapArray(node, schema);
  node = resolveRef(node, schema);
  const props = getProps(node, schema, existingProps);
  if (!props) return [];

  return Object.entries(props).map(([k, v]) => {
    const resolved = resolveRef(v, schema);
    return {
      key:        k,
      type:       resolved.type || (resolved.properties ? 'object' : ''),
      description: resolved.description || '',
      isObject:   !!(resolved.properties || resolved.additionalProperties),
    };
  });
}

function resolveRef(node, root) {
  if (!node?.$ref) return node;
  const parts = node.$ref.replace(/^#\//, '').split('/');
  let cur = root;
  for (const p of parts) cur = cur?.[p];
  return cur ?? node;
}

function unwrapArray(node, root) {
  if (!node) return node;
  const r = resolveRef(node, root);
  if (r?.items) return resolveRef(r.items, root);
  return r;
}

function getProps(node, root, existingProps = null) {
  node = resolveRef(node, root);
  if (!node) return null;
  if (node.properties) return node.properties;
  const union = node.anyOf || node.oneOf || node.allOf || [];
  if (!union.length) return null;
  const merged = {};
  union.forEach(sub => {
    sub = unwrapArray(sub);
    const p = getProps(sub, root, existingProps) || {};
    Object.assign(merged, p);
  });
  return Object.keys(merged).length ? merged : null;
}

function resolveAnyOfFor(node, key, root) {
  const union = node?.anyOf || node?.oneOf || [];
  for (const sub of union) {
    const resolved = resolveRef(sub, root);
    if (resolved?.properties?.[key]) return resolved.properties[key];
  }
  return null;
}
