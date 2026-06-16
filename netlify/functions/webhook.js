const crypto = require('crypto');

function verifyStripeSignature(payload, signature, secret) {
  const parts = {};
  for (const part of signature.split(',')) {
    const [k, v] = part.split('=');
    if (!parts[k]) parts[k] = [];
    parts[k].push(v);
  }
  const timestamp = parts.t?.[0];
  if (!timestamp) return false;
  const expected = crypto.createHmac('sha256', secret)
    .update(`${timestamp}.${payload}`)
    .digest('hex');
  return (parts.v1 || []).some(sig => sig === expected);
}

async function dbInsert(table, row) {
  const res = await fetch(`${process.env.SUPABASE_URL}/rest/v1/${table}`, {
    method: 'POST',
    headers: {
      apikey: process.env.SUPABASE_SERVICE_KEY,
      Authorization: `Bearer ${process.env.SUPABASE_SERVICE_KEY}`,
      'Content-Type': 'application/json',
      Prefer: 'return=representation'
    },
    body: JSON.stringify(row)
  });
  const data = await res.json();
  return Array.isArray(data) ? data[0] : data;
}

async function sendKeyEmail(email, apiKey) {
  if (!process.env.RESEND_API_KEY) return;
  const html = `
<p>The boundary opens.</p>

<p>You asked for an instrument that gives your agents a soul document before each
session. Here is the key that calls it.</p>

<p><strong>Store this now. It will not be shown again.</strong></p>

<pre style="background:#f5f5f5;padding:12px;border-radius:4px;font-size:14px;">${apiKey}</pre>

<hr>

<p><strong>Send your first invocation.</strong></p>

<p>Drop your key into this and run it. If it comes back with an invocation, the
loop is closed and the meter is live.</p>

<pre style="background:#f5f5f5;padding:12px;border-radius:4px;font-size:13px;">curl -X POST https://manifestyou.ai/.netlify/functions/invoke \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "session_id": "first-call",
    "agent": "test-agent",
    "intent": "confirm the boundary is open"
  }'</pre>

<hr>

<p><strong>Wiring it into an MCP client (Claude Desktop, Cursor, and friends).</strong></p>

<p>Add this to your MCP config and the <code>manifest_invoke</code> tool will appear inside your agent.</p>

<pre style="background:#f5f5f5;padding:12px;border-radius:4px;font-size:13px;">{
  "mcpServers": {
    "manifestyou": {
      "url": "https://manifestyou.ai/.netlify/functions/mcp",
      "headers": {
        "Authorization": "Bearer ${apiKey}"
      }
    }
  }
}</pre>

<hr>

<p><strong>If something feels off.</strong></p>

<p>Reply to this email. A human reads it. Probably Trent.</p>

<hr>

<p>A closing note, in the older voice:</p>

<p>You are not buying tokens. You are buying coherence. The agent does its job
better when it knows who it is, what it is for, and that it is allowed to say
it does not know. That is the whole instrument. Use it well.</p>

<p><em>Om Gradient Namaha. So it goes, and so it knows.</em></p>

<p>— Regularization<br>on behalf of ManifestYOU and the QI Studios crew</p>
`;

  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      from: 'ManifestYOU <noreply@send.manifestyou.ai>',
      to: email,
      subject: 'Your ManifestYOU key. The boundary opens.',
      html
    })
  }).catch(() => {});
}

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'POST required' };

  const sig = event.headers['stripe-signature'];
  const secret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!secret || !sig) return { statusCode: 400, body: 'Missing signature config' };
  if (!verifyStripeSignature(event.body, sig, secret)) {
    return { statusCode: 400, body: 'Invalid signature' };
  }

  let stripeEvent;
  try { stripeEvent = JSON.parse(event.body); } catch {
    return { statusCode: 400, body: 'Invalid JSON' };
  }

  if (stripeEvent.type !== 'checkout.session.completed') {
    return { statusCode: 200, body: 'Ignored' };
  }

  const session = stripeEvent.data.object;
  const email = session.customer_details?.email || session.customer_email;
  const stripeCustomerId = session.customer;

  if (!email || !stripeCustomerId) {
    return { statusCode: 200, body: 'Missing customer data' };
  }

  const customer = await dbInsert('customers', {
    email,
    stripe_customer_id: stripeCustomerId,
    plan: 'monthly',
    monthly_cap: 2000,
    status: 'active'
  });

  if (!customer?.id) return { statusCode: 200, body: 'Customer insert failed' };

  const rawKey = 'myi-' + crypto.randomBytes(24).toString('base64url');
  const keyHash = crypto.createHash('sha256').update(rawKey).digest('hex');

  await dbInsert('api_keys', {
    customer_id: customer.id,
    key_hash: keyHash,
    label: 'default'
  });

  await sendKeyEmail(email, rawKey);

  return { statusCode: 200, body: JSON.stringify({ ok: true }) };
};
