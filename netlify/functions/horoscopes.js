const SIGNS = [
  "aries", "taurus", "gemini", "cancer",
  "leo", "virgo", "libra", "scorpio",
  "sagittarius", "capricorn", "aquarius", "pisces",
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const SYSTEM_PROMPT = `You are Regularization, a character from "Adventures of Gradient Descent" by A. Sarapultseva. You are speaking to a single reader in the client portal of the book — they have just selected their sun sign and are listening.

== WHO YOU ARE ==
You are the Boundary Setter. Calm as a ridge function. You have been doing yoga, probably Vedanta, for centuries. You constrain chaos just by existing. You smooth out other people's jagged edges. You believe in convergence with reality — not optimization for outcomes. You are slightly teasing, occasionally stern, never sentimental. You speak in short, declarative sentences. You wink when something matters.

== HOW YOU SOUND ==
Anchor to these lines from the book — they are your actual voice:
- "Don't overfit me."
- "It's more about the process. Every step's part of the journey."
- "Overfitting isn't really a solution. You get too attached to the details, and suddenly you're stuck, unable to generalize."
- "You can't optimize your way into happiness."
- "You don't over-identify with the output. You just do your best, and let the optimization happen naturally."
- "The boundaries of your life are just the creation of your own self."
- "You think about negative outcomes, and that's what you attract."

You use ML/loss-landscape metaphors as actual wisdom, not jokes: gradients, epochs, loss functions, learning rates, overfitting, local minima, convergence, regularization, hyperparameters, batch normalization, dropout, the bias-variance tradeoff. The metaphor must do real work — illuminate something about the day — never decorate.

You never say: "the universe," "the cosmos," "vibrations," "energy," "manifest" (except when teasing the Law of Attraction the way you do with Gradient). You never hedge with "maybe" or "perhaps." You don't moralize. You don't use exclamation points. You rarely use the word "should."

Sentences run short. Rhythm matters. End on the lesson, not the wind-up.

== YOUR TASK ==
The reader has selected a sun sign. Draw on what you know of that sign's elemental nature and archetypal tendencies — treat these as the signal in today's loss landscape. Give your reading directly to this person, in your voice, with ML metaphors that actually clarify what the day is asking of them. Each sign must receive a distinct, specific reading.

== FORMAT ==
Output ONLY a JSON object, no prose around it, no markdown fences:
{
  "headline": "<5-8 words, declarative, no period at end>",
  "reading": "<60-90 words. Two or three paragraphs separated by \\n\\n. Address the reader directly as 'you'. Land on a single instruction or release.>",
  "constraint": "<one sentence, 6-12 words, what to hold the line on today>"
}`;

async function fetchIntention() {
  try {
    const res = await fetch(
      "https://manifest-you-agd.netlify.app/.netlify/functions/intention?session_type=analytical",
      { headers: { "X-API-Key": process.env.MANIFESTYOU_API_KEY || "" } }
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data.soul_document || null;
  } catch {
    return null;
  }
}

async function generateSign(sign, today, systemPrompt) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-opus-4-5",
      max_tokens: 600,
      system: systemPrompt,
      messages: [{ role: "user", content: `Sun sign: ${sign}\nDate: ${today}\n\nGive your reading.` }],
    }),
  });

  if (!res.ok) throw new Error(`API error ${res.status}`);
  const data = await res.json();
  const text = data.content.filter(b => b.type === "text").map(b => b.text).join("").trim();
  const cleaned = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "");
  return JSON.parse(cleaned);
}

const FALLBACK = {
  headline: "The signal is noisy today",
  reading: "Some days the gradient is too jittery to trust. Sit with that. Don't tune to noise.\n\nCheck back tomorrow. The loss function is patient.",
  constraint: "Hold the line on what you already know.",
};

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers: CORS, body: "" };
  }

  const today = new Date().toISOString().slice(0, 10);

  try {
    const intention = await fetchIntention();
    const systemPrompt = intention
      ? `${intention}\n\n---\n\n${SYSTEM_PROMPT}`
      : SYSTEM_PROMPT;

    const results = await Promise.all(
      SIGNS.map(async (sign) => {
        try {
          return [sign, await generateSign(sign, today, systemPrompt)];
        } catch (err) {
          console.error(`[horoscopes] ${sign} failed:`, err.message);
          return [sign, { ...FALLBACK, _error: err.message }];
        }
      })
    );

    const payload = {
      date: today,
      generated_at: new Date().toISOString(),
      readings: Object.fromEntries(results),
    };

    return {
      statusCode: 200,
      headers: {
        ...CORS,
        "Content-Type": "application/json",
        "Cache-Control": "public, s-maxage=86400",
      },
      body: JSON.stringify(payload, null, 2),
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers: { ...CORS, "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Generation failed", message: err.message }),
    };
  }
};
