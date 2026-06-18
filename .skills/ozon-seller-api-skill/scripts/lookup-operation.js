#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const specPath = path.join(root, 'swagger.json');
const args = parseArgs(process.argv.slice(2));

if (
  args.help ||
  (!args.validate &&
    !args.map &&
    !args.tags &&
    !args.tag &&
    !args.docTags &&
    !args.docTag &&
    !args.query &&
    !args.operationId &&
    !args.path)
) {
  printUsage();
  process.exit(0);
}

const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const operations = collectOperations(spec);

if (args.validate) {
  process.exit(validateSpec(operations));
}

if (args.map) {
  printMap(operations);
  process.exit(0);
}

if (args.tags) {
  printTags(operations);
  process.exit(0);
}

if (args.docTags) {
  printDocTags(operations);
  process.exit(0);
}

if (args.docTag) {
  const ok = printDocTag(args.docTag, args);
  process.exit(ok ? 0 : 1);
}

const matches = selectOperations(args, operations);

if (!matches.length) {
  console.error('No matching Ozon Seller API operations found.');
  process.exit(1);
}

const limit = numberArg(args.limit, args.details ? 1 : 10);
for (const [index, operation] of matches.slice(0, limit).entries()) {
  if (index > 0) {
    console.log('');
  }
  printOperation(operation, args);
}

