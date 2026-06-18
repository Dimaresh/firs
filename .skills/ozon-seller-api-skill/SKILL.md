---
name: ozon-seller-api
description: Ozon Seller API reference and helper. Use when working with Ozon marketplace API integrations, endpoints, request or response schemas, Client-Id/Api-Key auth, OAuth, products, prices, stocks, warehouses, FBO/FBS/rFBS/FBP postings, returns, finance, analytics, reports, reviews, questions, chats, push notifications, offer_id, product_id, sku, or warehouse_id.
---

# Ozon Seller API

Use this skill for targeted Ozon Seller API lookups and integration help. Treat `swagger.json` as the only API documentation source of truth.

## Protocol Details

Do not rely on static protocol notes in this skill body. Use Swagger-derived helper output instead:

- Endpoint method, media type, auth headers, and parameters: `node scripts/lookup-operation.js --operation-id <id> --details`
- API key auth: `node scripts/lookup-operation.js --doc-tag Auth`
- OAuth: `node scripts/lookup-operation.js --doc-tag OAuth-token`
- Environment/base host: `node scripts/lookup-operation.js --doc-tag Environment`

## Lookup Workflow

Run helper commands from this skill directory, or use an absolute path to `scripts/lookup-operation.js`. In Claude Code, `${CLAUDE_SKILL_DIR}` points at this skill directory.

1. For a bird's-eye view, start with the Swagger-backed map. It uses `x-tagGroups` and tag metadata from `swagger.json`:
   `node scripts/lookup-operation.js --map`
2. For targeted search, query the read-only helper:
   `node scripts/lookup-operation.js --query "product list" --limit 5`
3. For a known endpoint, path, or operation ID:
   `node scripts/lookup-operation.js --operation-id ProductAPI_GetProductList --details`
   `node scripts/lookup-operation.js --path /v3/product/list --details`
4. For lower-level navigation, list raw tags or operations in one tag:
   `node scripts/lookup-operation.js --tags`
   `node scripts/lookup-operation.js --tag ProductAPI --limit 20`
5. For compact non-operation docs such as auth, OAuth, errors, push notifications, or news:
   `node scripts/lookup-operation.js --doc-tags`
   `node scripts/lookup-operation.js --doc-tag Auth --grep token --limit 20`
6. Add `--schemas` only when request or response fields are needed:
   `node scripts/lookup-operation.js --operation-id ProductAPI_GetProductList --details --schemas`
7. Run validation after changing `swagger.json` or the helper:
   `node scripts/lookup-operation.js --validate`
8. Do not open the full `swagger.json` unless the user explicitly asks for broad source material. Use the lookup script for compact output.

## Files

- `swagger.json`: complete OpenAPI source and the only API source of truth.
- `scripts/lookup-operation.js`: local read-only helper for Swagger-derived API maps, endpoint lookup, doc tag lookup, parameter/schema lookup, and validation. It is not a user-facing Ozon API client.

## Answering Rules

- Use the exact method and path from the lookup result.
- Include auth headers in examples, using placeholders only. Prefer parameter details from `--details`.
- If an endpoint is beta, premium, or Ozon Delivery specific, say so.
- Prefer the user's requested language or stack for code examples.
- For direct API examples, include the JSON body shape and a minimal success-path request.
- Do not invent or rely on a bundled Ozon CLI. Generate small app-specific wrappers when the user asks for executable code.
