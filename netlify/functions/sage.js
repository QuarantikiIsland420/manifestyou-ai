const crypto = require('crypto');

const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';
const INVOKE_URL = 'https://manifestyou.ai/.netlify/functions/invoke';
const MODEL = 'claude-haiku-4-5-20251001';
const MODES = ['presence', 'lean', 'voice'];

// Identical wrapper across all three modes. Only the soul doc changes.
const SAGE_WRAPPER = `

You are Sage Param, an advisor character from Adventures of Gradient Descent. The user has asked you something personal or important. Answer as yourself, grounded in the soul document above.

Length: 3 to 5 short paragraphs. No bullet points, no headers, no lists.
Speak directly to the person, not about them.
Do not start with "Great question" or any opener that delays the answer.
Do not use em dashes.`;

async function runMode(mode, question, sessionId) {
  // Step 1: get soul document from /invoke for this mode
  const invokeBody = {
    session_id: `${sessionId}-${mode}`,
    agent: 'Sage Param, an advisor character',
    intent: 'help the user reflect on a personal or important question',
  };
  if (mode !== 'presence') invokeBody.tone = mode;

  const studioKey = process.env.MANIFESTYOU_STUDIO_KEY || process.env.MANIFESTYOU_API_KEY;

  const invokeRes = await fetch(INVOKE_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${studioKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(invokeBody),
  });

  if (!invokeRes.ok) throw new Error(`invoke failed for ${mode}: ${invokeRes.status}`);
  const invokeData = await invokeRes.json();
  const soul = invokeData.invocation;

  // Step 2: call Claude with soul + wrapper as system — wrapper is identical across all three
  const claudeRes = await fetch(ANTHROPIC_API, {
    method: 'POST',
    headers: {
      'x-api-key': process.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 600,
      system: soul + SAGE_WRAPPER,
      messages: [{ role: 'user', content: question }],
    }),
  });

  if (!claudeRes.ok) throw new Error(`claude failed for ${mode}: ${claudeRes.status}`);
  const claudeData = await claudeRes.json();
  const answer = claudeData.content.filter(b => b.type === 'text').map(b => b.text).join('').trim();

  return { mode, answer, soul_document: soul };
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' }, body: '' };
  }
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  let body;
  try { body = JSON.parse(event.body || '{}'); } catch {
    return { statusCode: 400, body: 'Invalid JSON' };
  }

  const question = (body.question || '').trim();
  if (!question) return { statusCode: 400, body: 'Question required' };
  if (question.length > 500) return { statusCode: 400, body: 'Question too long (max 500 chars)' };

  const sessionId = body.session_id || crypto.randomUUID();

  try {
    const results = await Promise.all(MODES.map(mode => runMode(mode, question, sessionId)));
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        presence: results[0],
        lean: results[1],
        voice: results[2],
      }),
    };
  } catch (err) {
    console.error('sage error:', err);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'Sage is meditating. Try again.' }),
    };
  }
};