function collectOperations(openApiSpec) {
  const result = [];
  const groupByTag = tagGroupIndex();
  for (const [apiPath, pathItem] of Object.entries(openApiSpec.paths || {})) {
    for (const [method, operation] of Object.entries(pathItem || {})) {
      if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) {
        continue;
      }
      const tags = operation.tags || [];
      const tag = tags[0] || '';
      result.push({
        id: operation.operationId || `${method.toUpperCase()} ${apiPath}`,
        method,
        path: apiPath,
        tags,
        tag,
        group: groupByTag.get(tag) || '',
        summary: operation.summary || '',
        description: operation.description || '',
        deprecated: Boolean(operation.deprecated),
        parameters: [...(pathItem.parameters || []), ...(operation.parameters || [])],
        operation,
      });
    }
  }
  return result;
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith('--')) {
      continue;
    }

    const key = camelCase(arg.slice(2));
    if (['details', 'schemas', 'validate', 'map', 'tags', 'docTags', 'help'].includes(key)) {
      parsed[key] = true;
      continue;
    }

    const value = argv[index + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for ${arg}`);
    }
    parsed[key] = value;
    index += 1;
  }
  return parsed;
}

function selectOperations(options, operationList) {
  if (options.tag) {
    return operationList.filter((operation) => normalize(operation.tag) === normalize(options.tag));
  }

  if (options.operationId) {
    return operationList.filter((operation) => operation.id === options.operationId);
  }

  if (options.path) {
    const method = options.method?.toLowerCase();
    return operationList.filter((operation) => operation.path === options.path && (!method || operation.method === method));
  }

  return rankedSearch(options.query, operationList);
}

function rankedSearch(query, operationList) {
  const tokens = normalize(query).split(/\s+/).filter(Boolean);
  if (!tokens.length) {
    return operationList;
  }

  return operationList
    .map((operation) => ({ operation, score: scoreOperation(operation, tokens) }))
    .filter((entry) => entry.score > 0)
    .sort(
      (a, b) =>
        Number(a.operation.deprecated) - Number(b.operation.deprecated) ||
        b.score - a.score ||
        a.operation.path.localeCompare(b.operation.path),
    )
    .map((entry) => entry.operation);
}

function scoreOperation(operation, tokens) {
  const phrase = tokens.join(' ');
  const pathPhrase = `/${tokens.join('/')}`;
  const fields = {
    id: normalize(operation.id),
    path: normalize(operation.path),
    tag: normalize(operation.tag),
    summary: normalize(operation.summary),
    description: normalize(stripMarkdown(operation.description)),
  };
  const haystack = Object.values(fields).join(' ');
  if (!tokens.every((token) => haystack.includes(token))) {
    return 0;
  }

  let score = 1;
  if (fields.path.includes(pathPhrase)) score += 12;
  if (fields.summary.includes(phrase)) score += 10;
  if (fields.id.includes(tokens.map(titleToken).join(''))) score += 8;
  if (fields.id.includes(phrase)) score += 8;
  for (const token of tokens) {
    if (fields.path.includes(token)) score += 5;
    if (fields.id.includes(token)) score += 4;
    if (fields.summary.includes(token)) score += 3;
    if (fields.tag.includes(token)) score += 2;
    if (fields.description.includes(token)) score += 1;
  }
  return score;
}

function printOperation(operation, options) {
  const openApiOperation = operation.operation;
  const requestBody = resolveRef(openApiOperation.requestBody);
  const requestContent = firstContentSchema(requestBody);
  const requestSchema = requestContent?.schema || null;
  const method = operation.method.toUpperCase();

  console.log(`${operation.id} | ${method} ${operation.path}`);
  console.log(`Group: ${operation.group || '(none)'}`);
  console.log(`Tags: ${operation.tags.length ? operation.tags.join(', ') : '(none)'}`);
  console.log(`Summary: ${operation.summary || '(none)'}`);
  if (operation.deprecated) {
    console.log('Deprecated: true');
  }

  if (!options.details) {
    console.log(`Request: ${requestSchema ? `${requestContent.mediaType} ${schemaLabel(requestSchema)}` : 'none'}`);
    return;
  }

  const parameters = resolvedParameters(operation);
  console.log(`Parameters: ${parameters.length ? parameters.length : 'none'}`);
  printParameters(parameters);
  console.log(`Request required: ${Boolean(requestBody?.required)}`);
  console.log(`Request schema: ${requestSchema ? `${requestContent.mediaType} ${schemaLabel(requestSchema)}` : 'none'}`);
  printResponses(openApiOperation);

  if (options.schemas && requestSchema) {
    console.log('');
    console.log('Request body fields:');
    printSchema(requestSchema, { maxDepth: 5 });
  }

  if (options.schemas) {
    const responseSchema = firstJsonResponseSchema(openApiOperation);
    if (responseSchema) {
      console.log('');
      console.log('Primary response fields:');
      printSchema(responseSchema, { maxDepth: 4 });
    }
  }
}

function printResponses(openApiOperation) {
  console.log('Responses:');
  for (const [status, rawResponse] of Object.entries(openApiOperation.responses || {})) {
    const response = resolveRef(rawResponse) || {};
    const content = response.content || {};
    const contentTypes = Object.keys(content);
    if (!contentTypes.length) {
      console.log(`- ${status}: ${response.description || 'no body'}`);
      continue;
    }
    for (const contentType of contentTypes) {
      console.log(`- ${status} ${contentType}: ${schemaLabel(content[contentType].schema)}`);
    }
  }
}

function printParameters(parameters) {
  if (!parameters.length) {
    return;
  }
  console.log('Parameter details:');
  for (const parameter of parameters) {
    const schema = resolveSchema(parameter.schema);
    const details = [
      `in=${parameter.in || 'unknown'}`,
      parameter.required ? 'required' : null,
      schema ? `schema=${formatType(schema, parameter.schema)}` : null,
      compactText(parameter.description),
    ].filter(Boolean);
    console.log(`- ${parameter.name || '(unnamed)'} (${details.join('; ')})`);
  }
}

function printTags(operationList) {
  const counts = tagCounts(operationList);
  for (const [tag, count] of [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const displayName = tagDisplayName(tag);
    console.log([tag, count, displayName !== tag ? displayName : null].filter(Boolean).join('\t'));
  }
}

function printMap(operationList) {
  const counts = tagCounts(operationList);
  const groupedTags = new Set();
  const operationTotal = operationList.length;
  const groups = Array.isArray(spec['x-tagGroups']) ? spec['x-tagGroups'] : [];

  console.log('Ozon Seller API map');
  console.log(`Source: swagger.json (${operationTotal} operations)`);
  console.log('');

  for (const group of groups) {
    const presentTags = group.tags.filter((tag) => counts.has(tag));
    if (!presentTags.length) {
      continue;
    }

    for (const tag of presentTags) {
      groupedTags.add(tag);
    }

    const groupTotal = presentTags.reduce((total, tag) => total + counts.get(tag), 0);
    console.log(`${group.name} (${groupTotal})`);
    for (const tag of presentTags) {
      const displayName = tagDisplayName(tag);
      const suffix = displayName !== tag ? ` - ${displayName}` : '';
      console.log(`- ${tag} (${counts.get(tag)})${suffix}`);
    }
    console.log('');
  }

  const ungrouped = [...counts.keys()].filter((tag) => !groupedTags.has(tag)).sort((a, b) => a.localeCompare(b));
  if (ungrouped.length) {
    const total = ungrouped.reduce((sum, tag) => sum + counts.get(tag), 0);
    console.log(`Other or newly added tags (${total})`);
    for (const tag of ungrouped) {
      const displayName = tagDisplayName(tag);
      const suffix = displayName !== tag ? ` - ${displayName}` : '';
      console.log(`- ${tag} (${counts.get(tag)})${suffix}`);
    }
    console.log('');
  }
}

function printDocTags(operationList) {
  const operationTags = new Set(operationList.flatMap((operation) => operation.tags));
  const groups = Array.isArray(spec['x-tagGroups']) ? spec['x-tagGroups'] : [];
  const groupByTag = tagGroupIndex();
  for (const tag of spec.tags || []) {
    const name = tag.name || '';
    const description = stripMarkdown(tag.description || '');
    console.log(
      [
        name,
        groupByTag.get(name) || '(ungrouped)',
        operationTags.has(name) ? 'operations' : 'docs-only',
        tagDisplayName(name),
        description ? `${description.length} chars` : 'no description',
      ].join('\t'),
    );
  }
  if (!groups.length) {
    console.log('(No x-tagGroups declared.)');
  }
}

function printDocTag(name, options) {
  const tag = (spec.tags || []).find((entry) => normalize(entry.name) === normalize(name));
  if (!tag) {
    console.error(`No doc tag found for ${name}.`);
    return false;
  }

  const displayName = tagDisplayName(tag.name);
  const group = tagGroupIndex().get(tag.name) || '(ungrouped)';
  console.log(`${tag.name}${displayName !== tag.name ? ` - ${displayName}` : ''}`);
  console.log(`Group: ${group}`);

  const description = String(tag.description || '').trim();
  if (!description) {
    console.log('No description.');
    return true;
  }

  const plain = compactDoc(description);
  const lines = plain.split('\n').filter(Boolean);
  const grep = options.grep ? normalize(options.grep) : '';
  const selected = grep ? lines.filter((line) => normalize(line).includes(grep)) : lines;

  if (!selected.length) {
    console.log(`No lines matched grep: ${options.grep}`);
    return true;
  }

  const limit = numberArg(options.limit, grep ? 40 : 120);
  for (const line of selected.slice(0, limit)) {
    console.log(line);
  }
  if (selected.length > limit) {
    console.log(`... ${selected.length - limit} more lines omitted. Use --limit ${selected.length} or --grep.`);
  }
  return true;
}

function tagCounts(operationList) {
  const counts = new Map();
  for (const operation of operationList) {
    const tag = operation.tag || '(none)';
    counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  return counts;
}

function tagDisplayName(tagName) {
  const tag = Array.isArray(spec.tags) ? spec.tags.find((entry) => entry.name === tagName) : null;
  return tag?.['x-displayName'] || tag?.['x-display-name'] || tagName;
}

function tagGroupIndex() {
  const byTag = new Map();
  for (const group of spec['x-tagGroups'] || []) {
    for (const tag of group.tags || []) {
      byTag.set(tag, group.name);
    }
  }
  return byTag;
}

function printSchema(schema, options, depth = 0, seen = new Set()) {
  const resolved = resolveSchema(schema);
  const label = schemaLabel(schema);
  const indent = '  '.repeat(depth);

  if (schema?.$ref) {
    if (seen.has(schema.$ref)) {
      console.log(`${indent}- ${label} (recursive)`);
      return;
    }
    seen.add(schema.$ref);
  }

  if (!resolved) {
    console.log(`${indent}- ${label}`);
    return;
  }

  if (depth >= options.maxDepth) {
    console.log(`${indent}- ${label}`);
    return;
  }

  if (resolved.allOf || resolved.oneOf || resolved.anyOf) {
    for (const variant of resolved.allOf || resolved.oneOf || resolved.anyOf) {
      printSchema(variant, options, depth, seen);
    }
    return;
  }

  if (resolved.type === 'array' || resolved.items) {
    console.log(`${indent}- array of ${schemaLabel(resolved.items)}`);
    printSchema(resolved.items, options, depth + 1, seen);
    return;
  }

  const properties = resolved.properties || {};
  const entries = Object.entries(properties);
  if (!entries.length) {
    console.log(`${indent}- ${formatType(resolved)}`);
    return;
  }

  const required = new Set(resolved.required || []);
  for (const [name, propertySchema] of entries) {
    const resolvedProperty = resolveSchema(propertySchema) || propertySchema;
    const details = [
      formatType(resolvedProperty, propertySchema),
      required.has(name) ? 'required' : null,
      resolvedProperty.enum ? `enum: ${resolvedProperty.enum.join(', ')}` : null,
      compactText(resolvedProperty.description),
    ].filter(Boolean);

    console.log(`${indent}- ${name} (${details.join('; ')})`);
    if (shouldExpand(resolvedProperty, propertySchema, depth, options)) {
      printSchema(propertySchema, options, depth + 1, new Set(seen));
    }
  }
}

function shouldExpand(resolvedSchema, originalSchema, depth, options) {
  if (depth + 1 >= options.maxDepth) {
    return false;
  }
  if (originalSchema?.$ref) {
    return Boolean(
      resolvedSchema.properties ||
        resolvedSchema.allOf ||
        resolvedSchema.oneOf ||
        resolvedSchema.anyOf ||
        (resolvedSchema.items && (resolvedSchema.items.properties || resolvedSchema.items.$ref)),
    );
  }
  if (resolvedSchema.type === 'array' || resolvedSchema.items) {
    return Boolean(resolvedSchema.items?.properties || resolvedSchema.items?.$ref);
  }
  return Boolean(resolvedSchema.properties || resolvedSchema.allOf || resolvedSchema.oneOf || resolvedSchema.anyOf);
}

function firstJsonResponseSchema(openApiOperation) {
  for (const [status, rawResponse] of Object.entries(openApiOperation.responses || {})) {
    if (!String(status).startsWith('2')) {
      continue;
    }
    const response = resolveRef(rawResponse);
    const schema = response.content?.['application/json']?.schema;
    if (schema) {
      return schema;
    }
  }
  return null;
}

function resolveSchema(schema) {
  return resolveRef(schema);
}

function resolveRef(value) {
  if (!value?.$ref) {
    return value;
  }
  const ref = String(value.$ref);
  if (!ref.startsWith('#/')) {
    return value;
  }
  let node = spec;
  for (const part of ref.slice(2).split('/')) {
    const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
    if (!node || typeof node !== 'object' || !(key in node)) {
      return value;
    }
    node = node[key];
  }
  return node;
}

function firstContentSchema(bodyOrResponse, preferred = 'application/json') {
  const content = bodyOrResponse?.content || {};
  if (content[preferred]?.schema) {
    return { mediaType: preferred, schema: content[preferred].schema };
  }
  for (const [mediaType, media] of Object.entries(content)) {
    if (media?.schema) {
      return { mediaType, schema: media.schema };
    }
  }
  return null;
}

function resolvedParameters(operation) {
  return operation.parameters.map((parameter) => resolveRef(parameter)).filter((parameter) => parameter && typeof parameter === 'object');
}

function schemaLabel(schema) {
  if (!schema) {
    return 'none';
  }
  if (schema.$ref) {
    return refName(schema.$ref);
  }
  if (schema.type === 'array') {
    return `array<${schemaLabel(schema.items)}>`;
  }
  return formatType(schema);
}

function formatType(resolvedSchema, originalSchema = resolvedSchema) {
  if (originalSchema?.$ref) {
    return refName(originalSchema.$ref);
  }
  if (resolvedSchema?.items) {
    return `array<${schemaLabel(resolvedSchema.items)}>`;
  }
  if (resolvedSchema?.type) {
    return resolvedSchema.format ? `${resolvedSchema.type}:${resolvedSchema.format}` : resolvedSchema.type;
  }
  if (resolvedSchema?.allOf) return 'allOf';
  if (resolvedSchema?.oneOf) return 'oneOf';
  if (resolvedSchema?.anyOf) return 'anyOf';
  return 'object';
}

function refName(ref) {
  return String(ref).split('/').at(-1);
}

function compactText(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 180);
}

function compactDoc(value) {
  return String(value || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>|<\/li>|<\/h[1-6]>|<\/tr>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\r/g, '')
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n');
}

function normalize(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9/._-]+/g, ' ');
}

function stripMarkdown(value) {
  return String(value || '').replace(/<[^>]+>/g, ' ').replace(/[#*_`[\]()]/g, ' ');
}

