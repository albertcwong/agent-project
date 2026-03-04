# Auth0 Setup Instructions

This app uses Auth0 for user authentication. Follow these steps to configure Auth0.

## 1. Create an Auth0 Account

1. Go to [auth0.com](https://auth0.com) and sign up or log in.
2. Create a new tenant if you don't have one.

## 2. Create an Application

1. In the Auth0 Dashboard, go to **Applications** → **Applications**.
2. Click **Create Application**.
3. Name it (e.g. "Agent Suite Chat").
4. Select **Regular Web Application**.
5. Click **Create**.

## 3. Configure Application Settings

1. Go to **Settings** for your application.
2. Note your **Domain**, **Client ID**, and **Client Secret**.
3. Under **Application URIs**:
   - **Allowed Callback URLs**: Add `http://localhost:3000/auth/callback` (dev) and your production URL (e.g. `https://your-app.com/auth/callback`).
   - **Allowed Logout URLs**: Add `http://localhost:3000` (dev) and your production URL.
   - **Allowed Web Origins**: Add `http://localhost:3000` and your production URL.
4. Click **Save Changes**.

## 4. Configure Tableau with Auth0 (Optional)

If your Tableau Server uses Auth0 as the identity provider:

1. In Auth0 Dashboard, go to **Applications** → your Tableau-connected app (or create one).
2. Ensure the Tableau Server is configured to use Auth0 for user authentication.
3. When users connect a Tableau MCP server in Settings, they will sign in via Tableau’s OAuth flow (which uses Auth0 if Tableau is configured that way).

## 5. Environment Variables

Add to your `.env` file:

```env
# Auth0 (required for app login)
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=your_client_id
AUTH0_CLIENT_SECRET=your_client_secret
AUTH0_SECRET=generate_with_openssl_rand_hex_32

# Optional: for production
APP_BASE_URL=https://your-app.com
```

Generate `AUTH0_SECRET`:

```bash
openssl rand -hex 32
```

## 6. Verify

1. Run `npm run dev`.
2. Open the app and click **Log in** in the sidebar.
3. You should be redirected to Auth0 to sign in.
4. After signing in, you should see **Log out** in the sidebar.
