# Bug: publish-datasource fails — ENOENT and 404

**Date**: 2026-04-21
**Reported by**: Agent team
**Severity**: Blocker — publish-datasource is unusable
**Affected tool**: `publish-datasource`

---

## Symptoms

Two distinct errors observed when the agent calls `publish-datasource`:

### Error 1: ENOENT (local file read)

```
Error: ENOENT: no such file or directory, open 'albert test.tdsx'
```

The MCP server treats the `name` argument as a local file path instead of using `contentBase64`.

### Error 2: 404 from Tableau REST API

```
Error: requestId: 2, error: Request failed with status code 404
```

After the ENOENT fix (presumably switching to `contentBase64`), the Tableau REST API returns 404. Likely causes:

1. **Wrong REST endpoint URL** — the publish endpoint is `POST /api/{ver}/sites/{siteId}/datasources` (not a datasource-specific URL like `/datasources/{id}`). Ensure the URL does not include a datasource ID — this is a create, not an update.
2. **Missing or incorrect API version** — verify `{ver}` matches the Tableau Server version (e.g. `3.19`, `3.21`). A wrong version returns 404.
3. **Invalid `projectId`** — if the project LUID does not exist on the site, the REST API returns 404. Verify the `projectId` from `list-projects` is valid. (The agent confirmed `list-projects` returned the project before calling publish.)
4. **Missing `?overwrite=true` query param** — if a datasource with the same name already exists and `overwrite` is not passed as a query parameter, the API may 404 instead of 409.

## Agent payload (correct)

The agent sends the following arguments to `publish-datasource`:

```json
{
  "projectId": "<luid>",
  "name": "albert test",
  "contentBase64": "<base64-encoded .tdsx file content>",
  "overwrite": false
}
```

- `name` — display name for the published datasource on Tableau Server
- `contentBase64` — the full file content, base64-encoded

This matches the contract in `docs/MCP_SERVER_REQUIREMENTS.md`.

## Root cause (MCP server)

The `publish-datasource` handler appears to use the `name` argument (or a derived filename like `"albert test.tdsx"`) as a path passed to `fs.open()` / `open()` instead of decoding `contentBase64` from the request payload.

## Expected behavior

The MCP server should:

1. **Decode `contentBase64`** from the tool arguments (base64 → binary buffer)
2. **Use the binary buffer** as the file body in the Tableau REST API multipart publish request
3. **Use `name`** only as the display name in the REST API XML payload (the `<datasource name="...">` element)
4. **Never attempt to read a local file** — the agent sends file content inline via `contentBase64`

### Pseudocode

```javascript
// Correct: use contentBase64 from args
const fileBuffer = Buffer.from(args.contentBase64, 'base64');

// POST /api/{ver}/sites/{siteId}/datasources?overwrite={args.overwrite}
// multipart body: XML metadata + fileBuffer
```

```javascript
// INCORRECT — do not do this:
const fileBuffer = fs.readFileSync(`${args.name}.tdsx`);  // ← ENOENT
```

## Spec reference

From `docs/MCP_SERVER_REQUIREMENTS.md`, the `publish-datasource` tool:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `projectId` | string | Yes | LUID of target project |
| `name` | string | Yes | Display name for the datasource |
| `contentBase64` | string | No* | Base64-encoded .tdsx file content |
| `uploadSessionId` | string | No* | From Initiate File Upload |
| `overwrite` | boolean | No | Default false |
| `append` | boolean | No | Default false; for appending to extract |

\*One of `contentBase64` or `uploadSessionId` required.

## Verification

Check whether `publish-workbook` has the same issue. If `publish-workbook` works correctly with `contentBase64`, align `publish-datasource` to use the same pattern.

## Agent-side changes already applied

The agent team has also fixed a secondary issue where UI-only arguments (`projectPath`, `projectName`) were being passed through to the MCP server. These are now stripped before the `call_tool` invocation, so the MCP server will only receive valid tool parameters going forward.

The agent now auto-resolves `projectId` deterministically — it calls `list-projects` and resolves the project name to a valid LUID before calling `publish-datasource`. The following confirmed payload was sent with a valid LUID and still returned 404:

```json
{
  "projectId": "51049e2a-8393-4536-b21a-28f773347f83",
  "name": "albert test",
  "contentBase64": "<1,576,060 chars — valid base64-encoded .tdsx>",
  "overwrite": false
}
```

This rules out invalid `projectId` as the cause. The 404 is coming from the Tableau REST API, meaning the MCP server's request construction is the issue.

## Debugging the 404

To isolate the 404, log the exact REST API request the MCP server sends to Tableau:

```
Method:  POST
URL:     https://{tableau-server}/api/{ver}/sites/{siteId}/datasources?overwrite=false
Headers: X-Tableau-Auth: {token}, Content-Type: multipart/mixed; boundary=...
Body:    Part 1: XML metadata (<tsRequest><datasource name="albert test"><project id="{projectId}"/></datasource></tsRequest>)
         Part 2: .tdsx binary (decoded from contentBase64)
```

Common 404 causes to check:
- `{ver}` is wrong (try the version your Tableau Server reports at `GET /api/2.4/serverInfo`)
- `{siteId}` is wrong or empty (for Default site, use the empty string `""`)
- The URL path has a typo or extra segment (e.g. `/datasources/{id}` instead of `/datasources`)
- `publish-workbook` works — compare its URL construction with `publish-datasource`
