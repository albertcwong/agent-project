# Authentication Flow Diagram

## Mermaid Diagrams

### App Login (Auth0)

```mermaid
sequenceDiagram
    participant U as User
    participant A as Next.js App
    participant Auth0 as Auth0

    U->>A: Click "Log in"
    A->>Auth0: Redirect /auth/login
    Auth0->>U: Show login page
    U->>Auth0: Enter credentials
    Auth0->>A: Redirect /auth/callback?code=...
    A->>A: Exchange code, set session cookie
    A->>U: App (logged in)
```

### Tableau MCP OAuth (MCP → Tableau → Auth0)

```mermaid
sequenceDiagram
    participant U as User
    participant A as Next.js App
    participant MCP as Tableau MCP
    participant T as Tableau OAuth
    participant Auth0 as Auth0 (IdP)

    U->>A: "Sign in with Tableau"
    A->>MCP: Redirect /oauth/authorize (PKCE)
    MCP->>T: Redirect to Tableau OAuth
    T->>Auth0: Login (if Tableau uses Auth0)
    U->>Auth0: Credentials
    Auth0->>T: Auth
    T->>MCP: Callback with code
    MCP->>A: Redirect /api/mcp/oauth/callback?code=...
    A->>MCP: POST /oauth/token (code + verifier)
    MCP->>A: access_token (JWE)
    A->>U: Store token, redirect to app
```

### Agent Request with Token

```mermaid
sequenceDiagram
    participant U as User
    participant A as Next.js App
    participant API as Agent API
    participant MCP as Tableau MCP

    U->>A: Ask (Tableau mode)
    A->>API: POST /agent/ask { tokens }
    API->>MCP: Request + Bearer JWE
    MCP->>API: Tool result
    API->>A: { answer }
    A->>U: Display answer
```

---

## ASCII Diagrams

### 1. App Login (Auth0)

```
┌─────────┐     ┌─────────────┐     ┌─────────┐     ┌─────────────┐     ┌─────────┐
│  User   │     │  Next.js     │     │  Auth0  │     │  Auth0      │     │  User   │
│         │     │  App         │     │  Login  │     │  Callback   │     │         │
└────┬────┘     └──────┬──────┘     └────┬────┘     └──────┬──────┘     └────┬────┘
     │                 │                 │                 │                 │
     │  Click "Log in"  │                 │                 │                 │
     │────────────────>│                 │                 │                 │
     │                 │  Redirect to    │                 │                 │
     │                 │  /auth/login    │                 │                 │
     │                 │────────────────>│                 │                 │
     │                 │                 │                 │                 │
     │                 │  Auth0 login    │                 │                 │
     │                 │  page          │                 │                 │
     │<────────────────│<────────────────│                 │                 │
     │                 │                 │                 │                 │
     │  Enter credentials               │                 │                 │
     │─────────────────────────────────>│                 │                 │
     │                 │                 │                 │                 │
     │                 │  Redirect to    │                 │                 │
     │                 │  /auth/callback │                 │                 │
     │                 │<────────────────│                 │                 │
     │                 │                 │                 │                 │
     │                 │  Set session    │                 │                 │
     │                 │  cookie         │                 │                 │
     │                 │                 │                 │                 │
     │  App (logged in)                 │                 │                 │
     │<────────────────│                 │                 │                 │
     │                 │                 │                 │                 │
```

### 2. Tableau MCP Connection (MCP OAuth → Tableau → Auth0)

When the user clicks "Sign in with Tableau" for an OAuth-protected MCP server:

```
┌─────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────┐
│  User   │   │  Next.js    │   │  Tableau    │   │  Tableau    │   │  Auth0  │
│         │   │  App        │   │  MCP Server │   │  OAuth      │   │ (IdP)   │
└────┬────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └────┬────┘
     │               │                 │                 │               │
     │ "Sign in with  │                 │                 │               │
     │  Tableau"     │                 │                 │               │
     │──────────────>│                 │                 │               │
     │               │                 │                 │               │
     │               │  Redirect to    │                 │               │
     │               │  /api/mcp/oauth/connect?serverId=X │               │
     │               │────────────────>                 │               │
     │               │                 │                 │               │
     │               │  Redirect to    │                 │               │
     │               │  MCP /oauth/authorize             │               │
     │               │  (PKCE)         │                 │               │
     │               │────────────────>                 │               │
     │               │                 │                 │               │
     │               │  Redirect to    │                 │               │
     │               │  Tableau OAuth  │                 │               │
     │               │                 │────────────────>│               │
     │               │                 │                 │               │
     │               │                 │  Tableau login   │               │
     │               │                 │  (Auth0 if      │               │
     │               │                 │  configured)    │               │
     │               │                 │                 │──────────────>│
     │               │                 │                 │               │
     │<──────────────────────────────────────────────────────────────────│
     │  User signs in via Auth0 (if Tableau uses Auth0)                   │
     │               │                 │                 │<───────────────│
     │               │                 │                 │               │
     │               │                 │  Tableau auth   │               │
     │               │                 │  code            │               │
     │               │                 │<────────────────│               │
     │               │                 │                 │               │
     │               │  MCP callback   │                 │               │
     │               │  with MCP code  │                 │               │
     │               │<────────────────│                 │               │
     │               │                 │                 │               │
     │               │  Redirect to    │                 │               │
     │               │  /api/mcp/oauth/callback?code=...  │               │
     │               │<────────────────                  │               │
     │               │                 │                 │               │
     │               │  POST /oauth/token                 │               │
     │               │  (exchange code)│                 │               │
     │               │────────────────>│                 │               │
     │               │                 │                 │               │
     │               │  access_token    │                 │               │
     │               │  (JWE)           │                 │               │
     │               │<────────────────│                 │               │
     │               │                 │                 │               │
     │               │  HTML + script:  │                 │               │
     │               │  store token in │                 │               │
     │               │  localStorage,   │                 │               │
     │               │  redirect to /   │                 │               │
     │               │                 │                 │               │
     │  App with     │                 │                 │               │
     │  MCP connected│                 │                 │               │
     │<──────────────│                 │                 │               │
     │               │                 │                 │               │
```

### 3. Agent Request (with stored token)

```
┌─────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  User   │   │  Next.js    │   │  Agent API  │   │  Tableau    │
│         │   │  App        │   │  (Python)   │   │  MCP Server │
└────┬────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
     │               │                 │                 │
     │  Ask question │                 │                 │
     │  (Tableau mode)                 │                 │
     │──────────────>│                 │                 │
     │               │                 │                 │
     │               │  POST /api/agent/ask              │
     │               │  { question, connectedServers,    │
     │               │    tokens: { serverId: JWE } }   │
     │               │────────────────>                 │
     │               │                 │                 │
     │               │                 │  MCP request   │
     │               │                 │  Authorization: │
     │               │                 │  Bearer <JWE>   │
     │               │                 │────────────────>│
     │               │                 │                 │
     │               │                 │  Tool result    │
     │               │                 │<────────────────│
     │               │                 │                 │
     │               │  { answer }      │                 │
     │               │<────────────────│                 │
     │               │                 │                 │
     │  Answer       │                 │                 │
     │<──────────────│                 │                 │
     │               │                 │                 │
```
