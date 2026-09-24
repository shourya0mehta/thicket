#!/usr/bin/env node
// Generates src/api/generated.ts from the canonical API contract in
// ../shared/api.schema.json (itself exported from backend/thicket/api/schemas.py).
//
//   npm run gen:types          write src/api/generated.ts
//   npm run check:types-fresh  fail if regenerating would change the file
//
// Never edit generated.ts by hand and never define a competing response shape.

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compile } from 'json-schema-to-typescript';

const here = dirname(fileURLToPath(import.meta.url));
const SCHEMA_PATH = resolve(here, '../../shared/api.schema.json');
const OUT_PATH = resolve(here, '../src/api/generated.ts');

const BANNER = `/* eslint-disable */
/**
 * GENERATED FILE. DO NOT EDIT.
 *
 * Source: shared/api.schema.json (exported from backend/thicket/api/schemas.py).
 * Regenerate with \`npm run gen:types\`; CI checks freshness with
 * \`npm run check:types-fresh\`.
 */`;

/**
 * Normalizes one JSON Schema node for json-schema-to-typescript:
 * - `$defs` becomes `definitions` (and refs follow) so every model is emitted.
 * - Titles are kept only on top-level definitions; otherwise every titled
 *   property becomes its own alias (Id, Id1, Id2...).
 * - A `$ref` with only annotation siblings (default, description) is reduced to
 *   the bare ref, otherwise the referenced enum is emitted twice (ReviewStatus1).
 * Property names inside `properties` are data, never keywords, so they are
 * walked as a map and never stripped.
 */
const ANNOTATIONS = new Set(['title', 'description', 'default', 'examples']);

function normalizeSchema(node, isDefinitionRoot = false) {
  if (Array.isArray(node)) return node.map((n) => normalizeSchema(n));
  if (node === null || typeof node !== 'object') return node;

  if (typeof node.$ref === 'string') {
    const siblings = Object.keys(node).filter((k) => k !== '$ref');
    if (siblings.every((k) => ANNOTATIONS.has(k))) {
      return { $ref: node.$ref.replace('#/$defs/', '#/definitions/') };
    }
  }

  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === 'title' && !isDefinitionRoot) continue;
    if (key === 'description') continue; // keeps the output compact and stable
    if (key === '$defs' || key === 'definitions') {
      out.definitions = Object.fromEntries(
        Object.entries(value).map(([name, def]) => [name, normalizeSchema(def, true)]),
      );
    } else if (key === 'properties' || key === 'patternProperties') {
      out[key] = Object.fromEntries(
        Object.entries(value).map(([name, prop]) => [name, normalizeSchema(prop)]),
      );
    } else if (key === '$ref' && typeof value === 'string') {
      out.$ref = value.replace('#/$defs/', '#/definitions/');
    } else {
      out[key] = normalizeSchema(value);
    }
  }
  return out;
}

async function generate() {
  const raw = JSON.parse(await readFile(SCHEMA_PATH, 'utf8'));
  const schemaVersion = raw['x-schema-version'] ?? 'unknown';
  const schema = normalizeSchema(raw);
  delete schema['x-schema-version'];
  delete schema.$schema;
  schema.type = 'object';
  schema.additionalProperties = false;
  schema.properties = {};

  const body = await compile(schema, 'ThicketAPI', {
    bannerComment: BANNER,
    unreachableDefinitions: true,
    additionalProperties: false,
    strictIndexSignatures: false,
    enableConstEnums: false,
    format: true,
    style: { singleQuote: true, semi: true, printWidth: 100, trailingComma: 'all' },
  });

  return `${body.trimEnd()}\n\n/** Schema version these types were generated from. */\nexport const API_SCHEMA_VERSION = '${schemaVersion}';\n`;
}

const text = await generate();
if (process.argv.includes('--check')) {
  let current = '';
  try {
    current = await readFile(OUT_PATH, 'utf8');
  } catch {
    // missing file is stale by definition
  }
  if (current !== text) {
    console.error(
      'src/api/generated.ts is stale relative to ../shared/api.schema.json. Run `npm run gen:types` and commit the result.',
    );
    process.exit(1);
  }
  console.log('src/api/generated.ts is up to date.');
} else {
  await writeFile(OUT_PATH, text);
  console.log(`Wrote ${OUT_PATH}`);
}
