const OPENAI_API_KEY = (typeof process !== 'undefined' ? process.env.OPENAI_API_KEY : '')
  || globalThis.OPENAI_API_KEY || '';

export function hasAPIKey(){
  return !!OPENAI_API_KEY;
}

export async function getStarters(){
  if(!OPENAI_API_KEY) return [];
  const res = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENAI_API_KEY}`
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini',
      input: 'List four short example questions a citizen might ask about local government data.'
    })
  });
  const data = await res.json();
  const text = data.output_text || '';
  return text
    .split('\n')
    .map(s => s.replace(/^[\s\d\-\*\.]+/, '').trim())
    .filter(Boolean)
    .slice(0,4);
}

export async function sendChat(messages){
  if(!OPENAI_API_KEY) throw new Error('Missing OPENAI_API_KEY');
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENAI_API_KEY}`
    },
    body: JSON.stringify({ model: 'gpt-4o-mini', messages })
  });
  const data = await res.json();
  return data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content
    ? data.choices[0].message.content.trim()
    : '';
}
