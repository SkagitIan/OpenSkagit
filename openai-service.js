import OpenAI from 'https://cdn.jsdelivr.net/npm/openai@latest/dist/index.min.js';

const API_KEY_URL = 'https://openai-proxy-810345357173.us-west1.run.app';
let clientPromise;

async function getClient(){
  if(!clientPromise){
    clientPromise = fetch(API_KEY_URL)
      .then(r => r.text())
      .then(key => new OpenAI({ apiKey: key.trim(), dangerouslyAllowBrowser: true }));
  }
  return clientPromise;
}

export async function hasAPIKey(){
  try {
    await getClient();
    return true;
  } catch (e) {
    console.error('Error fetching API key:', e);
    return false;
  }
}

export async function getStarters(){
  const client = await getClient();
  const res = await client.responses.create({
    model: 'gpt-4o-mini',
    input: 'List four short example questions a citizen might ask about local government data.'
  });
  const text = res.output_text || '';
  return text
    .split('\n')
    .map(s => s.replace(/^[\s\d\-\*\.]+/, '').trim())
    .filter(Boolean)
    .slice(0,4);
}

export async function sendChat(messages){
  const client = await getClient();
  const res = await client.responses.create({ model: 'gpt-4o-mini', messages });
  return res.output_text ? res.output_text.trim() : '';
}
