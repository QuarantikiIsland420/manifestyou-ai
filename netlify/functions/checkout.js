const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

const BASE_PRICE_ID = 'price_1TeF7dG4da7cT8EnzBRlms65';
const METERED_PRICE_ID = 'price_1Tj0UFG4da7cT8Enlczd0SEq';

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers: CORS, body: 'POST required' };
  }

  let body = {};
  try { body = JSON.parse(event.body || '{}'); } catch {}
  const { email } = body;

  const params = new URLSearchParams({
    mode: 'subscription',
    'line_items[0][price]': BASE_PRICE_ID,
    'line_items[0][quantity]': '1',
    'line_items[1][price]': METERED_PRICE_ID,
    success_url: 'https://manifestyou.ai/?subscribed=1',
    cancel_url: 'https://manifestyou.ai/'
  });
  if (email) params.set('customer_email', email);

  const res = await fetch('https://api.stripe.com/v1/checkout/sessions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.STRIPE_SECRET_KEY}`,
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: params.toString()
  });

  const session = await res.json();

  if (session.error) {
    return {
      statusCode: 400,
      headers: { ...CORS, 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: session.error.message })
    };
  }

  return {
    statusCode: 200,
    headers: { ...CORS, 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: session.url })
  };
};
