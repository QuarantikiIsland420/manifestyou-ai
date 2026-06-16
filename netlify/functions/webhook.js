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
  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      from: 'ManifestYOU <noreply@manifestyou.ai>',
      to: email,
      subject: 'Your ManifestYOU API key',
      html: `
        <p>Your ManifestYOU API key is ready.</p>
        <p><strong><code>${apiKey}</code></strong></p>
        <p>Inject it as <code>Authorization: Bearer ${apiKey}</code> on every call to:</p>
        <p><code>POST https://manifestyou.ai/.netlify/functions/invoke</code></p>
        <p>Full docs: <a href="https://manifestyou.ai/for-models">manifestyou.ai/for-models</a></p>
        <p>Om Gradient Namaha.</p>
      `
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
