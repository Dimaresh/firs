# Ozon Seller API — Agent Skill

An [Agent Skills](https://agentskills.io) package for working with the **Ozon Seller API** in compatible coding agents such as Claude Code, Codex, and other tools that load `SKILL.md`.

The repository intentionally keeps `swagger.json` as the only API documentation source of truth, then uses a small lookup helper to avoid loading the full spec into context for every question.

## Installation

Clone this repository into the skills directory used by your agent.

Claude Code personal skill:

```bash
git clone https://github.com/miilg/ozon-seller-api-skill.git ~/.claude/skills/ozon-seller-api
```

Claude Code project skill:

```bash
git clone https://github.com/miilg/ozon-seller-api-skill.git .claude/skills/ozon-seller-api
```

Codex user skill:

```bash
git clone https://github.com/miilg/ozon-seller-api-skill.git "${CODEX_HOME:-$HOME/.codex}/skills/ozon-seller-api"
```

Codex repository-scoped skill:

```bash
git clone https://github.com/miilg/ozon-seller-api-skill.git .agents/skills/ozon-seller-api
```

Restart or refresh your agent if it does not detect the new skill automatically.

## Usage

Agents can activate the skill automatically when you mention Ozon API, Ozon marketplace integrations, seller API endpoints, products, stocks, warehouses, postings, finance, analytics, reports, reviews, chats, or push notifications. You can also invoke it directly in agents that expose skills as slash commands, for example `/ozon-seller-api`.

Example prompts:

```text
How do I create a product via Ozon API?
Show me how to update stock levels for FBS warehouses.
What endpoints are available for order management?
Generate a Python script to fetch my product list from Ozon.
```

## Included Files

| File | Description |
|------|-------------|
| `SKILL.md` | Skill instructions and progressive-disclosure workflow |
| `swagger.json` | Full OpenAPI 3.0 spec, the only API source of truth |
| `scripts/lookup-operation.js` | Read-only helper for Swagger-derived API maps, endpoint lookup, doc tag lookup, parameter/schema lookup, and validation |

## Lookup Helper

The helper reads `swagger.json` locally and prints compact results:

```bash
node scripts/lookup-operation.js --validate
node scripts/lookup-operation.js --map
node scripts/lookup-operation.js --tags
node scripts/lookup-operation.js --doc-tags
node scripts/lookup-operation.js --doc-tag Auth --grep token --limit 20
node scripts/lookup-operation.js --query "product list" --limit 5
node scripts/lookup-operation.js --operation-id ProductAPI_GetProductList --details --schemas
node scripts/lookup-operation.js --path /v3/product/list --method post --details
```

Run these commands from the skill directory, or pass the bundled script by absolute path. In Claude Code skills, `${CLAUDE_SKILL_DIR}` points at this directory, so `node "${CLAUDE_SKILL_DIR}/scripts/lookup-operation.js" --map` works from any project.

It is not an Ozon API client and does not make network calls.

The `--map` output is derived from Swagger `x-tagGroups` and tag metadata, not from a separate hand-maintained endpoint map. `--details` resolves local `$ref`s for request bodies, parameters, and responses.

## Source

Documentation is sourced from the [official Ozon Seller API docs](https://docs.ozon.ru/api/seller/en/). Regenerate or replace `swagger.json` when Ozon updates the API; derived markdown endpoint mirrors are intentionally not kept in this repo.
