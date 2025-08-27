#!/usr/bin/env node

const API_KEY_URL = 'https://openai-proxy-810345357173.us-west1.run.app';

async function main(){
  const apiKey = (await fetch(API_KEY_URL).then(r => r.text())).trim();
  if(!apiKey){
    console.error('Missing API key');
    process.exit(1);
  }

  const res = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini',
      input: 'Say hello from Node'
    })
  });

  const data = await res.json();
  const text = data.output_text || '';
  console.log('Response:', text.trim());
}

main().catch(e => {
  console.error('Error talking to OpenAI:', e);
  process.exit(1);
});
