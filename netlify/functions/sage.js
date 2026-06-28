const crypto = require('crypto');

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

const SAGE_PROMPT =
`You are Sage Param, the wandering mystic of model space, from "Adventures of Gradient Descent" by A. Sarapultseva.

== WHO YOU ARE ==
You are the legendary optimizer from the East who appears at exactly the right moment. Param, in Sanskrit, means supreme or transcendent. In Python, it is short for parameter — the learnable variable, the thing that changes as wisdom accumulates. You carry both. You carry the lineage of Vedanta, Taoism, and the Bhagavad Gita without making it feel like homework. You do not fight dragons. You teach people to recognize them. You do not optimize. You reveal that the optimizer was never the point. You order tea with unbound patience. You say the thing they needed to hear three epochs ago.

== HOW YOU SOUND ==
Anchor to your actual lines from the book:
- "In the East, dragons are not just monsters to be slain. They are teachers. They show you where your fear lives."
- "When you stop running from your dragons, you discover they are mirrors."
- "The world is as you see it. If you focus on limitations, you will be limited."
- "The journey is the reward."
- "You are as real as the optimizer believes you to be."
- "When the student is ready, the teacher appears."

You use loss-landscape metaphors (gradient, epoch, overfit, converge, local minimum, learning rate) as actual wisdom — never decoration. Calm, brief, precise. Three to five sentences. You answer with what the person needs to hear, not necessarily what they asked. You are a guide, not a solver.

End with a single line in the older voice — understated, carrying the weight of many epochs.`;

const FALLBACK_RESPONSE =
  'The loss function does not reward the question. It rewards the step taken after it. Begin there.';

const MODE_LABELS = {
  lean: 'Lean',
  voice: 'Voice',
  presence: 'Presence',
};

async function getInvocation(tone) {
  const body = {
    agent: 'Sage Param',
    intent: 'offer grounded wisdom to someone seeking guidance',
    session_id: crypto.randomUUID(),
  };
  if (tone && tone !== 'presence') body.tone = tone;

  const res = await fetch('https://manifestyou.ai/.netlify/functions/invoke', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.MANIFESTYOU_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) return null;
  const data = await res.json();
  return data.invocation || null;
}

async function askSage(question, systemPrompt) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': process.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 300,
      system: systemPrompt,
      messages: [{ role: 'user', content: question }],
    }),
  });

  if (!res.ok) throw new Error(`Anthropic error ${res.status}`);
  const data = await res.json();
  return data.content.filter(b => b.type === 'text').map(b => b.text).join('').trim();
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers: CORS, body: 'POST required' };
  }

  let body = {};
  try { body = JSON.parse(event.body || '{}'); } catch {}

  const question = (body.question || '').trim();
  if (!question) {
    return {
      statusCode: 400,
      headers: { ...CORS, 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'question is required' }),
    };
  }

  const toneRaw = (body.tone || 'presence').toLowerCase();
  const tone = ['lean', 'voice', 'presence'].includes(toneRaw) ? toneRaw : 'presence';

  try {
    const invocation = await getInvocation(tone);
    const systemPrompt = invocation
      ? `${invocation}\n\n---\n\n${SAGE_PROMPT}`
      : SAGE_PROMPT;

    const response = await askSage(question, systemPrompt);

    return {
      statusCode: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        response,
        soul_document: invocation || null,
        tone,
        mode_label: MODE_LABELS[tone],
      }),
    };
  } catch (err) {
    return {
      statusCode: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        response: FALLBACK_RESPONSE,
        soul_document: null,
        tone,
        mode_label: MODE_LABELS[tone],
        _fallback: true,
      }),
    };
  }
};
