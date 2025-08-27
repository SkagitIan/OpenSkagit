#!/usr/bin/env node
const apiKey = process.env.OPENAI_API_KEY;
if(!apiKey){
  console.error('Missing OPENAI_API_KEY');
  process.exit(1);
}

fetch('https://api.openai.com/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiKey}`
  },
  body: JSON.stringify({
    model: 'gpt-4o-mini',
    messages: [{ role: 'user', content: 'Say hello from Node' }]
  })
})
  .then(r => r.json())
  .then(d => {
    const text = d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content ? d.choices[0].message.content.trim() : '';
    console.log('Response:', text);
  })
  .catch(e => {
    console.error('Error talking to OpenAI:', e);
    process.exit(1);
  });