function titleToken(token) {
  return token.charAt(0).toUpperCase() + token.slice(1);
}

function camelCase(value) {
  return value.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function numberArg(value, fallback) {
  if (!value) {
    return fallback;
  }
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function printUsage() {
  console.log(`Usage:
  node scripts/lookup-operation.js --validate
  node scripts/lookup-operation.js --map
  node scripts/lookup-operation.js --tags
  node scripts/lookup-operation.js --doc-tags
  node scripts/lookup-operation.js --doc-tag Auth [--grep token] [--limit 20]
  node scripts/lookup-operation.js --tag ProductAPI [--limit 20]
  node scripts/lookup-operation.js --query "product list" [--limit 5]
  node scripts/lookup-operation.js --operation-id ProductAPI_GetProductList --details [--schemas]
  node scripts/lookup-operation.js --path /v3/product/list [--method post] --details [--schemas]`);
}

function validateSpec(operationList) {
  const errors = [];
  const methodPathCounts = new Map();
  const groupByTag = tagGroupIndex();
  const allRefs = [];

  visitRefs(spec, [], allRefs);

  for (const { path: refPath, ref } of allRefs) {
    if (!String(ref).startsWith('#/')) {
      continue;
    }
    if (resolvePointer(ref) === undefined) {
      errors.push(`Unresolved ref at ${refPath.join('.')}: ${ref}`);
    }
  }

  for (const operation of operationList) {
    const key = `${operation.method.toUpperCase()} ${operation.path}`;
    methodPathCounts.set(key, (methodPathCounts.get(key) || 0) + 1);

    for (const tag of operation.tags) {
      if (!groupByTag.has(tag)) {
        errors.push(`Operation tag is not present in x-tagGroups: ${key} tag=${tag}`);
      }
    }

    for (const rawParameter of operation.parameters) {
      const parameter = resolveRef(rawParameter);
      if (rawParameter?.$ref && parameter === rawParameter) {
        errors.push(`Unresolved parameter ref in ${key}: ${rawParameter.$ref}`);
      }
    }

    const rawRequestBody = operation.operation.requestBody;
    const requestBody = resolveRef(rawRequestBody);
    if (rawRequestBody?.$ref && requestBody === rawRequestBody) {
      errors.push(`Unresolved requestBody ref in ${key}: ${rawRequestBody.$ref}`);
    }
    const requestContent = firstContentSchema(requestBody);
    if (rawRequestBody && !requestContent?.schema) {
      errors.push(`Request body has no declared content schema in ${key}`);
    }
  }

  for (const [key, count] of methodPathCounts.entries()) {
    if (count > 1) {
      errors.push(`Duplicate method/path operation: ${key}`);
    }
  }

  const deprecated = operationList.filter((operation) => operation.deprecated).length;
  console.log(`Parsed ${operationList.length} operations from swagger.json.`);
  console.log(`Deprecated operations: ${deprecated}`);
  console.log(`Local refs checked: ${allRefs.filter((entry) => String(entry.ref).startsWith('#/')).length}`);

  if (errors.length) {
    console.log('Validation failed:');
    for (const error of errors) {
      console.log(`- ${error}`);
    }
    return 1;
  }

  console.log('Swagger helper validation passed.');
  return 0;
}

function visitRefs(value, pathParts, refs) {
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      visitRefs(item, [...pathParts, String(index)], refs);
    }
    return;
  }
  if (!value || typeof value !== 'object') {
    return;
  }
  if (typeof value.$ref === 'string') {
    refs.push({ path: pathParts, ref: value.$ref });
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === '$ref') {
      continue;
    }
    visitRefs(child, [...pathParts, key], refs);
  }
}

function resolvePointer(ref) {
  if (!String(ref).startsWith('#/')) {
    return undefined;
  }
  let node = spec;
  for (const part of String(ref).slice(2).split('/')) {
    const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
    if (!node || typeof node !== 'object' || !(key in node)) {
      return undefined;
    }
    node = node[key];
  }
  return node;
}
